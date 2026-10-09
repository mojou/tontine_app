"""Abonnement : gratuit jusqu'à 10 membres, 200 FCFA x membres au-delà, grâce 7 jours puis lecture seule,
paiement SasPay validé par le super-admin, mois offerts, version offerte, suppression d'une tontine."""
import html
import os
import re
import sys
from datetime import date, timedelta
from decimal import Decimal

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'ab.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402
import billing  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'),
                  BACKUP_FOLDER=os.path.join(S, 'backups'), SASPAY_PAYMENT_URL='https://pay.example/ghelia?montant={montant}&ref={reference}')
from models import Tontine, Member, User, Transaction, BillingPayment  # noqa: E402
from tenancy import tenant_bypass  # noqa: E402

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def text(r):
    h = re.sub(r'(?s)<(script|style)\b.*?</\1>', ' ', r.get_data(as_text=True))
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', h)))


# ---------------------------------------------------------------- règles de prix
check(billing.monthly_price(10) == 0 and billing.monthly_price(11) == 2200 and billing.monthly_price(15) == 3000,
      'prix : 10 membres gratuit, 11 -> 2 200, 15 -> 3 000 FCFA/mois (200 x tous les membres)')

# ---------------------------------------------------------------- tontine de 10 membres : gratuite
pres = app.test_client()
pres.post('/inscription', data={'name': 'Tontine Grande', 'slug': 'grande', 'first_name': 'Hélène', 'last_name': 'Ngo',
                                'email': 'h@grande.cm', 'phone': '699000001', 'username': 'helene',
                                'password': 'Helene2026', 'password_confirm': 'Helene2026'})


def add_member(i, role='MEMBRE'):
    pres.post('/members/add', data={'first_name': f'Membre{i}', 'last_name': 'Test', 'email': f'm{i}@grande.cm',
                                    'phone': f'6991{i:05d}', 'username': f'membre{i}', 'role': role,
                                    'password': 'Passw0rd1', 'confirm_password': 'Passw0rd1'})


add_member(1, 'TRESORIER')
for i in range(2, 10):
    add_member(i)
with app.app_context():
    tid = Tontine.query.filter_by(slug='grande').one().id
    check(Member.query.filter_by(tontine_id=tid).count() == 10, '10 membres actifs')
h = text(pres.get('/abonnement'))
check('Gratuite (jusqu\'à 10 membres)' in h and 'Tout est en ordre' in h, 'page Abonnement : gratuite jusqu\'à 10 membres')
check('Abonnement à régler' not in text(pres.get('/dashboard')), 'pas de bandeau de paiement')

# ---------------------------------------------------------------- 11e membre : payante, délai de grâce
add_member(10)
h = text(pres.get('/abonnement'))
check('11 × 200 = 2 200 FCFA / mois' in h and 'Payante' in h, '11 membres : 11 x 200 = 2 200 FCFA/mois')
grace_end = (date.today() + timedelta(days=6)).strftime('%d/%m/%Y')
check(f'Abonnement à régler avant le {grace_end}' in text(pres.get('/dashboard')), f'bandeau : 7 jours de grâce (jusqu\'au {grace_end})')
check('Payer avec SasPay' in h, 'bouton « Payer avec SasPay »')
check('href="https://pay.example/ghelia?montant=2200&amp;ref=grande"' in pres.get('/abonnement').get_data(as_text=True),
      'lien SasPay rempli avec le montant et la référence de la tontine')
membre = app.test_client()
membre.post('/login', data={'tontine': 'grande', 'username': 'membre3', 'password': 'Passw0rd1'})
check('Le président ou le trésorier doit régler' in text(membre.get('/dashboard')), 'un membre voit le rappel, sans bouton de paiement')
check(membre.get('/abonnement').status_code in (302, 403), "un simple membre n'accède pas à la page Abonnement")

# ---------------------------------------------------------------- après 7 jours : lecture seule
with app.app_context(), tenant_bypass():
    db.session.get(Tontine, tid).billing_started_on = date.today() - timedelta(days=8)
    db.session.commit()
    paul = Member.query.filter_by(tontine_id=tid, first_name='Membre2').one().id
h = text(pres.get('/dashboard'))
check('Lecture seule' in h, 'après 7 jours : bandeau « lecture seule »')
check(pres.get('/members').status_code == 200 and pres.get('/transactions').status_code == 200, 'les pages restent consultables')
r = pres.post('/transactions/add', data={'member_id': paul, 'type': 'PRESENCE', 'amount': 1050, 'payment_mode': 'ESPECE',
                                         'description': 'bloquée'}, follow_redirects=True)
with app.app_context():
    check(Transaction.query.filter_by(description='bloquée').count() == 0 and 'lecture seule' in text(r),
          'lecture seule : aucune saisie enregistrée, message explicite')

# ---------------------------------------------------------------- déclarer un paiement SasPay
r = pres.post('/abonnement', data={'months': '13', 'reference': 'SP-1'}, follow_redirects=True)
check('Choisissez entre 1 et 12 mois' in text(r), 'nombre de mois limité à 12')
r = pres.post('/abonnement', data={'months': '2', 'reference': 'SP-2026-104582'}, follow_redirects=True)
with app.app_context(), tenant_bypass():
    pay = BillingPayment.query.filter_by(tontine_id=tid).one()
    check(pay.amount == Decimal('4400') and pay.status == 'EN_ATTENTE' and pay.members_count == 11,
          'paiement déclaré en lecture seule : 2 mois x 2 200 = 4 400, en attente de validation')
r = pres.post('/abonnement', data={'months': '1', 'reference': 'sp-2026-104582'}, follow_redirects=True)
check('déjà été déclarée' in text(r), 'même référence refusée (doublon)')
check('SP-2026-104582' in text(pres.get('/abonnement')) and 'En attente de validation' in text(pres.get('/abonnement')),
      "l'historique montre le paiement en attente")

# ---------------------------------------------------------------- super-admin : valider
with app.app_context(), tenant_bypass():
    u = User.query.filter_by(role='SUPERADMIN').first()
    u.set_password('Super2026x')
    db.session.commit()
    sa_name = u.username
sa = app.test_client()
sa.post('/login', data={'tontine': m.PLATFORM_LOGIN, 'username': sa_name, 'password': 'Super2026x'})
h = text(sa.get('/superadmin'))
check('Paiements d\'abonnement à valider' in h and 'SP-2026-104582' in h and '4 400 FCFA' in h, 'super-admin : paiement à valider listé')
check('lecture seule' in h, "super-admin : l'état « lecture seule » de la tontine est visible")
check(pres.post(f'/superadmin/paiements/{pay.id}', data={'action': 'valider'}).status_code in (302, 403), 'le président ne peut pas valider')
with app.app_context(), tenant_bypass():
    check(db.session.get(BillingPayment, pay.id).status == 'EN_ATTENTE', '… et rien n\'a changé')
sa.post(f'/superadmin/paiements/{pay.id}', data={'action': 'valider'})
expected_end = billing.add_months(date.today(), 2) - timedelta(days=1)
with app.app_context(), tenant_bypass():
    t = db.session.get(Tontine, tid)
    check(t.paid_until == expected_end, f'validé : payée jusqu\'au {expected_end:%d/%m/%Y}')
h = text(pres.get('/dashboard'))
check('Lecture seule' not in h and 'Abonnement à régler' not in h, 'plus de bandeau après validation')
pres.post('/transactions/add', data={'member_id': paul, 'type': 'PRESENCE', 'amount': 1050, 'payment_mode': 'ESPECE', 'description': 'ok'})
with app.app_context():
    check(Transaction.query.filter_by(description='ok').count() == 1, 'les saisies fonctionnent à nouveau')

# second paiement : prolonge à la suite ; un troisième refusé
pres.post('/abonnement', data={'months': '1', 'reference': 'SP-2026-200'})
pres.post('/abonnement', data={'months': '1', 'reference': 'SP-FAUX-1'})
with app.app_context(), tenant_bypass():
    p2 = BillingPayment.query.filter_by(reference='SP-2026-200').one().id
    p3 = BillingPayment.query.filter_by(reference='SP-FAUX-1').one().id
sa.post(f'/superadmin/paiements/{p2}', data={'action': 'valider'})
sa.post(f'/superadmin/paiements/{p3}', data={'action': 'refuser', 'note': 'Paiement introuvable sur SasPay'})
with app.app_context(), tenant_bypass():
    t = db.session.get(Tontine, tid)
    check(t.paid_until == billing.add_months(expected_end + timedelta(days=1), 1) - timedelta(days=1),
          'un nouveau paiement prolonge à la suite de la période déjà payée')
    check(db.session.get(BillingPayment, p3).status == 'REFUSE', 'paiement refusé')
check('Paiement introuvable sur SasPay' in text(pres.get('/abonnement')), 'le président voit le motif du refus')
r = sa.post(f'/superadmin/paiements/{p3}', data={'action': 'valider'}, follow_redirects=True)
check('déjà été traité' in text(r), 'un paiement traité ne peut pas être revalidé')

# ---------------------------------------------------------------- mois offerts et version offerte
with app.app_context(), tenant_bypass():
    paid_until = db.session.get(Tontine, tid).paid_until
sa.post(f'/superadmin/tontines/{tid}/abonnement', data={'action': 'offrir_mois', 'months': '3'})
with app.app_context(), tenant_bypass():
    t = db.session.get(Tontine, tid)
    check(t.free_until == billing.add_months(paid_until + timedelta(days=1), 3) - timedelta(days=1),
          '3 mois offerts, à la suite de la période payée')
check('Mois offerts jusqu\'au' in text(pres.get('/abonnement')), 'le président voit les mois offerts')
sa.post(f'/superadmin/tontines/{tid}/abonnement', data={'action': 'offrir_illimite'})
h = text(pres.get('/abonnement'))
check('Version complète offerte' in h and 'Payer l\'abonnement' not in h, 'version payante offerte : plus rien à payer')
with app.app_context(), tenant_bypass():
    t = db.session.get(Tontine, tid)
    t.paid_until, t.free_until = None, None
    t.billing_started_on = date.today() - timedelta(days=30)
    db.session.commit()
check('Lecture seule' not in text(pres.get('/dashboard')), "offerte : jamais de lecture seule, même sans paiement")
sa.post(f'/superadmin/tontines/{tid}/abonnement', data={'action': 'retirer_illimite'})
check('Lecture seule' in text(pres.get('/dashboard')), 'offre retirée : la facturation normale reprend')
sa.post(f'/superadmin/tontines/{tid}/abonnement', data={'action': 'offrir_mois', 'months': '1'})
check('Lecture seule' not in text(pres.get('/dashboard')), "1 mois offert à une tontine en lecture seule : débloquée tout de suite")

# ---------------------------------------------------------------- repasser à 10 membres : gratuite
with app.app_context(), tenant_bypass():
    mb = Member.query.filter_by(tontine_id=tid, first_name='Membre10').one()
    mb.is_active = False
    t = db.session.get(Tontine, tid)
    t.free_until = None
    db.session.commit()
check('Gratuite' in text(pres.get('/abonnement')), 'retour à 10 membres : de nouveau gratuite')

# ---------------------------------------------------------------- supprimer une tontine
r = sa.post(f'/superadmin/tontines/{tid}/supprimer', data={'confirm_name': 'mauvais nom'}, follow_redirects=True)
with app.app_context(), tenant_bypass():
    check(db.session.get(Tontine, tid) is not None and 'Suppression annulée' in text(r), 'nom mal tapé : suppression annulée')
r = sa.post(f'/superadmin/tontines/{tid}/supprimer', data={'confirm_name': 'Tontine Grande'}, follow_redirects=True)
with app.app_context(), tenant_bypass():
    left = (Member.query.filter_by(tontine_id=tid).count() + User.query.filter_by(tontine_id=tid).count()
            + BillingPayment.query.filter_by(tontine_id=tid).count() + Transaction.query.filter_by(tontine_id=tid).count())
    check(db.session.get(Tontine, tid) is None and left == 0, f'tontine supprimée avec tout son contenu (reste {left})')
backups = os.listdir(os.path.join(S, 'backups')) if os.path.isdir(os.path.join(S, 'backups')) else []
check(any(b.startswith('avant-suppression-grande-') for b in backups), 'copie de sauvegarde faite avant la suppression')
check('supprimée définitivement' in text(r), 'message de confirmation de la suppression')

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)

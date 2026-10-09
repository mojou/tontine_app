"""Aides sociales : règles d'éligibilité, barème, justificatif, double validation, versement."""
import io
import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'ai.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'))
from models import Tontine, Member, Aide, AidType, Transaction, Sanction, ContributionType, User  # noqa: E402

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def body(r):
    return r.get_data(as_text=True)


PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 200


def doc():
    return (io.BytesIO(PNG), 'acte.png')


pres = app.test_client()
pres.post('/inscription', data={'name': 'Tontine Solidarité', 'slug': 'solidarite', 'first_name': 'Hélène', 'last_name': 'Abena',
                                'email': 'h@sol.cm', 'phone': '699000000', 'username': 'helene', 'password': 'Helene2026',
                                'password_confirm': 'Helene2026'})
for fn, role in [('Paul', 'MEMBRE'), ('Awa', 'MEMBRE'), ('Jean', 'TRESORIER'), ('Rose', 'SECRETAIRE')]:
    pres.post('/members/add', data={'first_name': fn, 'last_name': 'Fouda', 'email': f'{fn.lower()}@sol.cm', 'phone': '699111111',
                                    'username': fn.lower(), 'role': role, 'password': 'Passw0rd1', 'confirm_password': 'Passw0rd1'})
with app.app_context():
    tid = Tontine.query.filter_by(slug='solidarite').one().id
    mem = {x.first_name: x.id for x in Member.query.filter_by(tontine_id=tid).all()}
    types = {t.code: t.id for t in AidType.query.filter_by(tontine_id=tid).all()}
check(len(types) == 7 and 'DECES_MEMBRE' in types, f'barème par défaut créé ({len(types)} événements)')


def login(u):
    c = app.test_client()
    c.post('/login', data={'tontine': 'solidarite', 'username': u, 'password': 'Passw0rd1'})
    return c


paul, awa, jean, rose = login('paul'), login('awa'), login('jean'), login('rose')
ten_days_ago = (date.today() - timedelta(days=10)).isoformat()


def ask(client, **extra):
    data = {'aid_type_id': types['NAISSANCE'], 'event_date': ten_days_ago, 'description': 'Naissance de ma fille', 'document': doc()}
    data.update(extra)
    return client.post('/aides/request', data=data, content_type='multipart/form-data', follow_redirects=True)


def count(member):
    with app.app_context():
        return Aide.query.filter_by(member_id=mem[member]).count()


# ---------------------------------------------------------------- 1. conditions d'éligibilité
h = body(ask(paul))
check(count('Paul') == 0 and 'Conditions non remplies' in h and 'Ancienneté' in h and 'Fonds de caisse' in h,
      'nouveau membre sans fonds de caisse : demande refusée avec les raisons')
h = body(paul.get('/aides'))
check('Mon droit à une aide' in h and 'fa-times-circle' in h, "le membre voit les conditions qu'il ne remplit pas")

with app.app_context():
    paul_m = db.session.get(Member, mem['Paul'])
    paul_m.registration_date = date.today() - timedelta(days=120)
    sec = ContributionType.query.filter_by(tontine_id=tid, category='SECOURS').one()
    sec.created_at = datetime.now() - timedelta(days=70)   # 2 mois échus x 1 000
    db.session.commit()
pres.post('/transactions/add', data={'member_id': mem['Paul'], 'type': 'FONDS_CAISSE', 'amount': 5000, 'payment_mode': 'ESPECE', 'description': ''})
h = body(ask(paul))
check(count('Paul') == 0 and 'caisse de secours' in h, 'fonds de caisse payé mais pas à jour du secours : refusée')
pres.post('/transactions/add', data={'member_id': mem['Paul'], 'type': 'SECOURS', 'amount': 2000, 'payment_mode': 'ESPECE', 'description': ''})

# ---------------------------------------------------------------- 2. justificatif, délai, date, barème
ask(paul, document=(io.BytesIO(b''), ''))
check(count('Paul') == 0, 'justificatif obligatoire pour une naissance')
ask(paul, event_date=(date.today() - timedelta(days=40)).isoformat())
check(count('Paul') == 0, 'événement déclaré après 30 jours : refusé')
ask(paul, event_date=(date.today() + timedelta(days=2)).isoformat())
check(count('Paul') == 0, 'date dans le futur : refusée')
ask(paul, amount='999999')
with app.app_context():
    a1 = Aide.query.filter_by(member_id=mem['Paul']).one()
    a1_id = a1.id
    check(a1.amount == Decimal('10000') and a1.status == 'PENDING', 'demande acceptée au montant du barème (10 000), pas au montant saisi')
    check(a1.document and not a1.document.startswith('static'), 'justificatif enregistré')
    stored = os.path.join(P, 'instance', 'justificatifs', a1.document)
    check(os.path.isfile(stored) and 'static' not in stored, 'justificatif rangé hors du dossier public')
ask(paul)
check(count('Paul') == 1, 'même événement déclaré deux fois : refusé')

# ---------------------------------------------------------------- 3. montant libre plafonné, plafonds annuels
ask(paul, aid_type_id=types['AUTRE'], amount='25000', description='Incendie de cuisine')
check(count('Paul') == 1, '« Autre » au-delà du plafond (20 000) : refusé')
ask(paul, aid_type_id=types['AUTRE'], amount='15000', description='Incendie de cuisine')
with app.app_context():
    check(Aide.query.filter_by(member_id=mem['Paul'], aid_type_id=types['AUTRE']).one().amount == Decimal('15000'), '« Autre » à 15 000 accepté')
ask(paul, aid_type_id=types['MALADIE'], description='Hospitalisation')
check(count('Paul') == 3, 'troisième aide de l\'année acceptée (plafond 3)')
ask(paul, aid_type_id=types['MARIAGE'], description='Mariage')
check(count('Paul') == 3, 'quatrième aide de l\'année : plafond annuel atteint')

# ---------------------------------------------------------------- 4. double validation, pas de validation de sa propre aide
jean.post(f'/aides/{a1_id}/approve')
with app.app_context():
    a = db.session.get(Aide, a1_id)
    check(a.status == 'PENDING' and a.treasurer_approved_by, 'validation du trésorier : 1/2, toujours en attente')
check(paul.post(f'/aides/{a1_id}/approve').status_code == 302, 'un membre ne peut pas valider')
with app.app_context():
    check(db.session.get(Aide, a1_id).president_approved_by is None, '... aucune validation enregistrée')
pres.post(f'/aides/{a1_id}/approve')
with app.app_context():
    check(db.session.get(Aide, a1_id).status == 'APPROVED', 'validation du président : aide approuvée (2/2)')
with app.app_context():
    jean_m = db.session.get(Member, mem['Jean'])
    jean_m.registration_date = date.today() - timedelta(days=200)
    db.session.add(Transaction(tontine_id=tid, member_id=jean_m.id, type='FONDS_CAISSE', amount=5000, date=date.today()))
    db.session.add(Transaction(tontine_id=tid, member_id=jean_m.id, type='SECOURS', amount=2000, date=date.today()))
    db.session.commit()
ask(jean)
with app.app_context():
    jid = Aide.query.filter_by(member_id=mem['Jean']).one().id
jean.post(f'/aides/{jid}/approve')
with app.app_context():
    check(db.session.get(Aide, jid).treasurer_approved_by is None, 'le trésorier ne peut pas valider sa propre aide')

# ---------------------------------------------------------------- 5. versement : caisse de secours, amendes retenues
h = body(jean.post(f'/aides/{a1_id}/pay', data={'payment_mode': 'ORANGE_MONEY'}, follow_redirects=True))
with app.app_context():
    check(not db.session.get(Aide, a1_id).is_paid and 'insuffisante' in h, 'caisse de secours insuffisante : versement bloqué')
    db.session.add(Transaction(tontine_id=tid, member_id=mem['Rose'], type='SECOURS', amount=30000, date=date.today()))
    db.session.add(Sanction(tontine_id=tid, member_id=mem['Paul'], type_sanction='ABSENCE', amount=Decimal('500'),
                            description='Absence', sanction_date=date.today(), status='PENDING'))
    db.session.commit()
jean.post(f'/aides/{a1_id}/pay', data={'payment_mode': 'ORANGE_MONEY'})
with app.app_context():
    a = db.session.get(Aide, a1_id)
    check(a.is_paid and a.sanctions_deducted == Decimal('500'), 'aide versée, amende de 500 retenue')
    check(Transaction.query.filter_by(member_id=mem['Paul'], type='AIDE').one().amount == Decimal('10000'), 'écriture « Aide » de 10 000 (sortie de la caisse de secours)')
    check(Sanction.query.filter_by(member_id=mem['Paul'], status='PENDING').count() == 0, "l'amende retenue est soldée")
jean.post(f'/aides/{a1_id}/pay')
with app.app_context():
    check(Transaction.query.filter_by(member_id=mem['Paul'], type='AIDE').count() == 1, 'pas de double versement')

# ---------------------------------------------------------------- 6. confidentialité
check(paul.get(f'/aides/{a1_id}/justificatif').status_code == 200, 'le membre voit son propre justificatif')
check(rose.get(f'/aides/{a1_id}/justificatif').status_code == 200, 'la secrétaire voit le justificatif')
check(awa.get(f'/aides/{a1_id}/justificatif').status_code == 404, "un autre membre ne voit pas le justificatif")
check('Naissance de ma fille' not in body(awa.get('/aides')), "un autre membre ne voit pas les demandes de Paul")
with app.app_context():
    jsb_pres = User.query.filter(User.username == 'president', User.tontine_id != tid).first()
    jsb_pres.set_password('JsbPass123')
    db.session.commit()
jsb = app.test_client()
jsb.post('/login', data={'tontine': 'jsb', 'username': 'president', 'password': 'JsbPass123'})
check(jsb.get(f'/aides/{a1_id}/justificatif').status_code == 404, "une autre tontine ne voit pas le justificatif")
check(jsb.get('/aides').status_code == 200, 'les anciennes aides (avant le barème) restent consultables')

# ---------------------------------------------------------------- 7. refus motivé, dérogation du président
ask(awa)
with app.app_context():
    check(Aide.query.filter_by(member_id=mem['Awa']).count() == 0, 'Awa (nouvelle, sans fonds de caisse) : refusée')
pres.post('/aides/request', data={'member_id': mem['Awa'], 'aid_type_id': types['DECES_PARENT'], 'event_date': ten_days_ago,
                                  'document': doc(), 'derogation': 'Dérogation votée en AG du 12/10'},
          content_type='multipart/form-data')
with app.app_context():
    a = Aide.query.filter_by(member_id=mem['Awa']).one()
    check(a.amount == Decimal('25000') and 'Dérogation' in (a.description or ''), 'dérogation du président tracée dans la demande')
    awa_aid = a.id
pres.post(f'/aides/{awa_aid}/reject', data={'reason': 'Justificatif illisible'})
with app.app_context():
    a = db.session.get(Aide, awa_aid)
    check(a.status == 'REJECTED' and a.rejection_reason == 'Justificatif illisible', 'refus avec motif')

# ---------------------------------------------------------------- 8. paramètres
pres.post('/parametres/aides', data={'section': 'rules', 'aid_min_seniority_days': '30', 'aid_declaration_days': '60',
                                     'max_aid_per_member': '2', 'aid_require_secours': 'on', 'aid_double_validation': 'on'})
with app.app_context():
    t = db.session.get(Tontine, tid)
    check(t.aid_min_seniority_days == 30 and t.aid_require_fonds_caisse is False and t.aid_deduct_sanctions is False
          and t.max_aid_per_member == 2, 'règles enregistrées (fonds de caisse non exigé, amendes non retenues)')
pres.post('/parametres/aides', data={'section': 'type', 'type_id': types['MARIAGE'], 'name': 'Mariage', 'amount': '20000',
                                     'max_per_year': '1', 'requires_document': 'on'})
with app.app_context():
    mt = db.session.get(AidType, types['MARIAGE'])
    check(mt.amount == Decimal('20000') and not mt.is_active, "barème modifié, case « Actif » décochée = désactivé")
pres.post('/parametres/aides', data={'section': 'type', 'name': 'Rentrée scolaire', 'amount': '7500', 'max_per_year': '1',
                                     'requires_document': 'on'})
with app.app_context():
    check(AidType.query.filter_by(tontine_id=tid, name='Rentrée scolaire', is_active=True).count() == 1, 'nouvel événement ajouté au barème')
h = body(pres.get('/parametres'))
check('id="aides"' in h and 'form="aidType' in h, 'section Aides sociales dans Paramètres (champs reliés à leur formulaire)')
check(paul.post('/parametres/aides', data={'section': 'rules'}).status_code == 302, 'un membre ne peut pas modifier les règles')

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)

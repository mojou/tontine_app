"""Fermer une séance = l'archiver (lecture seule, historique) ; supprimer seulement une séance vide ;
rouvrir : président seulement, avec motif."""
import html
import os
import re
import sys

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'sa2.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'))
from models import Tontine, Member, ContributionType, Seance, SeanceEvent, AuditLog  # noqa: E402
from tenancy import tenant_bypass  # noqa: E402

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def text(r):
    h = re.sub(r'(?s)<(script|style)\b.*?</\1>', ' ', r.get_data(as_text=True))
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', h)))


pres = app.test_client()
pres.post('/inscription', data={'name': 'Tontine Archives', 'slug': 'archives', 'first_name': 'Hélène', 'last_name': 'Ngo',
                                'email': 'h@arch.cm', 'phone': '699000001', 'username': 'helene',
                                'password': 'Mbalmayo2026', 'password_confirm': 'Mbalmayo2026'})
pres.post('/members/add', data={'first_name': 'Paul', 'last_name': 'Tresor', 'email': 'paul@arch.cm', 'phone': '699111220',
                                'username': 'paul', 'role': 'TRESORIER', 'password': 'Passw0rd1', 'confirm_password': 'Passw0rd1'})
with app.app_context(), tenant_bypass():
    tid = Tontine.query.filter_by(slug='archives').one().id
    paul_mid = Member.query.filter_by(tontine_id=tid, first_name='Paul').one().id
    presence = ContributionType.query.filter_by(tontine_id=tid, category='PRESENCE').first().id
tres = app.test_client()
tres.post('/login', data={'tontine': 'archives', 'username': 'paul', 'password': 'Passw0rd1'})


def new_seance(title):
    pres.post('/seances/add', data={'date': m.date.today().isoformat(), 'title': title, 'columns': [f'r{presence}']})
    with app.app_context(), tenant_bypass():
        return Seance.query.filter_by(tontine_id=tid, title=title).one().id


# ---------------------------------------------------------------- séance vide : suppression possible
s_vide = new_seance('Ouverte par erreur')
h = pres.get(f'/seances/{s_vide}').get_data(as_text=True)
check('Supprimer (vide)' in h, 'séance vide : bouton « Supprimer (vide) »')
r = pres.post(f'/seances/{s_vide}/delete', follow_redirects=True)
with app.app_context(), tenant_bypass():
    check(Seance.query.filter_by(id=s_vide).first() is None and 'supprimée (elle était vide)' in text(r), 'séance vide supprimée')
    check(AuditLog.query.filter(AuditLog.action.like('%Ouverte par erreur%vide%')).count() == 1,
          "la suppression est notée dans l'historique des actions")

# ---------------------------------------------------------------- séance avec de l'argent : pas de suppression
sid = new_seance('Réunion du mois')
pres.post(f'/seances/{sid}', data={'payment_mode': 'ESPECE', f'pay_{paul_mid}_r{presence}': 'on', f'amt_{paul_mid}_r{presence}': '500'})
h = pres.get(f'/seances/{sid}').get_data(as_text=True)
check('Supprimer (vide)' not in h, "séance avec des paiements : pas de bouton « Supprimer »")
r = pres.post(f'/seances/{sid}/delete', follow_redirects=True)
with app.app_context(), tenant_bypass():
    check(Seance.query.filter_by(id=sid).first() is not None and 'on ne peut pas la supprimer' in text(r),
          'suppression refusée : les comptes en dépendent, elle reste dans les archives')

# ---------------------------------------------------------------- fermer = archiver
check('Réunion du mois' in text(pres.get('/seances')), 'avant fermeture : la séance est dans « En cours »')
r = pres.post(f'/seances/{sid}/close', follow_redirects=True)
check('rangée dans les Archives' in text(r), 'fermeture : message « rangée dans les Archives »')
with app.app_context(), tenant_bypass():
    se = db.session.get(Seance, sid)
    check(se.is_closed and se.closed_at is not None and se.closed_by is not None, 'séance fermée : date et auteur de la fermeture gardés')
check('Réunion du mois' not in text(pres.get('/seances')), 'elle disparaît de « En cours »…')
t = text(pres.get('/seances?vue=archives'))
check('Réunion du mois' in t and 'Archivée' in t, '… et apparaît dans « Archives »')
t = text(pres.get(f'/seances/{sid}'))
check('Séance archivée' in t and 'lecture seule' in t and 'Enregistrer les paiements cochés' not in t,
      'séance archivée : lecture seule (plus d\'enregistrement possible)')
r = pres.post(f'/seances/{sid}', data={'payment_mode': 'ESPECE', f'pay_{paul_mid}_r{presence}': 'on', f'amt_{paul_mid}_r{presence}': '500'},
              follow_redirects=True)
check('fermée' in text(r), 'on ne peut plus ajouter de paiement à une séance archivée')

# ---------------------------------------------------------------- rouvrir : président seulement, avec motif
r = tres.post(f'/seances/{sid}/close', data={'reason': 'je veux'}, follow_redirects=True)
with app.app_context(), tenant_bypass():
    check(db.session.get(Seance, sid).is_closed and 'Seul le président' in text(r), 'le trésorier ne peut pas rouvrir une séance archivée')
r = pres.post(f'/seances/{sid}/close', data={'reason': ''}, follow_redirects=True)
with app.app_context(), tenant_bypass():
    check(db.session.get(Seance, sid).is_closed and 'motif' in text(r), 'sans motif : réouverture refusée')
r = pres.post(f'/seances/{sid}/close', data={'reason': 'oubli du paiement de Rose'}, follow_redirects=True)
with app.app_context(), tenant_bypass():
    check(not db.session.get(Seance, sid).is_closed and 'Séance rouverte' in text(r), 'le président rouvre avec un motif')
    evs = [(e.action, e.detail) for e in SeanceEvent.query.filter_by(seance_id=sid).order_by(SeanceEvent.id).all()]
    check([a for a, _ in evs] == ['FERMEE', 'ROUVERTE'] and 'oubli du paiement de Rose' in evs[1][1],
          'fermeture et réouverture (avec son motif) sont gardées')

# ---------------------------------------------------------------- historique visible dans la séance
t = text(pres.get(f'/seances/{sid}'))
check('Historique de la séance' in t and 'Séance ouverte' in t and '1 paiement(s) reçu(s) : 500 FCFA' in t
      and 'Séance fermée et archivée' in t and 'Rouverte - motif : oubli du paiement de Rose' in t,
      "historique : ouverture, paiements reçus, fermeture, réouverture avec motif")
check('Imprimer le résumé' in t, 'bouton « Imprimer le résumé »')

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)

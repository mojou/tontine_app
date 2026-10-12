"""Tirage de l'ordre de passage : automatique (par l'application) ou manuel (tirage en réunion, numéros écrits ensuite)."""
import html
import os
import re
import sys

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'tm.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'))
from models import Tontine, Member, ContributionType, TontineCycleDetail, CycleParticipant, TontineDraw  # noqa: E402

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def text(r):
    h = re.sub(r'(?s)<(script|style)\b.*?</\1>', ' ', r.get_data(as_text=True))
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', h)))


pres = app.test_client()
pres.post('/inscription', data={'name': 'Tontine Tirage', 'slug': 'tirage', 'first_name': 'Hélène', 'last_name': 'Ngo',
                                'email': 'h@tirage.cm', 'phone': '699000001', 'username': 'helene',
                                'password': 'Mbalmayo2026', 'password_confirm': 'Mbalmayo2026'})
names = ['Marc', 'Awa', 'Kofi']
for i, first in enumerate(names):
    pres.post('/members/add', data={'first_name': first, 'last_name': 'Test', 'email': f'{first.lower()}@tirage.cm',
                                    'phone': f'69911122{i}', 'username': first.lower(), 'role': 'MEMBRE',
                                    'password': 'Passw0rd1', 'confirm_password': 'Passw0rd1'})
with app.app_context():
    tid = Tontine.query.filter_by(slug='tirage').one().id
    ids = {x.first_name: x.id for x in Member.query.filter_by(tontine_id=tid).all()}
    level = ContributionType.query.filter_by(tontine_id=tid, category='TONTINE').first().id

# ---------------------------------------------------------------- réglage
t = text(pres.get('/parametres'))
check("Tirage de l'ordre de passage" in t and "Règle actuelle : automatique" in t, 'Paramètres : réglage du tirage, automatique par défaut')
marc = app.test_client()
marc.post('/login', data={'tontine': 'tirage', 'username': 'marc', 'password': 'Passw0rd1'})
marc.post('/parametres/tirage', data={'draw_mode': 'MANUEL'})
with app.app_context():
    check(not db.session.get(Tontine, tid).draw_is_manual, 'un membre ne peut pas changer le mode de tirage')
r = pres.post('/parametres/tirage', data={'draw_mode': 'MANUEL'}, follow_redirects=True)
check('Règle enregistrée : tirage fait en réunion' in text(r) and 'Règle actuelle : manuel' in text(r), 'le président choisit « manuel »')
check(pres.post('/parametres/tirage', data={'draw_mode': 'N_IMPORTE'}).status_code == 400, 'valeur inconnue refusée')

# ---------------------------------------------------------------- création du cycle en mode manuel
check("Écrire l'ordre de passage tout de suite" in text(pres.get('/tontine-cycles/add')), 'formulaire du cycle : « Écrire l\'ordre de passage »')
r = pres.post('/tontine-cycles/add', data={'contribution_type_id': level, 'mode': 'TIRAGE', 'draw_now': 'on',
                                           f'hands_{ids["Marc"]}': 2, f'hands_{ids["Awa"]}': 1, f'hands_{ids["Kofi"]}': 1})
with app.app_context():
    cyc = TontineCycleDetail.query.filter_by(tontine_id=tid).one()
    cid = cyc.id
    parts = {p.id: (p.member_id, p.hand_number) for p in cyc.participants}
    check(TontineDraw.query.filter_by(cycle_id=cid).count() == 0 and all(p.position is None for p in cyc.participants),
          "mode manuel : l'application ne tire pas au sort à la création")
check(r.status_code == 302 and r.headers['Location'].endswith(f'/tontine-cycles/{cid}/tirage'), 'on arrive sur la page pour écrire l\'ordre')
h = pres.get(f'/tontine-cycles/{cid}/tirage').get_data(as_text=True)
check("Écrire l'ordre de passage" in h and h.count('class="form-control form-control-sm pos-input"') == 4 and 'Lancer le tirage' not in h,
      '4 mains à numéroter (Marc a 2 mains), pas de bouton de tirage automatique')
by_hand = {v: k for k, v in parts.items()}
pids = [by_hand[(ids['Marc'], 1)], by_hand[(ids['Marc'], 2)], by_hand[(ids['Awa'], 1)], by_hand[(ids['Kofi'], 1)]]


def send(numbers, notes=''):
    data = {f'pos_{pid}': str(n) for pid, n in zip(pids, numbers) if n is not None}
    data['notes'] = notes
    return pres.post(f'/tontine-cycles/{cid}/tirage', data=data, follow_redirects=True)


def positions():
    with app.app_context():
        return [db.session.get(CycleParticipant, pid).position for pid in pids]


r = send([1, 2, 2, 4])
check('Le numéro 2 est donné deux fois' in text(r) and positions() == [None] * 4, 'numéro en double : refusé, rien enregistré')
check('value="4"' in r.get_data(as_text=True), 'les numéros déjà écrits restent dans le formulaire')
r = send([1, 2, 3, 9])
check('le numéro doit être entre 1 et 4' in text(r) and positions() == [None] * 4, 'numéro hors limite : refusé')
r = send([1, 2, 3, None])
check('Numéro manquant pour Kofi Test' in text(r) and positions() == [None] * 4, 'numéro manquant : refusé')
r = send([3, 1, 4, 2], 'Tirage en réunion du 12/10')
check(positions() == [3, 1, 4, 2] and 'Ordre de passage enregistré' in text(r), 'ordre écrit : Marc 3 et 1, Awa 4, Kofi 2')
with app.app_context():
    d = TontineDraw.query.filter_by(cycle_id=cid).one()
    check(d.is_manual and [(x.position, x.member_id) for x in d.results] ==
          [(1, ids['Marc']), (2, ids['Kofi']), (3, ids['Marc']), (4, ids['Awa'])], "l'ordre est gardé dans l'historique, marqué « en réunion »")
    check(db.session.get(TontineCycleDetail, cid).get_next_participant().member_id == ids['Marc'], 'le n° 1 reçoit la première cagnotte')
t = text(marc.get('/tirages'))
check('Tirage en réunion' in t, 'les membres voient le tirage dans l\'historique')

# ---------------------------------------------------------------- après le premier tour : seules les mains restantes
pres.post(f'/tontine-cycles/{cid}/register-benefit', data={'expected_turn': 1, 'payment_mode': 'ESPECE', 'confirm_offline': 'on'})
with app.app_context():
    check(db.session.get(TontineCycleDetail, cid).beneficiaries_count == 1, 'tour 1 versé')
h = pres.get(f'/tontine-cycles/{cid}/tirage').get_data(as_text=True)
check(h.count('pos-input"') == 3 and 'min="2" max="4"' in h, 'nouvel ordre : 3 mains restantes, numéros 2 à 4')
served = pids[1]
pids = [p for p in pids if p != served]
r = send([1, 2, 3])
check('le numéro doit être entre 2 et 4' in text(r), 'le n° 1 est déjà pris par celui qui a reçu')
send([2, 4, 3])
check(positions() == [2, 4, 3], 'nouvel ordre enregistré pour les mains restantes')

# ---------------------------------------------------------------- retour au mode automatique
pres.post('/parametres/tirage', data={'draw_mode': 'AUTO'})
r = pres.post(f'/tontine-cycles/{cid}/tirage', data={'notes': ''})
with app.app_context():
    last = TontineDraw.query.filter_by(cycle_id=cid).order_by(TontineDraw.id.desc()).first()
    check(r.status_code == 302 and 'reveal=' in r.headers['Location'] and not last.is_manual,
          'mode automatique : le tirage est fait par l\'application')
    check(sorted(positions()) == [2, 3, 4], 'les mains restantes gardent les numéros 2 à 4')

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)

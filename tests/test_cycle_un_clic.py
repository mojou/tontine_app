"""Verser la cagnotte en UNE étape : on coche qui a payé sa part (enregistrée avec le versement), sans « Régulariser ».
Versement fait depuis la page du cycle : rattaché à la séance ouverte du jour. Membre recréé / mot de passe provisoire."""
import html
import os
import re
import sys
from decimal import Decimal

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'uc.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'), FORCE_PASSWORD_CHANGE=True)
from models import (Tontine, Member, ContributionType, TontineCycleDetail, CycleParticipant, CycleBeneficiary,  # noqa: E402
                    Transaction, Sanction, Seance, User)

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def text(r):
    h = re.sub(r'(?s)<(script|style)\b.*?</\1>', ' ', r.get_data(as_text=True))
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', h)))


pres = app.test_client()
pres.post('/inscription', data={'name': 'Tontine Un Clic', 'slug': 'unclic', 'first_name': 'Hélène', 'last_name': 'Ngo',
                                'email': 'h@unclic.cm', 'phone': '699000001', 'username': 'helene',
                                'password': 'Mbalmayo2026', 'password_confirm': 'Mbalmayo2026'})

# ---------------------------------------------------------------- création des membres par la présidente
r = pres.post('/members/add', data={'first_name': 'Marie', 'last_name': 'Talla', 'email': 'marie@unclic.cm', 'phone': '699111220',
                                    'username': 'marie', 'role': 'MEMBRE', 'password': 'Marie2026', 'confirm_password': 'Marie2026'},
              follow_redirects=True)
check('Membre ajouté' in text(r), 'mot de passe provisoire « Marie2026 » pour « marie » accepté (il sera changé à la 1re connexion)')
c = app.test_client()
r = c.post('/login', data={'tontine': 'unclic', 'username': 'marie', 'password': 'Marie2026'}, follow_redirects=True)
check('Choisissez votre mot de passe' in text(r), 'Marie se connecte avec le mot de passe donné par la présidente')
for i, first in enumerate(['Awa', 'Kofi']):
    pres.post('/members/add', data={'first_name': first, 'last_name': 'Test', 'email': f'{first.lower()}@unclic.cm',
                                    'phone': f'69922233{i}', 'username': first.lower(), 'role': 'MEMBRE',
                                    'password': 'Passw0rd1', 'confirm_password': 'Passw0rd1'})
with app.app_context():
    tid = Tontine.query.filter_by(slug='unclic').one().id
    ids = {x.first_name: x.id for x in Member.query.filter_by(tontine_id=tid).all()}
pres.post(f'/members/{ids["Kofi"]}/delete')
r = pres.post('/members/add', data={'first_name': 'Kofi', 'last_name': 'Mensah', 'email': 'kofi@unclic.cm', 'phone': '699222339',
                                    'username': 'kofi', 'role': 'MEMBRE', 'password': 'Kribi2026', 'confirm_password': 'Kribi2026'},
              follow_redirects=True)
check('Membre ajouté' in text(r) and 'devient « kofi.ancien' in text(r), 'Kofi retiré puis recréé avec le même identifiant et le même e-mail')
k = app.test_client()
check(k.post('/login', data={'tontine': 'unclic', 'username': 'kofi', 'password': 'Kribi2026'}).headers.get('Location', '').endswith('/dashboard'),
      'le nouveau Kofi se connecte avec son nouveau mot de passe')
r = pres.post('/members/add', data={'first_name': 'Awa', 'last_name': 'Bis', 'email': 'awa2@unclic.cm', 'phone': '699222338',
                                    'username': 'awa', 'role': 'MEMBRE', 'password': 'Passw0rd2', 'confirm_password': 'Passw0rd2'},
              follow_redirects=True)
check("L'identifiant « awa » est déjà utilisé par Awa Test" in text(r) and "n'a PAS été créé" in text(r),
      'identifiant d\'un membre actif : refus clair (« n\'a PAS été créé »)')

# ---------------------------------------------------------------- bouton « Retirer » : sur chaque fiche sauf la sienne
with app.app_context():
    pres_user = User.query.filter_by(tontine_id=tid, role='PRESIDENT').one()
    actives = Member.query.filter_by(tontine_id=tid, is_active=True).all()
    others = [x.id for x in actives if x.id != pres_user.member_id]
h = pres.get('/members').get_data(as_text=True)
shown = set(int(x) for x in re.findall(r'data-target="#deleteMemberModal(\d+)"', h))
check(shown == set(others), f"bouton « Retirer » sur tous les membres sauf la présidente elle-même ({len(shown)}/{len(others)})")
# même quand le numéro d'une fiche membre est égal au numéro du compte de la présidente (cas de Boris)
twin = next((x for x in actives if x.id == pres_user.id and x.id != pres_user.member_id), None)
if twin:
    check(twin.id in shown, f'fiche n° {twin.id} (même numéro que le compte de la présidente) : bouton « Retirer » présent')
r = pres.post(f'/members/{pres_user.member_id}/delete', follow_redirects=True)
with app.app_context():
    check(db.session.get(Member, pres_user.member_id).is_active and 'retirer vous-même' in text(r),
          'la présidente ne peut pas se retirer elle-même')

# ---------------------------------------------------------------- cycle de 3 mains (Marie, Awa, Kofi) à 10 000
with app.app_context():
    ids = {x.first_name: x.id for x in Member.query.filter_by(tontine_id=tid, is_active=True).all()}
    level = ContributionType.query.filter_by(tontine_id=tid, category='TONTINE', amount=10000).first().id
pres.post('/tontine-cycles/add', data={'contribution_type_id': level, 'mode': 'TIRAGE', 'draw_now': 'on',
                                       **{f'hands_{ids[n]}': 1 for n in ('Marie', 'Awa', 'Kofi')}})
with app.app_context():
    cid = TontineCycleDetail.query.filter_by(tontine_id=tid).one().id


def contrib():
    with app.app_context():
        m.g.tenant_id = tid
        return m.cycle_contribution_status(db.session.get(TontineCycleDetail, cid))


def verser(turn, paid, seance_id=None):
    data = {'expected_turn': turn, 'payment_mode': 'ESPECE', 'payers_form': '1'}
    data.update({f'paid_{ids[n]}': 'on' for n in paid})
    if seance_id:
        data['seance_id'] = seance_id
    return pres.post(f'/tontine-cycles/{cid}/register-benefit', data=data, follow_redirects=True)


h = text(pres.get(f'/tontine-cycles/{cid}'))
check('Qui a payé sa part ?' in h and 'décochez ceux qui n\'ont pas payé' in h, 'page du cycle : liste « Qui a payé sa part ? », tous cochés')

# Séance ouverte aujourd'hui avec ce cycle : le versement fait depuis la page du cycle s'y rattache
pres.post('/seances/add', data={'date': m.date.today().isoformat(), 'columns': [f'c{cid}']})
with app.app_context():
    sid = Seance.query.filter_by(tontine_id=tid).one().id

# Tour 1 : tout le monde a payé -> une seule action, cagnotte complète
r = verser(1, ['Marie', 'Awa', 'Kofi'])
with app.app_context():
    b1 = CycleBeneficiary.query.filter_by(cycle_id=cid, position=1).one()
    parts = Transaction.query.filter_by(cycle_id=cid, type='TONTINE').count()
    check(b1.net_amount == 30000 and parts == 3, 'tour 1 : les 3 parts enregistrées avec le versement, cagnotte complète 30 000')
    check(all(t.seance_id == sid for t in Transaction.query.filter_by(cycle_id=cid).all()),
          'parts et cagnotte rattachées à la séance ouverte du jour (versement fait depuis la page du cycle)')
    check(Transaction.query.filter(Transaction.description.like('Rattrapage%')).count() == 0, 'aucun « Régulariser » nécessaire')
check(contrib()['late_total'] == 0, 'état des cotisations : personne en retard')
r = pres.get(f'/seances/{sid}')
check('30 000' in text(r), 'la séance affiche les 30 000 reçus et la cagnotte versée')

# Tour 2 : un membre n'a pas payé -> on le décoche : cagnotte réduite + amende, sans autre manipulation
with app.app_context():
    nxt = TontineCycleDetail.query.get(cid).get_next_participant()
    unpaid = [n for n in ('Marie', 'Awa', 'Kofi') if ids[n] != nxt.member_id][0]
    paid2 = [n for n in ('Marie', 'Awa', 'Kofi') if n != unpaid]
verser(2, paid2)
with app.app_context():
    b2 = CycleBeneficiary.query.filter_by(cycle_id=cid, position=2).one()
    check(b2.net_amount == 20000 and b2.pending_amount == 10000, f'tour 2 : {unpaid} décoché -> cagnotte réduite 20 000 (10 000 à recevoir)')
    check(Sanction.query.filter_by(member_id=ids[unpaid], status='PENDING').count() == 1, f'{unpaid} reçoit l\'amende de retard')
check(contrib()['late_total'] == 10000, f'état : {unpaid} doit 10 000')

# Tour 3 : le retardataire paie sa part + son retard -> enregistré en une fois, le bénéficiaire du tour 2 est complété
verser(3, ['Marie', 'Awa', 'Kofi'])
with app.app_context():
    b2 = CycleBeneficiary.query.filter_by(cycle_id=cid, position=2).one()
    late_tx = Transaction.query.filter_by(cycle_id=cid, member_id=ids[unpaid], type='TONTINE').order_by(Transaction.id.desc()).first()
    check(late_tx.amount == 20000 and 'dont retard 10 000' in late_tx.description, f'{unpaid} paie 20 000 (sa part + son retard) en une fois')
    check(b2.net_amount == 30000 and not b2.pending_amount, 'le bénéficiaire du tour 2 reçoit automatiquement les 10 000 qui manquaient')
    cy = db.session.get(TontineCycleDetail, cid)
    check(cy.status == 'TERMINE' and contrib()['late_total'] == 0 and contrib()['advance_total'] == 0,
          'cycle terminé, aucun écart : rien à régulariser')

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)

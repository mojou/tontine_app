"""Séance ↔ cycle : verser la cagnotte du tour depuis la feuille de séance."""
import html
import re
import os
import sys
from decimal import Decimal

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'sc.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'))
from models import (Tontine, Member, Transaction, ContributionType, TontineCycleDetail, Seance,  # noqa: E402
                    CycleBeneficiary, Sanction)

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def body(r):
    return re.sub(r"\s+", " ", re.sub(r"</?(strong|span)[^>]*>", "", html.unescape(r.get_data(as_text=True))))


c = app.test_client()
c.post('/inscription', data={'name': 'Njangi Akwa', 'slug': 'akwa', 'first_name': 'Hélène', 'last_name': 'Ekwalla',
                             'email': 'h@akwa.cm', 'phone': '699000009', 'username': 'helene',
                             'password': 'Helene2026', 'password_confirm': 'Helene2026'})
for i, (fn, role) in enumerate([('Paul', 'MEMBRE'), ('Rose', 'CENSEUR'), ('Jean', 'TRESORIER')]):
    c.post('/members/add', data={'first_name': fn, 'last_name': 'Eboa', 'email': f'{fn.lower()}@akwa.cm', 'phone': f'69922233{i}',
                                 'username': fn.lower(), 'role': role, 'password': 'Passw0rd1', 'confirm_password': 'Passw0rd1'})
with app.app_context():
    tid = Tontine.query.filter_by(slug='akwa').one().id
    mem = {x.first_name: x.id for x in Member.query.filter_by(tontine_id=tid).all()}
    lv = {int(x.amount): x.id for x in ContributionType.query.filter_by(tontine_id=tid, category='TONTINE').all()}
    rub = {x.category: x.id for x in ContributionType.query.filter_by(tontine_id=tid).all() if x.category != 'TONTINE'}

# Cycle 10 000 par tirage (4 mains) et cycle 10 000... par enchère sur un autre niveau
c.post('/cotisations/rubriques/add', data={'category': 'TONTINE', 'amount': '5000', 'frequency': 'BIMENSUEL', 'next': '/parametres'})
with app.app_context():
    lv = {int(x.amount): x.id for x in ContributionType.query.filter_by(tontine_id=tid, category='TONTINE').all()}
c.post('/tontine-cycles/add', data={'contribution_type_id': lv[10000], 'mode': 'TIRAGE', 'draw_now': 'on',
                                    **{f'hands_{mid}': 1 for mid in mem.values()}})
c.post('/tontine-cycles/add', data={'contribution_type_id': lv[5000], 'mode': 'ENCHERE',
                                    f'hands_{mem["Paul"]}': 1, f'hands_{mem["Rose"]}': 1})
with app.app_context():
    cyc = {int(x.amount_per_member): x for x in TontineCycleDetail.query.filter_by(tontine_id=tid).all()}
    tirage, enchere = cyc[10000].id, cyc[5000].id
    first = cyc[10000].get_next_participant()
    first_member, first_label = first.member_id, first.label
    # une amende impayée du premier bénéficiaire, à retenir sur la cagnotte
    db.session.add(Sanction(tontine_id=tid, member_id=first_member, type_sanction='RETARD_REUNION', amount=Decimal('500'),
                            sanction_date=m.date.today(), status='PENDING', description='Retard'))
    db.session.commit()
check(len(cyc) == 2, 'deux cycles en cours (tirage et enchère)')

c.post('/seances/add', data={'date': m.date.today().isoformat(), 'columns': [f'c{tirage}', f'c{enchere}', f'r{rub["PRESENCE"]}']})
with app.app_context():
    sid = Seance.query.filter_by(tontine_id=tid).one().id

# ---------------------------------------------------------------- feuille : bloc « Cagnottes du jour »
h = body(c.get(f'/seances/{sid}'))
check('id="cagnottes"' in h and 'Cagnottes du jour' in h, 'la feuille de séance affiche les cagnottes du jour')
check(f'Tour 1 : {first_label}' in h, f'le bénéficiaire prévu du tirage est proposé ({first_label})')
check("40 000 FCFA de cotisations n'ont pas été enregistrées" in h and 'name="confirm_offline"' in h,
      "alerte tant que les cotisations du tour ne sont pas enregistrées")

# ---------------------------------------------------------------- versement refusé sans les cotisations
r = c.post(f'/tontine-cycles/{tirage}/register-benefit', data={'expected_turn': 1, 'seance_id': sid, 'payment_mode': 'ESPECE'})
with app.app_context():
    check(CycleBeneficiary.query.filter_by(cycle_id=tirage).count() == 0,
          'cagnotte refusée tant que les cotisations du tour ne sont pas enregistrées')
check('Amendes impayées : 500 FCFA' in h, "les amendes du bénéficiaire sont signalées")
check('Enchère du tour 1' in h and 'name="bid_amount"' in h, "le cycle par enchère propose gagnant et mise")

# encaissement des 4 parts
form = {'payment_mode': 'ESPECE'}
for mid in mem.values():
    form[f'pay_{mid}_c{tirage}'] = 'on'
    form[f'amt_{mid}_c{tirage}'] = '10000'
c.post(f'/seances/{sid}', data=form)
h = body(c.get(f'/seances/{sid}'))
check("n'ont pas été enregistrées" not in h.split(f'data-cycle="{tirage}"')[1].split('data-cycle=')[0], 'plus d\'alerte une fois les 4 parts encaissées')

# ---------------------------------------------------------------- droits
censeur = app.test_client()
censeur.post('/login', data={'tontine': 'akwa', 'username': 'rose', 'password': 'Passw0rd1'})
hc = body(censeur.get(f'/seances/{sid}'))
check('Cagnottes du jour' in hc and 'Verser la cagnotte' not in hc, 'le censeur voit les cagnottes sans pouvoir verser')
r = censeur.post(f'/tontine-cycles/{tirage}/register-benefit', data={'expected_turn': 1, 'seance_id': sid})
with app.app_context():
    check(CycleBeneficiary.query.filter_by(cycle_id=tirage).count() == 0, 'le censeur ne peut pas verser')

# ---------------------------------------------------------------- versement depuis la séance
r = c.post(f'/tontine-cycles/{tirage}/register-benefit', data={'expected_turn': 1, 'seance_id': sid, 'payment_mode': 'ESPECE',
                                                               'deduct_sanctions': 'on'})
check(r.status_code == 302 and f'/seances/{sid}' in r.headers['Location'], 'après versement on revient à la feuille de séance')
with app.app_context():
    b = CycleBeneficiary.query.filter_by(cycle_id=tirage).one()
    check(b.member_id == first_member and b.net_amount == Decimal('39500'), f'cagnotte 40 000 − amende 500 = {b.net_amount}')
    tx = Transaction.query.filter_by(cycle_id=tirage, type='BENEFICE_TONTINE').one()
    check(tx.seance_id == sid, 'le versement est rattaché à la séance')
    check(Transaction.query.filter_by(seance_id=sid, type='SANCTION').count() == 1, "l'amende retenue est rattachée à la séance")
    s = db.session.get(Seance, sid)
    check(s.total_collected == Decimal('40500') and s.total_paid_out == Decimal('40000'),
          f'séance : encaissé {s.total_collected} (parts + amende), versé {s.total_paid_out}')

# double clic : même tour renvoyé
c.post(f'/tontine-cycles/{tirage}/register-benefit', data={'expected_turn': 1, 'seance_id': sid, 'payment_mode': 'ESPECE'})
with app.app_context():
    check(CycleBeneficiary.query.filter_by(cycle_id=tirage).count() == 1, 'double clic : la cagnotte n\'est pas versée deux fois')
h = body(c.get(f'/seances/{sid}'))
check('Versée pendant cette séance à' in h and 'Tour 2 :' in h, 'la feuille montre le versement fait et propose le tour suivant')
check('Cagnottes versées : 40 000 FCFA' in h, "l'en-tête affiche le total versé")
check('40 500 FCFA' in body(c.get('/seances')), 'la liste des séances compte les encaissements, pas les sorties')

# ---------------------------------------------------------------- enchère depuis la séance
with app.app_context():
    from models import CycleParticipant
    rose_part = CycleParticipant.query.filter_by(cycle_id=enchere, member_id=mem['Rose']).one().id
c.post(f'/tontine-cycles/{enchere}/register-benefit', data={'expected_turn': 1, 'seance_id': sid, 'participant_id': rose_part,
                                                            'bid_amount': '1000', 'payment_mode': 'ESPECE', 'confirm_offline': 'on'})
with app.app_context():
    b = CycleBeneficiary.query.filter_by(cycle_id=enchere).one()
    check(b.member_id == mem['Rose'] and b.net_amount == Decimal('9000'), f'enchère depuis la séance : 10 000 − mise 1 000 = {b.net_amount}')
    check(Transaction.query.filter_by(seance_id=sid, type='ENCHERE').count() == 1, 'la mise est rattachée à la séance')
    reg = Transaction.query.filter(Transaction.cycle_id == enchere, Transaction.type == 'TONTINE',
                                   Transaction.description.like('Régularisation%')).all()
    check(len(reg) == 2 and sum(t.amount for t in reg) == Decimal('10000'),
          "« encaissées hors application » : les 2 cotisations manquantes sont enregistrées (10 000)")
    st = m.cycle_contribution_status(db.session.get(TontineCycleDetail, enchere), through_turn=1)
    check(st['missing'] == 0, 'après régularisation, le cycle par enchère est à jour')

# ---------------------------------------------------------------- garde-fous
c.post('/seances/add', data={'date': m.date.today().isoformat(), 'title': 'Autre', 'columns': [f'r{rub["PRESENCE"]}']})
with app.app_context():
    other = Seance.query.filter_by(tontine_id=tid, title='Autre').one().id
r = c.post(f'/tontine-cycles/{tirage}/register-benefit', data={'expected_turn': 2, 'seance_id': other, 'payment_mode': 'ESPECE'})
with app.app_context():
    check(CycleBeneficiary.query.filter_by(cycle_id=tirage).count() == 1, 'refus si le cycle ne fait pas partie de la séance')
c.post(f'/seances/{sid}/close')
c.post(f'/tontine-cycles/{tirage}/register-benefit', data={'expected_turn': 2, 'seance_id': sid, 'payment_mode': 'ESPECE'})
with app.app_context():
    check(CycleBeneficiary.query.filter_by(cycle_id=tirage).count() == 1, 'refus si la séance est clôturée')
check('Verser la cagnotte' not in body(c.get(f'/seances/{sid}')), 'séance clôturée : plus de bouton de versement')
check(c.post(f'/tontine-cycles/{tirage}/register-benefit', data={'expected_turn': 2, 'seance_id': 99999}).status_code == 404,
      'séance inconnue : 404')
# le versement classique depuis la page du cycle fonctionne toujours
r = c.post(f'/tontine-cycles/{tirage}/register-benefit', data={'expected_turn': 2, 'payment_mode': 'ESPECE', 'confirm_offline': 'on'})
with app.app_context():
    check(CycleBeneficiary.query.filter_by(cycle_id=tirage).count() == 2
          and Transaction.query.filter_by(cycle_id=tirage, type='BENEFICE_TONTINE', seance_id=None).count() == 1,
          'le versement depuis la page du cycle reste possible (sans séance)')

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)

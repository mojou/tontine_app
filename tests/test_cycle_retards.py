"""Cycle : montant composé (1 000 / 2 000 / 5 000 / 10 000), cagnotte réduite quand un membre ne paie pas,
amende de 10 %, retard réclamé à la séance suivante et reversé au bénéficiaire quand il est payé."""
import html
import os
import re
import sys
from decimal import Decimal

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'cr.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'))
from models import (Tontine, Member, ContributionType, TontineCycleDetail, Transaction, Seance, Sanction,  # noqa: E402
                    CycleBeneficiary, CycleShortfall)
from tenancy import tenant_bypass  # noqa: E402

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def text(r):
    h = re.sub(r'(?s)<(script|style)\b.*?</\1>', ' ', r.get_data(as_text=True))
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', h)))


c = app.test_client()
c.post('/inscription', data={'name': 'Tontine Retards', 'slug': 'retards', 'first_name': 'Ana', 'last_name': 'Abena',
                             'email': 'ana@retards.cm', 'phone': '699000001', 'username': 'ana',
                             'password': 'Retard2026x', 'password_confirm': 'Retard2026x'})
for i, fn in enumerate(['Ben', 'Cle', 'Dan']):
    c.post('/members/add', data={'first_name': fn, 'last_name': 'Test', 'email': f'{fn.lower()}@retards.cm',
                                 'phone': f'69911122{i}', 'username': fn.lower(), 'role': 'MEMBRE',
                                 'password': 'Passw0rd1', 'confirm_password': 'Passw0rd1'})
with app.app_context(), tenant_bypass():
    tid = Tontine.query.filter_by(slug='retards').one().id
    ids = {x.first_name: x.id for x in Member.query.filter_by(tontine_id=tid).all()}

# ---------------------------------------------------------------- 1. montant composé
h = c.get('/tontine-cycles/add').get_data(as_text=True)
check(all(f'data-bill="{b}"' in h for b in (1000, 2000, 5000, 10000)) and 'id="composerClear"' in h,
      'formulaire : boutons +1 000, +2 000, +5 000, +10 000 et « Effacer »')
check('Montants déjà utilisés' in h and 'data-amount="10000"' in h, 'les montants existants restent proposés en raccourci')
r = c.post('/tontine-cycles/add', data={'contribution_type_id': '', 'custom_amount': '25000', 'mode': 'TIRAGE', 'draw_now': 'on',
                                        **{f'hands_{i}': 1 for i in ids.values()}})
with app.app_context(), tenant_bypass():
    cy = TontineCycleDetail.query.filter_by(tontine_id=tid).order_by(TontineCycleDetail.id.desc()).first()
    cid = cy.id
    lvl = cy.contribution_type
    check(int(cy.amount_per_member) == 25000 and lvl is not None and lvl.name == 'Tontine 25 000' and lvl.category == 'TONTINE',
          '25 000 composé (10 000 + 10 000 + 5 000) : cycle créé et rubrique « Tontine 25 000 » créée automatiquement')
    lvl.late_fine = Decimal('500')   # amende de séance sur ce niveau : ne doit pas s'ajouter à l'amende de 10 %
    db.session.commit()
    n_levels = ContributionType.query.filter_by(tontine_id=tid, category='TONTINE', amount=25000).count()
r = c.post('/tontine-cycles/add', data={'contribution_type_id': '', 'custom_amount': '25000', 'mode': 'TIRAGE',
                                        **{f'hands_{i}': 1 for i in ids.values()}}, follow_redirects=True)
check('est déjà en cours' in text(r), 'second cycle au même montant pendant que le premier tourne : refusé')
with app.app_context(), tenant_bypass():
    check(ContributionType.query.filter_by(tontine_id=tid, category='TONTINE', amount=25000).count() == n_levels == 1,
          'aucune rubrique en double')

# ---------------------------------------------------------------- 2. tour 1 : Cle ne paie pas
c.post('/seances/add', data={'date': m.date.today().isoformat(), 'title': 'Tour 1', 'columns': [f'c{cid}']})
with app.app_context(), tenant_bypass():
    s1 = Seance.query.filter_by(tontine_id=tid, title='Tour 1').one().id
pay = {'payment_mode': 'ESPECE'}
for n in ('Ana', 'Ben', 'Dan'):
    pay[f'pay_{ids[n]}_c{cid}'] = 'on'
    pay[f'amt_{ids[n]}_c{cid}'] = '25000'
c.post(f'/seances/{s1}', data=pay)
h = text(c.get(f'/seances/{s1}'))
check('Qui a payé sa part ?' in h and h.count('paie 25 000 FCFA') == 1 and 'amende de 10 %' in h,
      "le versement liste le membre qui doit encore sa part (25 000), avec l'amende de 10 % s'il est décoché")
r = c.post(f'/tontine-cycles/{cid}/register-benefit', data={'expected_turn': 1, 'seance_id': s1, 'payment_mode': 'ESPECE'},
           follow_redirects=True)
with app.app_context(), tenant_bypass():
    check(CycleBeneficiary.query.filter_by(cycle_id=cid).count() == 0 and 'cagnotte réduite' in text(r),
          'sans choix : rien versé, le bureau doit choisir (réduite ou réellement encaissé)')
r = c.post(f'/tontine-cycles/{cid}/register-benefit', data={'expected_turn': 1, 'seance_id': s1, 'payment_mode': 'ESPECE',
                                                            'late_mode': 'reduite'}, follow_redirects=True)
with app.app_context(), tenant_bypass():
    b1 = CycleBeneficiary.query.filter_by(cycle_id=cid).one()
    first = b1.member_id
    out = sum(t.amount for t in Transaction.query.filter_by(cycle_id=cid, type='BENEFICE_TONTINE'))
    check(b1.net_amount == Decimal('75000') and b1.pending_amount == Decimal('25000') and out == Decimal('75000'),
          f'bénéficiaire du tour 1 : reçoit 75 000, reste à recevoir 25 000 (sorti de la caisse : {out})')
    fine = Sanction.query.filter_by(member_id=ids['Cle'], type_sanction='RETARD_COTISATION').all()
    check(len(fine) == 1 and fine[0].amount == Decimal('2500') and fine[0].status == 'PENDING',
          'Cle : amende de 10 % de sa part (2 500), à payer')
    sf = CycleShortfall.query.filter_by(cycle_id=cid).one()
    check(sf.member_id == ids['Cle'] and sf.amount == Decimal('25000') and sf.beneficiary_id == b1.id,
          'dette de Cle envers le bénéficiaire du tour 1 enregistrée (25 000)')
    check(Transaction.query.filter_by(cycle_id=cid, member_id=ids['Cle'], type='TONTINE').count() == 0,
          "aucun faux paiement enregistré pour Cle")
check('Les parts non payées lui seront reversées' in text(r), 'message clair au bureau')
c.post(f'/seances/{s1}/close')
with app.app_context(), tenant_bypass():
    check(Sanction.query.filter_by(member_id=ids['Cle']).count() == 1,
          'clôture de séance : pas de seconde amende pour la même part (pas de double peine)')
h = text(c.get(f'/tontine-cycles/{cid}'))
check('25 000 FCFA en retard' in h and 'reste à recevoir 25 000 (retards)' in h,
      'page du cycle : retard de Cle et part encore due au bénéficiaire')

# ---------------------------------------------------------------- 3. séance suivante : le retard est réclamé
c.post('/seances/add', data={'date': m.date.today().isoformat(), 'title': 'Tour 2', 'columns': [f'c{cid}']})
with app.app_context(), tenant_bypass():
    s2 = Seance.query.filter_by(tontine_id=tid, title='Tour 2').one().id
raw = c.get(f'/seances/{s2}').get_data(as_text=True)
val = re.search(rf'name="amt_{ids["Cle"]}_c{cid}"[^>]*value="(\d+)"', raw)
check(val and val.group(1) == '50000' and 'dont 25 000 de retard' in html.unescape(raw),
      'séance suivante : Cle doit 50 000 (dont 25 000 de retard)')
val_ben = re.search(rf'name="amt_{ids["Ben"]}_c{cid}"[^>]*value="(\d+)"', raw)
check(val_ben and val_ben.group(1) == '25000', 'Ben, à jour : seulement 25 000 (sa part du tour)')

# Cle ne paie que 25 000 : son retard est réglé en premier et reversé au bénéficiaire du tour 1
c.post(f'/seances/{s2}', data={'payment_mode': 'ORANGE_MONEY', f'pay_{ids["Cle"]}_c{cid}': 'on', f'amt_{ids["Cle"]}_c{cid}': '25000'})
with app.app_context(), tenant_bypass():
    b1 = db.session.get(CycleBeneficiary, b1.id)
    comp = Transaction.query.filter(Transaction.cycle_id == cid, Transaction.member_id == first,
                                    Transaction.description.like('Complément de cagnotte%')).all()
    check(b1.pending_amount == 0 and b1.net_amount == Decimal('100000') and len(comp) == 1 and comp[0].amount == Decimal('25000'),
          'Cle paie 25 000 : reversés au bénéficiaire du tour 1, qui a maintenant ses 100 000')
    check(CycleShortfall.query.filter_by(cycle_id=cid).one().remaining == 0, 'dette de Cle soldée')
    st = m.cycle_contribution_status(db.session.get(TontineCycleDetail, cid))
    cle = next(r for r in st['rows'] if r['member'].id == ids['Cle'])
    check(cle['late'] == 0 and cle['current_due'] == Decimal('25000'), 'Cle : plus de retard, reste sa part du tour 2')
    fund = (sum(t.amount for t in Transaction.query.filter_by(cycle_id=cid, type='TONTINE'))
            - sum(t.amount for t in Transaction.query.filter_by(cycle_id=cid, type='BENEFICE_TONTINE')))
    check(fund == 0, f'caisse du cycle équilibrée ({fund})')

# ---------------------------------------------------------------- 4. tour 2 : Dan ne paie pas ; il régularise plus tard
for n in ('Ana', 'Ben', 'Cle'):
    c.post(f'/seances/{s2}', data={'payment_mode': 'ESPECE', f'pay_{ids[n]}_c{cid}': 'on', f'amt_{ids[n]}_c{cid}': '25000'}) \
        if n != 'Cle' else None
c.post('/seances/add', data={'date': m.date.today().isoformat(), 'title': 'Tour 2 bis', 'columns': [f'c{cid}']})
with app.app_context(), tenant_bypass():
    s3 = Seance.query.filter_by(tontine_id=tid, title='Tour 2 bis').one().id
c.post(f'/seances/{s3}', data={'payment_mode': 'ESPECE', f'pay_{ids["Cle"]}_c{cid}': 'on', f'amt_{ids["Cle"]}_c{cid}': '25000'})
c.post(f'/tontine-cycles/{cid}/register-benefit', data={'expected_turn': 2, 'payment_mode': 'ESPECE', 'late_mode': 'reduite'})
with app.app_context(), tenant_bypass():
    b2 = CycleBeneficiary.query.filter_by(cycle_id=cid, position=2).one()
    check(b2.net_amount == Decimal('75000') and b2.pending_amount == Decimal('25000'), 'tour 2 : Dan ne paie pas, cagnotte réduite à 75 000')
    check(Sanction.query.filter_by(member_id=ids['Dan'], type_sanction='RETARD_COTISATION').one().amount == Decimal('2500'),
          'Dan : amende de 2 500')
r = c.post(f'/tontine-cycles/{cid}/regulariser', data={'member_id': ids['Dan'], 'action': 'encaisser', 'amount': '25000',
                                                       'payment_mode': 'MTN_MOBILE'}, follow_redirects=True)
with app.app_context(), tenant_bypass():
    b2 = db.session.get(CycleBeneficiary, b2.id)
    check(b2.pending_amount == 0 and b2.net_amount == Decimal('100000') and 'reversés' in text(r),
          '« Régulariser » le retard de Dan : reversé au bénéficiaire du tour 2')

# ---------------------------------------------------------------- 5. « réellement encaissé » : pas d'amende
with app.app_context(), tenant_bypass():
    before = Sanction.query.filter_by(type_sanction='RETARD_COTISATION').count()
c.post(f'/tontine-cycles/{cid}/register-benefit', data={'expected_turn': 3, 'payment_mode': 'ESPECE', 'late_mode': 'hors_app'})
with app.app_context(), tenant_bypass():
    b3 = CycleBeneficiary.query.filter_by(cycle_id=cid, position=3).one()
    check(b3.net_amount == Decimal('100000') and not b3.pending_amount
          and Sanction.query.filter_by(type_sanction='RETARD_COTISATION').count() == before,
          'argent réellement reçu hors application : cagnotte complète, pas d\'amende')

# ---------------------------------------------------------------- 6. cycle « Tontine 25 000 » visible dans Cotisations
check('Tontine 25 000' in text(c.get('/cotisations')), 'le niveau 25 000 apparaît dans Cotisations (amende de retard réglable)')

# ---------------------------------------------------------------- 7. règle d'amende choisie par la réunion (Paramètres)
h = text(c.get('/parametres'))
check('Amende quand un membre ne paie pas sa part du tour' in h and 'Un pourcentage' in h and 'Un montant fixe' in h
      and 'Règle actuelle : amende de 10 %' in h, 'Paramètres : choix pourcentage / montant fixe (10 % par défaut)')
r = c.post('/parametres/amende-cycle', data={'cycle_penalty_mode': 'FIXED', 'cycle_penalty_value': '1000'}, follow_redirects=True)
check('amende de 1 000 FCFA' in text(r), 'réunion qui choisit un montant fixe : 1 000 FCFA par échec')
c.post('/seances/add', data={'date': m.date.today().isoformat(), 'title': 'Tour 4', 'columns': [f'c{cid}']})
with app.app_context(), tenant_bypass():
    s4 = Seance.query.filter_by(tontine_id=tid, title='Tour 4').one().id
pay = {'payment_mode': 'ESPECE'}
for n in ('Ana', 'Cle', 'Dan'):
    pay[f'pay_{ids[n]}_c{cid}'] = 'on'
    pay[f'amt_{ids[n]}_c{cid}'] = '25000'
c.post(f'/seances/{s4}', data=pay)
check('amende de 1 000 FCFA' in text(c.get(f'/seances/{s4}')), 'la fenêtre de versement annonce la règle de la tontine')
c.post(f'/tontine-cycles/{cid}/register-benefit', data={'expected_turn': 4, 'seance_id': s4, 'payment_mode': 'ESPECE', 'late_mode': 'reduite'})
with app.app_context(), tenant_bypass():
    fine = Sanction.query.filter_by(member_id=ids['Ben'], type_sanction='RETARD_COTISATION').one()
    check(fine.amount == Decimal('1000') and '1 000 FCFA' in fine.description, 'Ben ne paie pas le tour 4 : amende fixe de 1 000 FCFA')
r = c.post('/parametres/amende-cycle', data={'cycle_penalty_mode': 'PERCENT', 'cycle_penalty_value': '150'}, follow_redirects=True)
check('Valeur invalide' in text(r), 'pourcentage supérieur à 100 refusé')
c.post('/parametres/amende-cycle', data={'cycle_penalty_mode': 'PERCENT', 'cycle_penalty_value': '0'})
with app.test_request_context():
    m.g.tenant_id = tid
    t = db.session.get(Tontine, tid)
    check(m.cycle_penalty_amount(t, Decimal('25000')) == 0 and m.cycle_penalty_label(t) is None, '0 % : aucune amende')
ben = app.test_client()
ben.post('/login', data={'tontine': 'retards', 'username': 'ben', 'password': 'Passw0rd1'})
ben.post('/parametres/amende-cycle', data={'cycle_penalty_mode': 'FIXED', 'cycle_penalty_value': '99999'})
with app.app_context(), tenant_bypass():
    check(db.session.get(Tontine, tid).cycle_penalty_mode == 'PERCENT', 'un simple membre ne peut pas changer la règle')

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)

"""Amendes de retard de cotisation : champ sur chaque cotisation, infligées à la clôture de la séance."""
import html
import os
import re
import sys
from decimal import Decimal

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'am.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'))
from models import Tontine, Member, ContributionType, TontineCycleDetail, Seance, Sanction  # noqa: E402

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def text(r):
    h = re.sub(r'(?s)<(script|style)\b.*?</\1>', ' ', r.get_data(as_text=True))
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', h)))


c = app.test_client()
c.post('/inscription', data={'name': 'Tontine Rigueur', 'slug': 'rigueur', 'first_name': 'Hélène', 'last_name': 'Ngo',
                             'email': 'h@rigueur.cm', 'phone': '699000001', 'username': 'helene',
                             'password': 'Helene2026', 'password_confirm': 'Helene2026'})
for i, fn in enumerate(['Paul', 'Rose', 'Jean']):
    c.post('/members/add', data={'first_name': fn, 'last_name': 'Test', 'email': f'{fn.lower()}@rigueur.cm',
                                 'phone': f'69911122{i}', 'username': fn.lower(), 'role': 'MEMBRE',
                                 'password': 'Passw0rd1', 'confirm_password': 'Passw0rd1'})
with app.app_context():
    tid = Tontine.query.filter_by(slug='rigueur').one().id
    ids = {x.first_name: x.id for x in Member.query.filter_by(tontine_id=tid).all()}
    rubs = {r.category: r for r in ContributionType.query.filter_by(tontine_id=tid).all()}
    rub = {k: v.id for k, v in rubs.items()}
    rub_data = {k: dict(name=v.name, category=v.category, amount=str(int(v.amount or 0)), frequency=v.frequency,
                        description=v.description or '', display_order=v.display_order) for k, v in rubs.items()}


def set_fine(category, fine, mandatory=True):
    data = dict(rub_data[category], late_fine=str(fine))
    if mandatory:
        data['is_mandatory'] = 'on'
    return c.post(f'/cotisations/rubriques/{rub[category]}', data=data)


# ---------------------------------------------------------------- le champ « Amende si retard »
h = text(c.get('/cotisations'))
check('Amende si retard' in h and 'aucune' in h, 'page Cotisations : colonne « Amende si retard » (aucune par défaut)')
check('name="late_fine"' in c.get('/cotisations').get_data(as_text=True), 'formulaire de cotisation : champ « Amende si retard »')
set_fine('TONTINE', 500)
set_fine('PRESENCE', 200)
set_fine('FONDS_CAISSE', 1000)
set_fine('SECOURS', 300, mandatory=False)   # facultative : jamais d'amende
with app.app_context():
    check(db.session.get(ContributionType, rub['TONTINE']).late_fine == Decimal('500')
          and db.session.get(ContributionType, rub['PRESENCE']).late_fine == Decimal('200'),
          'amendes enregistrées sur les cotisations (tontine 500, présence 200, fonds de caisse 1 000)')
h = text(c.get('/cotisations'))
check('500 FCFA' in h and '1 000 FCFA' in h, 'les amendes apparaissent dans la liste des cotisations')
# Ajout rapide d'un niveau (Paramètres) : pas de champ amende -> 0, sans erreur
c.post('/cotisations/rubriques/add', data={'category': 'TONTINE', 'amount': '2000', 'frequency': 'BIMENSUEL', 'next': '/parametres'})
with app.app_context():
    lv2 = ContributionType.query.filter_by(tontine_id=tid, category='TONTINE', amount=2000).one()
    check((lv2.late_fine or 0) == 0, 'ajout rapide d\'un niveau : aucune amende par défaut')

# ---------------------------------------------------------------- séance
# Hélène a déjà payé son fonds de caisse (cotisation unique) avant la séance
c.post('/transactions/add', data={'member_id': ids['Hélène'], 'type': 'FONDS_CAISSE', 'contribution_type_id': rub['FONDS_CAISSE'],
                                  'amount': 5000, 'payment_mode': 'ESPECE', 'description': ''})
c.post('/tontine-cycles/add', data={'contribution_type_id': rub['TONTINE'], 'mode': 'TIRAGE', 'draw_now': 'on',
                                    **{f'hands_{i}': 1 for i in ids.values()}})
with app.app_context():
    cyc = TontineCycleDetail.query.filter_by(tontine_id=tid).one().id
c.post('/seances/add', data={'date': m.date.today().isoformat(),
                             'columns': [f'c{cyc}', f'r{rub["PRESENCE"]}', f'r{rub["FONDS_CAISSE"]}', f'r{rub["SECOURS"]}']})
with app.app_context():
    sid = Seance.query.filter_by(tontine_id=tid).one().id


def pay(who, cols):
    form = {'payment_mode': 'ESPECE'}
    for col, amount in cols:
        form[f'pay_{ids[who]}_{col}'] = 'on'
        form[f'amt_{ids[who]}_{col}'] = str(amount)
    c.post(f'/seances/{sid}', data=form)


cc, pr, fc = f'c{cyc}', f'r{rub["PRESENCE"]}', f'r{rub["FONDS_CAISSE"]}'
pay('Paul', [(cc, 10000), (pr, 1050), (fc, 5000)])     # tout payé
pay('Rose', [(cc, 10000)])                              # ni présence ni fonds de caisse
pay('Hélène', [(cc, 10000), (pr, 1050)])                # fonds de caisse déjà payé avant
#   Jean : rien payé

h = text(c.get(f'/seances/{sid}'))
check('amende si retard : 500' in h and 'amende si retard : 200' in h, 'la feuille rappelle l\'amende de chaque colonne')
check('Amendes de retard de cotisation' in h and 'À la clôture de la séance, ces amendes seront infligées' in h,
      'aperçu des amendes avant la clôture')
with app.test_request_context():
    m.g.tenant_id = tid
    preview = m.seance_late_fines(db.session.get(Seance, sid))
    got = sorted((f['member'].first_name, f['label'], int(f['amount'])) for f in preview)
expected = sorted([('Jean', 'Cycle #1 · Tontine 10 000', 500), ('Rose', 'Droit de présence', 200), ('Jean', 'Droit de présence', 200),
                   ('Rose', 'Fonds de caisse', 1000), ('Jean', 'Fonds de caisse', 1000)])
check(got == expected, f'retardataires exacts : Jean (tout), Rose (présence, fonds de caisse) ; Paul et Hélène à jour {got}')
check(not any(f['label'] == 'Caisse de secours' for f in preview), 'cotisation facultative : pas d\'amende')

# ---------------------------------------------------------------- clôture
r = c.post(f'/seances/{sid}/close', follow_redirects=True)
check('5 amende(s) de retard infligée(s) pour 2 900 FCFA' in text(r), 'clôture : 5 amendes, 2 900 FCFA, message clair')
with app.app_context():
    auto = Sanction.query.filter_by(type_sanction='RETARD_COTISATION').all()
    check(len(auto) == 5 and all(s.status == 'PENDING' and s.origin_key.startswith(f'seance{sid}:') for s in auto),
          '5 amendes « Retard de cotisation » à payer, rattachées à la séance')
    jean = [s for s in auto if s.member_id == ids['Jean']]
    check(sum(s.amount for s in jean) == Decimal('1700'), 'Jean : 500 + 200 + 1 000 = 1 700')
h = text(c.get('/sanctions'))
check('Retard de cotisation' in h, 'les amendes apparaissent dans Sanctions avec le type « Retard de cotisation »')
h = text(c.get(f'/seances/{sid}'))
check('Amendes infligées à la clôture' in h and 'à payer' in h, 'la feuille clôturée liste les amendes infligées')

# Rose paie son amende de présence
with app.app_context():
    rose_pres = Sanction.query.filter_by(member_id=ids['Rose'], type_sanction='RETARD_COTISATION').filter(
        Sanction.origin_key.like(f'%:{pr}')).one().id
c.post(f'/sanctions/{rose_pres}/pay', data={'payment_mode': 'ESPECE'})

# ---------------------------------------------------------------- réouverture : correction d'un oubli
r = c.post(f'/seances/{sid}/close', follow_redirects=True)
check('4 amende(s) de retard non payée(s) annulée(s)' in text(r), 'réouverture : les 4 amendes non payées sont annulées')
pay('Jean', [(pr, 1050)])   # Jean avait en fait payé sa présence
c.post(f'/seances/{sid}/close')
with app.app_context():
    auto = Sanction.query.filter_by(type_sanction='RETARD_COTISATION').all()
    got = sorted((s.member_id == ids['Jean'], s.origin_key.split(':')[1], s.status) for s in auto)
    check(len(auto) == 4, f'nouvelle clôture : 4 amendes (Jean n\'a plus celle de présence) {got}')
    check(len([s for s in auto if s.member_id == ids['Rose'] and s.origin_key.endswith(pr)]) == 1,
          "l'amende déjà payée par Rose n'est pas refaite en double")

# ---------------------------------------------------------------- avance : pas d'amende
c.post(f'/tontine-cycles/{cyc}/register-benefit', data={'expected_turn': 1, 'payment_mode': 'ESPECE', 'confirm_offline': 'on'})
c.post('/seances/add', data={'date': m.date.today().isoformat(), 'title': 'Tour 2', 'columns': [cc]})
with app.app_context():
    sid2 = Seance.query.filter_by(tontine_id=tid, title='Tour 2').one().id
form = {'payment_mode': 'ESPECE', f'pay_{ids["Paul"]}_{cc}': 'on', f'amt_{ids["Paul"]}_{cc}': '20000'}   # Paul paie 2 tours
c.post(f'/seances/{sid2}', data=form)
for who in ('Rose', 'Hélène', 'Jean'):
    c.post(f'/seances/{sid2}', data={'payment_mode': 'ESPECE', f'pay_{ids[who]}_{cc}': 'on', f'amt_{ids[who]}_{cc}': '10000'})
c.post(f'/seances/{sid2}/close')
with app.app_context():
    check(Sanction.query.filter(Sanction.origin_key.like(f'seance{sid2}:%')).count() == 0,
          'tour 2 : tout le monde a payé, aucune amende')
c.post(f'/tontine-cycles/{cyc}/register-benefit', data={'expected_turn': 2, 'payment_mode': 'ESPECE'})
c.post('/seances/add', data={'date': m.date.today().isoformat(), 'title': 'Tour 3', 'columns': [cc]})
with app.test_request_context():
    m.g.tenant_id = tid
    sid3 = Seance.query.filter_by(tontine_id=tid, title='Tour 3').one().id
    late = sorted(f['member'].first_name for f in m.seance_late_fines(db.session.get(Seance, sid3)))
check('Paul' not in late and len(late) == 3, f'tour 3 : Paul a payé d\'avance, pas d\'amende pour lui ({late})')

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)

"""Parcours utilisateur : chaque page de chaque rôle, en français, sans code interne ni chiffre faux."""
import html
import os
import re
import sys

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'pa.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402
from permissions import MENU_ITEMS  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'))
from models import Tontine, Member, ContributionType, TontineCycleDetail  # noqa: E402

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def visible(r):
    h = re.sub(r'(?s)<(script|style)\b.*?</\1>', ' ', r.get_data(as_text=True))
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', h))).strip()


BAD = [(r'\b[A-Z]{3,}_[A-Z_]{2,}\b', 'code interne'),
       (r'\b(None|True|False|N/A|null|undefined|NaN)\b', 'valeur brute'),
       (r'\b(PENDING|PAID|APPROVED|REJECTED|OVERDUE|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|'
        r'January|February|March|April|June|July|August|September|October|November|December)\b', 'anglais'),
       (r'\b\d{1,3}(?:,\d{3})+\b', 'montant à l\'anglaise'),
       (r'\b(VERT|ORANGE|ROUGE)\b', 'statut brut'),
       (r'Traceback|Internal Server Error', 'erreur')]

# ---------------------------------------------------------------- mise en place
pres = app.test_client()
pres.post('/inscription', data={'name': 'Njangi Parcours', 'slug': 'parcours', 'first_name': 'Hélène', 'last_name': 'Mballa',
                                'email': 'h@parcours.cm', 'phone': '699000000', 'username': 'helene',
                                'password': 'Mbalmayo2026', 'password_confirm': 'Mbalmayo2026'})
roles = [('Paul', 'MEMBRE'), ('Rose', 'CENSEUR'), ('Jean', 'TRESORIER'), ('Lucie', 'SECRETAIRE'), ('Marc', 'COMMUNICATION')]
for i, (fn, role) in enumerate(roles):
    pres.post('/members/add', data={'first_name': fn, 'last_name': 'Essai', 'email': f'{fn.lower()}@parcours.cm',
                                    'phone': f'69911111{i}', 'username': fn.lower(), 'role': role,
                                    'password': 'Passw0rd1', 'confirm_password': 'Passw0rd1'})
with app.app_context():
    tid = Tontine.query.filter_by(slug='parcours').one().id
    ids = {x.first_name: x.id for x in Member.query.filter_by(tontine_id=tid).all()}
    rub = {r.category: r.id for r in ContributionType.query.filter_by(tontine_id=tid).all() if r.category != 'TONTINE'}
    lv = ContributionType.query.filter_by(tontine_id=tid, category='TONTINE').first().id
for name in ids:
    for cat, amount in (('FONDS_CAISSE', 5000), ('EPARGNE', 20000)):
        pres.post('/transactions/add', data={'member_id': ids[name], 'type': cat, 'contribution_type_id': rub[cat],
                                             'amount': amount, 'payment_mode': 'ORANGE_MONEY', 'description': ''})
r = pres.post('/tontine-cycles/add', data={'contribution_type_id': lv, 'mode': 'TIRAGE', 'draw_now': 'on',
                                           **{f'hands_{i}': 1 for i in ids.values()}}, follow_redirects=True)
check('60 000 FCFA' in visible(r) and '60,000' not in visible(r), 'message de création du cycle : « 60 000 FCFA » à la française')
with app.app_context():
    cyc = TontineCycleDetail.query.filter_by(tontine_id=tid).first().id
pres.post('/seances/add', data={'date': m.date.today().isoformat(), 'columns': [f'c{cyc}', f'r{rub["PRESENCE"]}']})
pres.post('/sanctions/add', data={'member_id': ids['Paul'], 'type_sanction': 'RETARD_REUNION', 'amount': '500',
                                  'sanction_date': m.date.today().isoformat(), 'description': 'Retard'})
clients = {'PRESIDENT': pres}
for fn, role in roles:
    c = app.test_client()
    c.post('/login', data={'tontine': 'parcours', 'username': fn.lower(), 'password': 'Passw0rd1'})
    clients[role] = c
paul = clients['MEMBRE']
r = paul.post('/loan/request', data={'member_id': ids['Paul'], 'amount': 30000, 'duration_months': 2,
                                     'guarantor_ids': [ids['Rose']]}, follow_redirects=True)
check('30 000 FCFA' in visible(r), 'message de demande de prêt à la française')

# ---------------------------------------------------------------- toutes les pages, tous les rôles
menu_urls = {}
with app.test_request_context():
    for role in clients:
        menu_urls[role] = [m.url_for(item['url']) for item in MENU_ITEMS[role]]
problems = []
for role, c in clients.items():
    for url in menu_urls[role] + (['/members/%d' % ids['Paul'], '/tontine-cycles/%d' % cyc, '/seances/1', '/transactions/add']
                                  if role == 'PRESIDENT' else []):
        r = c.get(url)
        if r.status_code >= 400:
            problems.append(f'{role} {url} : HTTP {r.status_code}')
            continue
        text = visible(r)
        for pattern, label in BAD:
            for hit in sorted(set(re.findall(pattern, text)))[:3]:
                problems.append(f'{role} {url} : {label} « {hit} »')
check(not problems, f'toutes les pages de tous les rôles : français, sans code interne ni montant à l\'anglaise {problems[:8]}')

# ---------------------------------------------------------------- chiffres justes
t = visible(paul.get('/dashboard'))
check('25 000 Total de mes versements' in t, 'tableau de bord du membre : total de ses versements = 25 000')
check("Mon épargne (rendue en fin d'année) : 20 000 FCFA" in t and '🟢 En règle' in t, 'situation du membre lisible (épargne, statut)')
check('Ajouter un paiement' not in t, "un membre ne voit pas « Ajouter un paiement » (il n'y a pas droit)")
check(re.search(r'(Lundi|Mardi|Mercredi|Jeudi|Vendredi|Samedi|Dimanche) \d{1,2} \w+ 20\d\d', t), 'date du jour en français')
t = visible(pres.get('/reports'))
check('Total contributions 150 000 FCFA' in t, 'rapports : total des contributions = 150 000 (toutes les cotisations)')
check('Paul Essai 25 000 FCFA' in t, 'rapports : classement des contributeurs rempli')
check('Épargne 6 120 000 FCFA' in t and 'Fonds de caisse 6 30 000 FCFA' in t, 'rapports : types en français, montants à la française')
t = visible(paul.get('/loans'))
check('(épargne : 20 000 FCFA)' in t and 'Ajouter un membre' not in t, "emprunts : épargne réelle affichée, pas de bouton « Ajouter un membre »")
t = visible(clients['CENSEUR'].get('/avals'))
check("Mon épargne (FCFA)" in t and "Mon épargne bloquée parce que je garantis des emprunts" in t and '10 000' in t,
      "avals : Rose voit 10 000 d'épargne bloquée par l'aval de Paul (30 000 / 3)")
check("Je peux avaliser un emprunt jusqu'à (FCFA)" in t and '30 000' in t, 'avals : capacité restante = 3 x (20 000 - 10 000)')
check('Capacité d\'aval restante (indicative)' not in t, "avals : l'ancien calcul (avoirs) a disparu")

# ---------------------------------------------------------------- menu rangé par rubriques
h = pres.get('/dashboard').get_data(as_text=True)
sections = re.findall(r'<li class="nav-item menu-section">([^<]+)</li>', h)
check(sections == ['Argent', 'Tontine', 'Vie du groupe', 'Administration'], f'menu du président en 4 rubriques {sections}')
entries = [re.sub(r'\s+', ' ', e).strip() for e in re.findall(r'class="nav-link[^"]*"\s*href="[^"]*">\s*<i[^>]*></i>([^<]+)</a>', h)]
check('Caisse' in entries and 'Séances' in entries and not {'Transactions', 'Cotisations', 'Procès-verbaux', 'Réunions'} & set(entries),
      f'menu du président : « Caisse » et « Séances » remplacent 4 entrées {entries}')
t = pres.get('/transactions').get_data(as_text=True)
check('Journal des mouvements' in t and 'Situation' in t and re.search(r'nav-link active"\s*href="/cotisations"', t),
      'Journal des mouvements : onglet de la Caisse, entrée « Caisse » allumée dans le menu')
t = pres.get('/meetings').get_data(as_text=True)
check('Feuilles de séance' in t and 'Nouveau procès-verbal' in t and re.search(r'nav-link active"\s*href="/seances"', t),
      'procès-verbaux : onglet des Séances, entrée « Séances » allumée')
h = paul.get('/dashboard').get_data(as_text=True)
check('Procès-verbaux' in h and 'Caisse' in h and 'Mes transactions' not in h and 'menu-section' in h,
      'membre : menu rangé, « Caisse » et « Procès-verbaux » (il n\'a pas les feuilles de séance)')
t = paul.get('/meetings').get_data(as_text=True)
check('Feuilles de séance' not in t and 'Nouveau procès-verbal' not in t, 'membre : PV en lecture seule, sans onglet séance')
t = paul.get('/transactions', follow_redirects=True).get_data(as_text=True)
check('Mes mouvements' in t, 'membre : onglet « Mes mouvements » dans la Caisse')
t = visible(pres.get('/audit-logs'))
check('Ajout transaction : Fonds de caisse 5 000 FCFA' in t and 'Président' in t, "journal d'audit lisible (type et rôle en français)")

# ---------------------------------------------------------------- pages publiques : tarifs, FAQ, guide illustré
visitor = app.test_client()
t = visible(visitor.get('/'))
check('Gratuit pour démarrer' in t and '200 FCFA / membre / mois' in t and 'Jusqu\'à 10 membres actifs' in t,
      "page d'accueil : tarifs (gratuit jusqu'à 10, 200 FCFA / membre / mois)")
check('15 membres 3 000 FCFA' in t and '10 membres Gratuit' in t, 'exemples de prix calculés avec les vraies règles')
h = visitor.get('/').get_data(as_text=True)
check(h.count('class="faq-item"') >= 10 and 'href="/guide"' in h, 'FAQ (au moins 10 questions) et lien vers le guide')
r = visitor.get('/guide')
h = r.get_data(as_text=True)
imgs = re.findall(r'<img src="/static/docs/([^"]+)"', h)
missing = [i for i in imgs if not os.path.exists(os.path.join(P, 'app', 'static', 'docs', i))]
check(r.status_code == 200 and len(imgs) >= 15 and not missing, f'guide illustré : {len(imgs)} captures, toutes présentes {missing}')
check('Créer sa tontine' in visible(r) and 'Abonnement' in visible(r), 'le guide couvre de la création à l\'abonnement')
check(pres.get('/guide').status_code == 200, 'le guide reste accessible une fois connecté')

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)

"""Sanctions : infliger (fenêtre + page), afficher, payer, modifier, droits."""
import os
import re
import sys
from decimal import Decimal

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'sa.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'))
from models import Tontine, Member, Sanction, Transaction  # noqa: E402

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def body(r):
    return r.get_data(as_text=True)


pres = app.test_client()
pres.post('/inscription', data={'name': 'Tontine Discipline', 'slug': 'discipline', 'first_name': 'Hélène', 'last_name': 'Mballa',
                                'email': 'h@dis.cm', 'phone': '699000000', 'username': 'helene', 'password': 'Helene2026',
                                'password_confirm': 'Helene2026'})
for fn, role in [('Paul', 'MEMBRE'), ('Rose', 'CENSEUR'), ('Jean', 'TRESORIER')]:
    pres.post('/members/add', data={'first_name': fn, 'last_name': 'Ndongo', 'email': f'{fn.lower()}@dis.cm', 'phone': '699111111',
                                    'username': fn.lower(), 'role': role, 'password': 'Passw0rd1', 'confirm_password': 'Passw0rd1'})
with app.app_context():
    tid = Tontine.query.filter_by(slug='discipline').one().id
    paul = Member.query.filter_by(tontine_id=tid, first_name='Paul').one().id


def login(username):
    client = app.test_client()
    client.post('/login', data={'tontine': 'discipline', 'username': username, 'password': 'Passw0rd1'})
    return client


censeur, tresorier, membre = login('rose'), login('jean'), login('paul')

# ---------------------------------------------------------------- bouton et fenêtre
h = body(censeur.get('/sanctions'))
check('data-target="#addSanctionModal"' in h and 'id="addSanctionModal"' in h, 'le bouton ouvre une fenêtre qui existe')
check(h.count('Paul Ndongo') >= 1 and 'Mauvais comportement' in h, 'la fenêtre liste les membres et tous les types (dont « Mauvais comportement »)')
check('addSanctionModal' not in body(membre.get('/sanctions')), 'un simple membre ne voit pas le bouton')

# ---------------------------------------------------------------- infliger avec la protection CSRF ACTIVE (conditions réelles)
app.config['WTF_CSRF_ENABLED'] = True
h = body(censeur.get('/sanctions'))
modal = h[h.index('id="addSanctionModal"'):]
token = re.search(r'name="csrf_token" value="([^"]+)"', modal)
check(token is not None, 'la fenêtre contient le jeton de sécurité CSRF')
r = censeur.post('/sanctions/add', data={'csrf_token': token.group(1) if token else '', 'member_id': paul,
                                         'type_sanction': 'RETARD_REUNION', 'amount': '500', 'sanction_date': m.date.today().isoformat(),
                                         'description': "Arrivé à l'ouverture de la séance du 12/10 (40 min de retard)"})
with app.app_context():
    s1 = Sanction.query.filter_by(member_id=paul).first()
    check(r.status_code == 302 and s1 is not None and s1.amount == Decimal('500'),
          "sanction infligée depuis la fenêtre (texte avec apostrophe, / et parenthèses accepté)")
h = body(censeur.get('/sanctions/add'))
check('csrf_token' in h and 'Paul Ndongo' in h, 'page /sanctions/add : jeton CSRF et liste des membres présents')
token2 = re.search(r'name="csrf_token" type="hidden" value="([^"]+)"|name="csrf_token" value="([^"]+)"', h)
tok = (token2.group(1) or token2.group(2)) if token2 else ''
r = censeur.post('/sanctions/add', data={'csrf_token': tok, 'member_id': paul, 'type_sanction': 'COMPORTEMENT', 'amount': '1000',
                                         'sanction_date': m.date.today().isoformat(), 'description': 'Propos déplacés en séance'})
with app.app_context():
    check(Sanction.query.filter_by(member_id=paul, type_sanction='COMPORTEMENT').count() == 1, 'page dédiée : type « Mauvais comportement » accepté')
app.config['WTF_CSRF_ENABLED'] = False

# ---------------------------------------------------------------- affichage et droits
h = body(censeur.get('/sanctions'))
check('Retard à la réunion' in h and 'Mauvais comportement' in h, 'la colonne « Infraction » affiche le type')
check('pay_sanction' not in h and '/pay"' not in h, 'le censeur ne voit pas le bouton Payer (réservé au trésorier/président)')
ht = body(tresorier.get('/sanctions'))
check('/pay"' in ht and 'editSanctionModal' not in ht, 'le trésorier peut encaisser mais pas modifier')
hm = body(membre.get('/sanctions'))
check('/pay"' not in hm and 'editSanctionModal' not in hm and 'À payer' in hm, 'le membre voit ses sanctions « À payer », sans actions')

# ---------------------------------------------------------------- modifier : le membre sanctionné reste le même même s'il est suspendu
with app.app_context():
    db.session.get(Member, paul).status = 'SUSPENDU'
    db.session.commit()
h = body(censeur.get('/sanctions'))
check(f'<option value="{paul}" selected>Paul Ndongo (inactif)</option>' in h, 'membre suspendu : toujours présélectionné dans la modification')
censeur.post(f'/sanctions/{s1.id}/edit', data={'member_id': paul, 'type_sanction': 'RETARD_REUNION', 'amount': '750',
                                               'sanction_date': m.date.today().isoformat(), 'description': "Retard de 40 min à l'ouverture"})
with app.app_context():
    s1b = db.session.get(Sanction, s1.id)
    check(s1b.member_id == paul and s1b.amount == Decimal('750'), f'modification enregistrée sans changer de membre ({s1b.amount})')
    db.session.get(Member, paul).status = 'ACTIF'
    db.session.commit()

# ---------------------------------------------------------------- payer
tresorier.post(f'/sanctions/{s1.id}/pay', data={'payment_mode': 'ORANGE_MONEY'})
with app.app_context():
    check(db.session.get(Sanction, s1.id).status == 'PAID', 'le trésorier encaisse la sanction')
    check(Transaction.query.filter_by(member_id=paul, type='SANCTION').count() == 1, "l'encaissement crée l'écriture en caisse")
check(membre.post(f'/sanctions/{s1.id}/pay').status_code == 302, 'un membre ne peut pas encaisser')

# ---------------------------------------------------------------- textes français ailleurs (même règle de validation)
pres.post('/transactions/add', data={'member_id': paul, 'type': 'PRESENCE', 'amount': 1050, 'payment_mode': 'ESPECE',
                                     'description': "Présence d'octobre (séance du 12/10)"})
with app.app_context():
    check(Transaction.query.filter(Transaction.description == "Présence d'octobre (séance du 12/10)").count() == 1,
          'description de transaction avec apostrophe et date acceptée')
pres.post('/transactions/add', data={'member_id': paul, 'type': 'PRESENCE', 'amount': 1050, 'payment_mode': 'ESPECE',
                                     'description': '<script>alert(1)</script>'})
with app.app_context():
    check(Transaction.query.filter(Transaction.description.like('%script%')).count() == 0, 'les balises de code restent refusées')

# ---------------------------------------------------------------- contrôle statique de toutes les pages
import glob  # noqa: E402
tpl_dir = os.path.join(P, 'app', 'templates')
base_html = open(os.path.join(tpl_dir, 'base.html'), encoding='utf-8').read()
missing_csrf, broken_buttons = [], []
for f in glob.glob(os.path.join(tpl_dir, '*.html')):
    src = open(f, encoding='utf-8').read()
    for form in re.finditer(r'<form\b[^>]*>', src, re.I):
        if re.search(r'method\s*=\s*["\']?post', form.group(0), re.I):
            end = src.find('</form>', form.end())
            block = src[form.end(): end if end != -1 else len(src)]
            if 'csrf_token' not in block and 'hidden_tag()' not in block:
                missing_csrf.append(os.path.basename(f))
    ids = {re.sub(r'\{\{[^}]+\}\}', '{}', i) for i in re.findall(r'id="([^"]+)"', src + base_html)}
    for target in re.findall(r'data-target="#([^"]+)"', src):
        if re.sub(r'\{\{[^}]+\}\}', '{}', target) not in ids:
            broken_buttons.append(f'{os.path.basename(f)} #{target}')
syntax_errors, form_in_row = [], []
for f in glob.glob(os.path.join(tpl_dir, '*.html')):
    src = open(f, encoding='utf-8').read()
    try:
        app.jinja_env.parse(src)
    except Exception as exc:  # erreur de syntaxe Jinja : la page planterait à l'ouverture
        syntax_errors.append(f'{os.path.basename(f)}: {exc}')
    if re.search(r'<tr\b[^>]*>\s*<form\b', src):  # <form> directement dans <tr> : HTML invalide, champs non envoyés
        form_in_row.append(os.path.basename(f))
check(not syntax_errors, f'tous les templates compilent {syntax_errors or ""}')
check(not form_in_row, f'aucun formulaire placé directement dans une ligne de tableau {form_in_row or ""}')
check(not missing_csrf, f'tous les formulaires envoyés ont leur jeton CSRF {missing_csrf or ""}')
check(not broken_buttons, f'aucun bouton n\'ouvre une fenêtre inexistante {broken_buttons or ""}')

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)

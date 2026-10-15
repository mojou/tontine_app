"""Connexion d'un membre créé par le président : majuscules du téléphone, espaces, mot de passe court, sécurité."""
import html
import os
import re
import sys

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'cx.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'))
from models import User, Tontine  # noqa: E402
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
pres.post('/inscription', data={'name': 'Tontine Connexion', 'slug': 'connexion', 'first_name': 'Germain', 'last_name': 'Fotsing',
                                'email': 'g@cx.cm', 'phone': '699000001', 'username': 'Germain',
                                'password': 'Fotsing2026', 'password_confirm': 'Fotsing2026'})
with app.app_context(), tenant_bypass():
    tid = Tontine.query.filter_by(slug='connexion').one().id
    check(User.query.filter_by(tontine_id=tid, role='PRESIDENT').one().username == 'germain',
          'identifiant du président enregistré en minuscules')


def add(username, password, i):
    return pres.post('/members/add', data={'first_name': f'Membre{i}', 'last_name': 'Talla', 'email': f'm{i}@cx.cm',
                                           'phone': f'69911122{i}', 'username': username, 'role': 'MEMBRE',
                                           'password': password, 'confirm_password': password}, follow_redirects=True)


r7 = add('patrick', 'abc1234', 1)
check('au moins 8 caractères' in text(r7),
      'mot de passe de 7 caractères refusé à la création, avec un message clair')
add('patrick', 'kribi2026', 1)
add('  Paul.Talla ', 'Paul2026', 2)
add('rose', 'Fleur@2026!', 3)
with app.app_context(), tenant_bypass():
    names = sorted(u.username for u in User.query.filter_by(tontine_id=tid, role='MEMBRE').all())
check(names == ['patrick', 'paul.talla', 'rose'], f'identifiants enregistrés sans espaces ni majuscules {names}')
r = add('PATRICK', 'Autre2026x', 4)
with app.app_context(), tenant_bypass():
    check(User.query.filter(User.tontine_id == tid, db.func.lower(User.username) == 'patrick').count() == 1
          and 'déjà utilisé par' in text(r), '« PATRICK » refusé : « patrick » existe déjà (pas de doublon selon les majuscules)')


def login(username, password, slug='connexion'):
    c = app.test_client()
    r = c.post('/login', data={'tontine': slug, 'username': username, 'password': password})
    return r.status_code == 302 and '/login' not in r.headers.get('Location', '')


check(login('patrick', 'kribi2026'), 'mot de passe donné par le président : connexion OK')
check(login('Patrick', 'kribi2026'), 'majuscule automatique du téléphone (« Patrick ») : connexion OK')
check(login('PATRICK ', 'kribi2026'), 'identifiant en majuscules avec espace final : connexion OK')
check(login('patrick', ' kribi2026 '), 'espaces ajoutés autour du mot de passe : connexion OK')
check(login('Paul.Talla', 'Paul2026') and login('paul.talla', 'Paul2026'), 'identifiant créé avec majuscules et espaces : connexion OK')
check(login('rose', 'Fleur@2026!'), 'mot de passe avec caractères spéciaux : connexion OK')
check(login('germain', 'Fotsing2026') and login('Germain', 'Fotsing2026'), 'président : connexion OK quelle que soit la casse')

# sécurité : rien d'autre ne passe
check(not login('patrick', 'KRIBI2026'), 'le mot de passe reste sensible aux majuscules')
check(not login('patrick', 'abc1234'), 'mauvais mot de passe : refusé')
check(not login('patrick', 'kribi2026', slug='jsb'), "bon identifiant mais mauvaise tontine : refusé")
c = app.test_client()
for _ in range(5):
    c.post('/login', data={'tontine': 'connexion', 'username': 'Rose', 'password': 'faux'})
r = c.post('/login', data={'tontine': 'connexion', 'username': 'rose', 'password': 'Fleur@2026!'})
check(r.status_code == 429 and 'Trop de tentatives' in text(r),
      '5 essais ratés : blocage 15 minutes, même en changeant les majuscules de l\'identifiant')

# formulaires : pas de majuscule automatique sur téléphone
h = pres.get('/members/add').get_data(as_text=True)
check('name="username"' in h and 'autocapitalize="none"' in h, 'création de membre : champ identifiant sans majuscule automatique')
h = app.test_client().get('/login').get_data(as_text=True)
check('autocapitalize="none"' in h, 'page de connexion : champ identifiant sans majuscule automatique')

# ---------------------------------------------------------------- le président change le mot de passe d'un membre
with app.app_context(), tenant_bypass():
    pat_id = User.query.filter_by(tontine_id=tid, username='patrick').one().member_id
edit = {'first_name': 'Membre1', 'last_name': 'Talla', 'email': 'm1@cx.cm', 'phone': '699111221'}
h = pres.get(f'/members/{pat_id}/edit').get_data(as_text=True)
check('value="patrick"' in h and 'name="new_password"' in h and 'Laisser vide pour ne pas le changer' in h,
      'page « Modifier » : identifiant prérempli, nouveau mot de passe facultatif')
r = pres.post(f'/members/{pat_id}/edit', data={**edit, 'username': 'patrick', 'new_password': 'Edea2026x',
                                               'new_password_confirm': 'Edea2026x'}, follow_redirects=True)
check('Nouveau mot de passe enregistré' in text(r), 'le président enregistre un nouveau mot de passe')
check(login('patrick', 'Edea2026x') and not login('patrick', 'kribi2026'),
      'le membre se connecte avec le NOUVEAU mot de passe ; l\'ancien ne marche plus')
pres.post(f'/members/{pat_id}/edit', data={**edit, 'username': 'patrick', 'new_password': '', 'new_password_confirm': ''})
check(login('patrick', 'Edea2026x'), 'mot de passe laissé vide : il ne change pas')
r = pres.post(f'/members/{pat_id}/edit', data={**edit, 'username': 'patrick', 'new_password': 'Autre2026x',
                                               'new_password_confirm': 'Autre2026y'}, follow_redirects=True)
check("ne sont pas identiques" in text(r) and login('patrick', 'Edea2026x'), 'confirmation différente : refus clair, rien ne change')
# la secrétaire bloquée par 5 essais ratés : un nouveau mot de passe donné par le président lève le blocage
with app.app_context(), tenant_bypass():
    paul_id = User.query.filter_by(tontine_id=tid, username='paul.talla').one().member_id
for _ in range(5):
    login('paul.talla', 'Mauvais2026')
check(not login('paul.talla', 'Paul2026'), 'après 5 essais ratés, le compte est bloqué 15 minutes')
pres.post(f'/members/{paul_id}/edit', data={'first_name': 'Membre2', 'last_name': 'Talla', 'email': 'm2@cx.cm', 'phone': '699111222',
                                            'username': 'paul.talla', 'new_password': 'Limbe2026x', 'new_password_confirm': 'Limbe2026x'})
check(login('paul.talla', 'Limbe2026x'), 'nouveau mot de passe donné par le président : blocage levé, connexion OK')

# ---------------------------------------------------------------- faire entrer un membre simple au bureau
h = pres.get(f'/members/{paul_id}').get_data(as_text=True)
check('Rôle dans le bureau' in h and 'Changer le rôle' in h and 'Membre (pas au bureau)' in h,
      'fiche du membre : réglage « Rôle dans le bureau » visible pour le président')
paul = app.test_client()
paul.post('/login', data={'tontine': 'connexion', 'username': 'paul.talla', 'password': 'Limbe2026x'})
check('Historique des actions' not in paul.get('/dashboard').get_data(as_text=True), 'avant : Paul a le menu d\'un simple membre')
r = pres.post(f'/members/{paul_id}/change-role', data={'role': 'SECRETAIRE'}, follow_redirects=True)
check('est maintenant au bureau : Secrétaire' in text(r), 'le président nomme Paul secrétaire (message clair)')
h = paul.get('/dashboard').get_data(as_text=True)
check('Historique des actions' in h and 'Secrétaire' in h, 'Paul, déjà connecté, a tout de suite le menu du bureau (secrétaire)')
check(paul.get('/members/add').status_code == 200, 'Paul secrétaire peut inscrire des membres')
with app.app_context(), tenant_bypass():
    germain = User.query.filter_by(tontine_id=tid, username='germain').one()
r = pres.post(f'/members/{germain.member_id}/change-role', data={'role': 'MEMBRE'}, follow_redirects=True)
check('se change par un vote' in text(r), 'impossible de retirer le président à la main (il faut une élection)')
r = pres.post(f'/members/{paul_id}/change-role', data={'role': 'ROI'}, follow_redirects=True)
check('Rôle invalide' in text(r), 'rôle inconnu refusé')
r = pres.post(f'/members/{paul_id}/change-role', data={'role': 'PRESIDENT'}, follow_redirects=True)
with app.app_context(), tenant_bypass():
    check('se change par un vote' in text(r) and User.query.filter_by(tontine_id=tid, username='paul.talla').one().role == 'SECRETAIRE',
          'nommer un président à la main est refusé : le président se change par un vote')
m_c = app.test_client()
m_c.post('/login', data={'tontine': 'connexion', 'username': 'rose', 'password': 'Fleur@2026!'})
with app.app_context(), tenant_bypass():
    rose_mid = User.query.filter_by(tontine_id=tid, username='rose').one().member_id
check(m_c.post(f'/members/{rose_mid}/change-role', data={'role': 'PRESIDENT'}).status_code in (302, 403),
      'un simple membre ne peut pas changer les rôles')
with app.app_context(), tenant_bypass():
    check(User.query.filter_by(tontine_id=tid, username='rose').one().role == 'MEMBRE', '… et Rose reste simple membre')

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)

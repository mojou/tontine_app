"""Sécurité des comptes : règle des mots de passe, mot de passe provisoire à changer, déconnexion des autres
appareils, session renouvelée, chiffrement scrypt, en-têtes de protection."""
import html
import os
import re
import sys

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'sx.db').replace(os.sep, '/')
os.environ['FORCE_PASSWORD_CHANGE'] = 'True'
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'), FORCE_PASSWORD_CHANGE=True)
from models import User, Tontine  # noqa: E402
from tenancy import tenant_bypass  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def text(r):
    h = re.sub(r'(?s)<(script|style)\b.*?</\1>', ' ', r.get_data(as_text=True))
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', h)))


# ---------------------------------------------------------------- règle des mots de passe
with app.test_request_context():
    pb = m.password_problems
    check(pb('Tontine2026x') == [], 'mot de passe correct accepté (8+ caractères, lettres et chiffres)')
    check(pb('abc1234') and pb('motdepasse') and pb('12345678') and pb('motdepasse1') and pb('aaaaaaa1'),
          'refusés : trop court, sans chiffre, sans lettre, trop courant, répétitif')
    check(pb('patrick2026', 'patrick') != [], "refusé : contient l'identifiant")

r = app.test_client().post('/inscription', data={'name': 'Faible', 'slug': 'faible', 'first_name': 'Ana', 'last_name': 'Abena',
                                                 'email': 'a@faible.cm', 'phone': '699000009', 'username': 'ana',
                                                 'password': '12345678', 'password_confirm': '12345678'}, follow_redirects=True)
check('Mot de passe trop faible' in text(r), 'création de tontine avec « 12345678 » : refusée')

pres = app.test_client()
pres.post('/inscription', data={'name': 'Tontine Sure', 'slug': 'sure', 'first_name': 'Germain', 'last_name': 'Fotsing',
                                'email': 'g@sure.cm', 'phone': '699000001', 'username': 'germain',
                                'password': 'Fotsing2026', 'password_confirm': 'Fotsing2026'})
with app.app_context(), tenant_bypass():
    tid = Tontine.query.filter_by(slug='sure').one().id
    check(User.query.filter_by(tontine_id=tid, username='germain').one().password_hash.startswith('scrypt:'),
          'mots de passe chiffrés avec scrypt (jamais en clair)')
check(pres.get('/dashboard').status_code == 200, 'le président qui a choisi son mot de passe accède directement')

# ---------------------------------------------------------------- mot de passe provisoire donné par le président
pres.post('/members/add', data={'first_name': 'Patrick', 'last_name': 'Talla', 'email': 'p@sure.cm', 'phone': '699111111',
                                'username': 'patrick', 'role': 'MEMBRE', 'password': 'Provisoire1', 'confirm_password': 'Provisoire1'})
with app.app_context(), tenant_bypass():
    check(User.query.filter_by(tontine_id=tid, username='patrick').one().must_change_password is True,
          'membre créé par le président : mot de passe marqué « provisoire »')
pat = app.test_client()
r = pat.post('/login', data={'tontine': 'sure', 'username': 'patrick', 'password': 'Provisoire1'}, follow_redirects=True)
check('Choisissez votre mot de passe' in text(r) and 'provisoire' in text(r), '1re connexion : page « Choisissez votre mot de passe »')
r = pat.get('/dashboard')
check(r.status_code == 302 and '/mot-de-passe' in r.headers['Location'], 'impossible d\'aller ailleurs avant de changer le mot de passe')
r = pat.post('/mot-de-passe', data={'current_password': 'faux', 'new_password': 'Patrick2027x', 'new_password_confirm': 'Patrick2027x'},
             follow_redirects=True)
check('Mot de passe actuel incorrect' in text(r), 'mot de passe provisoire faux : refusé')
r = pat.post('/mot-de-passe', data={'current_password': 'Provisoire1', 'new_password': 'Provisoire1', 'new_password_confirm': 'Provisoire1'},
             follow_redirects=True)
check('différent' in text(r), 'garder le même mot de passe : refusé')
r = pat.post('/mot-de-passe', data={'current_password': 'Provisoire1', 'new_password': 'Secret2027z', 'new_password_confirm': 'Secret2027z'},
             follow_redirects=True)
check('Mot de passe changé' in text(r) and pat.get('/dashboard').status_code == 200, 'nouveau mot de passe enregistré, accès au site')
check(not app.test_client().post('/login', data={'tontine': 'sure', 'username': 'patrick', 'password': 'Provisoire1'}).headers
      .get('Location', '/login').endswith('/dashboard'), 'le mot de passe provisoire ne fonctionne plus')

# ---------------------------------------------------------------- changement de mot de passe : autres appareils déconnectés
tel = app.test_client()
tel.post('/login', data={'tontine': 'sure', 'username': 'patrick', 'password': 'Secret2027z'})
check(tel.get('/dashboard').status_code == 200, 'Patrick connecté aussi sur son téléphone')
pat.post('/mot-de-passe', data={'current_password': 'Secret2027z', 'new_password': 'Nouveau2028k', 'new_password_confirm': 'Nouveau2028k'})
check(pat.get('/dashboard').status_code == 200, "l'appareil qui change le mot de passe reste connecté")
r = tel.get('/dashboard')
check(r.status_code == 302 and '/login' in r.headers['Location'], 'le téléphone (ancienne session) est déconnecté automatiquement')

# ---------------------------------------------------------------- nouvelle session à chaque connexion
c = app.test_client()
c.get('/login')
with c.session_transaction() as sess:
    sess['piege'] = 'valeur posée par un attaquant'
c.post('/login', data={'tontine': 'sure', 'username': 'germain', 'password': 'Fotsing2026'})
with c.session_transaction() as sess:
    check('piege' not in sess, 'la session est renouvelée à la connexion (pas de fixation de session)')

# ---------------------------------------------------------------- ancien chiffrement mis à niveau
with app.app_context(), tenant_bypass():
    u = User.query.filter_by(tontine_id=tid, username='germain').one()
    u.password_hash = generate_password_hash('Fotsing2026', method='pbkdf2:sha256')
    db.session.commit()
app.test_client().post('/login', data={'tontine': 'sure', 'username': 'germain', 'password': 'Fotsing2026'})
with app.app_context(), tenant_bypass():
    check(User.query.filter_by(tontine_id=tid, username='germain').one().password_hash.startswith('scrypt:'),
          'ancien chiffrement (pbkdf2) remplacé par scrypt à la connexion')

# ---------------------------------------------------------------- en-têtes de protection
r = app.test_client().get('/', headers={'X-Forwarded-Proto': 'https'})
hd = r.headers
check(hd.get('X-Frame-Options') == 'SAMEORIGIN' and "frame-ancestors 'self'" in hd.get('Content-Security-Policy', ''),
      'site non intégrable dans une autre page (anti « clickjacking »)')
check(hd.get('X-Content-Type-Options') == 'nosniff' and hd.get('Referrer-Policy') == 'strict-origin-when-cross-origin',
      'en-têtes nosniff et politique de référent')
check('https://pay.saspay.me' in hd.get('Content-Security-Policy', ''), 'la redirection vers la page de paiement SasPay reste permise')
check(pat.get('/dashboard').headers.get('Cache-Control') == 'no-store', 'pages personnelles jamais gardées en cache')

# ---------------------------------------------------------------- déconnexion avec « Se souvenir de moi »
for remember in (False, True):
    c = app.test_client()
    data = {'tontine': 'sure', 'username': 'germain', 'password': 'Fotsing2026'}
    if remember:
        data['remember'] = 'y'
    c.post('/login', data=data)
    h = c.get('/dashboard').get_data(as_text=True)
    if not remember:
        check('topbar-logout' in h, 'bouton « Déconnexion » toujours visible en haut de page (téléphone, tablette, PC)')
    c.get('/logout')
    r = c.get('/dashboard')
    check(r.status_code == 302 and '/login' in r.headers['Location'],
          'déconnexion effective' + (' même avec « Se souvenir de moi » coché' if remember else ''))

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)

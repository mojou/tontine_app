"""Réglages de mise en ligne (PythonAnywhere) : https dans les liens, vraie IP des visiteurs, cookies sécurisés."""
import os
import re
import sys

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'pr.db').replace(os.sep, '/')
os.environ['TRUST_PROXY'] = '1'
os.environ['SESSION_COOKIE_SECURE'] = 'True'
os.environ['REQUIRE_EMAIL_CONFIRMATION'] = 'True'
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, MAIL_USERNAME='', MAIL_PASSWORD='')
from models import LoginAttempt  # noqa: E402

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


PROXY = {'X-Forwarded-For': '41.202.219.75', 'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'germainbob.pythonanywhere.com'}
check(app.config['SESSION_COOKIE_SECURE'] and app.config['REMEMBER_COOKIE_SECURE'], 'cookies de connexion réservés au https')

c = app.test_client()
outbox = app.extensions.setdefault('outbox', [])
c.post('/inscription', headers=PROXY, data={'name': 'Tontine En Ligne', 'slug': 'en-ligne', 'first_name': 'Awa', 'last_name': 'Diop',
                                            'email': 'awa@exemple.cm', 'phone': '699000001', 'username': 'awa',
                                            'password': 'Awa2026xx', 'password_confirm': 'Awa2026xx'})
link = re.search(r'\S+/inscription/confirmer/\S+', outbox[-1]['body']).group(0) if outbox else ''
check(link.startswith('https://germainbob.pythonanywhere.com/inscription/confirmer/'),
      f'lien de confirmation en https sur germainbob.pythonanywhere.com ({link[:60]}…)')

r = c.post('/login', headers=PROXY, data={'tontine': 'en-ligne', 'username': 'inconnu', 'password': 'mauvais'})
with app.app_context():
    keys = [a.ip_address for a in LoginAttempt.query.all()]
check(any('41.202.219.75' in (k or '') for k in keys), f"tentatives comptées par la vraie IP du visiteur, pas celle du serveur ({keys[:2]})")

# ---------------------------------------------------------------- super-admin : connexion quand une seule tontine existe
from models import User, Tontine  # noqa: E402
from tenancy import tenant_bypass  # noqa: E402
with app.app_context(), tenant_bypass():
    public = Tontine.query.filter(Tontine.is_active == True, Tontine.pending_confirmation.isnot(True)).count()  # noqa: E712
    sa = User.query.filter_by(role='SUPERADMIN').first()
    sa.set_password('Super2026x')
    sa_name = sa.username
    db.session.commit()
check(public == 1, f'situation reproduite : une seule tontine publique ({public})')
v = app.test_client()
h = v.get('/login', headers=PROXY).get_data(as_text=True)
check('<select name="tontine"' in h and 'Administration de la plateforme' not in h and '__plateforme__' not in h,
      'page de connexion des membres : la liste des tontines, sans « Administration de la plateforme »')
r = v.get('/administration', headers=PROXY)
check(r.status_code == 302 and '/login?t=__plateforme__' in r.headers['Location'], 'adresse réservée /administration')
h = v.get(r.headers['Location'], headers=PROXY).get_data(as_text=True)
check('Administration de la plateforme' in h and 'name="tontine" value="__plateforme__"' in h and '<select name="tontine"' not in h,
      "/administration : connexion directe à l'administration, sans liste de tontines")
check('/administration' not in v.get('/', headers=PROXY).get_data(as_text=True), "l'adresse réservée n'apparaît pas sur le site")
r = v.post('/login', headers=PROXY, data={'tontine': m.PLATFORM_LOGIN, 'username': sa_name, 'password': 'Super2026x'})
check(r.status_code == 302 and r.headers['Location'].endswith('/superadmin'), 'le super-admin se connecte depuis la page de connexion')

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)

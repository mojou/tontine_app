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

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)

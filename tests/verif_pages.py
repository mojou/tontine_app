import os, sys
S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'mt.db').replace(os.sep, '/')
sys.path.insert(0, P); os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import app as m
app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, PROPAGATE_EXCEPTIONS=True)
from models import User, Member, Tontine
pages = ['/dashboard', '/members', '/transactions', '/transactions/add', '/loans', '/sanctions', '/sanctions/add',
         '/aides', '/meetings', '/meetings/add', '/annonces', '/annonces/add', '/tontine-cycles', '/tontine-cycles/add',
         '/reports', '/audit-logs', '/profile', '/votes', '/votes/add', '/tirages', '/galerie', '/parametres', '/members/add', '/avals', '/cotisations', '/cotisations?year=2025', '/seances', '/exercice', '/demandes-mot-de-passe']
bad = []
with app.app_context():
    users = [(u.id, u.role, u.username) for u in User.query.filter(User.is_active == True).all()]
    jsb = Tontine.query.filter_by(slug='jsb').first()
    member_ids = [x.id for x in Member.query.filter_by(tontine_id=jsb.id).limit(3).all()]
for uid, role, name in users:
    c = app.test_client()
    with c.session_transaction() as s:
        s['_user_id'] = str(uid); s['_fresh'] = True
    extra = [f'/members/{i}' for i in member_ids] + ['/tontine-cycles/1', '/tontine-cycles/1/tirage', '/meetings/1']
    for url in pages + extra:
        try:
            r = c.get(url)
            if r.status_code >= 500: bad.append((role, url, r.status_code))
        except Exception as e:
            bad.append((role, url, repr(e)[:160]))
c = app.test_client()
for url in ['/', '/t/jsb', '/t/demo', '/login', '/login?t=jsb', '/register?t=jsb', '/register', '/mot-de-passe-oublie', '/mot-de-passe-oublie?t=jsb', '/reinitialiser/xyz']:
    try:
        r = c.get(url)
        if r.status_code >= 500: bad.append(('anonyme', url, r.status_code))
    except Exception as e:
        bad.append(('anonyme', url, repr(e)[:160]))
print('roles testes:', sorted({r for _, r, _ in users}))
print(f'{len(users) * 30} requêtes')
print('ERREURS:', len(bad))
for b in bad: print(' ', b)

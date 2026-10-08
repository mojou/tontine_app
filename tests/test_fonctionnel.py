import os, sys, io, re
S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'test.db').replace(os.sep, '/')
sys.path.insert(0, P); os.chdir(P)
import app as m
app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'))
from models import User, Member, Poll, TontineDraw, TontineCycleDetail, GalleryPhoto

def check(cond, msg):
    print(('OK  ' if cond else 'FAIL') + ' ' + msg)
    if not cond: check.failed = True
check.failed = False

def login(c, username):
    with app.app_context():
        u = User.query.filter_by(username=username).first()
        uid = u.id
    with c.session_transaction() as s:
        s['_user_id'] = str(uid); s['_fresh'] = True

c = app.test_client()
r = c.get('/t/jsb'); html = r.get_data(as_text=True)
check(r.status_code == 200 and 'Le bureau exécutif' in html, 'landing anonyme 200')

login(c, 'president')
for url in ['/votes', '/votes/add', '/tirages', '/galerie', '/dashboard']:
    r = c.get(url); check(r.status_code == 200, f'GET {url} -> {r.status_code}')

# Vote
r = c.post('/votes/add', data={'title': 'Test élection', 'description': 'desc', 'options': 'Alice\nBob\nBob\n', 'is_anonymous': 'on'})
check(r.status_code == 302, 'création vote')
with app.app_context():
    poll = Poll.query.order_by(Poll.id.desc()).first(); pid = poll.id
    check(len(poll.options) == 2, 'doublons de choix supprimés')
    opt = poll.options[0].id
r = c.post('/votes/add', data={'title': 'X', 'options': 'Seul'}); check('au moins deux' in r.get_data(as_text=True), 'validation 2 choix')
r = c.get(f'/votes/{pid}'); check(r.status_code == 200, 'détail vote')
r = c.post(f'/votes/{pid}/vote', data={'option_id': opt}, follow_redirects=True)
check('vote a été enregistré' in r.get_data(as_text=True) or 'membres actifs' in r.get_data(as_text=True), 'vote enregistré (ou refusé si non actif)')
r = c.post(f'/votes/{pid}/vote', data={'option_id': opt}, follow_redirects=True)
check('déjà voté' in r.get_data(as_text=True) or 'membres actifs' in r.get_data(as_text=True), 'double vote refusé')
r = c.post(f'/votes/{pid}/close', follow_redirects=True); check('Résultats' in r.get_data(as_text=True), 'clôture + résultats')

# Tirage : création d'un cycle avec 3 membres actifs
with app.app_context():
    ids = [mm.id for mm in Member.query.filter_by(is_active=True, status='ACTIF').limit(4).all()]
    active = TontineCycleDetail.query.filter_by(status='EN_COURS').first()
print('membres pour cycle:', ids, 'cycle actif existant:', bool(active))
if True:
    r = c.post('/tontine-cycles/add', data=dict({'contribution_type_id': '', 'custom_amount': '5100', 'mode': 'TIRAGE'}, **{f'hands_{i}': 1 for i in ids}))
    check(r.status_code == 302, 'création cycle')
with app.app_context():
    cyc = TontineCycleDetail.query.filter_by(status='EN_COURS').order_by(TontineCycleDetail.id.desc()).first(); cid = cyc.id
r = c.get(f'/tontine-cycles/{cid}/tirage'); check(r.status_code == 200, 'page tirage')
r = c.post(f'/tontine-cycles/{cid}/tirage', data={'notes': 'test'}); check(r.status_code == 302 and 'reveal=' in r.headers['Location'], 'tirage effectué')
r = c.get(r.headers['Location']); h = r.get_data(as_text=True)
check(r.status_code == 200 and 'revealList' in h, 'animation de révélation')
with app.app_context():
    cyc = db.session.get(TontineCycleDetail, cid)
    d = TontineDraw.query.order_by(TontineDraw.id.desc()).first()
    pos = sorted(x.position for x in d.results)
    check(pos == list(range(cyc.beneficiaries_count + 1, cyc.beneficiaries_count + 1 + len(pos))), f'positions continues {pos}')
    nxt = cyc.get_next_beneficiary()
    check(nxt and nxt.id == d.results[0].member_id, 'prochain bénéficiaire = 1er tiré')
r = c.get(f'/tontine-cycles/{cid}'); check(r.status_code == 200, 'détail cycle (bouton tirage)')

# Galerie
img = open(os.path.join(P, 'app/static/images/images.png'), 'rb').read()
r = c.post('/galerie/upload', data={'photos': [(io.BytesIO(img), 'a.png'), (io.BytesIO(img), 'b.png')], 'caption': 'Réunion', 'is_hero': 'on'}, content_type='multipart/form-data')
check(r.status_code == 302, 'upload galerie')
with app.app_context():
    ph = GalleryPhoto.query.all(); check(sum(p.is_hero for p in ph) == 1 and len(ph) >= 2, 'une seule bannière')
    gid = [p.id for p in ph if not p.is_hero][0]
c2 = app.test_client(); h = c2.get('/t/jsb').get_data(as_text=True)
check('id="galerie"' in h and 'Réunion' in h, 'galerie affichée sur la landing')
r = c.post(f'/galerie/{gid}/delete'); check(r.status_code == 302, 'suppression photo')

# Membre simple : pas d'accès admin
with app.app_context():
    mu = User.query.filter_by(role='MEMBRE', is_active=True).first()
if mu:
    c3 = app.test_client(); login(c3, mu.username)
    check(c3.get('/votes').status_code == 200, 'membre voit les votes')
    check(c3.get('/galerie').status_code == 302, 'membre refusé sur la galerie admin')
    check(c3.post(f'/tontine-cycles/{cid}/tirage').status_code == 403, 'membre ne peut pas tirer')
print('RESULTAT:', 'ECHEC' if check.failed else 'TOUT OK')

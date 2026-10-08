import io
import os
import re
import sys

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'mt.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402
from flask import g  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'))
from models import (User, Member, Poll, Transaction, Tontine, GalleryPhoto,  # noqa: E402
                    TontineCycleDetail, TontineDraw)
from tenancy import tenant_bypass  # noqa: E402

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def set_password(tontine_slug, username, pwd):
    with app.app_context():
        q = User.query.filter_by(username=username)
        if tontine_slug is None:
            q = q.filter_by(tontine_id=None)
        else:
            q = q.filter_by(tontine_id=Tontine.query.filter_by(slug=tontine_slug).one().id)
        u = q.one()
        u.set_password(pwd)
        u.is_active = True
        db.session.commit()


def do_login(client, tontine, username, pwd):
    return client.post('/login', data={'tontine': tontine, 'username': username, 'password': pwd})


def body(r):
    return r.get_data(as_text=True)


# ---------------------------------------------------------------- données de départ
with app.app_context():
    jsb = Tontine.query.filter_by(slug='jsb').one()
    jsb_id = jsb.id
    jsb_member = Member.query.filter_by(tontine_id=jsb_id).order_by(Member.id).first()
    jsb_member_id, jsb_member_name = jsb_member.id, jsb_member.last_name
    jsb_tx_sum = float(db.session.query(db.func.sum(Transaction.amount)).filter(Transaction.tontine_id == jsb_id).scalar() or 0)
    check(Member.query.filter(Member.tontine_id.is_(None)).count() == 0, 'migration : tous les membres ont une tontine')
    check(User.query.filter(User.tontine_id.is_(None), User.role != 'SUPERADMIN').count() == 0, 'migration : tous les comptes ont une tontine')

set_password(None, 'superadmin', 'SuperPass123')
set_password('jsb', 'president', 'JsbPass123')

# ---------------------------------------------------------------- pages publiques
anon = app.test_client()
r = anon.get('/')
check(r.status_code == 200 and 'Hélen' in body(r), 'accueil plateforme (plus de redirection auto)')
r = anon.get('/t/jsb')
check(r.status_code == 200 and 'JSB Tontine' in body(r), 'accueil /t/jsb')
check(anon.get('/t/inexistante').status_code == 404, 'tontine inconnue -> 404')
check('admin123' not in body(anon.get('/login')), 'mots de passe de test retirés de la page de connexion')

# ---------------------------------------------------------------- super-admin
sa = app.test_client()
r = do_login(sa, '__plateforme__', 'superadmin', 'SuperPass123')
check(r.status_code == 302 and '/superadmin' in r.headers['Location'], 'connexion super-admin')
check(do_login(app.test_client(), 'jsb', 'superadmin', 'SuperPass123').status_code == 200, 'super-admin refusé via une tontine')
r = sa.get('/members')
check(r.status_code == 302 and '/superadmin' in r.headers['Location'], 'super-admin redirigé hors des pages métier')
r = sa.post('/superadmin/tontines/add', data={'name': 'Demo', 'slug': 'Mauvais Slug', 'first_name': 'a', 'last_name': 'b',
                                              'email': 'x@y.z', 'phone': '1', 'username': 'u', 'password': '12345678'})
check('Identifiant' in body(r), 'slug invalide refusé')
r = sa.post('/superadmin/tontines/add', data={'name': 'Tontine Démo', 'slug': 'demo', 'location': 'Douala',
                                              'first_name': 'Paul', 'last_name': 'Bmembre', 'email': 'paul@demo.cm',
                                              'phone': '699000000', 'username': 'president', 'password': 'DemoPass123'})
check(r.status_code == 302, 'création tontine « demo » avec président « president » (même identifiant que JSB)')
check(sa.post('/superadmin/tontines/add', data={'name': 'X', 'slug': 'demo', 'first_name': 'a', 'last_name': 'b', 'email': 'a@b.c',
                                                'phone': '1', 'username': 'u', 'password': '12345678'}).status_code == 200,
      'slug en double refusé')
with app.app_context():
    demo_id = Tontine.query.filter_by(slug='demo').one().id

r = anon.get('/')
check(r.status_code == 200 and 'Tontine Démo' in body(r) and 'JSB Tontine' in body(r), 'portail liste les 2 tontines')

# ---------------------------------------------------------------- même identifiant, deux tontines
a = app.test_client()
b = app.test_client()
check(do_login(a, 'jsb', 'president', 'JsbPass123').status_code == 302, 'login president@jsb')
check(do_login(b, 'demo', 'president', 'DemoPass123').status_code == 302, 'login president@demo')
check(do_login(app.test_client(), 'demo', 'president', 'JsbPass123').status_code == 200, 'mot de passe JSB refusé sur demo')

# ---------------------------------------------------------------- isolation lecture (tontine B)
r = b.get('/members')
check(r.status_code == 200 and 'Bmembre' in body(r) and jsb_member_name not in body(r), 'B ne voit que ses membres')
r = b.get(f'/members/{jsb_member_id}')
check(r.status_code in (302, 403, 404) and jsb_member_name not in body(r), f'B ne peut pas ouvrir un membre JSB ({r.status_code})')
r = b.get('/transactions')
check(r.status_code == 200 and jsb_member_name not in body(r), 'B ne voit aucune transaction JSB')
r = b.get('/dashboard')
check(r.status_code == 200, 'dashboard B')

# ---------------------------------------------------------------- isolation écriture
with app.app_context():
    b_member_id = Member.query.filter_by(tontine_id=demo_id).one().id
r = b.post('/transactions/add', data={'member_id': jsb_member_id, 'type': 'PRESENCE', 'amount': 1000,
                                      'description': 'pirate', 'payment_mode': 'ESPECE'})
with app.app_context():
    check(Transaction.query.filter_by(description='pirate').count() == 0, 'B ne peut pas créer une transaction pour un membre JSB')
r = b.post('/transactions/add', data={'member_id': b_member_id, 'type': 'PRESENCE', 'amount': 777,
                                      'description': 'cotisation B', 'payment_mode': 'ESPECE'})
with app.app_context():
    t = Transaction.query.filter_by(description='cotisation B').first()
    check(t is not None and t.tontine_id == demo_id, 'transaction B rattachée automatiquement à B')
r = b.post(f'/loan/request', data={'member_id': jsb_member_id, 'amount': 1000, 'duration_months': 3})
check(r.status_code == 404, 'B ne peut pas demander un emprunt pour un membre JSB')
r = b.post(f'/members/{jsb_member_id}/delete')
with app.app_context():
    check(db.session.get(Member, jsb_member_id).is_active, 'B ne peut pas désactiver un membre JSB')

# Ajout d'un membre B avec un email déjà utilisé dans JSB (autorisé : unicité par tontine)
with app.app_context():
    jsb_email = db.session.get(Member, jsb_member_id).email
r = b.post('/members/add', data={'first_name': 'Jean', 'last_name': 'Doublon', 'email': jsb_email, 'phone': '699111222',
                                 'username': 'jean', 'role': 'MEMBRE', 'password': 'Password123', 'confirm_password': 'Password123',
                                 'group_type': '', 'position_in_group': '', 'chosen_tontine_amount': ''})
with app.app_context():
    dup = Member.query.filter_by(last_name='Doublon').first()
    check(dup is not None and dup.tontine_id == demo_id, f'même email accepté dans une autre tontine ({r.status_code})')

# ---------------------------------------------------------------- votes / tirages / galerie
r = b.post('/votes/add', data={'title': 'Vote secret B', 'options': 'Oui\nNon', 'is_anonymous': 'on'})
with app.app_context():
    b_poll = Poll.query.filter_by(title='Vote secret B').one()
    b_poll_id = b_poll.id
    check(b_poll.tontine_id == demo_id and all(o.tontine_id == demo_id for o in b_poll.options), 'vote B + options rattachés à B')
check('Vote secret B' not in body(a.get('/votes')), 'JSB ne voit pas le vote de B')
check(a.get(f'/votes/{b_poll_id}').status_code == 404, 'JSB ne peut pas ouvrir le vote de B')
with app.app_context():
    opt = b_poll.options[0].id
a.post(f'/votes/{b_poll_id}/vote', data={'option_id': opt})
with app.app_context():
    check(Poll.query.get(b_poll_id).total_votes == 0, 'JSB ne peut pas voter dans B')

with app.app_context():
    b_ids = [x.id for x in Member.query.filter_by(tontine_id=demo_id).all()]
r = b.post('/tontine-cycles/add', data=dict({'contribution_type_id': '', 'custom_amount': '5000', 'mode': 'TIRAGE'}, **{f'hands_{i}': 1 for i in b_ids + [jsb_member_id]}))
with app.app_context():
    cyc = TontineCycleDetail.query.filter_by(tontine_id=demo_id).first()
    check(cyc is not None and cyc.cycle_number == 1, 'cycle B numéroté à partir de 1')
    check(cyc.group_type == str(len(b_ids)) and float(cyc.total_amount) == 5000 * len(b_ids), f'membre JSB injecté ignoré dans le cycle B ({cyc.group_type} membres, {cyc.total_amount})')
    check(db.session.get(Member, jsb_member_id).tontine_id == jsb_id, 'membre JSB non modifié')
    jsb_cycle = TontineCycleDetail.query.filter_by(tontine_id=jsb_id).first()
if jsb_cycle:
    check(b.get(f'/tontine-cycles/{jsb_cycle.id}/tirage').status_code == 404, 'B ne peut pas voir le tirage JSB')
    check(b.post(f'/tontine-cycles/{jsb_cycle.id}/tirage').status_code == 404, 'B ne peut pas lancer le tirage JSB')
r = b.post(f'/tontine-cycles/{cyc.id}/tirage', data={'notes': 'B'})
with app.app_context():
    d = TontineDraw.query.filter_by(tontine_id=demo_id).first()
    check(d is not None and all(x.member.tontine_id == demo_id for x in d.results), 'tirage B ne contient que des membres B')

img = open(os.path.join(P, 'app/static/images/images.png'), 'rb').read()
b.post('/galerie/upload', data={'photos': [(io.BytesIO(img), 'b.png')], 'caption': 'Photo B', 'is_hero': 'on'},
       content_type='multipart/form-data')
a.post('/galerie/upload', data={'photos': [(io.BytesIO(img), 'a.png')], 'caption': 'Photo A', 'is_hero': 'on'},
       content_type='multipart/form-data')
with app.app_context():
    pb = GalleryPhoto.query.filter_by(caption='Photo B').one()
    check(pb.is_hero and pb.filename.startswith(f'{demo_id}/'), 'bannière B conservée quand A change la sienne + dossier propre à B')
    check(os.path.isfile(os.path.join(S, 'uploads', pb.filename)), 'fichier B enregistré dans uploads/<id B>/')
home_a = body(anon.get('/t/jsb'))
with app.app_context():
    pa = GalleryPhoto.query.filter_by(caption='Photo A').one()
check(pb.filename not in home_a and pa.filename in home_a, 'accueil JSB : sa bannière, aucune photo de B')
check(a.post(f'/galerie/{pb.id}/delete').status_code == 404, 'JSB ne peut pas supprimer une photo de B')

# ---------------------------------------------------------------- agrégats, get(), UPDATE en masse
with app.test_request_context():
    g.tenant_id = demo_id
    total_b = float(db.session.query(db.func.sum(Transaction.amount)).scalar() or 0)
    check(total_b == 777.0, f'somme SQL filtrée sur B ({total_b})')
    check(db.session.get(Member, jsb_member_id) is None, 'session.get() sur un id JSB -> None depuis B')
    GalleryPhoto.query.update({'caption': 'piraté'})
    db.session.commit()
with app.app_context():
    check(GalleryPhoto.query.filter_by(caption='Photo A').count() == 1, 'UPDATE en masse depuis B sans effet sur JSB')
    jsb_after = float(db.session.query(db.func.sum(Transaction.amount)).filter(Transaction.tontine_id == jsb_id).scalar() or 0)
    check(jsb_after == jsb_tx_sum, 'totaux JSB inchangés')

with app.test_request_context():
    g.tenant_id = None  # requête sans tontine
    check(Member.query.count() == 0, 'requête sans tontine : aucune donnée visible (fermé par défaut)')
    db.session.add(Transaction(member_id=b_member_id, type='PRESENCE', amount=1))
    try:
        db.session.commit()
        check(False, 'insertion sans tontine refusée')
    except RuntimeError:
        db.session.rollback()
        check(True, 'insertion sans tontine refusée')

# ---------------------------------------------------------------- paramètres par tontine
r = b.post('/parametres', data={'name': 'Tontine Démo', 'presence_amount': '2000', 'fonds_caisse_amount': '7000',
                                'loan_interest_rate': '7', 'max_aid_per_member': '2', 'contact_phone': '699 00 00 00'})
check(r.status_code == 302, 'président B modifie ses paramètres')
with app.app_context():
    check(float(Tontine.query.get(demo_id).loan_interest_rate) == 7 and float(Tontine.query.get(jsb_id).loan_interest_rate) == 5,
          'taux propre à chaque tontine')
check(b.post('/parametres', data={'name': 'x', 'presence_amount': '1', 'fonds_caisse_amount': '1',
                                  'loan_interest_rate': '500', 'max_aid_per_member': '2'}).status_code == 200, 'taux > 100 % refusé')
check('699 00 00 00' in body(anon.get('/t/demo')), 'contact B affiché sur son accueil')

# ---------------------------------------------------------------- désactivation
sa.post(f'/superadmin/tontines/{demo_id}/toggle')
r = b.get('/dashboard')
check(r.status_code == 302, 'tontine désactivée : session B fermée')
check(anon.get('/t/demo').status_code == 404, 'tontine désactivée : accueil indisponible')
check(do_login(app.test_client(), 'demo', 'president', 'DemoPass123').status_code == 200, 'tontine désactivée : connexion refusée')
check(a.get('/dashboard').status_code == 200, 'JSB non affectée')

# ---------------------------------------------------------------- open redirect
c = app.test_client()
r = c.post('/login?next=https://evil.example', data={'tontine': 'jsb', 'username': 'president', 'password': 'JsbPass123'})
check('evil.example' not in r.headers.get('Location', ''), 'redirection externe après connexion bloquée')

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)

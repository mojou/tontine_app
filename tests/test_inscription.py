import os
import sys

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'su.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'))
from models import Tontine, Member, User  # noqa: E402

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def body(r):
    return r.get_data(as_text=True)


SIGNUP = {'name': 'Tontine des Amis', 'slug': 'amis', 'location': 'Bafoussam', 'first_name': 'Hélène',
          'last_name': 'Ngo', 'email': 'helene@amis.cm', 'phone': '699000001', 'username': 'helene',
          'password': 'Helene2026', 'password_confirm': 'Helene2026'}

anon = app.test_client()
r = anon.get('/')
h = body(r)
check(r.status_code == 200 and 'Hélen' in h and 'Créer ma tontine' in h and 'logo.svg' in h, "/ = page d'accueil Hélentine")
check('JSB Tontine' in h, "la JSB apparaît dans « Rejoindre une tontine »")
check(anon.get('/static/images/logo.svg').status_code == 200 and anon.get('/static/css/theme.css').status_code == 200, 'logo et thème servis')
check(anon.get('/inscription').status_code == 200, 'formulaire de création')

r = anon.post('/inscription', data=dict(SIGNUP, password_confirm='autre'))
check(r.status_code == 200 and 'correspondent pas' in body(r), 'mots de passe différents refusés')
r = anon.post('/inscription', data=dict(SIGNUP, website='spam'))
with app.app_context():
    check(Tontine.query.filter_by(slug='amis').count() == 0, 'robot (champ piège) ignoré')
r = anon.post('/inscription', data=dict(SIGNUP, slug='jsb'))
check('déjà prise' in body(r), 'adresse déjà prise refusée')

founder = app.test_client()
r = founder.post('/inscription', data=SIGNUP)
check(r.status_code == 302 and r.headers['Location'].endswith('/dashboard'), 'création -> connecté et redirigé vers le tableau de bord')
with app.app_context():
    t = Tontine.query.filter_by(slug='amis').one()
    u = User.query.filter_by(tontine_id=t.id, username='helene').one()
    check(u.role == 'PRESIDENT' and u.member.tontine_id == t.id, 'fondatrice = présidente de sa tontine')
h = body(founder.get('/dashboard'))
check('Premiers pas' in h and '/register?t=amis' in h, 'guide « Premiers pas » + lien d\'inscription')
check('Tontine des Amis' in h and 'JSB' not in h, 'tableau de bord de la nouvelle tontine uniquement')
check(founder.get('/inscription').status_code == 302, 'déjà connecté : /inscription redirige')

h = body(anon.get('/t/amis'))
check('Tontine des Amis' in h and 'Demander à rejoindre' in h and 'Propulsé par' in h, 'page publique de la nouvelle tontine')
check(anon.get('/register?t=amis').status_code == 200, 'formulaire d\'adhésion')
check(anon.get('/register').status_code == 302, 'adhésion sans tontine -> retour accueil')
r = anon.post('/register?t=amis', data={'first_name': 'Marc', 'last_name': 'Tchoua', 'email': 'marc@amis.cm', 'phone': '699123456',
                                        'cotisation_type': 'PRESENCE', 'tontine_amount': '', 'username': 'marc',
                                        'password': 'Marc2026', 'confirm_password': 'Marc2026'})
check(r.status_code == 302 and 't=amis' in r.headers['Location'], 'demande d\'adhésion envoyée')
with app.app_context():
    marc = Member.query.filter_by(email='marc@amis.cm').one()
    marc_id = marc.id
    check(marc.status == 'PENDING' and marc.tontine_id == t.id, 'membre en attente, rattaché à la bonne tontine')

member = app.test_client()
r = member.post('/login', data={'tontine': 'amis', 'username': 'marc', 'password': 'Marc2026'})
check(r.status_code == 200, 'compte en attente : connexion refusée')
check('Marc' in body(founder.get('/members?show_inactive=true')), 'la présidente voit la demande')
founder.post(f'/members/{marc_id}/activate')
r = member.post('/login', data={'tontine': 'amis', 'username': 'marc', 'password': 'Marc2026'})
check(r.status_code == 302, 'après validation : connexion du membre')
h = body(member.get('/dashboard'))
check(r.status_code == 302 and 'Premiers pas' not in h, 'le membre n\'a pas le guide du président')

app.config['ALLOW_PUBLIC_SIGNUP'] = False
check(app.test_client().get('/inscription').status_code == 302, 'création désactivable (ALLOW_PUBLIC_SIGNUP=False)')
check('Créer ma tontine' not in body(app.test_client().get('/')), 'bouton masqué quand désactivé')
app.config['ALLOW_PUBLIC_SIGNUP'] = True

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')

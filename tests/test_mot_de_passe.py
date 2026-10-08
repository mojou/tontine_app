import os
import re
import sys

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'rs.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'))
from models import Tontine, Member, User, PasswordResetRequest  # noqa: E402

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def body(r):
    return r.get_data(as_text=True)


def login(client, slug, username, pwd):
    return client.post('/login', data={'tontine': slug, 'username': username, 'password': pwd})


# Tontine « amis » : présidente Hélène, secrétaire Awa, membre Marc
pres = app.test_client()
pres.post('/inscription', data={'name': 'Tontine des Amis', 'slug': 'amis', 'first_name': 'Hélène', 'last_name': 'Ngo',
                                'email': 'h@amis.cm', 'phone': '+237699000001', 'username': 'helene',
                                'password': 'Helene2026', 'password_confirm': 'Helene2026'})
for fn, role, phone in [('Marc', 'MEMBRE', '+237699111222'), ('Awa', 'SECRETAIRE', '699333444')]:
    pres.post('/members/add', data={'first_name': fn, 'last_name': 'Test', 'email': f'{fn.lower()}@amis.cm', 'phone': phone,
                                    'username': fn.lower(), 'role': role, 'password': 'Passw0rd1', 'confirm_password': 'Passw0rd1'})
with app.app_context():
    tid = Tontine.query.filter_by(slug='amis').one().id
    marc_mid = Member.query.filter_by(tontine_id=tid, first_name='Marc').one().id
    helene_mid = Member.query.filter_by(tontine_id=tid, first_name='Hélène').one().id
    jsb_member = Member.query.filter(Member.tontine_id != tid).first().id

anon = app.test_client()
check('Mot de passe oublié' in body(anon.get('/login?t=amis')), 'lien « Mot de passe oublié ? » sur la connexion')
check(anon.get('/mot-de-passe-oublie?t=amis').status_code == 200, 'page mot de passe oublié')

r = anon.post('/mot-de-passe-oublie', data={'tontine': 'amis', 'identifier': 'inconnu'}, follow_redirects=True)
msg_unknown = 'Si un compte correspond' in body(r)
with app.app_context():
    check(PasswordResetRequest.query.count() == 0 and msg_unknown, 'compte inconnu : même message, aucune demande créée')
anon.post('/mot-de-passe-oublie', data={'tontine': 'amis', 'identifier': 'marc'})
anon.post('/mot-de-passe-oublie', data={'tontine': 'amis', 'identifier': 'MARC@amis.cm'})
with app.app_context():
    reqs = PasswordResetRequest.query.all()
    check(len(reqs) == 1 and reqs[0].tontine_id == tid, 'demande créée une seule fois (identifiant puis email)')
    check(not reqs[0].email_sent, "pas de serveur email : la demande passe par le bureau")
anon.post('/mot-de-passe-oublie', data={'tontine': 'jsb', 'identifier': 'marc'})
with app.app_context():
    check(PasswordResetRequest.query.count() == 1, "même identifiant dans une autre tontine : rien")

check(login(pres, 'amis', 'helene', 'Helene2026').status_code in (200, 302), 'présidente connectée')
h = body(pres.get('/dashboard'))
check('ont oublié leur mot de passe' in h, 'alerte sur le tableau de bord de la présidente')
h = body(pres.get('/demandes-mot-de-passe'))
check('marc' in h and '+237699111222' in h, 'la demande de Marc est listée avec son téléphone')

r = pres.post(f'/members/{marc_mid}/reset-link')
h = body(r)
link = re.search(r'value="(http[^"]+/reinitialiser/[^"]+)"', h)
check(r.status_code == 200 and link and 'wa.me/237699111222' in h, 'lien généré + bouton WhatsApp vers le numéro du membre')
link = link.group(1).replace('&amp;', '&') if link else ''
path = link.split('localhost')[-1] if 'localhost' in link else link[link.index('/reinitialiser'):]
with app.app_context():
    check(PasswordResetRequest.query.filter_by(status='EN_ATTENTE').count() == 0, 'demande marquée traitée')

marc = app.test_client()
check(marc.get(path).status_code == 200, 'le lien ouvre le formulaire')
r = marc.post(path, data={'password': 'court', 'password_confirm': 'court'})
check(r.status_code == 200 and 'au moins 8' in body(r), 'mot de passe trop faible refusé')
r = marc.post(path, data={'password': 'Nouveau2026', 'password_confirm': 'Autre2026'})
check('correspondent pas' in body(r), 'confirmation différente refusée')
r = marc.post(path, data={'password': 'Nouveau2026', 'password_confirm': 'Nouveau2026'})
check(r.status_code == 302 and 't=amis' in r.headers['Location'], 'mot de passe changé, retour à la connexion de la tontine')
check(login(app.test_client(), 'amis', 'marc', 'Passw0rd1').status_code == 200, 'ancien mot de passe refusé')
check(login(app.test_client(), 'amis', 'marc', 'Nouveau2026').status_code == 302, 'nouveau mot de passe accepté')
r = app.test_client().get(path, follow_redirects=True)
check('déjà été utilisé' in body(r), 'lien à usage unique')
r = app.test_client().get(path[:-3] + 'abc', follow_redirects=True)
check('invalide' in body(r), 'lien falsifié refusé')

# Droits
awa = app.test_client()
login(awa, 'amis', 'awa', 'Passw0rd1')
r = awa.post(f'/members/{helene_mid}/reset-link', follow_redirects=True)
check('Seul le président' in body(r), 'la secrétaire ne peut pas réinitialiser la présidente')
check(awa.post(f'/members/{marc_mid}/reset-link').status_code == 200, 'la secrétaire peut aider un membre')
marc_c = app.test_client()
login(marc_c, 'amis', 'marc', 'Nouveau2026')
check(marc_c.get('/demandes-mot-de-passe').status_code == 302, 'un membre ne voit pas les demandes')
check(pres.post(f'/members/{jsb_member}/reset-link').status_code == 404, "lien impossible pour un membre d'une autre tontine")

# Super-admin : président qui a oublié son mot de passe
with app.app_context():
    sa = User.query.filter_by(role='SUPERADMIN').one()
    sa.set_password('SuperPass123')
    db.session.commit()
sac = app.test_client()
login(sac, '__plateforme__', 'superadmin', 'SuperPass123')
check('Mot de passe du président' in body(sac.get('/superadmin')), 'bouton sur la page super-admin')
r = sac.post(f'/superadmin/tontines/{tid}/reset-president')
check(r.status_code == 200 and '/reinitialiser/' in body(r) and 'helene' in body(r), 'lien de réinitialisation du président')

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)

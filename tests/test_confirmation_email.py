"""Inscription d'une tontine : confirmation par e-mail sous 3 h, sinon suppression complète."""
import html
import os
import re
import sys
from datetime import timedelta

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'ce.db').replace(os.sep, '/')
os.environ['REQUIRE_EMAIL_CONFIRMATION'] = 'True'
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'),
                  REQUIRE_EMAIL_CONFIRMATION=True, EMAIL_CONFIRMATION_HOURS=3, MAIL_USERNAME='', MAIL_PASSWORD='')
from models import Tontine, Member, User, ContributionType, AidType, AuditLog  # noqa: E402
from tenancy import tenant_bypass  # noqa: E402

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def text(r):
    h = re.sub(r'(?s)<(script|style)\b.*?</\1>', ' ', r.get_data(as_text=True))
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', h)))


outbox = app.extensions.setdefault('outbox', [])


def signup(client, slug, email):
    return client.post('/inscription', data={'name': f'Tontine {slug}', 'slug': slug, 'first_name': 'Awa', 'last_name': 'Diop',
                                              'email': email, 'phone': '699000001', 'username': 'awa',
                                              'password': 'Awa2026xx', 'password_confirm': 'Awa2026xx'})


def tontine(slug):
    with app.app_context(), tenant_bypass():
        return Tontine.query.filter_by(slug=slug).first()


# ---------------------------------------------------------------- inscription : e-mail envoyé, tontine en attente
c = app.test_client()
r = signup(c, 'akwa', 'awa@akwa.cm')
check(r.status_code == 302 and '/inscription/en-attente/akwa' in r.headers['Location'], "après l'inscription : page « confirmez votre e-mail »")
t = tontine('akwa')
check(t is not None and t.pending_confirmation is True, 'la tontine est créée mais en attente de confirmation')
check(len(outbox) == 1 and outbox[0]['to'] == 'awa@akwa.cm' and 'Confirmez votre tontine' in outbox[0]['subject'],
      'un e-mail de confirmation est envoyé au fondateur')
mail = outbox[0]['body']
link = re.search(r'https?://\S+/inscription/confirmer/\S+', mail)
check(link is not None and '3 heures' in mail and 'supprimée' in mail and 'awa' in mail,
      "l'e-mail contient le lien, le délai de 3 h, l'avertissement et l'identifiant")
h = text(c.get('/inscription/en-attente/akwa'))
check('Confirmez votre adresse e-mail' in h and '3 heures' in h and 'a•' in h, 'page d\'attente : délai affiché, e-mail masqué')
check(c.get('/dashboard').status_code == 302, "pas connecté tant que l'e-mail n'est pas confirmé")

# invisible et inaccessible avant confirmation
v = app.test_client()
check(v.get('/t/akwa').status_code == 404, 'page publique de la tontine invisible avant confirmation')
check('Tontine akwa' not in text(v.get('/login')), 'absente de la liste de connexion')
r = v.post('/login', data={'tontine': 'akwa', 'username': 'awa', 'password': 'Awa2026xx'}, follow_redirects=True)
check("Confirmez d'abord votre adresse e-mail" in text(r), 'connexion refusée : « confirmez d\'abord votre adresse e-mail »')

# renvoyer le lien
c.post('/inscription/en-attente/akwa')
check(len(outbox) == 2, 'bouton « Renvoyer le lien » : un second e-mail part')

# ---------------------------------------------------------------- confirmation
path = link.group(0).split('localhost', 1)[-1]
r = c.get(path)
check(r.status_code == 302 and r.headers['Location'].endswith('/dashboard'), 'clic sur le lien : connecté et dirigé vers le tableau de bord')
t = tontine('akwa')
check(t.pending_confirmation is False and t.confirmed_at is not None, 'tontine confirmée (date de confirmation enregistrée)')
check('Adresse e-mail confirmée' in text(c.get('/dashboard')), 'message de bienvenue après confirmation')
check(v.get('/t/akwa').status_code == 200, 'la page publique devient visible')
r = app.test_client().get(path, follow_redirects=True)
check('déjà confirmée' in text(r), 'lien réutilisé : « déjà confirmée, connectez-vous »')
check(app.test_client().get('/inscription/confirmer/faux-jeton').status_code == 404, 'lien falsifié : refusé')

# ---------------------------------------------------------------- non confirmée dans les 3 h : supprimée
c2 = app.test_client()
signup(c2, 'oublie', 'paul@oublie.cm')
t = tontine('oublie')
with app.app_context(), tenant_bypass():
    tid = t.id
    check(Member.query.filter_by(tontine_id=tid).count() == 1 and ContributionType.query.filter_by(tontine_id=tid).count() > 0
          and AidType.query.filter_by(tontine_id=tid).count() > 0, 'tontine non confirmée : président, cotisations et barème créés')
    db.session.get(Tontine, tid).created_at -= timedelta(hours=2, minutes=59)
    db.session.commit()
with app.test_request_context():
    check(m.purge_unconfirmed_tontines(force=True) == 0, 'à 2 h 59 : encore conservée')
with app.app_context(), tenant_bypass():
    db.session.get(Tontine, tid).created_at -= timedelta(minutes=2)
    db.session.commit()
with app.test_request_context():
    check(m.purge_unconfirmed_tontines(force=True) == 1, 'après 3 h : supprimée')
with app.app_context(), tenant_bypass():
    leftovers = {name: model.query.filter_by(tontine_id=tid).count()
                 for name, model in [('membres', Member), ('comptes', User), ('cotisations', ContributionType), ('aides', AidType)]}
    check(tontine('oublie') is None and not any(leftovers.values()), f'suppression complète, rien ne reste {leftovers}')
    check(Tontine.query.filter_by(slug='akwa').first() is not None, 'la tontine confirmée, elle, est conservée')
old_link = re.search(r'https?://\S+/inscription/confirmer/\S+', outbox[-1]['body']).group(0).split('localhost', 1)[-1]
r = app.test_client().get(old_link, follow_redirects=True)
check("n'existe plus" in text(r) or 'expiré' in text(r), 'lien d\'une tontine supprimée : invite à la recréer')

# on peut la recréer avec la même adresse web et le même e-mail
r = signup(app.test_client(), 'oublie', 'paul@oublie.cm')
check(r.status_code == 302 and tontine('oublie') is not None, 'recréation possible avec la même adresse web')

# ---------------------------------------------------------------- lien expiré (plus de 3 h)
with app.test_request_context():
    with tenant_bypass():
        t = Tontine.query.filter_by(slug='oublie').first()
        u = User.query.filter_by(tontine_id=t.id).first()
        token = m._confirm_serializer().dumps({'t': t.id, 'u': u.id, 'e': u.email})


class _Expired:   # simule un lien de plus de 3 h (uniquement pour le lien de confirmation)
    def loads(self, *a, **kw):
        raise m.SignatureExpired('expiré')


real_serializer = m._confirm_serializer
m._confirm_serializer = lambda: _Expired()
r = app.test_client().get(f'/inscription/confirmer/{token}', follow_redirects=True)
m._confirm_serializer = real_serializer
check('Ce lien a expiré' in text(r) and 'Recréez-la' in text(r), 'lien expiré : message clair et retour à l\'inscription')

# ---------------------------------------------------------------- tontine créée par le super-admin : pas de confirmation
with app.app_context(), tenant_bypass():
    jsb = Tontine.query.filter_by(slug='jsb').first()
    check(jsb is None or not jsb.pending_confirmation, 'les tontines existantes ne sont pas concernées')
check(len([o for o in outbox if 'Confirmez' in o['subject']]) >= 3, "chaque inscription envoie bien son e-mail")

# ---------------------------------------------------------------- envoi réel via Gmail (serveur simulé)
import smtplib  # noqa: E402
from config import Config  # noqa: E402

check(Config.MAIL_USERNAME == 'ghelia.finance@gmail.com' and Config.MAIL_DEFAULT_SENDER == 'Ghelia Finance <ghelia.finance@gmail.com>'
      and Config.MAIL_SERVER == 'smtp.gmail.com' and Config.MAIL_PORT == 587, 'adresse d\'envoi : Ghelia Finance <ghelia.finance@gmail.com> via Gmail')
sent = {}


class FakeSMTP:
    def __init__(self, host, port, timeout=None):
        sent.update(host=host, port=port)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        sent['tls'] = True

    def login(self, user, pwd):
        sent.update(user=user, pwd=pwd)

    def send_message(self, msg):
        sent.update(sender=msg['From'], to=msg['To'], subject=msg['Subject'])


real_smtp = smtplib.SMTP
smtplib.SMTP = FakeSMTP
app.config.update(MAIL_USERNAME=Config.MAIL_USERNAME, MAIL_PASSWORD='abcdabcdabcdabcd', MAIL_DEFAULT_SENDER=Config.MAIL_DEFAULT_SENDER)
with app.test_request_context():
    ok = m.send_email('fondateur@exemple.cm', 'Confirmez votre tontine', 'corps')
smtplib.SMTP = real_smtp
app.config.update(MAIL_USERNAME='', MAIL_PASSWORD='')
check(ok and sent.get('host') == 'smtp.gmail.com' and sent.get('tls') and sent.get('user') == 'ghelia.finance@gmail.com'
      and sent.get('sender') == 'Ghelia Finance <ghelia.finance@gmail.com>' and sent.get('to') == 'fondateur@exemple.cm',
      f'avec le mot de passe : connexion sécurisée à Gmail, expéditeur « Ghelia Finance » {sent}')

# ---------------------------------------------------------------- envoi par l'API Brevo (serveur simulé)
import json  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

calls = []


class FakeResp:
    status = 201

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(req, timeout=None):
    calls.append(req)
    if req.headers.get('Api-key') == 'mauvaise-cle':
        raise urllib.error.HTTPError(req.full_url, 401, 'Unauthorized', {}, __import__('io').BytesIO(b'{"message":"Key not found"}'))
    return FakeResp()


real_urlopen = urllib.request.urlopen
urllib.request.urlopen = fake_urlopen
app.config.update(BREVO_API_KEY='xkeysib-test', MAIL_DEFAULT_SENDER=Config.MAIL_DEFAULT_SENDER, MAIL_USERNAME='', MAIL_PASSWORD='')
with app.test_request_context():
    ok = m.send_email('fondateur@exemple.cm', 'Confirmez votre tontine « Akwa »', 'Bonjour, lien : https://exemple/confirmer')
payload = json.loads(calls[-1].data.decode('utf-8')) if calls else {}
check(ok and calls and calls[-1].full_url == 'https://api.brevo.com/v3/smtp/email' and calls[-1].get_method() == 'POST'
      and calls[-1].headers.get('Api-key') == 'xkeysib-test', 'Brevo : appel de l\'API avec la clé (sans SMTP)')
check(payload.get('sender') == {'name': 'Ghelia Finance', 'email': 'ghelia.finance@gmail.com'}
      and payload.get('to') == [{'email': 'fondateur@exemple.cm'}] and '« Akwa »' in payload.get('subject', '')
      and 'confirmer' in payload.get('textContent', ''), f'Brevo : expéditeur Ghelia Finance, destinataire, sujet et texte {payload.get("sender")}')
app.config['BREVO_API_KEY'] = 'mauvaise-cle'
with app.test_request_context():
    ok = m.send_email('fondateur@exemple.cm', 'Sujet', 'corps')
check(ok is False, 'Brevo refuse (clé invalide) : échec signalé sans plantage')
urllib.request.urlopen = real_urlopen
app.config['BREVO_API_KEY'] = ''

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)

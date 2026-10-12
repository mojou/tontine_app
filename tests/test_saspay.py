"""SasPay : le client paie, l'abonnement est validé automatiquement (notification signée ou paiement en un clic)."""
import hashlib
import hmac
import html
import io
import json
import os
import re
import sys
import time
from datetime import date, timedelta
from decimal import Decimal

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'sp.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402
import saspay  # noqa: E402

app, db = m.app, m.db
SECRET = 'whsec_test_123'
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'),
                  SASPAY_WEBHOOK_SECRET=SECRET, SASPAY_SECRET_KEY='', SASPAY_PAYMENT_URL='https://pay.saspay.me/l/ghelia')
from models import Tontine, Member, BillingPayment, SasPayEvent, Transaction  # noqa: E402
from tenancy import tenant_bypass  # noqa: E402

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def text(r):
    h = re.sub(r'(?s)<(script|style)\b.*?</\1>', ' ', r.get_data(as_text=True))
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', h)))


def webhook(client, data, event='transaction.success', secret=SECRET, ts=None):
    body = json.dumps({'event': event, 'data': data})
    ts = str(int(ts or time.time()))
    sig = hmac.new(secret.encode(), f'{ts}.{body}'.encode(), hashlib.sha256).hexdigest()
    return client.post('/webhooks/saspay', data=body, content_type='application/json',
                       headers={'X-Webhook-Signature': sig, 'X-Webhook-Timestamp': ts, 'X-Webhook-Event': event})


def tx(tid, ref, amount, currency='XAF'):
    return {'id': tid, 'reference': ref, 'status': 'SUCCESS', 'amount': str(amount), 'net_amount': str(amount),
            'charged': str(amount + 50), 'currency': currency, 'country': 'CM', 'network': 'mtn_cm', 'msisdn': '237690000000'}


# ---------------------------------------------------------------- tontine de 12 membres, en lecture seule
pres = app.test_client()
pres.post('/inscription', data={'name': 'Tontine Payante', 'slug': 'payante', 'first_name': 'Hélène', 'last_name': 'Ngo',
                                'email': 'h@payante.cm', 'phone': '699000001', 'username': 'helene',
                                'password': 'Helene2026', 'password_confirm': 'Helene2026'})
for i in range(1, 12):
    pres.post('/members/add', data={'first_name': f'Membre{i}', 'last_name': 'Test', 'email': f'm{i}@payante.cm',
                                    'phone': f'6992{i:05d}', 'username': f'membre{i}', 'role': 'MEMBRE',
                                    'password': 'Passw0rd1', 'confirm_password': 'Passw0rd1'})
pres.get('/dashboard')
with app.app_context(), tenant_bypass():
    t = Tontine.query.filter_by(slug='payante').one()
    tid = t.id
    t.billing_started_on = date.today() - timedelta(days=10)
    db.session.commit()
    monthly = 12 * 200
check('Lecture seule' in text(pres.get('/dashboard')), 'situation de départ : 12 membres, abonnement impayé, lecture seule')
h = text(pres.get('/abonnement'))
check('validé automatiquement' in h and 'Payer avec SasPay' in h and 'Valider mon paiement' in h,
      "page Abonnement : lien SasPay et « validé automatiquement » (plus de validation par l'administrateur)")

# ---------------------------------------------------------------- notifications : sécurité
v = app.test_client()
r = v.post('/webhooks/saspay', data='{}', content_type='application/json')
check(r.status_code == 401, 'notification sans signature : refusée')
r = webhook(v, tx('t-0', 'TXN-0', monthly), secret='mauvais-secret')
check(r.status_code == 401, 'notification avec une fausse signature : refusée')
r = webhook(v, tx('t-0', 'TXN-0', monthly), ts=time.time() - 3600)
check(r.status_code == 401, 'notification trop ancienne (rejeu) : refusée')
check(webhook(v, {}, event='webhook.test').status_code == 200, "test d'envoi de SasPay accepté")

# ---------------------------------------------------------------- mode 1a : référence collée PUIS confirmation SasPay
r = pres.post('/abonnement', data={'months': '1', 'reference': 'TXN-20261010-0001'}, follow_redirects=True)
check('validé automatiquement dès que SasPay le confirme' in text(r), 'référence collée : en attente de la confirmation SasPay')
check('Lecture seule' in text(pres.get('/dashboard')), 'tant que SasPay n\'a pas confirmé : toujours en lecture seule')
r = webhook(v, tx('t-1', 'TXN-20261010-0001', monthly))
check(r.status_code == 200 and r.get_json().get('validated') is True, 'SasPay confirme : paiement validé automatiquement')
with app.app_context(), tenant_bypass():
    pay = BillingPayment.query.filter_by(reference='TXN-20261010-0001').one()
    t = db.session.get(Tontine, tid)
    check(pay.status == 'VALIDE' and pay.auto_validated and t.paid_until == pay.period_end and t.paid_until >= date.today(),
          f'abonnement réglé jusqu\'au {t.paid_until}, sans intervention de l\'administrateur')
check('Lecture seule' not in text(pres.get('/dashboard')), "l'accès complet est rétabli immédiatement")
check('confirmé automatiquement' in text(pres.get('/abonnement')), "l'historique indique « confirmé automatiquement »")
webhook(v, tx('t-1', 'TXN-20261010-0001', monthly))
with app.app_context(), tenant_bypass():
    check(SasPayEvent.query.filter_by(transaction_id='t-1').count() == 1, 'notification répétée par SasPay : enregistrée une seule fois')

# ---------------------------------------------------------------- mode 1b : confirmation SasPay AVANT la saisie
webhook(v, tx('t-2', 'TXN-20261010-0002', 3 * monthly))
r = pres.post('/abonnement', data={'months': '3', 'reference': 'txn-20261010-0002'}, follow_redirects=True)
check('Paiement confirmé par SasPay' in text(r), 'SasPay avait déjà confirmé : validation immédiate à la saisie')
with app.app_context(), tenant_bypass():
    pay2 = BillingPayment.query.filter(db.func.lower(BillingPayment.reference) == 'txn-20261010-0002').one()
    check(pay2.status == 'VALIDE' and pay2.period_start == pay.period_end + timedelta(days=1),
          '3 mois ajoutés à la suite de la période déjà payée')

# ---------------------------------------------------------------- garde-fous
webhook(v, tx('t-3', 'TXN-PEU', 500))
r = pres.post('/abonnement', data={'months': '1', 'reference': 'TXN-PEU'}, follow_redirects=True)
with app.app_context(), tenant_bypass():
    check(BillingPayment.query.filter_by(reference='TXN-PEU').one().status == 'EN_ATTENTE' and 'inférieur au montant dû' in text(r),
          'montant payé insuffisant (500 au lieu de 2 400) : non validé, message clair')
webhook(v, tx('t-4', 'TXN-EUR', monthly, currency='EUR'))
pres.post('/abonnement', data={'months': '1', 'reference': 'TXN-EUR'})
with app.app_context(), tenant_bypass():
    check(BillingPayment.query.filter_by(reference='TXN-EUR').one().status == 'EN_ATTENTE', 'mauvaise devise : non validé')
r = pres.post('/abonnement', data={'months': '1', 'reference': 'TXN-20261010-0001'}, follow_redirects=True)
check('déjà été déclarée' in text(r), 'une référence déjà utilisée ne peut pas resservir')

# ---------------------------------------------------------------- payeur au Bénin / en Côte d'Ivoire (XOF)
webhook(v, tx('t-6', 'TXN-BENIN-6', monthly, currency='XOF'))
r = pres.post('/abonnement', data={'months': '1', 'country': 'BJ', 'reference': 'TXN-BENIN-6'}, follow_redirects=True)
with app.app_context(), tenant_bypass():
    p6 = BillingPayment.query.filter_by(reference='TXN-BENIN-6').one()
    check(p6.status == 'VALIDE' and p6.currency == 'XOF' and p6.country == 'BJ' and 'Paiement confirmé par SasPay' in text(r),
          'payé depuis le Bénin en XOF (même valeur que le XAF) : validé automatiquement')

# ---------------------------------------------------------------- les 18 pays couverts par SasPay
app.config['SASPAY_PAYMENT_URL_XOF'] = 'https://pay.saspay.me/l/ghelia-xof'
raw = pres.get('/abonnement').get_data(as_text=True)
fcfa_countries = ['Bénin', 'Burkina Faso', "Côte d'Ivoire", 'Mali', 'Niger', 'Sénégal', 'Togo', 'Cameroun']
check(all(f'{c} (XO' in html.unescape(raw) or f'{c} (XAF)' in html.unescape(raw) for c in fcfa_countries),
      'les 8 pays du franc CFA couverts par SasPay sont proposés')
check('Ghana (GHS)' not in raw and 'Gabon' not in raw, "pays sans prix fixé (Ghana) ou non couverts par SasPay (Gabon) : non proposés")
check('value="BJ" data-currency="XOF"' in raw and 'data-url="https://pay.saspay.me/l/ghelia-xof"' in raw,
      'le Bénin utilise le lien de paiement en XOF')
app.config['SASPAY_PAYMENT_URL_XOF'] = ''

with app.app_context(), tenant_bypass():
    from models import User  # noqa: E402
    su = User.query.filter_by(role='SUPERADMIN').first()
    su.set_password('Super2026x')
    su_name = su.username
    db.session.commit()
sa = app.test_client()
sa.post('/login', data={'tontine': m.PLATFORM_LOGIN, 'username': su_name, 'password': 'Super2026x'})
h = text(sa.get('/superadmin'))
check('Pays de paiement SasPay' in h and 'GHS' in h and 'NGN' in h and 'KES' in h and 'ZMW' in h,
      'super-admin : réglage des 12 devises (dont cedi, naira, shilling kényan, kwacha)')
sa.post('/superadmin/paiement-pays', data={'code': 'GHS', 'price_per_member': '4', 'payment_url': 'https://pay.saspay.me/l/ghelia-ghs',
                                           'is_active': 'on'})
raw = pres.get('/abonnement').get_data(as_text=True)
check('Ghana (GHS)' in raw and f'data-monthly="{12 * 4}"' in raw, 'Ghana proposé après réglage : 12 membres × 4 GHS = 48 GHS / mois')
r = pres.post('/abonnement', data={'months': '2', 'country': 'GH', 'reference': 'TXN-GHANA-1'}, follow_redirects=True)
with app.app_context(), tenant_bypass():
    pg = BillingPayment.query.filter_by(reference='TXN-GHANA-1').one()
    check(pg.currency == 'GHS' and pg.amount == 96, f'paiement depuis le Ghana : 2 mois = 96 GHS ({pg.amount} {pg.currency})')
webhook(v, tx('t-7', 'TXN-GHANA-1', 96, currency='XAF'))
with app.app_context(), tenant_bypass():
    check(db.session.get(BillingPayment, pg.id).status == 'EN_ATTENTE', 'devise différente (XAF reçu pour un paiement en GHS) : non validé')
webhook(v, tx('t-8', 'TXN-GHANA-1', 96, currency='GHS'))
with app.app_context(), tenant_bypass():
    check(db.session.get(BillingPayment, pg.id).status == 'VALIDE', 'SasPay confirme 96 GHS : validé automatiquement')
r = sa.post('/superadmin/paiement-pays', data={'code': 'NGN', 'price_per_member': '300', 'payment_url': 'http://pas-https'},
            follow_redirects=True)
check('Lien de paiement invalide' in text(r), 'lien de paiement non sécurisé (http) refusé')
check(pres.post('/superadmin/paiement-pays', data={'code': 'NGN', 'price_per_member': '1'}).status_code in (302, 403),
      'un président ne peut pas régler les devises')
r = pres.post('/abonnement', data={'months': '1', 'country': 'NG', 'reference': 'TXN-NIGERIA'}, follow_redirects=True)
check("n'est pas proposé" in text(r), 'pays non activé (Nigeria) : paiement refusé')

# ---------------------------------------------------------------- mode 2 : paiement en un clic (SasPay simulé)
import urllib.request  # noqa: E402
calls = []


class Resp:
    def __init__(self, payload):
        self.payload = payload
        self.status = 200

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(req, timeout=None):
    calls.append(req)
    if req.get_method() == 'POST':
        sent = json.loads(req.data.decode())
        return Resp({'success': True, 'data': {'id': 'cs-123', 'checkout_url': 'https://pay.saspay.me/checkout/abc', 'status': 'PENDING',
                                               'amount': sent['amount'], 'metadata': sent['metadata']}})
    return Resp({'success': True, 'data': {'id': 'cs-123', 'status': 'PAID', 'paid_at': '2026-10-10T10:00:00Z'}})


check('Payer maintenant avec SasPay' not in text(pres.get('/abonnement')), 'sans clé : le bouton « en un clic » est caché')
app.config['SASPAY_SECRET_KEY'] = 'sk_test_simule'
real = urllib.request.urlopen
urllib.request.urlopen = fake_urlopen
h = text(pres.get('/abonnement'))
check('Payer maintenant avec SasPay' in h and "Côte d'Ivoire (XOF)" in h and 'Cameroun (XAF)' in h,
      'avec la clé : bouton « Payer maintenant » et choix du pays (XAF / XOF)')
r = pres.post('/abonnement/payer', data={'months': '2'})
sent = json.loads(calls[-1].data.decode()) if calls else {}
check(r.status_code == 302 and r.headers['Location'] == 'https://pay.saspay.me/checkout/abc', 'redirection vers la page de paiement SasPay')
check(calls and calls[-1].full_url == 'https://api.saspay.me/api/v1/checkout-sessions/' and calls[-1].headers.get('Authorization') == 'Bearer sk_test_simule'
      and sent.get('amount') == f'{2 * monthly}.00' and sent.get('currency') == 'XAF' and sent.get('country') == 'CM'
      and '/abonnement/retour/' in sent.get('return_url', ''), f'session SasPay : montant calculé ({sent.get("amount")} XAF), retour vers le site')
with app.app_context(), tenant_bypass():
    pay3 = BillingPayment.query.filter_by(checkout_session_id='cs-123').one()
r = pres.get(f'/abonnement/retour/{pay3.id}', follow_redirects=True)
with app.app_context(), tenant_bypass():
    check(db.session.get(BillingPayment, pay3.id).status == 'VALIDE' and 'Paiement confirmé' in text(r),
          'retour de SasPay : paiement vérifié auprès de SasPay et validé')
pres.post('/abonnement/payer', data={'months': '1', 'country': 'CI'})
sent_ci = json.loads(calls[-1].data.decode())
check(sent_ci.get('country') == 'CI' and sent_ci.get('currency') == 'XOF', "paiement en un clic depuis la Côte d'Ivoire : session en XOF")
with app.app_context(), tenant_bypass():
    for p_ in BillingPayment.query.filter(BillingPayment.provider == 'SASPAY_CHECKOUT', BillingPayment.status == 'EN_ATTENTE').all():
        p_.status = 'REFUSE'
    db.session.commit()
# notification avec l'identifiant du paiement (metadata) : validation même si le président ne revient pas sur le site
pres.post('/abonnement/payer', data={'months': '1'})
with app.app_context(), tenant_bypass():
    pay4 = BillingPayment.query.filter(BillingPayment.provider == 'SASPAY_CHECKOUT', BillingPayment.status == 'EN_ATTENTE').one()
data = tx('t-5', 'TXN-CHECKOUT-5', monthly)
data['metadata'] = {'billing_payment_id': pay4.id}
check(webhook(v, data).get_json().get('validated') is True, 'paiement en un clic confirmé par notification (sans retour sur le site)')


def blocked(req, timeout=None):
    raise urllib.error.URLError('Tunnel connection failed: 403 Forbidden')


import urllib.error  # noqa: E402
urllib.request.urlopen = blocked
r = pres.post('/abonnement/payer', data={'months': '1'}, follow_redirects=True)
check('momentanément indisponible' in text(r), 'SasPay injoignable (hébergeur) : message clair, le lien de paiement reste proposé')
urllib.request.urlopen = real
app.config['SASPAY_SECRET_KEY'] = ''

# ---------------------------------------------------------------- lecture seule : la page de paiement reste utilisable
with app.app_context(), tenant_bypass():
    t = db.session.get(Tontine, tid)
    t.paid_until, t.free_until = date.today() - timedelta(days=30), None
    db.session.commit()
r = pres.post('/abonnement', data={'months': '1', 'reference': 'TXN-LECTURE-SEULE'})
with app.app_context(), tenant_bypass():
    check(BillingPayment.query.filter_by(reference='TXN-LECTURE-SEULE').count() == 1, 'en lecture seule, on peut quand même payer')
check(app.test_client().get('/webhooks/saspay').status_code == 405, 'la notification n\'accepte que les envois de SasPay (POST)')

app.config['SASPAY_WEBHOOK_SECRET'] = ''
check(webhook(v, tx('t-9', 'TXN-9', monthly)).status_code == 404, "secret non configuré : l'adresse de notification n'existe pas (404)")

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)

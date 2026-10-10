# ============================================================
# SASPAY : encaissement automatique de l'abonnement
# ============================================================
# Documentation : https://docs.saspay.me
#
# Deux modes, sans aucune validation manuelle :
#   1. Lien de paiement + notification (webhook) : le président paie sur le lien SasPay,
#      colle la référence du reçu ; dès que SasPay confirme (webhook signé
#      « transaction.success »), l'abonnement est validé.
#   2. Paiement en un clic (session de checkout créée par l'API) : actif seulement si
#      SASPAY_SECRET_KEY est réglée ET que l'hébergeur autorise api.saspay.me.
#
# Les secrets (clé API, secret de signature des webhooks) ne sont lus que dans les
# variables d'environnement de l'hébergeur ; jamais dans le code ni dans git.

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation

SIGNATURE_MAX_AGE = 300            # secondes : une notification plus vieille est refusée
PAID_SESSION_STATUSES = {'PAID', 'SUCCESS', 'COMPLETED'}


class SasPayError(Exception):
    """Appel à l'API SasPay impossible (réseau bloqué, clé refusée…)"""


def verify_signature(secret, timestamp, raw_body, signature, now=None):
    """Signature des webhooks : HMAC-SHA256 hexadécimal de « <timestamp>.<corps brut> »"""
    if not (secret and timestamp and signature):
        return False
    try:
        age = abs((now or time.time()) - int(timestamp))
    except (TypeError, ValueError):
        return False
    if age > SIGNATURE_MAX_AGE:
        return False
    body = raw_body.decode('utf-8') if isinstance(raw_body, bytes) else raw_body
    expected = hmac.new(secret.encode('utf-8'), f"{timestamp}.{body}".encode('utf-8'), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


def decimal_or_none(value):
    try:
        return Decimal(str(value)) if value not in (None, '') else None
    except (InvalidOperation, ValueError):
        return None


def received_amount(data):
    """Montant réellement encaissé pour le marchand (hors frais ajoutés au client)"""
    for key in ('net_amount', 'requested_amount', 'amount'):
        amount = decimal_or_none(data.get(key))
        if amount is not None:
            return amount
    return None


def _call(method, url, secret_key, payload=None, timeout=20):
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        'Authorization': f'Bearer {secret_key}', 'Content-Type': 'application/json', 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode('utf-8') or '{}')
    except urllib.error.HTTPError as exc:
        raise SasPayError(f"SasPay a refusé la demande ({exc.code}) : {exc.read().decode('utf-8', 'replace')[:200]}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise SasPayError(f"SasPay injoignable : {exc}")
    # Réponses enveloppées : {"success": true, "data": {...}} ou objet direct
    if isinstance(body, dict) and body.get('success') is False:
        raise SasPayError(f"SasPay : {body.get('error', {}).get('message', 'erreur')}")
    return body.get('data', body) if isinstance(body, dict) else body


def create_checkout_session(base_url, secret_key, **fields):
    """POST /checkout-sessions/ -> {'id', 'checkout_url', 'status', ...}"""
    return _call('POST', f"{base_url.rstrip('/')}/checkout-sessions/", secret_key, fields)


def checkout_session(base_url, secret_key, session_id):
    """GET /checkout-sessions/{id}/ -> détail (status, transaction, paid_at…)"""
    return _call('GET', f"{base_url.rstrip('/')}/checkout-sessions/{session_id}/", secret_key)


def session_is_paid(session):
    return (str(session.get('status', '')).upper() in PAID_SESSION_STATUSES) or bool(session.get('paid_at'))

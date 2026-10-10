# ============================================================
# Fichier WSGI pour PythonAnywhere (Ghelia Finance)
# ============================================================
# À COPIER dans l'onglet « Web » de PythonAnywhere -> lien « WSGI configuration file »
# (remplacer tout le contenu existant), puis cliquer sur « Reload ».
#
# Seule la ligne BREVO_API_KEY est à compléter : la clé API Brevo (commence par « xkeysib- »).
# Ce fichier reste privé sur votre compte PythonAnywhere : ne le recopiez JAMAIS dans GitHub
# ni dans un message.

import os
import sys

PROJET = '/home/germainbob/tontine_app'
if PROJET not in sys.path:
    sys.path.insert(0, PROJET)
os.chdir(PROJET)

# Derrière le serveur de PythonAnywhere : vraie adresse IP des visiteurs et liens en https
os.environ.setdefault('TRUST_PROXY', '1')
# Cookies de connexion envoyés uniquement en https
os.environ.setdefault('SESSION_COOKIE_SECURE', 'True')

# E-mails de confirmation : PythonAnywhere gratuit bloque le SMTP (Gmail), on passe par l'API Brevo.
# Collez ici la clé API Brevo (expéditeur ghelia.finance@gmail.com validé dans Brevo)
os.environ['BREVO_API_KEY'] = 'COLLEZ_ICI_LA_CLE_BREVO'

# ---- SasPay : abonnements payés et validés automatiquement (sans intervention de l'administrateur)
# Lien de paiement SasPay (public, montant libre, devise XAF)
os.environ.setdefault('SASPAY_PAYMENT_URL', 'COLLEZ_ICI_LE_LIEN_DE_PAIEMENT')
# Secret de signature du webhook SasPay (adresse : https://germainbob.pythonanywhere.com/webhooks/saspay)
os.environ['SASPAY_WEBHOOK_SECRET'] = 'COLLEZ_ICI_LE_SIGNING_SECRET'
# Paiement en un clic : clé secrète sk_live_… — à remplir SEULEMENT quand PythonAnywhere aura autorisé api.saspay.me
os.environ['SASPAY_SECRET_KEY'] = ''

from app import app as application  # noqa: E402

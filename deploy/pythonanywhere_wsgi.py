# ============================================================
# Fichier WSGI pour PythonAnywhere (Ghelia Finance)
# ============================================================
# À COPIER dans l'onglet « Web » de PythonAnywhere -> lien « WSGI configuration file »
# (remplacer tout le contenu existant), puis cliquer sur « Reload ».
#
# Seule la ligne MAIL_PASSWORD est à compléter : le mot de passe d'application Gmail
# (16 lettres) de ghelia.finance@gmail.com. Ce fichier reste privé sur votre compte
# PythonAnywhere : ne le recopiez JAMAIS dans GitHub ni dans un message.

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

# E-mails de confirmation (Gmail) : collez ici le mot de passe d'application, sans espaces
os.environ['MAIL_PASSWORD'] = 'COLLEZ_ICI_LES_16_LETTRES'

# Lien de paiement SasPay (facultatif ; {montant} et {reference} sont remplacés automatiquement)
os.environ.setdefault('SASPAY_PAYMENT_URL', '')

from app import app as application  # noqa: E402

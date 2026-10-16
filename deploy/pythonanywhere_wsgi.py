# ============================================================
# Fichier WSGI pour PythonAnywhere (Ghelia Finance)
# ============================================================
# À COPIER dans l'onglet « Web » de PythonAnywhere -> lien « WSGI configuration file »
# (/var/www/germainbob_pythonanywhere_com_wsgi.py : remplacer tout le contenu), puis « Reload ».
# ATTENTION : ce n'est PAS le fichier ~/tontine_app/deploy/pythonanywhere_wsgi.py qui est lu par le site.
#
# Trois lignes à compléter : BREVO_API_KEY, SASPAY_SECRET_KEY, SASPAY_WEBHOOK_SECRET.
# Ce fichier reste privé sur votre compte PythonAnywhere : ne recopiez JAMAIS les clés dans GitHub
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
# Clé API Brevo (commence par « xkeysib- », expéditeur ghelia.finance@gmail.com validé dans Brevo)
os.environ['BREVO_API_KEY'] = 'COLLEZ_ICI_LA_CLE_BREVO'

# ---- SasPay : abonnements payés par l'API (aucun lien à copier), validés automatiquement
# Clé SECRÈTE de l'API SasPay (commence par « sk_live_ »)
os.environ['SASPAY_SECRET_KEY'] = 'COLLEZ_ICI_LA_CLE_SECRETE_SASPAY'
# « Signing secret » du webhook SasPay (adresse : https://germainbob.pythonanywhere.com/webhooks/saspay)
os.environ['SASPAY_WEBHOOK_SECRET'] = 'COLLEZ_ICI_LE_SIGNING_SECRET'

# TOUJOURS EN DERNIER : l'application lit les réglages ci-dessus au démarrage
from app import app as application  # noqa: E402

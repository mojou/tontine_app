#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Application Ghelia Finance (gestion de tontines)
Point d'entrée pour le développement local.

    python run.py                      -> http://127.0.0.1:5000 (cette machine uniquement)
    $env:HOST = "0.0.0.0"; python run.py   -> accessible depuis le réseau local
    $env:FLASK_DEBUG = "1"; python run.py  -> mode débogage (JAMAIS sur un réseau partagé)

En production, utiliser un serveur WSGI (ex. gunicorn "app:app") et non ce script.
"""

import os

from app import app

if __name__ == '__main__':
    debug = os.environ.get('FLASK_DEBUG', '0').lower() in ('1', 'true', 'yes')
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', '5000'))
    if debug and host not in ('127.0.0.1', 'localhost'):
        # La console de débogage permet d'exécuter du code : interdite hors de cette machine
        print("[SÉCURITÉ] Mode débogage refusé avec HOST={0} : écoute limitée à 127.0.0.1.".format(host))
        host = '127.0.0.1'
    print(f"Ghelia Finance démarre sur http://{host}:{port}" + (" (débogage)" if debug else ""))
    app.run(debug=debug, host=host, port=port, threaded=True)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Application Ghelia Finance (gestion de tontines)
Point d'entrée pour le développement local.

    python run.py                          -> démarre et ouvre http://127.0.0.1:5000 dans le navigateur
    $env:HOST = "0.0.0.0"; python run.py   -> accessible depuis le réseau local
    $env:FLASK_DEBUG = "1"; python run.py  -> mode débogage (JAMAIS sur un réseau partagé)
    $env:NO_BROWSER = "1"; python run.py   -> ne pas ouvrir le navigateur

La fenêtre doit rester ouverte : la fermer (ou Ctrl+C) arrête l'application.
En production, utiliser un serveur WSGI (ex. gunicorn "app:app") et non ce script.
"""

import os
import threading
import webbrowser

from app import app

if __name__ == '__main__':
    debug = os.environ.get('FLASK_DEBUG', '0').lower() in ('1', 'true', 'yes')
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', '5000'))
    if debug and host not in ('127.0.0.1', 'localhost'):
        # La console de débogage permet d'exécuter du code : interdite hors de cette machine
        print("[SÉCURITÉ] Mode débogage refusé avec HOST={0} : écoute limitée à 127.0.0.1.".format(host))
        host = '127.0.0.1'

    url = f"http://127.0.0.1:{port}"
    print("=" * 60)
    print(f"  Ghelia Finance est démarrée : {url}" + ("  (débogage)" if debug else ""))
    if host == '0.0.0.0':
        print(f"  Depuis un autre appareil du réseau : http://<adresse-IP-de-ce-PC>:{port}")
    print("  Laissez cette fenêtre ouverte. Ctrl+C pour arrêter.")
    print("=" * 60)

    # Ouvre le navigateur une seule fois (en débogage, le rechargeur relance le script)
    first_process = not debug or os.environ.get('WERKZEUG_RUN_MAIN') != 'true'
    if first_process and os.environ.get('NO_BROWSER', '').lower() not in ('1', 'true', 'yes'):
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    app.run(debug=debug, host=host, port=port, threaded=True)

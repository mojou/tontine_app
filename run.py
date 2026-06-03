#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Application de Gestion de Tontine
Point d'entrée principal
"""

from app import app, db

if __name__ == '__main__':
    # Créer les tables de la base de données si elles n'existent pas
    with app.app_context():
        db.create_all()
        print("✅ Base de données initialisée avec succès")
    
    # Démarrer l'application Flask
    app.run(
        debug=True,           # Mode debug activé pour le développement
        host='0.0.0.0',       # Écouter sur toutes les interfaces réseau
        port=5000,            # Port par défaut
        threaded=True         # Support du multi-threading
    )
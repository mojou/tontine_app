#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Passage de la base en mode multi-tenant (plusieurs tontines sur une même instance).

Usage :
    python setup_multitenant.py
    python setup_multitenant.py --name "JSB Tontine" --slug jsb --location "Lycée de Bahouan"
    python setup_multitenant.py --db chemin/vers/autre.db      (base précise)

Ce que fait le script (idempotent : peut être relancé sans risque) :
  1. copie de sauvegarde horodatée de la base ;
  2. création de la table `tontines` et d'une tontine par défaut qui reçoit
     TOUTES les données existantes ;
  3. ajout de `tontine_id` à chaque table métier (reconstruction SQLite
     sans perte, contrôle du nombre de lignes et des clés étrangères) ;
  4. création des tables manquantes ;
  5. création d'un compte super-admin (mot de passe aléatoire affiché une fois).
"""

import argparse
import os
import re
import secrets
import shutil
import sqlite3
import sys
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.dialects import sqlite as sqlite_dialect
from sqlalchemy.schema import CreateIndex, CreateTable
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from config import Config  # noqa: E402
from models import db  # noqa: E402  (enregistre tous les modèles dans db.metadata)

# Anciens comptes créés automatiquement avec des mots de passe connus
KNOWN_DEFAULT_ACCOUNTS = {
    'admin': 'admin123', 'president': 'president123', 'tresorier': 'tresorier123',
    'censeur': 'censeur123', 'communicateur': 'communicateur123',
}


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(' ')


def db_path_from_config():
    uri = Config.SQLALCHEMY_DATABASE_URI
    if not uri.startswith('sqlite:///'):
        sys.exit(f"Ce script gère uniquement SQLite (URI actuelle : {uri}).")
    return uri[len('sqlite:///'):]


def table_columns(conn, name):
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{name}")')]


def existing_tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def rebuild_table(conn, table, tontine_id):
    """Reconstruit `table` selon le modèle actuel en conservant toutes les lignes."""
    name = table.name
    tmp = f'{name}__mt_new'
    ddl = str(CreateTable(table).compile(dialect=sqlite_dialect.dialect()))
    ddl, n = re.subn(rf'^\s*CREATE TABLE "?{re.escape(name)}"?', f'CREATE TABLE "{tmp}"', ddl, count=1)
    if n != 1:
        raise RuntimeError(f'DDL inattendu pour {name}')

    old_cols = table_columns(conn, name)
    new_cols = [c.name for c in table.columns]
    lost = [c for c in old_cols if c not in new_cols]
    if lost:
        raise RuntimeError(f'{name} : colonnes absentes du modèle, migration interrompue : {lost}')

    common = [c for c in new_cols if c in old_cols]
    before = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]

    conn.execute(ddl)
    cols_sql = ', '.join(f'"{c}"' for c in common)
    if 'tontine_id' in old_cols:
        conn.execute(f'INSERT INTO "{tmp}" ({cols_sql}) SELECT {cols_sql} FROM "{name}"')
    else:
        conn.execute(
            f'INSERT INTO "{tmp}" ({cols_sql}, "tontine_id") SELECT {cols_sql}, ? FROM "{name}"',
            (tontine_id,),
        )
    conn.execute(f'DROP TABLE "{name}"')
    conn.execute(f'ALTER TABLE "{tmp}" RENAME TO "{name}"')
    for index in table.indexes:
        conn.execute(str(CreateIndex(index).compile(dialect=sqlite_dialect.dialect())))

    after = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
    if before != after:
        raise RuntimeError(f'{name} : {before} lignes avant, {after} après')
    print(f'  [OK] {name:28} {after} ligne(s)')


def main():
    # Console Windows (cp1252) : ne jamais planter sur un caractère non affichable
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--db', help='chemin de la base SQLite (défaut : celle de config.py)')
    parser.add_argument('--name', default='JSB Tontine', help='nom de la tontine existante')
    parser.add_argument('--slug', default='jsb', help='identifiant court dans les URL (/t/<slug>)')
    parser.add_argument('--location', default='Lycée de Bahouan')
    parser.add_argument('--superadmin', default='superadmin', help='identifiant du super-admin à créer')
    parser.add_argument('--superadmin-email', default='superadmin@plateforme.local')
    args = parser.parse_args()

    path = os.path.abspath(args.db or db_path_from_config())
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fresh = not os.path.exists(path)

    if not fresh:
        backup = f"{path}.avant_multitenant_{datetime.now():%Y%m%d_%H%M%S}"
        shutil.copy2(path, backup)
        print(f'Sauvegarde : {backup}')

    engine = create_engine(f'sqlite:///{path}')
    metadata = db.metadata
    metadata.tables['tontines'].create(engine, checkfirst=True)

    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute('PRAGMA foreign_keys=OFF')
    conn.execute('PRAGMA legacy_alter_table=ON')
    tables_in_db = existing_tables(conn)

    to_rebuild = [
        t for t in metadata.sorted_tables
        if t.name in tables_in_db and 'tontine_id' in t.c and 'tontine_id' not in table_columns(conn, t.name)
    ]

    tontine_id = None
    has_data = any(
        conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        for t in ('members', 'users') if t in tables_in_db
    )

    try:
        conn.execute('BEGIN')
        if to_rebuild or has_data:
            row = conn.execute('SELECT id FROM tontines WHERE slug = ?', (args.slug,)).fetchone()
            if row:
                tontine_id = row[0]
            else:
                cur = conn.execute(
                    'INSERT INTO tontines (slug, name, location, is_active, created_at, presence_amount, '
                    'fonds_caisse_amount, loan_interest_rate, max_aid_per_member) '
                    'VALUES (?, ?, ?, 1, ?, 1050, 5000, 5, 3)',
                    (args.slug, args.name, args.location, _utcnow()),
                )
                tontine_id = cur.lastrowid
                print(f'Tontine créée : « {args.name} » (id={tontine_id}, URL /t/{args.slug})')

        if to_rebuild:
            print('Ajout de tontine_id aux tables :')
            for table in to_rebuild:
                rebuild_table(conn, table, tontine_id)
        else:
            print('Tables déjà au format multi-tenant.')

        problems = conn.execute('PRAGMA foreign_key_check').fetchall()
        if problems:
            raise RuntimeError(f'Clés étrangères invalides : {problems[:10]}')
        conn.execute('COMMIT')
    except Exception:
        conn.execute('ROLLBACK')
        conn.close()
        print('\n[ERREUR] Migration annulée, la base n\'a pas été modifiée.')
        raise

    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
    if integrity != 'ok':
        sys.exit(f'[ERREUR] integrity_check : {integrity}')

    # Tables manquantes (votes, tirages, galerie... ou base neuve)
    conn.close()
    metadata.create_all(engine)
    from schema_upgrade import add_missing_columns
    add_missing_columns(engine, metadata)
    conn = sqlite3.connect(path)

    # Super-admin
    if not conn.execute("SELECT 1 FROM users WHERE role = 'SUPERADMIN'").fetchone():
        password = secrets.token_urlsafe(12)
        conn.execute(
            'INSERT INTO users (tontine_id, username, email, password_hash, role, member_id, is_active, created_at) '
            "VALUES (NULL, ?, ?, ?, 'SUPERADMIN', NULL, 1, ?)",
            (args.superadmin, args.superadmin_email, generate_password_hash(password), _utcnow()),
        )
        conn.commit()
        print('\n' + '=' * 60)
        print('  COMPTE SUPER-ADMIN CRÉÉ (notez ce mot de passe, il ne sera plus affiché)')
        print(f'  Identifiant  : {args.superadmin}')
        print(f'  Mot de passe : {password}')
        print("  Connexion    : adresse réservée /administration")
        print('=' * 60)
    else:
        print('Super-admin déjà présent.')

    # Alerte sur les anciens comptes par défaut encore actifs
    weak = []
    for username, pwd in KNOWN_DEFAULT_ACCOUNTS.items():
        for (h,) in conn.execute('SELECT password_hash FROM users WHERE username = ? AND is_active = 1', (username,)):
            if check_password_hash(h, pwd):
                weak.append(username)
    if weak:
        print(f"\n[ATTENTION] Comptes encore protégés par le mot de passe par défaut : {', '.join(weak)}")
        print('   Changez-les ou désactivez-les avant toute mise en ligne.')

    counts = conn.execute('SELECT t.slug, (SELECT COUNT(*) FROM members m WHERE m.tontine_id = t.id) FROM tontines t').fetchall()
    conn.close()
    print('\nMembres par tontine :', ', '.join(f'{s}={n}' for s, n in counts) or 'aucune tontine')
    print('Terminé.')


if __name__ == '__main__':
    main()

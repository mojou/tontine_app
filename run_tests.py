#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lance toute la batterie de tests de l'application.

    python run_tests.py            -> tous les tests (quelques minutes)
    python run_tests.py --rapide   -> sans les explorations exhaustives (routes, entrées piégées)

Chaque test travaille sur une COPIE TEMPORAIRE de la base de référence
(tests/fixtures/base_reference.db) migrée au format actuel : la vraie base
(instance/tontine.db) n'est jamais touchée.

À lancer après chaque modification du code : si une ligne indique « ÉCHEC »,
ne pas mettre la modification en service avant de l'avoir corrigée.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.join(ROOT, 'tests')
FIXTURE = os.path.join(TESTS, 'fixtures', 'base_reference.db')

# (script, base utilisée par le script, description)
SUITES = [
    ('test_fonctionnel.py', 'test.db', 'Votes, tirages, galerie'),
    ('test_multitenant.py', 'mt.db', 'Isolation entre tontines'),
    ('verif_pages.py', 'mt.db', 'Toutes les pages, tous les rôles'),
    ('test_inscription.py', 'su.db', 'Création de tontine et inscription'),
    ('test_avals_cotisations.py', 'av.db', 'Avals et cotisations'),
    ('test_cycles.py', 'cy.db', 'Cycles, mains, tirage, enchères'),
    ('test_ajout_cycle.py', 'aj.db', 'Ajout en cours de cycle (rappel)'),
    ('test_seances_exercice.py', 'se.db', "Séances et fin d'exercice"),
    ('test_mot_de_passe.py', 'rs.db', 'Mot de passe oublié'),
    ('test_sanctions.py', 'sa.db', 'Sanctions + contrôle de toutes les pages'),
    ('test_aides.py', 'ai.db', 'Aides sociales (règles, barème, versement)'),
    ('test_rapports.py', 'rp.db', 'Rapports PDF / CSV / Excel'),
    ('test_audit.py', 'au.db', "Défauts corrigés lors de l'audit"),
    ('test_fiche_membre.py', 'fm.db', 'Fiche membre : nature de chaque ligne'),
    ('test_seance_cagnotte.py', 'sc.db', 'Séance : versement des cagnottes'),
    ('test_avals_regles.py', 'ar.db', 'Règles pour avaliser'),
    ('test_parcours.py', 'pa.db', 'Parcours utilisateur (tous les rôles)'),
    ('test_amendes_retard.py', 'am.db', 'Amendes de retard de cotisation'),
    ('test_ecarts_cycle.py', 'ec.db', 'Écarts de cycle et régularisation'),
    ('test_confirmation_email.py', 'ce.db', "Confirmation e-mail à l'inscription"),
    ('test_abonnement.py', 'ab.db', 'Abonnement, paiements, offres, suppression'),
    ('test_production.py', 'pr.db', 'Réglages de mise en ligne (https, IP)'),
]
EXHAUSTIVE = [
    ('verif_routes.py', 'crawl.db', 'Exploration de toutes les routes'),
    ('verif_entrees_piegees.py', 'fuzz.db', 'Entrées malveillantes'),
]


def migrated_copy(workdir, name):
    path = os.path.join(workdir, name)
    for suffix in ('', '-journal', '-wal', '-shm'):
        if os.path.exists(path + suffix):
            os.remove(path + suffix)
    shutil.copy2(FIXTURE, path)
    subprocess.run([sys.executable, os.path.join(ROOT, 'setup_multitenant.py'), '--db', path],
                   cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace', check=True)
    return path


def run(script, workdir, extra=()):
    # Les séries existantes créent leurs tontines sans e-mail ; test_confirmation_email l'active lui-même
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONWARNINGS='ignore', REQUIRE_EMAIL_CONFIRMATION='False')
    env.pop('DATABASE_URL', None)
    proc = subprocess.run([sys.executable, os.path.join(TESTS, script), workdir, ROOT, *extra], cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding='utf-8', errors='replace')
    out = proc.stdout + proc.stderr
    ok = out.count('\nOK ') + out.startswith('OK ')
    import re
    counted = re.search(r'(\d+) requêtes', out)   # explorations : nombre de requêtes testées
    if counted:
        ok = int(counted.group(1))
    fails = [line for line in out.splitlines() if line.startswith('FAIL')]
    crashed = proc.returncode != 0 or 'Traceback' in out and 'RESULTAT' not in out and 'ERREURS' not in out
    errors_line = next((line for line in out.splitlines() if line.startswith('ERREURS:')), None)
    if errors_line and errors_line.strip() != 'ERREURS: 0':
        fails.append(errors_line)
        fails += [line for line in out.splitlines() if line.startswith('  (') or line.startswith('  GET') or line.startswith('  POST')][:10]
    return ok, fails, crashed, out


def main():
    if not os.path.exists(FIXTURE):
        sys.exit(f"Base de référence introuvable : {FIXTURE}")
    quick = '--rapide' in sys.argv
    workdir = tempfile.mkdtemp(prefix='ghelia_tests_')
    os.makedirs(os.path.join(workdir, 'uploads'), exist_ok=True)
    print(f"Tests dans {workdir}\n")
    started, total_ok, failures = time.time(), 0, 0
    try:
        prepared = None
        for script, db, label in SUITES + ([] if quick else EXHAUSTIVE):
            if script == 'verif_pages.py':
                pass  # réutilise la base laissée par test_multitenant
            elif script in ('verif_routes.py', 'verif_entrees_piegees.py'):
                if prepared is None:
                    migrated_copy(workdir, 'se.db')
                    run('test_seances_exercice.py', workdir)
                    prepared = True
                shutil.copy2(os.path.join(workdir, 'se.db'), os.path.join(workdir, db))
            else:
                migrated_copy(workdir, db)
            extra = (db,) if script in ('verif_routes.py', 'verif_entrees_piegees.py') else ()
            ok, fails, crashed, out = run(script, workdir, extra)
            total_ok += ok
            status = 'OK    ' if not fails and not crashed else 'ÉCHEC '
            unit = 'requête(s) sans erreur' if extra or script == 'verif_pages.py' else 'vérification(s)'
            print(f"{status}{label:<40} {ok:>6} {unit}")
            if fails or crashed:
                failures += 1
                for line in fails[:15]:
                    print('       ' + line)
                if crashed:
                    print('       --- sortie ---')
                    print('       ' + '\n       '.join(out.strip().splitlines()[-12:]))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    print(f"\n{total_ok} vérifications en {time.time() - started:.0f} s : "
          + ("TOUT EST VERT" if not failures else f"{failures} SÉRIE(S) EN ÉCHEC"))
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Script de sauvegarde automatique pour l'application de tontine
À exécuter quotidiennement via les Scheduled Tasks de PythonAnywhere
"""

import os
import shutil
import sqlite3
import gzip
import json
from datetime import datetime, timedelta
import glob
import sys

# ============================================================
# CONFIGURATION
# ============================================================

# Configuration des chemins
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_FOLDER = os.path.join(BASE_DIR, 'backups')
DATABASE_PATH = os.path.join(BASE_DIR, 'tontine.db')  # Base SQLite
DATABASE_URL = os.environ.get('DATABASE_URL')  # Pour PostgreSQL (optionnel)

# Configuration des sauvegardes
RETENTION_DAYS = 30  # Garder les sauvegardes des 30 derniers jours
MAX_BACKUPS = 30  # Nombre maximum de sauvegardes
COMPRESS_LEVEL = 9  # Niveau de compression (1-9, 9 = maximum)
ENABLE_CSV_EXPORT = False  # Activer l'export CSV (désactivé par défaut pour économiser l'espace)
ENABLE_EMAIL_NOTIFICATION = False  # Activer les notifications par email

# Configuration email (si activé)
EMAIL_CONFIG = {
    'smtp_server': 'smtp.gmail.com',
    'smtp_port': 587,
    'sender_email': 'votre_email@gmail.com',
    'sender_password': 'votre_mot_de_passe',
    'recipient_email': 'admin@tontine.com'
}


# ============================================================
# FONCTIONS PRINCIPALES
# ============================================================

def ensure_backup_folder():
    """Crée le dossier de backup s'il n'existe pas"""
    if not os.path.exists(BACKUP_FOLDER):
        os.makedirs(BACKUP_FOLDER)
        print(f"Dossier de sauvegarde créé: {BACKUP_FOLDER}")


def get_database_size():
    """Retourne la taille de la base de données"""
    if os.path.exists(DATABASE_PATH):
        return os.path.getsize(DATABASE_PATH) / (1024 * 1024)  # Taille en MB
    return 0


def create_backup():
    """Crée une sauvegarde compressée de la base de données"""
    
    ensure_backup_folder()
    
    # Vérifier que la base existe
    if not os.path.exists(DATABASE_PATH):
        print(f"❌ Erreur: Base de données non trouvée à {DATABASE_PATH}")
        return False
    
    # Générer le nom du fichier de backup
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_filename = f"tontine_backup_{timestamp}.db.gz"
    backup_path = os.path.join(BACKUP_FOLDER, backup_filename)
    
    try:
        db_size = get_database_size()
        print(f"Base de données: {db_size:.2f} MB")
        
        # Lire et compresser la base de données
        with open(DATABASE_PATH, 'rb') as f_in:
            with gzip.open(backup_path, 'wb', compresslevel=COMPRESS_LEVEL) as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        # Taille de la sauvegarde
        backup_size = os.path.getsize(backup_path) / (1024 * 1024)
        compression_ratio = (backup_size / db_size * 100) if db_size > 0 else 0
        
        print(f"✅ Sauvegarde créée: {backup_filename}")
        print(f"   Taille: {backup_size:.2f} MB (compressé à {compression_ratio:.1f}%)")
        
        # Nettoyer les anciennes sauvegardes
        cleanup_old_backups()
        
        return True
        
    except Exception as e:
        print(f"❌ Erreur lors de la sauvegarde: {str(e)}")
        return False


def cleanup_old_backups():
    """Supprime les sauvegardes plus anciennes que RETENTION_DAYS"""
    
    cutoff_date = datetime.now() - timedelta(days=RETENTION_DAYS)
    backup_files = glob.glob(os.path.join(BACKUP_FOLDER, "tontine_backup_*.db.gz"))
    
    # Trier par date (les plus anciens d'abord)
    backup_files.sort(key=os.path.getmtime)
    
    deleted_count = 0
    total_size_saved = 0
    
    for backup_file in backup_files:
        # Extraire la date du nom de fichier
        filename = os.path.basename(backup_file)
        try:
            date_str = filename.replace('tontine_backup_', '').replace('.db.gz', '')
            file_date = datetime.strptime(date_str, '%Y%m%d_%H%M%S')
            
            if file_date < cutoff_date:
                file_size = os.path.getsize(backup_file) / (1024 * 1024)
                os.remove(backup_file)
                deleted_count += 1
                total_size_saved += file_size
                print(f"🗑️  Supprimé: {filename} ({file_size:.2f} MB)")
        except Exception as e:
            print(f"⚠️ Erreur lors de la suppression de {filename}: {e}")
    
    if deleted_count > 0:
        print(f"Nettoyage terminé: {deleted_count} ancienne(s) sauvegarde(s) supprimée(s), {total_size_saved:.2f} MB libérés")


def export_to_csv_backup():
    """Exporte les données importantes en CSV (backup supplémentaire)"""
    
    timestamp = datetime.now().strftime('%Y%m%d')
    csv_folder = os.path.join(BACKUP_FOLDER, f"csv_export_{timestamp}")
    
    if not os.path.exists(csv_folder):
        os.makedirs(csv_folder)
    
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.text_factory = str  # Pour gérer l'UTF-8 correctement
        cursor = conn.cursor()
        
        # Liste des tables à exporter (ordre important pour les clés étrangères)
        tables = [
            'users', 'members', 'transactions', 'loans', 'sanctions',
            'tontine_cycles', 'tontine_positions', 'tontine_cycle_details',
            'cycle_beneficiaries', 'aides', 'announcements', 'audit_logs'
        ]
        
        exported_count = 0
        for table in tables:
            try:
                cursor.execute(f"SELECT * FROM {table}")
                rows = cursor.fetchall()
                
                if rows:
                    # Récupérer les noms des colonnes
                    cursor.execute(f"PRAGMA table_info({table})")
                    columns = [col[1] for col in cursor.fetchall()]
                    
                    # Écrire le fichier CSV avec BOM pour UTF-8
                    csv_path = os.path.join(csv_folder, f"{table}.csv")
                    with open(csv_path, 'w', encoding='utf-8-sig') as f:
                        f.write(','.join(columns) + '\n')
                        for row in rows:
                            # Convertir les valeurs en chaînes, gérer None
                            formatted_row = [str(val) if val is not None else '' for val in row]
                            # Échapper les virgules dans les valeurs
                            formatted_row = [f'"{v}"' if ',' in v else v for v in formatted_row]
                            f.write(','.join(formatted_row) + '\n')
                    
                    exported_count += 1
                    print(f"📄 Export CSV: {table}.csv ({len(rows)} lignes)")
            except sqlite3.OperationalError:
                print(f"⚠️ Table non trouvée: {table}")
            except Exception as e:
                print(f"⚠️ Erreur export {table}: {e}")
        
        conn.close()
        
        print(f"✅ Export CSV terminé: {exported_count} tables exportées")
        return True
        
    except Exception as e:
        print(f"❌ Erreur lors de l'export CSV: {e}")
        return False


def verify_backup_integrity():
    """Vérifie l'intégrité de la dernière sauvegarde"""
    
    backup_files = glob.glob(os.path.join(BACKUP_FOLDER, "tontine_backup_*.db.gz"))
    if not backup_files:
        print("⚠️ Aucune sauvegarde trouvée pour vérification")
        return False
    
    # Prendre la plus récente
    latest_backup = max(backup_files, key=os.path.getctime)
    backup_name = os.path.basename(latest_backup)
    
    print(f"Vérification de l'intégrité: {backup_name}")
    
    test_path = latest_backup.replace('.gz', '.test.db')
    
    try:
        # Tester la décompression
        with gzip.open(latest_backup, 'rb') as f_in:
            with open(test_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        # Tester l'intégrité SQLite
        conn = sqlite3.connect(test_path)
        cursor = conn.cursor()
        
        # Vérifier les tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        
        # Vérifier quelques comptages
        table_counts = {}
        for table in tables:
            table_name = table[0]
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            table_counts[table_name] = count
        
        conn.close()
        
        # Nettoyer le fichier test
        os.remove(test_path)
        
        print(f"✅ Vérification réussie: {len(tables)} tables trouvées")
        for table, count in list(table_counts.items())[:5]:  # Afficher les 5 premières tables
            print(f"   - {table}: {count} enregistrements")
        
        return True
        
    except Exception as e:
        print(f"❌ Erreur de vérification: {e}")
        if os.path.exists(test_path):
            try:
                os.remove(test_path)
            except:
                pass
        return False


def generate_backup_report(success, backup_size=None, export_success=None):
    """Génère un rapport de sauvegarde"""
    
    report = {
        'date': datetime.now().isoformat(),
        'success': success,
        'backup_size_mb': backup_size,
        'csv_export': export_success,
        'database_size_mb': get_database_size(),
        'retention_days': RETENTION_DAYS
    }
    
    # Sauvegarder le rapport
    report_path = os.path.join(BACKUP_FOLDER, f"backup_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    
    # Nettoyer les anciens rapports
    old_reports = glob.glob(os.path.join(BACKUP_FOLDER, "backup_report_*.json"))
    for old_report in sorted(old_reports)[:-MAX_BACKUPS]:
        try:
            os.remove(old_report)
        except:
            pass
    
    return report


def send_email_notification(subject, body):
    """Envoie une notification par email (optionnel)"""
    if not ENABLE_EMAIL_NOTIFICATION:
        return
    
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        msg = MIMEMultipart()
        msg['From'] = EMAIL_CONFIG['sender_email']
        msg['To'] = EMAIL_CONFIG['recipient_email']
        msg['Subject'] = subject
        
        msg.attach(MIMEText(body, 'plain'))
        
        with smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port']) as server:
            server.starttls()
            server.login(EMAIL_CONFIG['sender_email'], EMAIL_CONFIG['sender_password'])
            server.send_message(msg)
        
        print(f"📧 Notification email envoyée: {subject}")
    except Exception as e:
        print(f"⚠️ Erreur envoi email: {e}")


def list_backups():
    """Liste toutes les sauvegardes disponibles"""
    
    backup_files = glob.glob(os.path.join(BACKUP_FOLDER, "tontine_backup_*.db.gz"))
    if not backup_files:
        print("Aucune sauvegarde trouvée")
        return
    
    print("\n📁 Liste des sauvegardes:")
    print("-" * 60)
    
    total_size = 0
    for backup_file in sorted(backup_files, key=os.path.getmtime, reverse=True):
        filename = os.path.basename(backup_file)
        size_mb = os.path.getsize(backup_file) / (1024 * 1024)
        modified = datetime.fromtimestamp(os.path.getmtime(backup_file))
        
        print(f"📄 {filename}")
        print(f"   Taille: {size_mb:.2f} MB - Date: {modified.strftime('%Y-%m-%d %H:%M:%S')}")
        total_size += size_mb
    
    print("-" * 60)
    print(f"Total: {len(backup_files)} sauvegarde(s) - {total_size:.2f} MB")


def restore_backup(backup_filename):
    """Restaure une sauvegarde spécifique"""
    
    backup_path = os.path.join(BACKUP_FOLDER, backup_filename)
    
    if not os.path.exists(backup_path):
        print(f"❌ Sauvegarde non trouvée: {backup_filename}")
        return False
    
    try:
        # Sauvegarder la base actuelle avant restauration
        if os.path.exists(DATABASE_PATH):
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            pre_restore_backup = f"{DATABASE_PATH}.pre_restore_{timestamp}.bak"
            shutil.copy2(DATABASE_PATH, pre_restore_backup)
            print(f"✅ Sauvegarde pré-restauration créée: {pre_restore_backup}")
        
        # Décompresser et restaurer
        with gzip.open(backup_path, 'rb') as f_in:
            with open(DATABASE_PATH, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        print(f"✅ Base de données restaurée depuis: {backup_filename}")
        return True
        
    except Exception as e:
        print(f"❌ Erreur lors de la restauration: {e}")
        return False


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("🔄 SAUVEGARDE AUTOMATIQUE - Tontine Manager")
    print("=" * 60)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Dossier de sauvegarde: {BACKUP_FOLDER}")
    print(f"Rétention: {RETENTION_DAYS} jours")
    print("-" * 60)
    
    # Vérifier les arguments de ligne de commande
    if len(sys.argv) > 1:
        if sys.argv[1] == '--list':
            list_backups()
            sys.exit(0)
        elif sys.argv[1] == '--restore' and len(sys.argv) > 2:
            restore_backup(sys.argv[2])
            sys.exit(0)
        elif sys.argv[1] == '--verify':
            verify_backup_integrity()
            sys.exit(0)
    
    # Créer la sauvegarde principale
    backup_success = create_backup()
    
    # Export CSV optionnel
    csv_success = None
    if ENABLE_CSV_EXPORT:
        print("\n📊 Export CSV...")
        csv_success = export_to_csv_backup()
    
    # Vérifier l'intégrité
    print("\n🔍 Vérification de l'intégrité...")
    integrity_ok = verify_backup_integrity()
    
    # Générer le rapport
    backup_size = None
    if backup_success:
        backup_files = glob.glob(os.path.join(BACKUP_FOLDER, "tontine_backup_*.db.gz"))
        if backup_files:
            latest = max(backup_files, key=os.path.getctime)
            backup_size = os.path.getsize(latest) / (1024 * 1024)
    
    report = generate_backup_report(backup_success, backup_size, csv_success)
    
    # Afficher le résumé
    print("\n" + "=" * 60)
    print("📋 RÉSUMÉ DE LA SAUVEGARDE")
    print("=" * 60)
    print(f"✅ Sauvegarde: {'Réussie' if backup_success else 'Échouée'}")
    if backup_size:
        print(f"📦 Taille: {backup_size:.2f} MB")
    if ENABLE_CSV_EXPORT:
        print(f"📊 Export CSV: {'Réussi' if csv_success else 'Échoué'}")
    print(f"🔍 Intégrité: {'OK' if integrity_ok else 'Problème détecté'}")
    print(f"💾 Base de données: {get_database_size():.2f} MB")
    print("=" * 60)
    
    # Notification par email (optionnel)
    if not backup_success:
        send_email_notification(
            "⚠️ ALERTE: Échec de la sauvegarde Tontine",
            f"La sauvegarde automatique a échoué à {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\nVérifiez les logs pour plus de détails."
        )
    
    print("\n✅ Script de sauvegarde terminé")
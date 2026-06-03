import os
from datetime import timedelta
from pathlib import Path

# Définir le chemin de base du projet
BASE_DIR = Path(__file__).resolve().parent

class Config:
    # ============================================================
    # SÉCURITÉ
    # ============================================================
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production-12345'
    
    # ============================================================
    # BASE DE DONNÉES
    # ============================================================
    # CORRECTION : Chemin cohérent avec run.py
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or f'sqlite:///{BASE_DIR}/instance/tontine.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 10,
        'pool_recycle': 3600,
        'pool_pre_ping': True
    }
    
    # ============================================================
    # SESSION
    # ============================================================
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # ============================================================
    # UPLOADS - FICHIERS ET IMAGES
    # ============================================================
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5MB max
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    
    # CORRECTION : Chemin correct pour les uploads
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'app', 'static', 'images')
    REPORTS_FOLDER = os.path.join(BASE_DIR, 'reports')
    BACKUP_FOLDER = os.path.join(BASE_DIR, 'backups')
    
    # ============================================================
    # PARAMÈTRES DE LA TONTINE
    # ============================================================
    PRESENCE_AMOUNT = 1050
    TONTINE_AMOUNTS = [5100, 10200, 20200]
    PRESENCE_FREQUENCY_WEEKS = 1
    TONTINE_FREQUENCY_PER_MONTH = 2
    
    # CORRECTION : Ajout des types de groupes cohérents avec le code
    GROUP_TYPES = ['8', '18', '100', '200']
    GROUP_SIZES = [8, 18, 100, 200]
    FONDS_CAISSE_AMOUNT = 5000
    MINIMUM_CAISSE_BALANCE = 5000
    CAISSE_ALERT_THRESHOLD = 10000
    
    # ============================================================
    # PARAMÈTRES DES EMPRUNTS
    # ============================================================
    LOAN_MAX_DURATION_MONTHS = 3
    LOAN_MAX_MULTIPLIER_SAVINGS = 3
    LOAN_INTEREST_RATE_NORMAL = 5.0
    LOAN_INTEREST_RATE_EARLY = 3.0
    LOAN_INTEREST_RATE_LATE = 8.0
    
    PENALTY_DAYS_GRACE = 0
    PENALTY_AMOUNT_PER_DAY = 500
    PENALTY_FAILED_CONTRIBUTION = 500
    
    # ============================================================
    # PARAMÈTRES DES AIDES
    # ============================================================
    MAX_AID_PER_MEMBER = 3
    AID_AMOUNTS = {
        'MALADIE': 15000,      # CORRECTION : Ajout du type MALADIE
        'DECES': 25000,
        'MARIAGE': 15000,
        'NAISSANCE': 10000,
        'AUTRE': 5000
    }
    
    # ============================================================
    # PAGINATION
    # ============================================================
    ITEMS_PER_PAGE = 20
    ADMIN_ITEMS_PER_PAGE = 50
    API_ITEMS_PER_PAGE = 100
    
    # ============================================================
    # BACKUP
    # ============================================================
    BACKUP_RETENTION_DAYS = 30
    BACKUP_AUTO_SCHEDULE = True
    BACKUP_TIME = "02:00"
    
    # ============================================================
    # LOGGING
    # ============================================================
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
    LOG_FILE = os.path.join(BASE_DIR, 'logs', 'tontine.log')
    LOG_MAX_BYTES = 10 * 1024 * 1024
    LOG_BACKUP_COUNT = 5
    
    # ============================================================
    # API ET PAIEMENTS (Optionnel)
    # ============================================================
    ORANGE_MONEY_API_URL = os.environ.get('ORANGE_MONEY_API_URL', 'https://api.orange.com')
    ORANGE_MONEY_CLIENT_ID = os.environ.get('ORANGE_MONEY_CLIENT_ID', '')
    ORANGE_MONEY_CLIENT_SECRET = os.environ.get('ORANGE_MONEY_CLIENT_SECRET', '')
    ORANGE_MONEY_MERCHANT_KEY = os.environ.get('ORANGE_MONEY_MERCHANT_KEY', '')
    
    MTN_MOMO_API_URL = os.environ.get('MTN_MOMO_API_URL', 'https://api.mtn.com')
    MTN_MOMO_CLIENT_ID = os.environ.get('MTN_MOMO_CLIENT_ID', '')
    MTN_MOMO_CLIENT_SECRET = os.environ.get('MTN_MOMO_CLIENT_SECRET', '')
    MTN_MOMO_SUBSCRIPTION_KEY = os.environ.get('MTN_MOMO_SUBSCRIPTION_KEY', '')
    
    WEBHOOK_SECRET = os.environ.get('WEBHOOK_SECRET', 'webhook-secret-change-in-production')
    WEBHOOK_BASE_URL = os.environ.get('WEBHOOK_BASE_URL', 'https://your-domain.com')
    
    # ============================================================
    # EMAIL
    # ============================================================
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@tontine.com')
    
    # ============================================================
    # DEBUG
    # ============================================================
    DEBUG = os.environ.get('DEBUG', 'True').lower() == 'true'
    TESTING = os.environ.get('TESTING', 'False').lower() == 'true'
    ASSETS_DEBUG = DEBUG
    
    # ============================================================
    # MÉTHODES UTILITAIRES
    # ============================================================
    
    @classmethod
    def init_app(cls, app):
        """Initialisation de l'application"""
        folders = [
            cls.UPLOAD_FOLDER,
            cls.REPORTS_FOLDER,
            cls.BACKUP_FOLDER,
            os.path.join(BASE_DIR, 'logs'),
            os.path.join(BASE_DIR, 'instance')  # CORRECTION : Ajout du dossier instance
        ]
        
        for folder in folders:
            if not os.path.exists(folder):
                os.makedirs(folder)
                print(f"Dossier créé: {folder}")
        
        if cls.LOG_FILE:
            import logging
            from logging.handlers import RotatingFileHandler
            
            os.makedirs(os.path.dirname(cls.LOG_FILE), exist_ok=True)
            file_handler = RotatingFileHandler(
                cls.LOG_FILE,
                maxBytes=cls.LOG_MAX_BYTES,
                backupCount=cls.LOG_BACKUP_COUNT
            )
            file_handler.setFormatter(logging.Formatter(
                '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
            ))
            file_handler.setLevel(logging.INFO)
            app.logger.addHandler(file_handler)
            app.logger.setLevel(logging.INFO)
            app.logger.info('Application démarrée')
    
    @classmethod
    def get_tontine_amount_display(cls):
        return [(str(amount), f"{amount:,.0f} FCFA") for amount in cls.TONTINE_AMOUNTS]
    
    @classmethod
    def get_group_type_display(cls):
        """Retourne les types de groupes disponibles"""
        return [(str(size), f"Groupe de {size} membres") for size in cls.GROUP_TYPES]
    
    @classmethod
    def get_interest_rate_display(cls):
        return [
            (cls.LOAN_INTEREST_RATE_EARLY, f"{cls.LOAN_INTEREST_RATE_EARLY}% (Remboursement < 90 jours)"),
            (cls.LOAN_INTEREST_RATE_NORMAL, f"{cls.LOAN_INTEREST_RATE_NORMAL}% (Normal)"),
            (cls.LOAN_INTEREST_RATE_LATE, f"{cls.LOAN_INTEREST_RATE_LATE}% (Retard)")
        ]
    
    @classmethod
    def get_aid_types_display(cls):
        return [
            ('MALADIE', f"Maladie ({cls.AID_AMOUNTS['MALADIE']:,.0f} FCFA)"),
            ('DECES', f"Décès ({cls.AID_AMOUNTS['DECES']:,.0f} FCFA)"),
            ('MARIAGE', f"Mariage ({cls.AID_AMOUNTS['MARIAGE']:,.0f} FCFA)"),
            ('NAISSANCE', f"Naissance ({cls.AID_AMOUNTS['NAISSANCE']:,.0f} FCFA)"),
            ('AUTRE', f"Autre ({cls.AID_AMOUNTS['AUTRE']:,.0f} FCFA)")
        ]


# ============================================================
# CONFIGURATIONS SPÉCIFIQUES PAR ENVIRONNEMENT
# ============================================================

class DevelopmentConfig(Config):
    """Configuration pour le développement"""
    DEBUG = True
    TESTING = False
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{BASE_DIR}/instance/tontine_dev.db'
    SECRET_KEY = 'dev-secret-key-12345'
    SESSION_COOKIE_SECURE = False
    MAIL_SUPPRESS_SEND = True


class TestingConfig(Config):
    """Configuration pour les tests"""
    TESTING = True
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{BASE_DIR}/instance/tontine_test.db'
    SECRET_KEY = 'test-secret-key'
    WTF_CSRF_ENABLED = False
    SERVER_NAME = 'localhost.localdomain'
    PRESERVE_CONTEXT_ON_EXCEPTION = False
    MAIL_SUPPRESS_SEND = True


class ProductionConfig(Config):
    """Configuration pour la production - Nécessite des variables d'environnement"""
    DEBUG = False
    TESTING = False
    
    # CORRECTION : Définir directement les valeurs depuis les variables d'environnement
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:////var/lib/tontine/tontine.db')
    SECRET_KEY = os.environ.get('SECRET_KEY')
    WEBHOOK_SECRET = os.environ.get('WEBHOOK_SECRET')
    
    @classmethod
    def check_environment(cls):
        """Vérifie que toutes les variables d'environnement sont définies"""
        required_vars = ['DATABASE_URL', 'SECRET_KEY']
        missing = [var for var in required_vars if not os.environ.get(var)]
        
        if missing:
            raise ValueError(f"Variables d'environnement manquantes en production: {', '.join(missing)}")
    
    @classmethod
    def init_app(cls, app):
        """Initialisation avec vérification de l'environnement"""
        cls.check_environment()
        super().init_app(app)


# ============================================================
# SÉLECTION DE LA CONFIGURATION
# ============================================================

# Déterminer l'environnement
_ENV = os.environ.get('FLASK_ENV', 'development').lower()

# Sélectionner la configuration
if _ENV == 'production':
    CurrentConfig = ProductionConfig
elif _ENV == 'testing':
    CurrentConfig = TestingConfig
else:
    CurrentConfig = DevelopmentConfig

# Exporter la configuration courante
current_config = CurrentConfig


# ============================================================
# FONCTION DE VÉRIFICATION DE LA BASE DE DONNÉES
# ============================================================

def check_database_connection():
    """Vérifie que la base de données est correctement configurée"""
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import SQLAlchemyError
    
    try:
        engine = create_engine(CurrentConfig.SQLALCHEMY_DATABASE_URI)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1")).scalar()
            if result == 1:
                print(f"✅ Connexion BD OK: {CurrentConfig.SQLALCHEMY_DATABASE_URI}")
                return True
    except SQLAlchemyError as e:
        print(f"❌ Erreur de connexion BD: {e}")
        return False


# Pour la compatibilité avec l'ancien code
def get_config():
    """Retourne la configuration en fonction de l'environnement"""
    return current_config
# permissions.py
from flask_login import current_user

# ============================================================
# MATRICE DES PERMISSIONS
# ============================================================

PERMISSIONS = {
    'view_dashboard': {
        'PRESIDENT': ['read'], 'SECRETAIRE': ['read'], 'TRESORIER': ['read'],
        'COMMUNICATION': ['read'], 'CENSEUR': ['read'], 'MEMBRE': ['read']
    },
    'manage_members': {
        'PRESIDENT': ['create', 'read', 'update', 'delete'],
        'SECRETAIRE': ['create', 'read', 'update'],
        'TRESORIER': ['read'], 'COMMUNICATION': ['read'], 
        'CENSEUR': ['read'], 'MEMBRE': []
    },
    'manage_transactions': {
        'PRESIDENT': ['create', 'read', 'update', 'delete'],
        'SECRETAIRE': ['create', 'read', 'update'],
        'TRESORIER': ['create', 'read', 'update'],
        'CENSEUR': ['read'], 'COMMUNICATION': ['read'], 'MEMBRE': ['read']
    },
    'manage_loans': {
        'PRESIDENT': ['create', 'read', 'update', 'delete'],
        'SECRETAIRE': ['create', 'read', 'update'],
        'TRESORIER': ['create', 'read', 'update'],
        'CENSEUR': ['read'], 'COMMUNICATION': ['read'], 'MEMBRE': ['create', 'read']
    },
    'manage_tontine': {
        'PRESIDENT': ['create', 'read', 'update', 'delete'],
        'SECRETAIRE': ['create', 'read', 'update'],
        'TRESORIER': ['create', 'read', 'update'],
        'CENSEUR': ['read'], 'COMMUNICATION': ['read'], 'MEMBRE': ['read']
    },
    'manage_sanctions': {
        'PRESIDENT': ['create', 'read', 'update', 'delete'],
        'SECRETAIRE': ['create', 'read', 'update'],
        'CENSEUR': ['create', 'read', 'update', 'delete'],
        'TRESORIER': ['read'], 'COMMUNICATION': ['read'], 'MEMBRE': ['read']
    },
    'manage_announcements': {
        'PRESIDENT': ['create', 'read', 'update', 'delete'],
        'SECRETAIRE': ['create', 'read', 'update', 'delete'],
        'COMMUNICATION': ['create', 'read', 'update', 'delete'],
        'TRESORIER': ['read'], 'CENSEUR': ['read'], 'MEMBRE': ['read']
    },
    'manage_aides': {
        'PRESIDENT': ['create', 'read', 'update', 'delete'],
        'SECRETAIRE': ['create', 'read', 'update'],
        'TRESORIER': ['create', 'read', 'update'],
        'CENSEUR': ['read'], 'COMMUNICATION': ['read'], 'MEMBRE': ['create', 'read']
    },
    'view_reports': {
        'PRESIDENT': ['read'], 'SECRETAIRE': ['read'],
        'TRESORIER': ['read'], 'CENSEUR': ['read'],
        'COMMUNICATION': ['read'], 'MEMBRE': []
    },
    'view_logs': {
        'PRESIDENT': ['read'], 'SECRETAIRE': ['read'], 
        'TRESORIER': [], 'COMMUNICATION': [], 'CENSEUR': [], 'MEMBRE': []
    }
}


# ============================================================
# MENU PAR RÔLE - CHAQUE RÔLE VOIT UNIQUEMENT CE QU'IL DOIT VOIR
# ============================================================

MENU_ITEMS = {
    'PRESIDENT': [
        {'name': 'Tableau de bord', 'icon': 'fas fa-tachometer-alt', 'url': 'dashboard'},
        {'name': 'Membres', 'icon': 'fas fa-users', 'url': 'members'},
        {'name': 'Transactions', 'icon': 'fas fa-exchange-alt', 'url': 'transactions'},
        {'name': 'Emprunts', 'icon': 'fas fa-hand-holding-usd', 'url': 'loans'},
        {'name': 'Cycles Tontine', 'icon': 'fas fa-random', 'url': 'tontine_cycles'},
        {'name': 'Sanctions', 'icon': 'fas fa-gavel', 'url': 'sanctions'},
        {'name': 'Aides sociales', 'icon': 'fas fa-heart', 'url': 'aides'},
        {'name': 'Réunions', 'icon': 'fas fa-calendar-alt', 'url': 'meetings'},
        {'name': 'Annonces', 'icon': 'fas fa-bullhorn', 'url': 'annonces'},
        {'name': 'Rapports', 'icon': 'fas fa-chart-line', 'url': 'reports'},
        {'name': 'Journal d\'audit', 'icon': 'fas fa-history', 'url': 'audit_logs'},
        {'name': 'Mon profil', 'icon': 'fas fa-user-circle', 'url': 'profile'},
    ],
    
    'SECRETAIRE': [
        {'name': 'Tableau de bord', 'icon': 'fas fa-tachometer-alt', 'url': 'dashboard'},
        {'name': 'Membres', 'icon': 'fas fa-users', 'url': 'members'},
        {'name': 'Transactions', 'icon': 'fas fa-exchange-alt', 'url': 'transactions'},
        {'name': 'Emprunts', 'icon': 'fas fa-hand-holding-usd', 'url': 'loans'},
        {'name': 'Cycles Tontine', 'icon': 'fas fa-random', 'url': 'tontine_cycles'},
        {'name': 'Sanctions', 'icon': 'fas fa-gavel', 'url': 'sanctions'},
        {'name': 'Aides sociales', 'icon': 'fas fa-heart', 'url': 'aides'},
        {'name': 'Réunions', 'icon': 'fas fa-calendar-alt', 'url': 'meetings'},
        {'name': 'Annonces', 'icon': 'fas fa-bullhorn', 'url': 'annonces'},
        {'name': 'Rapports', 'icon': 'fas fa-chart-line', 'url': 'reports'},
        {'name': 'Journal d\'audit', 'icon': 'fas fa-history', 'url': 'audit_logs'},
        {'name': 'Mon profil', 'icon': 'fas fa-user-circle', 'url': 'profile'},
    ],
    
    'TRESORIER': [
        {'name': 'Tableau de bord', 'icon': 'fas fa-tachometer-alt', 'url': 'dashboard'},
        {'name': 'Membres', 'icon': 'fas fa-users', 'url': 'members'},
        {'name': 'Transactions', 'icon': 'fas fa-exchange-alt', 'url': 'transactions'},
        {'name': 'Emprunts', 'icon': 'fas fa-hand-holding-usd', 'url': 'loans'},
        {'name': 'Cycles Tontine', 'icon': 'fas fa-random', 'url': 'tontine_cycles'},
        {'name': 'Aides sociales', 'icon': 'fas fa-heart', 'url': 'aides'},
        {'name': 'Rapports', 'icon': 'fas fa-chart-line', 'url': 'reports'},
        {'name': 'Mon profil', 'icon': 'fas fa-user-circle', 'url': 'profile'},
    ],
    
    'CENSEUR': [
        {'name': 'Tableau de bord', 'icon': 'fas fa-tachometer-alt', 'url': 'dashboard'},
        {'name': 'Membres', 'icon': 'fas fa-users', 'url': 'members'},
        {'name': 'Sanctions', 'icon': 'fas fa-gavel', 'url': 'sanctions'},
        {'name': 'Rapports', 'icon': 'fas fa-chart-line', 'url': 'reports'},
        {'name': 'Mon profil', 'icon': 'fas fa-user-circle', 'url': 'profile'},
    ],
    
    'COMMUNICATION': [
        {'name': 'Tableau de bord', 'icon': 'fas fa-tachometer-alt', 'url': 'dashboard'},
        {'name': 'Réunions', 'icon': 'fas fa-calendar-alt', 'url': 'meetings'},
        {'name': 'Annonces', 'icon': 'fas fa-bullhorn', 'url': 'annonces'},
        {'name': 'Mon profil', 'icon': 'fas fa-user-circle', 'url': 'profile'},
    ],
    
    'MEMBRE': [
        {'name': 'Tableau de bord', 'icon': 'fas fa-tachometer-alt', 'url': 'dashboard'},
        {'name': 'Mes transactions', 'icon': 'fas fa-exchange-alt', 'url': 'transactions'},
        {'name': 'Mes emprunts', 'icon': 'fas fa-hand-holding-usd', 'url': 'loans'},
        {'name': 'Mes sanctions', 'icon': 'fas fa-gavel', 'url': 'sanctions'},
        {'name': 'Mes aides', 'icon': 'fas fa-heart', 'url': 'aides'},
        {'name': 'Annonces', 'icon': 'fas fa-bullhorn', 'url': 'annonces'},
        {'name': 'Réunions', 'icon': 'fas fa-calendar-alt', 'url': 'meetings'},
        {'name': 'Mon profil', 'icon': 'fas fa-user-circle', 'url': 'profile'},
    ]
}


# ============================================================
# FONCTION POUR RÉCUPÉRER LE MENU DYNAMIQUE
# ============================================================

def get_user_menu():
    """
    Retourne le menu adapté au rôle de l'utilisateur connecté
    À utiliser dans base.html
    """
    if not current_user.is_authenticated:
        return []
    
    role = current_user.role
    # Récupérer le menu selon le rôle, sinon menu membre par défaut
    menu = MENU_ITEMS.get(role, MENU_ITEMS['MEMBRE'])
    
    return menu


def has_permission(permission, action='read'):
    """Vérifie si l'utilisateur a une permission"""
    if not current_user.is_authenticated:
        return False
    
    role = current_user.role
    if role in PERMISSIONS.get(permission, {}):
        return action in PERMISSIONS[permission][role]
    return False


def is_admin():
    return current_user.is_authenticated and current_user.role in ['PRESIDENT', 'SECRETAIRE']


def is_bureau_member():
    return current_user.is_authenticated and current_user.role in ['PRESIDENT', 'SECRETAIRE', 'TRESORIER', 'CENSEUR', 'COMMUNICATION']


def user_can(permission, action='read'):
    return has_permission(permission, action)
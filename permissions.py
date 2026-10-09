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
    'SUPERADMIN': [
        {'name': 'Tontines de la plateforme', 'icon': 'fas fa-building', 'url': 'superadmin'},
    ],

    'PRESIDENT': [
        {'name': 'Tableau de bord', 'icon': 'fas fa-tachometer-alt', 'url': 'dashboard'},
        {'name': 'Membres', 'icon': 'fas fa-users', 'url': 'members'},
        {'name': 'Transactions', 'icon': 'fas fa-exchange-alt', 'url': 'transactions'},
        {'name': 'Emprunts', 'icon': 'fas fa-hand-holding-usd', 'url': 'loans'},
        {'name': 'Cycles Tontine', 'icon': 'fas fa-random', 'url': 'tontine_cycles'},
        {'name': 'Sanctions', 'icon': 'fas fa-gavel', 'url': 'sanctions'},
        {'name': 'Aides sociales', 'icon': 'fas fa-heart', 'url': 'aides'},
        {'name': 'Procès-verbaux', 'icon': 'fas fa-file-signature', 'url': 'meetings'},
        {'name': 'Annonces', 'icon': 'fas fa-bullhorn', 'url': 'annonces'},
        {'name': 'Rapports', 'icon': 'fas fa-chart-line', 'url': 'reports'},
        {'name': 'Journal d\'audit', 'icon': 'fas fa-history', 'url': 'audit_logs'},
        {'name': 'Mots de passe oubliés', 'icon': 'fas fa-key', 'url': 'password_requests'},
        {'name': 'Cotisations', 'icon': 'fas fa-coins', 'url': 'cotisations'},
        {'name': 'Séances', 'icon': 'fas fa-clipboard-check', 'url': 'seances'},
        {'name': "Fin d'exercice", 'icon': 'fas fa-calendar-check', 'url': 'exercise'},
        {'name': 'Avals', 'icon': 'fas fa-handshake', 'url': 'avals'},
        {'name': 'Votes', 'icon': 'fas fa-vote-yea', 'url': 'votes'},
        {'name': 'Tirages au sort', 'icon': 'fas fa-dice', 'url': 'tirages'},
        {'name': 'Galerie accueil', 'icon': 'fas fa-images', 'url': 'gallery_admin'},
        {'name': 'Paramètres', 'icon': 'fas fa-sliders-h', 'url': 'tontine_settings'},
        {'name': 'Abonnement', 'icon': 'fas fa-credit-card', 'url': 'abonnement'},
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
        {'name': 'Procès-verbaux', 'icon': 'fas fa-file-signature', 'url': 'meetings'},
        {'name': 'Annonces', 'icon': 'fas fa-bullhorn', 'url': 'annonces'},
        {'name': 'Rapports', 'icon': 'fas fa-chart-line', 'url': 'reports'},
        {'name': 'Journal d\'audit', 'icon': 'fas fa-history', 'url': 'audit_logs'},
        {'name': 'Mots de passe oubliés', 'icon': 'fas fa-key', 'url': 'password_requests'},
        {'name': 'Cotisations', 'icon': 'fas fa-coins', 'url': 'cotisations'},
        {'name': 'Séances', 'icon': 'fas fa-clipboard-check', 'url': 'seances'},
        {'name': "Fin d'exercice", 'icon': 'fas fa-calendar-check', 'url': 'exercise'},
        {'name': 'Avals', 'icon': 'fas fa-handshake', 'url': 'avals'},
        {'name': 'Votes', 'icon': 'fas fa-vote-yea', 'url': 'votes'},
        {'name': 'Tirages au sort', 'icon': 'fas fa-dice', 'url': 'tirages'},
        {'name': 'Galerie accueil', 'icon': 'fas fa-images', 'url': 'gallery_admin'},
        {'name': 'Abonnement', 'icon': 'fas fa-credit-card', 'url': 'abonnement'},
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
        {'name': 'Cotisations', 'icon': 'fas fa-coins', 'url': 'cotisations'},
        {'name': 'Séances', 'icon': 'fas fa-clipboard-check', 'url': 'seances'},
        {'name': "Fin d'exercice", 'icon': 'fas fa-calendar-check', 'url': 'exercise'},
        {'name': 'Avals', 'icon': 'fas fa-handshake', 'url': 'avals'},
        {'name': 'Votes', 'icon': 'fas fa-vote-yea', 'url': 'votes'},
        {'name': 'Tirages au sort', 'icon': 'fas fa-dice', 'url': 'tirages'},
        {'name': 'Abonnement', 'icon': 'fas fa-credit-card', 'url': 'abonnement'},
        {'name': 'Mon profil', 'icon': 'fas fa-user-circle', 'url': 'profile'},
    ],
    
    'CENSEUR': [
        {'name': 'Tableau de bord', 'icon': 'fas fa-tachometer-alt', 'url': 'dashboard'},
        {'name': 'Membres', 'icon': 'fas fa-users', 'url': 'members'},
        {'name': 'Sanctions', 'icon': 'fas fa-gavel', 'url': 'sanctions'},
        {'name': 'Rapports', 'icon': 'fas fa-chart-line', 'url': 'reports'},
        {'name': 'Cotisations', 'icon': 'fas fa-coins', 'url': 'cotisations'},
        {'name': 'Cycles Tontine', 'icon': 'fas fa-sync-alt', 'url': 'tontine_cycles'},
        {'name': 'Séances', 'icon': 'fas fa-clipboard-check', 'url': 'seances'},
        {'name': 'Avals', 'icon': 'fas fa-handshake', 'url': 'avals'},
        {'name': 'Votes', 'icon': 'fas fa-vote-yea', 'url': 'votes'},
        {'name': 'Tirages au sort', 'icon': 'fas fa-dice', 'url': 'tirages'},
        {'name': 'Mon profil', 'icon': 'fas fa-user-circle', 'url': 'profile'},
    ],
    
    'COMMUNICATION': [
        {'name': 'Tableau de bord', 'icon': 'fas fa-tachometer-alt', 'url': 'dashboard'},
        {'name': 'Procès-verbaux', 'icon': 'fas fa-file-signature', 'url': 'meetings'},
        {'name': 'Annonces', 'icon': 'fas fa-bullhorn', 'url': 'annonces'},
        {'name': 'Cotisations', 'icon': 'fas fa-coins', 'url': 'cotisations'},
        {'name': 'Cycles Tontine', 'icon': 'fas fa-sync-alt', 'url': 'tontine_cycles'},
        {'name': 'Avals', 'icon': 'fas fa-handshake', 'url': 'avals'},
        {'name': 'Votes', 'icon': 'fas fa-vote-yea', 'url': 'votes'},
        {'name': 'Tirages au sort', 'icon': 'fas fa-dice', 'url': 'tirages'},
        {'name': 'Galerie accueil', 'icon': 'fas fa-images', 'url': 'gallery_admin'},
        {'name': 'Mon profil', 'icon': 'fas fa-user-circle', 'url': 'profile'},
    ],
    
    'MEMBRE': [
        {'name': 'Tableau de bord', 'icon': 'fas fa-tachometer-alt', 'url': 'dashboard'},
        {'name': 'Mes transactions', 'icon': 'fas fa-exchange-alt', 'url': 'transactions'},
        {'name': 'Mes emprunts', 'icon': 'fas fa-hand-holding-usd', 'url': 'loans'},
        {'name': 'Mes sanctions', 'icon': 'fas fa-gavel', 'url': 'sanctions'},
        {'name': 'Mes aides', 'icon': 'fas fa-heart', 'url': 'aides'},
        {'name': 'Annonces', 'icon': 'fas fa-bullhorn', 'url': 'annonces'},
        {'name': 'Procès-verbaux', 'icon': 'fas fa-file-signature', 'url': 'meetings'},
        {'name': 'Cotisations', 'icon': 'fas fa-coins', 'url': 'cotisations'},
        {'name': 'Cycles Tontine', 'icon': 'fas fa-sync-alt', 'url': 'tontine_cycles'},
        {'name': 'Avals', 'icon': 'fas fa-handshake', 'url': 'avals'},
        {'name': 'Votes', 'icon': 'fas fa-vote-yea', 'url': 'votes'},
        {'name': 'Tirages au sort', 'icon': 'fas fa-dice', 'url': 'tirages'},
        {'name': 'Mon profil', 'icon': 'fas fa-user-circle', 'url': 'profile'},
    ]
}


# ============================================================
# FONCTION POUR RÉCUPÉRER LE MENU DYNAMIQUE
# ============================================================

# Rubriques du menu, dans l'ordre d'affichage : chaque page est rangée avec celles qui lui ressemblent
MENU_SECTIONS = [
    ('', ['dashboard']),
    ('Argent', ['seances', 'cotisations', 'transactions', 'loans', 'avals', 'exercise']),
    ('Tontine', ['tontine_cycles', 'tirages']),
    ('Vie du groupe', ['members', 'sanctions', 'aides', 'meetings', 'annonces', 'votes']),
    ('Administration', ['reports', 'abonnement', 'tontine_settings', 'password_requests', 'audit_logs', 'gallery_admin', 'superadmin']),
    ('', ['profile']),
]
_SECTION_OF = {url: (rank, title, pos) for rank, (title, urls) in enumerate(MENU_SECTIONS) for pos, url in enumerate(urls)}


def get_user_menu():
    """Menu du rôle connecté, rangé par rubriques (chaque entrée porte 'section' : titre à afficher ou '')"""
    if not current_user.is_authenticated:
        return []
    items = MENU_ITEMS.get(current_user.role, MENU_ITEMS['MEMBRE'])
    ordered = sorted(items, key=lambda it: _SECTION_OF.get(it['url'], (len(MENU_SECTIONS) - 1, '', 99))[::2])
    menu, last = [], None
    for item in ordered:
        rank, title, _ = _SECTION_OF.get(item['url'], (len(MENU_SECTIONS) - 1, '', 99))
        menu.append(dict(item, section=title if rank != last and title else ''))
        last = rank
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
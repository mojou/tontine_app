# decorators.py
from functools import wraps
from flask import flash, redirect, url_for, abort
from flask_login import current_user
# Importer les modèles nécessaires
from models import Transaction, Loan
# ============================================================
# DÉCORATEURS DE BASE PAR RÔLE
# ============================================================

def role_required(roles):
    """
    Vérifie que l'utilisateur a l'un des rôles autorisés
    Usage: @role_required(['PRESIDENT', 'SECRETAIRE'])
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Veuillez vous connecter.', 'warning')
                return redirect(url_for('login'))
            
            if current_user.role not in roles:
                flash(f'Accès refusé. Rôles requis: {", ".join(roles)}', 'danger')
                return redirect(url_for('dashboard'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def admin_required(f):
    """
    Pour les actions administratives sensibles (Président seulement)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Veuillez vous connecter.', 'warning')
            return redirect(url_for('login'))
        
        if current_user.role != 'PRESIDENT':
            flash('Accès refusé. Seul le Président peut effectuer cette action.', 'danger')
            return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function


def president_required(f):
    """
    Président seulement (actions critiques comme suppression)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Veuillez vous connecter.', 'warning')
            return redirect(url_for('login'))
        
        if current_user.role != 'PRESIDENT':
            flash('Accès refusé. Seul le Président peut effectuer cette action.', 'danger')
            return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function


def secretaire_required(f):
    """
    Secrétaire et Président
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Veuillez vous connecter.', 'warning')
            return redirect(url_for('login'))
        
        if current_user.role not in ['SECRETAIRE', 'PRESIDENT']:
            flash('Accès refusé. Seul le Secrétaire ou le Président peut effectuer cette action.', 'danger')
            return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function


def tresorier_required(f):
    """
    Trésorier et Président
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Veuillez vous connecter.', 'warning')
            return redirect(url_for('login'))
        
        if current_user.role not in ['TRESORIER', 'PRESIDENT']:
            flash('Accès refusé. Seul le Trésorier ou le Président peut effectuer cette action.', 'danger')
            return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function


def censeur_required(f):
    """
    Censeur, Président et Secrétaire
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Veuillez vous connecter.', 'warning')
            return redirect(url_for('login'))
        
        if current_user.role not in ['CENSEUR', 'PRESIDENT', 'SECRETAIRE']:
            flash('Accès refusé. Seul le Censeur, le Président ou le Secrétaire peut effectuer cette action.', 'danger')
            return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function


def communication_required(f):
    """
    Communication, Président et Secrétaire
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Veuillez vous connecter.', 'warning')
            return redirect(url_for('login'))
        
        if current_user.role not in ['COMMUNICATION', 'PRESIDENT', 'SECRETAIRE']:
            flash('Accès refusé. Seul le Responsable Communication, le Président ou le Secrétaire peut effectuer cette action.', 'danger')
            return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function


def bureau_required(f):
    """
    Pour tous les membres du bureau (Président, Secrétaire, Trésorier, Censeur, Communication)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Veuillez vous connecter.', 'warning')
            return redirect(url_for('login'))
        
        if current_user.role not in ['PRESIDENT', 'SECRETAIRE', 'TRESORIER', 'CENSEUR', 'COMMUNICATION']:
            flash('Accès refusé. Réservé aux membres du bureau.', 'danger')
            return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function


# ============================================================
# DÉCORATEURS DE PROTECTION DES DONNÉES
# ============================================================

def member_owner_required(f):
    """
    Vérifie que le membre ne voit que ses propres données
    Les membres du bureau (admin) voient tout
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Veuillez vous connecter.', 'warning')
            return redirect(url_for('login'))
        
        member_id = kwargs.get('member_id')
        
        # Les membres du bureau peuvent tout voir
        if current_user.is_admin():
            return f(*args, **kwargs)
        
        # Un membre simple ne voit que son propre profil
        if current_user.member_id == member_id:
            return f(*args, **kwargs)
        
        flash('Vous ne pouvez voir que votre propre profil.', 'danger')
        return redirect(url_for('dashboard'))
    return decorated_function


def transaction_owner_required(f):
    """
    Vérifie que l'utilisateur ne voit que ses propres transactions
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Veuillez vous connecter.', 'warning')
            return redirect(url_for('login'))
        
        transaction_id = kwargs.get('transaction_id')
        transaction = Transaction.query.get(transaction_id)
        
        if not transaction:
            abort(404)
        
        # Les membres du bureau peuvent tout voir
        if current_user.is_admin():
            return f(*args, **kwargs)
        
        # Un membre simple ne voit que ses propres transactions
        if current_user.member_id == transaction.member_id:
            return f(*args, **kwargs)
        
        flash('Vous ne pouvez voir que vos propres transactions.', 'danger')
        return redirect(url_for('dashboard'))
    return decorated_function


def loan_owner_required(f):
    """
    Vérifie que l'utilisateur ne voit que ses propres emprunts
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Veuillez vous connecter.', 'warning')
            return redirect(url_for('login'))
        
        loan_id = kwargs.get('loan_id')
        loan = Loan.query.get(loan_id)
        
        if not loan:
            abort(404)
        
        # Les membres du bureau peuvent tout voir
        if current_user.is_admin():
            return f(*args, **kwargs)
        
        # Un membre simple ne voit que ses propres emprunts
        if current_user.member_id == loan.member_id:
            return f(*args, **kwargs)
        
        flash('Vous ne pouvez voir que vos propres emprunts.', 'danger')
        return redirect(url_for('dashboard'))
    return decorated_function


# ============================================================
# DÉCORATEURS DE VÉRIFICATION D'ÉTAT
# ============================================================

def require_active_member(f):
    """
    Vérifie que le membre connecté est actif
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Veuillez vous connecter.', 'warning')
            return redirect(url_for('login'))
        
        if current_user.member_id:
            member = current_user.member
            if member and member.status != 'ACTIF':
                flash('Votre compte membre n\'est pas actif. Contactez l\'administration.', 'danger')
                return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function


def require_fonds_caisse_paid(f):
    """
    Vérifie que le membre a payé son fonds de caisse (pour emprunter)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Veuillez vous connecter.', 'warning')
            return redirect(url_for('login'))
        
        # Les membres du bureau n'ont pas cette restriction pour les actions admin
        if current_user.is_admin() and not kwargs.get('loan_request'):
            return f(*args, **kwargs)
        
        if current_user.member_id:
            member = current_user.member
            if member and not member.has_paid_fonds_caisse:
                flash('Vous devez payer le fonds de caisse (5 000 FCFA) pour effectuer cette action.', 'warning')
                return redirect(url_for('transactions'))
        
        return f(*args, **kwargs)
    return decorated_function


def require_no_active_loan(f):
    """
    Vérifie que le membre n'a pas d'emprunt actif (pour nouvelle demande)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Veuillez vous connecter.', 'warning')
            return redirect(url_for('login'))
        
        if current_user.member_id:
            active_loan = Loan.query.filter_by(
                member_id=current_user.member_id,
                status='ACTIF'
            ).first()
            if active_loan:
                flash('Vous avez déjà un emprunt en cours. Vous devez le rembourser avant d\'en faire une nouvelle demande.', 'warning')
                return redirect(url_for('loans'))
        
        return f(*args, **kwargs)
    return decorated_function


def require_not_red_status(f):
    """
    Vérifie que le membre n'est pas en statut ROUGE (2 échecs consécutifs)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Veuillez vous connecter.', 'warning')
            return redirect(url_for('login'))
        
        if current_user.member_id:
            member = current_user.member
            if member and member.tontine_status == 'ROUGE':
                flash('Vous êtes en statut ROUGE (2 échecs consécutifs). Veuillez régulariser votre situation.', 'danger')
                return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function


# ============================================================
# DÉCORATEURS POUR LES FONCTIONNALITÉS SPÉCIFIQUES
# ============================================================

def can_manage_members(f):
    """
    Gestion des membres (Président, Secrétaire)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Veuillez vous connecter.', 'warning')
            return redirect(url_for('login'))
        
        if current_user.role not in ['PRESIDENT', 'SECRETAIRE']:
            flash('Accès refusé. Seul le Président ou le Secrétaire peut gérer les membres.', 'danger')
            return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function


def can_manage_transactions(f):
    """
    Gestion des transactions (Trésorier, Président, Secrétaire)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Veuillez vous connecter.', 'warning')
            return redirect(url_for('login'))
        
        if current_user.role not in ['TRESORIER', 'PRESIDENT', 'SECRETAIRE']:
            flash('Accès refusé. Seul le Trésorier, le Président ou le Secrétaire peut gérer les transactions.', 'danger')
            return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function


def can_manage_loans(f):
    """
    Gestion des emprunts (Trésorier, Président, Secrétaire)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Veuillez vous connecter.', 'warning')
            return redirect(url_for('login'))
        
        if current_user.role not in ['TRESORIER', 'PRESIDENT', 'SECRETAIRE']:
            flash('Accès refusé. Seul le Trésorier, le Président ou le Secrétaire peut gérer les emprunts.', 'danger')
            return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function


def can_manage_sanctions(f):
    """
    Gestion des sanctions (Censeur, Président, Secrétaire)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Veuillez vous connecter.', 'warning')
            return redirect(url_for('login'))
        
        if current_user.role not in ['CENSEUR', 'PRESIDENT', 'SECRETAIRE']:
            flash('Accès refusé. Seul le Censeur, le Président ou le Secrétaire peut gérer les sanctions.', 'danger')
            return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function


def can_manage_tontine_cycles(f):
    """
    Gestion des cycles de tontine (Président, Secrétaire, Trésorier)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Veuillez vous connecter.', 'warning')
            return redirect(url_for('login'))
        
        if current_user.role not in ['PRESIDENT', 'SECRETAIRE', 'TRESORIER']:
            flash('Accès refusé. Seul le Président, le Secrétaire ou le Trésorier peut gérer les cycles de tontine.', 'danger')
            return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function


def can_manage_aides(f):
    """
    Gestion des aides (Président, Trésorier, Secrétaire)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Veuillez vous connecter.', 'warning')
            return redirect(url_for('login'))
        
        if current_user.role not in ['PRESIDENT', 'TRESORIER', 'SECRETAIRE']:
            flash('Accès refusé. Seul le Président, le Trésorier ou le Secrétaire peut gérer les aides.', 'danger')
            return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function


def can_manage_communications(f):
    """
    Gestion des communications (Communication, Président, Secrétaire)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Veuillez vous connecter.', 'warning')
            return redirect(url_for('login'))
        
        if current_user.role not in ['COMMUNICATION', 'PRESIDENT', 'SECRETAIRE']:
            flash('Accès refusé. Seul le responsable Communication, le Président ou le Secrétaire peut gérer les communications.', 'danger')
            return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function


def can_view_reports(f):
    """
    Visualisation des rapports (Tous les rôles sauf membre simple)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Veuillez vous connecter.', 'warning')
            return redirect(url_for('login'))
        
        if current_user.role == 'MEMBRE':
            flash('Accès refusé. Les rapports sont réservés aux membres du bureau.', 'danger')
            return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function


def can_generate_reports(f):
    """
    Génération de rapports (Président, Secrétaire, Trésorier)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Veuillez vous connecter.', 'warning')
            return redirect(url_for('login'))
        
        if current_user.role not in ['PRESIDENT', 'SECRETAIRE', 'TRESORIER']:
            flash('Accès refusé. Seul le Président, le Secrétaire ou le Trésorier peut générer des rapports.', 'danger')
            return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function


def can_view_audit_logs(f):
    """
    Visualisation des logs d'audit (Président, Secrétaire)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Veuillez vous connecter.', 'warning')
            return redirect(url_for('login'))
        
        if current_user.role not in ['PRESIDENT', 'SECRETAIRE']:
            flash('Accès refusé. Seul le Président ou le Secrétaire peut consulter les logs d\'audit.', 'danger')
            return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function


# ============================================================
# DÉCORATEURS POUR LES PAGES PUBLIQUES
# ============================================================

def public_only(f):
    """
    Redirige les utilisateurs connectés vers le dashboard
    Pour les pages comme login, register, index
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

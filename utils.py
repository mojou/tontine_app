import os
import uuid
import re
import random
import csv
from datetime import datetime, timedelta, date
from decimal import Decimal, ROUND_HALF_UP
from io import StringIO
from flask import current_app, request, has_request_context, Response
from werkzeug.utils import secure_filename

# Importation centralisée de SQLAlchemy et des modèles
from extensions import db 
from models import (
    Member, Loan, Transaction, AuditLog, 
    ContributionPlanning, TontineCycleDetail, CycleBeneficiary
)

# ============================================================
# GESTION DES FICHIERS
# ============================================================

def save_uploaded_file(file, upload_folder):
    """Sauvegarde un fichier uploadé et retourne le nom du fichier"""
    if not file or not hasattr(file, 'filename') or file.filename == '':
        return None
    
    # Vérifier l'extension
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
    
    if file_ext not in allowed_extensions:
        return None
    
    # Sécuriser le nom du fichier et générer un ID unique
    filename = secure_filename(file.filename)
    unique_filename = f"{uuid.uuid4().hex}_{filename}"
    
    # Créer le dossier si nécessaire
    os.makedirs(upload_folder, exist_ok=True)
    
    # Sauvegarder le fichier
    file_path = os.path.join(upload_folder, unique_filename)
    file.save(file_path)
    
    return unique_filename


# ============================================================
# CALCULS FINANCIERS
# ============================================================

def calculate_loan_interest(amount, rate=5.0):
    """Calcule les intérêts d'un prêt (par défaut 5%)"""
    try:
        amount_decimal = Decimal(str(amount))
        rate_decimal = Decimal(str(rate)) / Decimal('100')
        interest = (amount_decimal * rate_decimal).quantize(Decimal('0'), rounding=ROUND_HALF_UP)
        return float(interest)
    except Exception:
        return 0.0


def calculate_early_repayment_penalty(remaining_balance, penalty_rate=0.31):
    """Calcule la pénalité pour remboursement anticipé (31% par défaut)"""
    try:
        balance_decimal = Decimal(str(remaining_balance))
        penalty = (balance_decimal * Decimal(str(penalty_rate))).quantize(Decimal('0'), rounding=ROUND_HALF_UP)
        return float(penalty)
    except Exception:
        return 0.0


def calculate_penalty(loan, penalty_per_day=500, max_percent=0.5):
    """Calcule la pénalité pour un prêt en retard (Sécurisé en Decimal)"""
    if loan.status == 'COMPLETED':
        return 0
    
    today = date.today()
    if today <= loan.end_date:
        return 0
    
    # Calcul des jours de retard
    days_overdue = (today - loan.end_date).days
    penalty = Decimal(str(days_overdue * penalty_per_day))
    
    # Plafonner la pénalité à max_percent du montant restant en Decimal
    total_amt = Decimal(str(loan.total_amount or 0))
    amt_paid = Decimal(str(loan.amount_paid or 0))
    remaining = total_amt - amt_paid
    
    max_penalty = remaining * Decimal(str(max_percent))
    penalty = min(penalty, max_penalty)
    
    return float(penalty.quantize(Decimal('0'), rounding=ROUND_HALF_UP))


def apply_penalty_if_overdue(loan):
    """Applique la pénalité si le prêt est en retard"""
    if loan.status == 'COMPLETED':
        return 0
    
    if hasattr(loan, 'penalty_applied') and loan.penalty_applied and loan.penalty_amount > 0:
        return float(loan.penalty_amount)
    
    today = date.today()
    if today > loan.end_date:
        penalty = calculate_penalty(loan)
        if penalty > 0:
            loan.penalty_amount = Decimal(str(penalty))
            loan.penalty_applied = True
            return penalty
    
    return 0


def check_and_apply_all_penalties():
    """Vérifie tous les prêts actifs et applique les pénalités si nécessaire"""
    active_loans = Loan.query.filter(Loan.status == 'ACTIF').all()
    penalties_applied = []
    
    for loan in active_loans:
        if date.today() > loan.end_date:
            penalty = apply_penalty_if_overdue(loan)
            if penalty > 0:
                penalties_applied.append({
                    'loan_id': loan.id,
                    'member': getattr(loan, 'member_name', f"Membre #{loan.member_id}"),
                    'penalty': penalty
                })
    
    if penalties_applied:
        db.session.commit()
    
    return penalties_applied


# ============================================================
# AUDIT ET LOGS
# ============================================================

def get_client_ip():
    """Récupère l'adresse IP du client de manière sécurisée"""
    if has_request_context():
        if request.headers.get('X-Forwarded-For'):
            return request.headers.get('X-Forwarded-For').split(',')[0].strip()
        return request.remote_addr or 'unknown'
    return 'unknown'


def log_activity(user_id, user_role, action, ip_address=None):
    """Enregistre une activité dans les logs d'audit sans bloquer la session parente"""
    try:
        if ip_address is None:
            ip_address = get_client_ip()
        
        log = AuditLog(
            user_id=user_id,
            user_role=user_role,
            action=action,
            ip_address=ip_address,
            status='SUCCESS'
        )
        db.session.add(log)
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        print(f"Erreur d'écriture de l'Audit Log: {e}")
        return False


# ============================================================
# VALIDATIONS & NETTOYAGE
# ============================================================

def validate_phone_number(phone):
    """Valide un numéro de téléphone (8 à 15 chiffres)"""
    if not phone:
        return False
    clean_phone = re.sub(r'[\s\-\(\)\+]', '', str(phone))
    return bool(re.match(r'^[0-9]{8,15}$', clean_phone))


def validate_email(email):
    """Valide un email avec regex"""
    if not email:
        return False
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def sanitize_input(text):
    """Nettoie sommairement les entrées utilisateur contre les balises HTML"""
    if not text:
        return ""
    return re.sub(r'[<>]', '', str(text))


# ============================================================
# FORMATAGE
# ============================================================

def format_currency(amount):
    """Formate un montant en monnaie locale (FCFA)"""
    try:
        if amount is None:
            return "0 FCFA"
        if isinstance(amount, Decimal):
            amount = float(amount)
        return f"{amount:,.0f} FCFA".replace(",", " ")
    except Exception:
        return "0 FCFA"


def format_date(date_obj):
    """Formate une date en français"""
    if not date_obj:
        return ""
    return date_obj.strftime('%d/%m/%Y')


def format_datetime(datetime_obj):
    """Formate une date/heure en français"""
    if not datetime_obj:
        return ""
    return datetime_obj.strftime('%d/%m/%Y à %H:%M')


# ============================================================
# CALCULS DE DATES
# ============================================================

def calculate_days_remaining(end_date):
    """Calcule le nombre de jours restants jusqu'à une date"""
    try:
        today = date.today()
        delta = end_date - today
        return max(delta.days, 0)
    except Exception:
        return 0


def is_overdue(end_date):
    """Vérifie si une date est dépassée"""
    try:
        return date.today() > end_date
    except Exception:
        return False


def get_week_number(date_obj):
    """Retourne le numéro de semaine ISO"""
    if not date_obj:
        return 0
    return date_obj.isocalendar()[1]


def get_fortnight_number(date_obj):
    """Retourne le numéro de quinzaine (1 ou 2)"""
    if not date_obj:
        return 1
    return 1 if date_obj.day <= 15 else 2


def generate_unique_id(prefix=""):
    """Génère un identifiant unique compact"""
    return f"{prefix}{uuid.uuid4().hex[:8].upper()}"


# ============================================================
# PAGINATION GENÉRIQUE
# ============================================================

def paginate(query, page, per_page):
    """Fonction de pagination générique pour requêtes brutes"""
    try:
        total = query.count()
        items = query.limit(per_page).offset((page - 1) * per_page).all()
        total_pages = (total + per_page - 1) // per_page if per_page > 0 else 1
        
        return {
            'items': items, 'current_page': page, 'total_pages': total_pages,
            'total_items': total, 'has_prev': page > 1, 'has_next': page < total_pages,
            'prev_num': page - 1 if page > 1 else None, 'next_num': page + 1 if page < total_pages else None,
            'per_page': per_page
        }
    except Exception:
        return {
            'items': [], 'current_page': 1, 'total_pages': 1, 'total_items': 0,
            'has_prev': False, 'has_next': False, 'prev_num': None, 'next_num': None, 'per_page': per_page
        }


def get_pagination_data(pagination):
    """Convertit l'objet pagination natif SQLAlchemy pour les templates Jinja Pre-requisite"""
    if not pagination:
        return {
            'items': [], 'page': 1, 'pages': 1, 'total': 0, 'has_prev': False,
            'has_next': False, 'prev_num': None, 'next_num': None, 'per_page': 10
        }
    return {
        'items': pagination.items, 'page': pagination.page, 'pages': pagination.pages,
        'total': pagination.total, 'has_prev': pagination.has_prev, 'has_next': pagination.has_next,
        'prev_num': pagination.prev_num, 'next_num': pagination.next_num, 'per_page': pagination.per_page
    }


# ============================================================
# EXPORTATIONS
# ============================================================

def export_to_csv(data, headers, filename):
    """Exporte des données structurées au format CSV"""
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in data:
        writer.writerow(row)
    
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment;filename={filename}'}
    )


# ============================================================
# VÉRIFICATIONS CONDITIONS ET DROITS
# ============================================================

def check_member_can_request_loan(member_id):
    """Vérifie si un membre est éligible pour solliciter un emprunt"""
    member = db.session.get(Member, member_id)
    if not member:
        return False, "Membre non trouvé."
    
    if member.status != 'ACTIF' or not member.is_active:
        return False, "Le membre n'est pas actif."
    
    fond_caisse_paid = Transaction.query.filter(
        Transaction.member_id == member_id,
        Transaction.type == 'FONDS_CAISSE'
    ).first()
    
    if not fond_caisse_paid:
        return False, "Vous devez d'abord payer votre fonds de caisse (5 000 FCFA) pour pouvoir demander un prêt."
    
    active_loan = Loan.query.filter(
        Loan.member_id == member_id,
        Loan.status.in_(['PENDING', 'ACTIF'])
    ).first()
    
    if active_loan:
        return False, "Vous avez déjà un prêt en cours ou en attente de validation."
    
    if getattr(member, 'tontine_status', None) == 'ROUGE':
        return False, "Membre en statut ROUGE (irrégularités de paiement). Prêt refusé."
    
    return True, "OK"


def check_member_can_receive_benefit(member_id, cycle_id=None):
    """Vérifie si un membre peut toucher le pot de la tontine (la main)"""
    member = db.session.get(Member, member_id)
    if not member:
        return False, "Membre non trouvé.", 0
    
    if member.status != 'ACTIF' or not member.is_active:
        return False, "Le membre n'est pas actif.", 0
    
    if not member.position_in_group:
        return False, "Position dans le groupe non définie.", 0
    
    if cycle_id:
        already_benefited = CycleBeneficiary.query.filter_by(
            cycle_id=cycle_id, member_id=member_id
        ).first()
        if already_benefited:
            return False, "Ce membre a déjà bénéficié dans ce cycle.", 0
    
    cycle = db.session.get(TontineCycleDetail, cycle_id) if cycle_id else None
    if cycle:
        net_amount = member.calculate_net_benefit(cycle.total_amount)
    else:
        net_amount = Decimal('0.00')
    
    if net_amount <= 0:
        return False, "Le montant net à bénéficier est insuffisant ou nul (absorbé par des dettes/sanctions).", 0
    
    return True, "OK", float(net_amount)


def check_cotisation_eligibility(member_id, cotisation_type, date_obj=None):
    """Vérifie si le créneau de cotisation d'un membre est libre ou déjà payé"""
    if date_obj is None:
        date_obj = date.today()
    
    member = db.session.get(Member, member_id)
    if not member:
        return False, "Membre non trouvé."
    
    if cotisation_type == 'PRESENCE':
        week_num = date_obj.isocalendar()[1]
        year = date_obj.year
        
        existing = Transaction.query.filter(
            Transaction.member_id == member_id,
            Transaction.type == 'PRESENCE',
            Transaction.week_number == week_num,
            Transaction.year == year
        ).first()
        
        if existing:
            return False, f"Cotisation présence déjà effectuée pour la semaine {week_num} de {year}."
        return True, "OK"
    
    elif cotisation_type == 'TONTINE':
        month = date_obj.month
        year = date_obj.year
        fortnight = 1 if date_obj.day <= 15 else 2
        
        count = Transaction.query.filter(
            Transaction.member_id == member_id,
            Transaction.type == 'TONTINE',
            Transaction.year == year,
            Transaction.month == month
        ).count()
        
        if count >= 2:
            return False, f"Limite de 2 cotisations tontine par mois atteinte pour {month}/{year}."
        
        existing = Transaction.query.filter(
            Transaction.member_id == member_id,
            Transaction.type == 'TONTINE',
            Transaction.year == year,
            Transaction.month == month,
            Transaction.fortnight_number == fortnight
        ).first()
        
        if existing:
            return False, f"Cotisation tontine déjà validée pour la quinzaine {fortnight} de {month}/{year}."
        return True, "OK"
    
    return False, "Type de cotisation inconnu."


# ============================================================
# STATISTIQUES ET RAPPORTS
# ============================================================

def calculate_caisse_balance():
    """📈 Calcule le solde net en caisse"""
    entrees = db.session.query(db.func.sum(Transaction.amount)).filter(
        Transaction.type.in_(['TONTINE', 'PRESENCE', 'SANCTION', 'REMBOURSEMENT', 'FONDS_CAISSE'])
    ).scalar() or Decimal('0.00')
    
    sorties = db.session.query(db.func.sum(Transaction.amount)).filter(
        Transaction.type.in_(['SORTIE_LOAN', 'AIDE', 'BENEFICE_TONTINE'])
    ).scalar() or Decimal('0.00')
    
    return float(entrees - sorties)


def get_member_summary(member_id):
    """Retourne la fiche synthétique financière d'un membre"""
    member = db.session.get(Member, member_id)
    if not member:
        return None
    
    return {
        'total_cotisations': float((member.total_savings or 0) + (member.total_presence_paid or 0)),
        'total_tontine': float(member.total_savings or 0),
        'total_presence': float(member.total_presence_paid or 0),
        'total_sanctions': float(member.total_sanctions_pending or 0),
        'active_loans': member.loans.filter_by(status='ACTIF').count() if hasattr(member, 'loans') else 0,
        'total_loans_amount': sum(float(l.amount or 0) for l in member.loans.filter_by(status='ACTIF').all()) if hasattr(member, 'loans') else 0,
        'credit_balance': float(member.credit_balance or 0),
        'debit_balance': float(member.debit_balance or 0),
        'participation_score': getattr(member, 'participation_score', 100),
        'tontine_status': getattr(member, 'tontine_status', 'VERT')
    }


# ============================================================
# ACTIVATIONS ET INSCRIPTIONS
# ============================================================

def get_pending_members():
    return Member.query.filter_by(status='PENDING', is_active=False).all()

def get_pending_members_count():
    return Member.query.filter_by(status='PENDING', is_active=False).count()


def activate_member(member_id, group_type, position_in_group, chosen_tontine_amount):
    """Valide l'adhésion d'un nouveau membre et lui attribue ses paramètres fondamentaux"""
    member = db.session.get(Member, member_id)
    if not member:
        return False, "Membre non trouvé"
    
    # Validation de sécurité sur le montant saisi
    try:
        amount_decimal = Decimal(str(chosen_tontine_amount))
    except (ValueError, TypeError):
        return False, "Le montant de tontine choisi est invalide."

    # Empêcher les doublons sur les numéros de chaises/positions actives
    existing = Member.query.filter_by(
        group_type=group_type,
        position_in_group=position_in_group,
        is_active=True
    ).first()
    
    if existing:
        return False, f"La position {position_in_group} est déjà prise par un membre actif dans le groupe de {group_type}."
    
    member.group_type = group_type
    member.position_in_group = position_in_group
    member.chosen_tontine_amount = amount_decimal
    member.status = 'ACTIF'
    member.is_active = True
    
    if hasattr(member, 'user_account') and member.user_account:
        member.user_account.is_active = True
        
    db.session.commit()
    return True, "Membre activé avec succès"


# ============================================================
# AUTOMATISATION DES PLANS DE FLUX (PLANNING DE CAISSE)
# ============================================================

PRESENCE_AMOUNT = 1050

def generate_weekly_presence_contributions(presence_amount=None):
    """Génère les fiches d'appels de présence prévisionnelles pour la semaine courante (Cron)"""
    if presence_amount is None:
        presence_amount = PRESENCE_AMOUNT
        
    today = date.today()
    week_num = today.isocalendar()[1]
    year = today.year
    
    active_members = Member.query.filter_by(is_active=True, status='ACTIF').all()
    created_count = 0
    
    for member in active_members:
        existing = ContributionPlanning.query.filter_by(
            member_id=member.id, year=year, week_number=week_num, contribution_type='PRESENCE'
        ).first()
        
        if not existing:
            planning = ContributionPlanning(
                member_id=member.id, year=year, month=today.month, week_number=week_num,
                contribution_type='PRESENCE', expected_amount=Decimal(str(presence_amount)),
                expected_date=today, is_paid=False
            )
            db.session.add(planning)
            created_count += 1
            
    if created_count > 0:
        db.session.commit()
    return created_count


def generate_monthly_tontine_contributions():
    """Génère les fiches de planification tontine globales (Quinzaine 1 et 2 calendaires)"""
    today = date.today()
    year = today.year
    month = today.month
    
    active_members = Member.query.filter_by(is_active=True, status='ACTIF').all()
    created_count = 0
    
    for member in active_members:
        if member.chosen_tontine_amount:
            # 1ère Quinzaine
            first_date = date(year, month, 1)
            first_exists = ContributionPlanning.query.filter_by(
                member_id=member.id, year=year, month=month,
                fortnight_number=1, contribution_type='TONTINE'
            ).first()
            
            if not first_exists:
                planning1 = ContributionPlanning(
                    member_id=member.id, year=year, month=month, fortnight_number=1,
                    contribution_type='TONTINE', expected_amount=member.chosen_tontine_amount,
                    expected_date=first_date, is_paid=False
                )
                db.session.add(planning1)
                created_count += 1
            
            # 2ème Quinzaine (Sécurisée contre février)
            try:
                second_date = date(year, month, 16)
            except ValueError:
                second_date = date(year, month, 15)
                
            second_exists = ContributionPlanning.query.filter_by(
                member_id=member.id, year=year, month=month,
                fortnight_number=2, contribution_type='TONTINE'
            ).first()
            
            if not second_exists:
                planning2 = ContributionPlanning(
                    member_id=member.id, year=year, month=month, fortnight_number=2,
                    contribution_type='TONTINE', expected_amount=member.chosen_tontine_amount,
                    expected_date=second_date, is_paid=False
                )
                db.session.add(planning2)
                created_count += 1
                
    if created_count > 0:
        db.session.commit()
    return created_count


def generate_cycle_contributions(cycle_id, ordered_members_ids, amount_per_member):
    """
    🟢 INCLUSION : Planifie de façon séquentielle les cotisations attendues pour un cycle de tontine.
    Appelé directement par la route de création de cycle (chaque étape est espacée de 14 jours).
    ATTENTION : Pas de db.session.commit() ici pour permettre un pilotage transactionnel par la route.
    """
    start_date = date.today()
    amount_decimal = Decimal(str(amount_per_member))
    
    for index, member_id in enumerate(ordered_members_ids):
        # 1 tirage / étape toutes les 2 semaines (14 jours d'intervalle cumulatif)
        expected_date = start_date + timedelta(days=index * 14)
        
        planning = ContributionPlanning(
            member_id=member_id,
            year=expected_date.year,
            month=expected_date.month,
            week_number=expected_date.isocalendar()[1],
            fortnight_number=(1 if expected_date.day <= 15 else 2),
            contribution_type='TONTINE',
            expected_amount=amount_decimal,
            expected_date=expected_date,
            is_paid=False,
            # Supposons que votre modèle intègre une liaison optionnelle au cycle de tontine :
            # cycle_id=cycle_id 
        )
        db.session.add(planning)


# ============================================================
# NOTIFICATIONS ET EMAILS (STUBS ACCESSIBLES)
# ============================================================

def send_activation_email(member):
    print(f"📧 Notification mail d'activation expédiée à {member.email}")
    return True

def send_welcome_email(member):
    print(f"📧 Notification mail de bienvenue expédiée à {member.email}")
    return True


# ============================================================
# HELPERS GÉNÉRAUX D'APPOINT
# ============================================================

def get_current_date():
    return date.today()

def get_current_datetime():
    return datetime.now()

def decimal_to_float(decimal_value):
    return float(decimal_value) if decimal_value is not None else 0.0

def float_to_decimal(float_value, precision=2):
    if float_value is None:
        return Decimal('0.00')
    return Decimal(str(round(float_value, precision)))

def safe_division(numerator, denominator, default=0):
    try:
        return numerator / denominator if denominator != 0 else default
    except Exception:
        return default
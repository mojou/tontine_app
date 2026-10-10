# ============================================================
# APPLICATION DE GESTION DE TONTINE - VERSION CORRIGÉE
# ============================================================

import os
from datetime import datetime, timedelta, date
from decimal import Decimal
import random
import io

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort, make_response, send_file, g, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from flask_wtf.csrf import CSRFProtect, generate_csrf
from flask_migrate import Migrate
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

# Importation des modules personnalisés
from config import Config
from forms import (
    LoginForm, MemberForm, TransactionForm, LoanRequestForm, LoanRepaymentForm,
    SanctionForm, AnnouncementForm, ProfileEditForm, TontineCycleForm, MemberEditForm,
    AideForm, AideApprovalForm, MeetingAttendanceForm, TontineBenefitForm, ReportForm,
    MemberFilterForm, TransactionFilterForm, PresenceTransactionForm, TontineTransactionForm,
    LoanApprovalForm, MemberRegistrationForm
)
from decorators import role_required, president_required, member_owner_required
from permissions import get_user_menu, has_permission
from utils import save_uploaded_file, log_activity, calculate_loan_interest, calculate_early_repayment_penalty, get_pagination_data

# Configuration des chemins
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# INITIALISATION DE L'APPLICATION
# ============================================================

app = Flask(__name__,
            template_folder=os.path.join(BASE_DIR, 'app', 'templates'),
            static_folder=os.path.join(BASE_DIR, 'app', 'static'))

app.config.from_object(Config)

# En ligne (PythonAnywhere…), les visites passent par un serveur intermédiaire : on lit la vraie
# adresse IP (limitation des tentatives de connexion) et le https (liens envoyés par e-mail).
if os.environ.get('TRUST_PROXY', '').lower() in ('1', 'true', 'yes'):
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# Initialisation des extensions
csrf = CSRFProtect()
csrf.init_app(app)

from models import db
from extensions import utcnow
db.init_app(app)

migrate = Migrate(app, db)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Veuillez vous connecter pour accéder à cette page.'

# ============================================================
# CONTEXT PROCESSOR
# ============================================================
# Dans app.py, après la création de l'app et avant les routes

@app.context_processor
def utility_processor():
    # Importation des fonctions depuis permissions.py
    from permissions import get_user_menu, has_permission, is_admin, is_bureau_member
    
    def get_current_year():
        return datetime.now().year

    def get_current_date_str():
        return datetime.now().strftime('%Y-%m-%d')

    return dict(
        # Fonctions de permissions
        get_user_menu=get_user_menu,
        has_permission=has_permission,
        is_admin=is_admin,
        is_bureau_member=is_bureau_member,
        
        # Tontine courante (None pour le super-admin et les visiteurs du portail)
        current_tontine=g.get('tontine'),

        # Identité de la plateforme
        app_name=app.config['APP_NAME'],
        app_name_parts=app.config['APP_NAME_PARTS'],
        app_tagline=app.config['APP_TAGLINE'],
        allow_signup=app.config['ALLOW_PUBLIC_SIGNUP'],
        transaction_types=finance.TRANSACTION_TYPES,
        manual_transaction_types=finance.MANUAL_TYPES,
        type_hints=finance.TYPE_HINTS,
        outflow_types=finance.OUTFLOW_TYPES,
        payment_modes=finance.PAYMENT_MODES,
        timedelta=timedelta,
        pending_aval_count=_pending_aval_count(),
        pending_reset_count=_pending_reset_count(),

        # Utilitaires
        now=datetime.now(),
        current_year=get_current_year(),
        current_date=get_current_date_str(),
        csrf_token=generate_csrf
    )
# ============================================================
# CHARGEMENT DES MODÈLES
# ============================================================

from models import (
    User, Member, Transaction, Loan, TontineCycle, TontinePosition,
    Sanction, Announcement, AuditLog, AgendaItem, MeetingBeneficiary,
    Aide, TontineCycleDetail, CycleBeneficiary, MeetingAttendanceDetail,
    ContributionPlanning, CycleReport, CaisseBalance,
    Poll, PollOption, PollVote, TontineDraw, TontineDrawResult, GalleryPhoto, Tontine,
    ContributionType, LoanGuarantor, CycleParticipant, Seance, ExerciseClosure, PasswordResetRequest, BillingPayment,
    LoginAttempt, AidType
)
import finance
import report_export
import billing
import re
import time

_THOUSANDS_COMMA = re.compile(r'(?<=\d),(?=\d{3}\b)')


def french_numbers(text):
    """« 60,000 FCFA » -> « 60 000 FCFA » (séparateur de milliers français)"""
    return _THOUSANDS_COMMA.sub(' ', str(text))


_flask_flash = flash


def flash(message, category='message'):   # noqa: F811 - remplace flask.flash dans ce module
    _flask_flash(french_numbers(message), category)

import secrets
import uuid
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from tenancy import set_current_tenant, tenant_bypass

# ============================================================
# USER LOADER
# ============================================================

@login_manager.user_loader
def load_user(user_id):
    # Chargé avant que la tontine courante soit connue : pas de filtre ici
    with tenant_bypass():
        return db.session.get(User, int(user_id))


# ============================================================
# MULTI-TENANT : TONTINE COURANTE
# ============================================================

# Pages accessibles au super-admin (qui n'appartient à aucune tontine)
SUPERADMIN_ENDPOINTS = {'superadmin', 'superadmin_add_tontine', 'superadmin_toggle_tontine',
                        'superadmin_billing_payment', 'superadmin_billing_offer', 'superadmin_delete_tontine',
                        'logout', 'static', 'index', 'tontine_home', 'login', 'signup', 'guide',
                        'superadmin_reset_president', 'reset_password'}
# Pages publiques qui fixent elles-mêmes la tontine (via l'URL ou le formulaire)
PUBLIC_ENDPOINTS = {'static', 'index', 'tontine_home', 'login', 'register', 'signup', 'forgot_password', 'reset_password'}


@app.before_request
def resolve_current_tenant():
    g.tenant_id = None
    g.tontine = None
    if not current_user.is_authenticated:
        return None

    if current_user.is_superadmin:
        if request.endpoint not in SUPERADMIN_ENDPOINTS:
            return redirect(url_for('superadmin'))
        return None

    tontine = db.session.get(Tontine, current_user.tontine_id) if current_user.tontine_id else None
    if not tontine or not tontine.is_active:
        logout_user()
        flash("Votre tontine est désactivée. Contactez l'administrateur de la plateforme.", 'danger')
        return redirect(url_for('index'))
    set_current_tenant(tontine.id)
    g.tontine = tontine
    g.billing = tontine_billing(tontine)
    # Abonnement impayé après le délai de grâce : lecture seule (tout se consulte, rien ne s'enregistre)
    if (g.billing['state'] == billing.READ_ONLY and request.method == 'POST'
            and request.endpoint not in BILLING_ALLOWED_ENDPOINTS):
        flash("Abonnement impayé : la tontine est en lecture seule. Réglez l'abonnement pour enregistrer à nouveau.", 'danger')
        return redirect(url_for('abonnement') if current_user.role in BILLING_MANAGERS else url_for('dashboard'))
    return None


BILLING_MANAGERS = ['PRESIDENT', 'TRESORIER']
# Toujours permis en lecture seule : payer, se déconnecter, changer son mot de passe
BILLING_ALLOWED_ENDPOINTS = {'abonnement', 'logout', 'login', 'change_password', 'profile'}


def active_members_count(tontine_id):
    with tenant_bypass():
        return Member.query.filter_by(tontine_id=tontine_id, is_active=True, status='ACTIF').count()


def tontine_billing(tontine):
    """Situation d'abonnement ; mémorise le premier jour au-delà de 10 membres (départ du délai de grâce)"""
    members = active_members_count(tontine.id)
    if billing.monthly_price(members) and not tontine.billing_started_on:
        tontine.billing_started_on = date.today()
        db.session.commit()
    elif not billing.monthly_price(members) and tontine.billing_started_on:
        tontine.billing_started_on = None   # repassée à 10 membres ou moins : nouveau délai si elle grandit
        db.session.commit()
    return billing.status(tontine, members)


def current_tontine():
    return g.get('tontine')


def email_taken(email, exclude_member_id=None):
    """Email déjà utilisé par un autre membre ou un autre compte de la tontine courante ?"""
    email = (email or '').strip().lower()
    if not email:
        return False
    members = Member.query.filter(db.func.lower(Member.email) == email)
    users = User.query.filter(User.tontine_id == g.get('tenant_id'), db.func.lower(User.email) == email)
    if exclude_member_id:
        members = members.filter(Member.id != exclude_member_id)
        users = users.filter(db.or_(User.member_id.is_(None), User.member_id != exclude_member_id))
    return members.first() is not None or users.first() is not None


def _pending_aval_count():
    """Nombre de demandes d'aval qui attendent la réponse de l'utilisateur connecté"""
    if not g.get('tenant_id') or not current_user.is_authenticated or not current_user.member_id:
        return 0
    return LoanGuarantor.query.filter_by(member_id=current_user.member_id, status='EN_ATTENTE').count()


def _pending_reset_count():
    """Demandes de mot de passe oublié à traiter (président / secrétaire)"""
    if not g.get('tenant_id') or not current_user.is_authenticated or current_user.role not in ('PRESIDENT', 'SECRETAIRE'):
        return 0
    return PasswordResetRequest.query.filter_by(status='EN_ATTENTE').count()


def ensure_contribution_types(tontine):
    """Crée les rubriques de cotisation par défaut si la tontine n'en a aucune"""
    if ContributionType.query.filter_by(tontine_id=tontine.id).count():
        return
    for order, data in enumerate(finance.default_contribution_types(tontine)):
        db.session.add(ContributionType(tontine_id=tontine.id, display_order=order, **data))
    db.session.commit()


def save_tenant_upload(file):
    """Enregistre un fichier dans le dossier de la tontine courante.
    Retourne un chemin relatif à static/images (ex. '3/abc_photo.jpg') ou None."""
    tid = g.get('tenant_id')
    if not tid:
        return None
    filename = save_uploaded_file(file, os.path.join(app.config['UPLOAD_FOLDER'], str(tid)))
    return f"{tid}/{filename}" if filename else None


def safe_next_url(target):
    """Évite les redirections ouvertes après connexion."""
    if target and target.startswith('/') and not target.startswith('//') and '\\' not in target:
        return target
    return None

# ============================================================
# FONCTIONS UTILITAIRES
# ============================================================

def set_member_choices(form):
    """Configure les choix de membres pour les formulaires"""
    members = Member.query.filter_by(is_active=True, status='ACTIF').all()
    choices = [(0, '-- Aucun --')] + [(m.id, m.full_name) for m in members]
    
    if hasattr(form, 'beneficiary_member_id'):
        form.beneficiary_member_id.choices = choices
    if hasattr(form, 'loan_member_id'):
        form.loan_member_id.choices = choices
    if hasattr(form, 'aid_member_id'):
        form.aid_member_id.choices = choices
    if hasattr(form, 'sanction_member_id'):
        form.sanction_member_id.choices = choices
    
    return members

def generate_cycle_contributions(cycle_id, ordered_member_ids, amount_per_member):
    """Génère automatiquement les échéances planifiées pour le cycle de tontine"""
    cycle = db.session.get(TontineCycleDetail, cycle_id)
    if not cycle:
        return False

    base_date = cycle.start_date
    
    for index, member_id in enumerate(ordered_member_ids):
        days_to_add = index * 14
        expected_draw_date = base_date + timedelta(days=days_to_add)
        
        contribution = ContributionPlanning(
            member_id=member_id,
            year=expected_draw_date.year,
            month=expected_draw_date.month,
            fortnight_number=1 if expected_draw_date.day <= 15 else 2,
            contribution_type='TONTINE',
            expected_amount=amount_per_member,
            expected_date=expected_draw_date,
            is_paid=False
        )
        db.session.add(contribution)
    
    db.session.commit()
    return True

# ============================================================
# CRÉATION DES TABLES ET DONNÉES INITIALES
# ============================================================

with app.app_context():
    upload_folder = app.config.get('UPLOAD_FOLDER', os.path.join(BASE_DIR, 'app', 'static', 'images'))
    os.makedirs(upload_folder, exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, 'reports'), exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, 'logs'), exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, 'instance'), exist_ok=True)
    
    # Base existante pas encore migrée en multi-tenant : on refuse de démarrer
    # plutôt que de mélanger les données de plusieurs tontines.
    from sqlalchemy import inspect as sa_inspect
    _inspector = sa_inspect(db.engine)
    _member_columns = ([c['name'] for c in _inspector.get_columns('members')]
                       if 'members' in _inspector.get_table_names() else None)
    if _member_columns is not None and 'tontine_id' not in _member_columns:
        raise SystemExit(
            "\n[ERREUR] La base n'est pas encore au format multi-tenant.\n"
            "Lancez d'abord :  python setup_multitenant.py\n"
        )

    db.create_all()
    from schema_upgrade import add_missing_columns
    add_missing_columns(db.engine, db.metadata)

    # Reprise des anciens cycles (groupe = membres ayant le même group_type) en participations
    for _cycle in TontineCycleDetail.query.all():
        if _cycle.participants:
            continue
        _served = {b.member_id: b for b in _cycle.benefits.order_by(CycleBeneficiary.position).all()}
        _ids = list(_served)
        for _m in Member.query.filter_by(tontine_id=_cycle.tontine_id, group_type=_cycle.group_type).all():
            if _m.id not in _ids:
                _ids.append(_m.id)
        _taken = {b.position for b in _served.values()}
        for _mid in _ids:
            _b = _served.get(_mid)
            _member = db.session.get(Member, _mid)
            _pos = _b.position if _b else _member.position_in_group
            if not _b and _pos in _taken:
                _pos = None  # position en conflit : sera fixée par un nouveau tirage
            _p = CycleParticipant(tontine_id=_cycle.tontine_id, cycle_id=_cycle.id, member_id=_mid, hand_number=1,
                                  position=_pos, served=bool(_b), served_at=_b.benefit_date if _b else None)
            db.session.add(_p)
            db.session.flush()
            if _b:
                _b.participant_id = _p.id
        if _ids:
            print(f"[INFO] Cycle #{_cycle.cycle_number} (tontine {_cycle.tontine_id}) : {len(_ids)} participations reprises.")
    db.session.commit()

    # Plus de comptes par défaut à mot de passe connu : le super-admin est créé
    # par setup_multitenant.py, puis il crée chaque tontine et son président.
    if not User.query.filter_by(role='SUPERADMIN').first():
        print("[INFO] Aucun super-admin : lancez  python setup_multitenant.py  pour en créer un.")

# ============================================================
# ROUTES PRINCIPALES
# ============================================================
# ============================================================
# AUTHENTIFICATION ET DASHBOARD
# ============================================================

PLATFORM_LOGIN = '__plateforme__'


def _public_tontines():
    """Tontines actives et confirmées (une inscription en attente de confirmation reste invisible)"""
    return Tontine.query.filter(Tontine.is_active == True, Tontine.pending_confirmation.isnot(True))  # noqa: E712


def _active_tontines():
    return _public_tontines().order_by(Tontine.name).all()


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    # L'inscription se fait toujours auprès d'une tontine précise : /register?t=<slug>
    slug = request.args.get('t', '')
    tontine = _public_tontines().filter_by(slug=slug).first() if slug else None
    if not tontine:
        flash('Choisissez votre tontine avant de vous inscrire.', 'warning')
        return redirect(url_for('index'))
    set_current_tenant(tontine.id)
    g.tontine = tontine

    form = MemberRegistrationForm()
    # Montants proposés = niveaux de cotisation définis par la tontine
    ensure_contribution_types(tontine)
    levels = tontine_levels()
    form.tontine_amount.choices = [('', '-- Choisissez un niveau --')] + [
        (str(int(l.amount)), f"{int(l.amount):,} FCFA · {l.frequency_display.lower()}".replace(',', ' ')) for l in levels]
    form.cotisation_type.choices = [('', '-- Sélectionnez --'), ('PRESENCE', 'Présence / épargne uniquement'),
                                    ('TONTINE', 'Tontine (je choisis un niveau de cotisation)')]
    if form.tontine_amount.data and form.tontine_amount.data not in [c[0] for c in form.tontine_amount.choices]:
        form.tontine_amount.data = ''

    if form.validate_on_submit():
        existing_member = Member.query.filter_by(email=form.email.data).first()
        if existing_member:
            flash('Cet email est déjà utilisé. Veuillez vous connecter.', 'danger')
            return redirect(url_for('login', t=tontine.slug))

        existing_user = User.query.filter_by(tontine_id=tontine.id, username=form.username.data).first()
        if existing_user:
            flash('Ce nom d\'utilisateur est déjà pris.', 'danger')
            return render_template('register.html', form=form, tontine=tontine, levels=levels)

        member = Member(
            first_name=form.first_name.data,
            last_name=form.last_name.data,
            email=form.email.data,
            phone=form.phone.data,
            address=form.address.data,
            profession=form.profession.data,
            city=form.city.data,
            registration_date=date.today(),
            status='PENDING',
            is_active=False,
            tontine_status='VERT',
            consecutive_failures=0,
            credit_balance=Decimal('0.00'),
            debit_balance=Decimal('0.00'),
            amount_to_receive=Decimal('0.00'),
            group_type=None,
            position_in_group=None,
            has_received_benefit=False,
            chosen_tontine_amount=Decimal(str(form.tontine_amount.data)) if form.cotisation_type.data == 'TONTINE' and form.tontine_amount.data else Decimal('0.00')
        )

        db.session.add(member)
        db.session.flush()

        user = User(
            tontine_id=tontine.id,
            username=form.username.data,
            email=form.email.data,
            role='MEMBRE',
            member_id=member.id,
            is_active=False
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()

        log_activity(None, 'PUBLIC', f"Nouvelle inscription: {member.full_name}", request.remote_addr)

        flash('Inscription réussie ! Votre dossier est en attente de validation.', 'success')
        return redirect(url_for('login', t=tontine.slug))

    return render_template('register.html', form=form, tontine=tontine, levels=levels)


# ---------------------------------------------------------------- limitation des tentatives
# Les échecs sont enregistrés en base (table login_attempts) : la protection
# survit aux redémarrages et fonctionne avec plusieurs processus.

MAX_FAILED_ATTEMPTS = 5          # échecs autorisés par compte et par adresse IP
MAX_FAILED_PER_IP = 30           # tous comptes confondus (robot qui essaie des identifiants)
LOCK_SECONDS = 15 * 60


def _recent_failures(key):
    """key = (scope, ip) ou (scope, ip, identifiant)"""
    since = utcnow() - timedelta(seconds=LOCK_SECONDS)
    query = LoginAttempt.query.filter(LoginAttempt.scope == key[0], LoginAttempt.ip_address == key[1],
                                      LoginAttempt.created_at >= since)
    if len(key) > 2:
        query = query.filter(LoginAttempt.identifier == key[2][:200])
    return query.count()


def _record_failure(*keys):
    """Enregistre un échec ; seules les clés complètes (scope, ip, identifiant) sont stockées,
    le décompte par IP s'en déduit."""
    for key in keys:
        if len(key) > 2:
            db.session.add(LoginAttempt(scope=key[0], ip_address=key[1][:45], identifier=key[2][:200]))
    # Purge des traces de plus d'un jour
    LoginAttempt.query.filter(LoginAttempt.created_at < utcnow() - timedelta(days=1)).delete(synchronize_session=False)
    db.session.commit()


def _clear_failures(key):
    LoginAttempt.query.filter_by(scope=key[0], ip_address=key[1], identifier=key[2][:200]).delete(synchronize_session=False)
    db.session.commit()


def is_rate_limited(scope, identifier):
    ip = request.remote_addr or '?'
    return (_recent_failures((scope, ip, identifier.lower())) >= MAX_FAILED_ATTEMPTS
            or _recent_failures((scope, ip)) >= MAX_FAILED_PER_IP)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    form = LoginForm()
    tontines = _active_tontines()
    # Tontine présélectionnée depuis sa page d'accueil (/login?t=<slug>)
    selected = request.form.get('tontine') or request.args.get('t', '')
    if not selected and len(tontines) == 1:
        selected = tontines[0].slug

    if form.validate_on_submit():
        attempt_key = ('login', request.remote_addr or '?', f"{selected}:{form.username.data}".lower())
        if is_rate_limited('login', f"{selected}:{form.username.data}"):
            app.logger.warning(f"Connexion bloquée (trop de tentatives) : {form.username.data} depuis {request.remote_addr}")
            flash('Trop de tentatives de connexion. Réessayez dans 15 minutes ou utilisez « Mot de passe oublié ».', 'danger')
            selected_tontine = next((t for t in tontines if t.slug == selected), None)
            return render_template('login.html', form=form, tontines=tontines, selected=selected,
                                   selected_tontine=selected_tontine, platform_value=PLATFORM_LOGIN), 429
        user = None
        # Chargement explicite par tontine, sans filtre automatique : sinon le critère
        # « aucune tontine » du visiteur anonyme serait propagé à user.member.
        with tenant_bypass():
            if selected == PLATFORM_LOGIN:
                user = User.query.filter_by(username=form.username.data, role='SUPERADMIN', tontine_id=None).first()
            else:
                tontine = Tontine.query.filter_by(slug=selected, is_active=True).first()
                if tontine:
                    user = User.query.filter_by(tontine_id=tontine.id, username=form.username.data).first()

        if user and user.check_password(form.password.data) and user.is_active:
            _clear_failures(attempt_key)
            if user.tontine and user.tontine.pending_confirmation:
                flash(f"Confirmez d'abord votre adresse e-mail : un lien a été envoyé à {user.email}. Sans confirmation, "
                      f"la tontine est supprimée {app.config['EMAIL_CONFIRMATION_HOURS']} h après sa création.", 'warning')
                return redirect(url_for('signup_pending', slug=user.tontine.slug))
            login_user(user, remember=form.remember.data)
            user.last_login = utcnow()
            db.session.commit()

            if user.is_superadmin:
                flash('Bienvenue dans l\'administration de la plateforme.', 'success')
                return redirect(url_for('superadmin'))

            set_current_tenant(user.tontine_id)
            name = user.member.full_name if user.member else user.username
            flash(f'Bienvenue {name} ({user.get_role_display()}) !', 'success')
            return redirect(safe_next_url(request.args.get('next')) or url_for('dashboard'))
        _record_failure(attempt_key, ('login', request.remote_addr or '?'))
        flash('Tontine, nom d\'utilisateur ou mot de passe incorrect.', 'danger')

    selected_tontine = next((t for t in tontines if t.slug == selected), None)
    return render_template('login.html', form=form, tontines=tontines, selected=selected,
                           selected_tontine=selected_tontine, platform_value=PLATFORM_LOGIN)


@app.route('/logout')
@login_required
def logout():
    tontine = current_tontine()
    logout_user()
    flash('Vous avez été déconnecté.', 'info')
    if tontine:
        return redirect(url_for('tontine_home', slug=tontine.slug))
    return redirect(url_for('index'))


@app.route('/dashboard')
@login_required
def dashboard():
    member = current_user.member
    is_bureau = current_user.is_admin()
    
    if is_bureau:
        total_members = Member.query.filter_by(is_active=True).count()
        active_members = Member.query.filter_by(status='ACTIF', is_active=True).count()
        
        entrees = db.session.query(db.func.sum(Transaction.amount)).filter(
            Transaction.type.in_(finance.INFLOW_TYPES)
        ).scalar() or 0

        sorties = db.session.query(db.func.sum(Transaction.amount)).filter(
            Transaction.type.in_(finance.OUTFLOW_TYPES)
        ).scalar() or 0
        
        loan_stats = db.session.query(
            db.func.count(Loan.id), 
            db.func.sum(Loan.total_amount - Loan.amount_paid)
        ).filter(Loan.status == 'ACTIF').first()
        
        total_active_loans = loan_stats[0] if loan_stats[0] else 0
        total_loan_amount = loan_stats[1] if loan_stats[1] else 0
        
        sanction_stats = db.session.query(db.func.count(Sanction.id), db.func.sum(Sanction.amount)).filter(
            Sanction.status == 'PENDING'
        ).first()
        pending_sanctions, total_sanctions_amount = sanction_stats if sanction_stats[0] else (0, 0)
        
        next_cycle = TontineCycleDetail.query.filter_by(status='EN_COURS').first()
        next_beneficiary = next_cycle.get_next_beneficiary() if next_cycle else None
        
        # Chaque fonds a son propre solde : la caisse générale ne se mélange pas avec
        # l'argent de la tontine (à reverser) ni avec l'épargne (qui appartient aux membres)
        balances = finance.fund_balances(dict(
            db.session.query(Transaction.type, db.func.sum(Transaction.amount)).group_by(Transaction.type).all()))
        stats = {
            'total_members': total_members,
            'active_members': active_members,
            'total_cotisations': float(entrees),
            'fonds_caisse': float(balances['CAISSE']),
            'fund_balances': [(code, finance.FUNDS[code], balances[code]) for code in finance.FUNDS
                              if code in ('CAISSE', 'TONTINE', 'EPARGNE', 'SECOURS') or balances[code]],
            'treasury': float(entrees - sorties),
            'total_active_loans': int(total_active_loans or 0),
            'total_loan_amount': float(total_loan_amount or 0),
            'pending_sanctions': int(pending_sanctions or 0),
            'total_sanctions_amount': float(total_sanctions_amount or 0),
            'next_beneficiary': next_beneficiary.full_name if next_beneficiary else None,
            'upcoming_meetings': Announcement.query.filter(
                Announcement.announcement_type == 'REUNION',
                Announcement.event_date >= date.today()
            ).order_by(Announcement.event_date).limit(5).all()
        }
    else:
        my_loans_total = db.session.query(db.func.sum(Loan.total_amount - Loan.amount_paid)).filter(
            Loan.member_id == member.id, 
            Loan.status == 'ACTIF'
        ).scalar() or 0
        
        stats = {
            # Tout ce que le membre a versé (tontine, présence, fonds de caisse, épargne, secours...)
            'my_cotisations': float(member._sum_types(finance.CONTRIBUTION_CATEGORIES)),
            'my_savings': float(member.savings_balance),
            'my_presence': float(member.total_presence_paid or 0),
            'my_loans': float(my_loans_total or 0),
            'my_sanctions': float(member.total_sanctions_pending or 0),
            'my_position': ' · '.join(
                f"{p.cycle.display_name} : " + (f"tour {p.position}/{p.cycle.total_members}" if p.position else "à tirer")
                for p in CycleParticipant.query.filter_by(member_id=member.id, served=False).all()
                if p.cycle.status == 'EN_COURS'
            ) or "Aucun cycle en cours",
            'my_status': member.tontine_status,
            'my_credit': float(member.credit_balance or 0),
            'my_debit': float(member.debit_balance or 0)
        }
    
    query = Transaction.query if is_bureau else Transaction.query.filter_by(member_id=member.id)
    recent_transactions = query.order_by(Transaction.date.desc()).limit(10).all()
    
    # Guide de démarrage pour le président d'une tontine nouvellement créée
    onboarding = None
    if current_user.role == 'PRESIDENT':
        tontine = current_tontine()
        steps = [
            {'label': 'Compléter la présentation et les règles de la tontine',
             'done': bool(tontine.tagline or tontine.location), 'url': url_for('tontine_settings'),
             'icon': 'fas fa-sliders-h'},
            {'label': 'Ajouter les membres du bureau et les premiers membres',
             'done': Member.query.count() > 1, 'url': url_for('add_member'), 'icon': 'fas fa-user-plus'},
            {'label': 'Partager le lien d\'inscription aux futurs membres',
             'done': Member.query.filter_by(status='PENDING').count() > 0 or Member.query.count() > 3,
             'url': None, 'icon': 'fas fa-share-alt'},
            {'label': 'Créer le premier cycle de tontine',
             'done': TontineCycleDetail.query.count() > 0, 'url': url_for('add_tontine_cycle'), 'icon': 'fas fa-sync-alt'},
            {'label': 'Tirer au sort l\'ordre des bénéficiaires',
             'done': TontineDraw.query.count() > 0, 'url': url_for('tirages'), 'icon': 'fas fa-dice'},
            {'label': 'Ajouter des photos sur la page d\'accueil',
             'done': GalleryPhoto.query.count() > 0, 'url': url_for('gallery_admin'), 'icon': 'fas fa-images'},
        ]
        done = sum(1 for s in steps if s['done'])
        if done < len(steps):
            onboarding = {
                'steps': steps, 'done': done, 'total': len(steps),
                'signup_url': url_for('register', t=tontine.slug, _external=True),
                'home_url': url_for('tontine_home', slug=tontine.slug, _external=True),
            }

    return render_template('dashboard.html',
                           stats=stats,
                           is_bureau=is_bureau,
                           recent_transactions=recent_transactions,
                           member=member,
                           onboarding=onboarding)


# ============================================================
#index
@app.route('/')
def index():
    """Portail public : liste des tontines hébergées sur la plateforme"""
    if current_user.is_authenticated:
        return redirect(url_for('superadmin' if current_user.is_superadmin else 'dashboard'))

    tontines = _active_tontines()
    return render_template('home.html', tontines=tontines, pricing=_pricing())


def _pricing():
    """Tarifs affichés publiquement (mêmes règles que la facturation : billing.py)"""
    return {'free': billing.FREE_MEMBERS, 'price': billing.PRICE_PER_MEMBER, 'grace': billing.GRACE_DAYS,
            'examples': [(n, billing.monthly_price(n)) for n in (5, 10, 11, 15, 20, 30)]}


@app.route('/guide')
def guide():
    """Documentation illustrée (publique) : prise en main de l'application, écran par écran"""
    return render_template('guide.html', pricing=_pricing())


@app.route('/t/<slug>')
def tontine_home(slug):
    """Page d'accueil publique d'une tontine"""
    if current_user.is_authenticated and not current_user.is_superadmin:
        return redirect(url_for('dashboard'))

    tontine = _public_tontines().filter_by(slug=slug).first_or_404()
    set_current_tenant(tontine.id)
    g.tontine = tontine

    # Statistiques pour la page d'accueil (filtrées sur cette tontine)
    total_members = Member.query.filter_by(is_active=True).count()
    active_loans = Loan.query.filter_by(status='ACTIF').count()
    total_collected = db.session.query(db.func.sum(Transaction.amount)).filter(
        Transaction.type.in_(['TONTINE', 'PRESENCE'])
    ).scalar() or 0
    
    stats = {
        'total_members': total_members,
        'active_loans': active_loans,
        'total_collected': float(total_collected),
        'completed_cycles': TontineCycleDetail.query.filter_by(status='TERMINE').count(),
    }

    # Bureau exécutif : membres réels selon leur rôle (photo de profil incluse)
    role_order = ['PRESIDENT', 'SECRETAIRE', 'TRESORIER', 'CENSEUR', 'COMMUNICATION']
    bureau_users = User.query.filter(User.tontine_id == tontine.id, User.role.in_(role_order),
                                     User.is_active == True).all()
    bureau = sorted(
        [u for u in bureau_users if u.member],
        key=lambda u: role_order.index(u.role)
    )

    photos = GalleryPhoto.query.order_by(GalleryPhoto.display_order, GalleryPhoto.created_at.desc()).all()
    hero_photo = next((p for p in photos if p.is_hero), None)
    gallery = [p for p in photos if not p.is_hero]

    upcoming = Announcement.query.filter(
        Announcement.announcement_type == 'REUNION',
        Announcement.event_date >= date.today()
    ).order_by(Announcement.event_date).first()

    return render_template('index.html', tontine=tontine, stats=stats, bureau=bureau,
                           hero_photo=hero_photo, gallery=gallery, upcoming=upcoming)
# ============================================================
# ============================================================
# GESTION DES MEMBRES
# ============================================================

@app.route('/members')
@login_required
@role_required(['SECRETAIRE', 'PRESIDENT', 'TRESORIER', 'COMMUNICATION', 'CENSEUR'])
def members():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    search = request.args.get('search', '')
    status_filter = request.args.get('status', '')
    tontine_status_filter = request.args.get('tontine_status', '')
    group_type_filter = request.args.get('group_type', '')
    show_inactive = request.args.get('show_inactive', 'false') == 'true'
    
    query = Member.query
    
    if not show_inactive:
        query = query.filter_by(is_active=True)
    
    if search:
        query = query.filter(
            db.or_(
                Member.first_name.ilike(f'%{search}%'),
                Member.last_name.ilike(f'%{search}%'),
                Member.phone.contains(search),
                Member.email.ilike(f'%{search}%')
            )
        )
    
    if status_filter:
        query = query.filter_by(status=status_filter)
    if tontine_status_filter:
        query = query.filter_by(tontine_status=tontine_status_filter)
    if group_type_filter:
        query = query.filter_by(group_type=group_type_filter)
    
    pagination = query.order_by(Member.last_name).paginate(page=page, per_page=per_page, error_out=False)
    pagination_data = get_pagination_data(pagination)
    
    form = MemberForm()
    
    return render_template('members.html', 
                           members=pagination_data['items'], 
                           pagination=pagination_data, 
                           search=search,
                           status_filter=status_filter,
                           tontine_status_filter=tontine_status_filter,
                           group_type_filter=group_type_filter,
                           show_inactive=show_inactive,
                           form=form)

@app.route('/members/<int:member_id>')
@login_required
@member_owner_required
def member_detail(member_id):
    member = db.get_or_404(Member, member_id)
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    transactions_query = Transaction.query.filter_by(member_id=member_id).order_by(Transaction.date.desc())
    transactions_pagination = transactions_query.paginate(page=page, per_page=per_page, error_out=False)
    transactions_pagination_data = get_pagination_data(transactions_pagination)
    
    loans = Loan.query.filter_by(member_id=member_id).all()
    sanctions = Sanction.query.filter_by(member_id=member_id, status='PENDING').all()
    aides = Aide.query.filter_by(member_id=member_id).all()
    cycle_benefits = CycleBeneficiary.query.filter_by(member_id=member_id).all()
    
    total_contributions = db.session.query(db.func.sum(Transaction.amount)).filter(
        Transaction.member_id == member_id,
        Transaction.type.in_(['TONTINE', 'PRESENCE', 'FONDS_CAISSE'])
    ).scalar() or 0
    
    total_loans = db.session.query(db.func.sum(Loan.amount)).filter(
        Loan.member_id == member_id,
        Loan.status == 'ACTIF'
    ).scalar() or 0
    
    can_edit = current_user.role == 'PRESIDENT'
    can_change_role = current_user.role == 'PRESIDENT'

    # Avoirs par fonds : chaque somme a une destination différente
    fund_summary = [
        ('Tontine (cycles)', member._sum_types(['TONTINE']), finance.type_hint('TONTINE')),
        ('Fonds de caisse', member._sum_types(['FONDS_CAISSE']), finance.type_hint('FONDS_CAISSE')),
        ('Épargne personnelle (restituable)', member.savings_balance, finance.type_hint('EPARGNE')),
    ]

    return render_template('member_detail.html',
                           fund_summary=fund_summary,
                           member=member,
                           transactions=transactions_pagination_data['items'],
                           transactions_pagination=transactions_pagination_data,
                           loans=loans,
                           sanctions=sanctions,
                           aides=aides,
                           cycle_benefits=cycle_benefits,
                           total_contributions=total_contributions,
                           total_loans=total_loans,
                           can_edit=can_edit,
                           can_change_role=can_change_role)

@app.route('/members/add', methods=['GET', 'POST'])
@login_required
@role_required(['PRESIDENT', 'SECRETAIRE'])
def add_member():
    form = MemberForm()
    
    # UTILISEZ LA VALIDATION DU FORMULAIRE !!!
    if form.validate_on_submit():
        # Les données sont automatiquement validées et nettoyées
        first_name = form.first_name.data
        last_name = form.last_name.data
        email = form.email.data
        phone = form.phone.data
        address = form.address.data
        profession = form.profession.data
        city = form.city.data
        group_type = form.group_type.data
        position_in_group = form.position_in_group.data
        chosen_tontine_amount = form.chosen_tontine_amount.data
        username = form.username.data
        role = form.role.data
        password = form.password.data
        confirm_password = form.confirm_password.data
        
        # Vérification supplémentaire des mots de passe
        if password != confirm_password:
            flash('Les mots de passe ne correspondent pas.', 'danger')
            return render_template('member_form.html', title="Ajouter un membre", form=form)
        
        # Vérification des doublons
        existing_member = Member.query.filter_by(email=email).first()
        if existing_member:
            flash(f'L\'email "{email}" est déjà utilisé.', 'danger')
            return render_template('member_form.html', title="Ajouter un membre", form=form)
        
        existing_user = User.query.filter_by(tontine_id=g.tenant_id, username=username).first()
        if existing_user:
            flash(f'Le nom d\'utilisateur "{username}" est déjà pris.', 'danger')
            return render_template('member_form.html', title="Ajouter un membre", form=form)
        
        # Création du membre
        member = Member(
            first_name=first_name, last_name=last_name, email=email,
            phone=phone, address=address, profession=profession, city=city,
            registration_date=date.today(), status='ACTIF', is_active=True,
            tontine_status='VERT', consecutive_failures=0,
            credit_balance=Decimal('0.00'), debit_balance=Decimal('0.00'),
            amount_to_receive=Decimal('0.00'), group_type=group_type,
            position_in_group=int(position_in_group) if position_in_group else None,
            has_received_benefit=False,
            chosen_tontine_amount=Decimal(str(chosen_tontine_amount)) if chosen_tontine_amount else None
        )
        
        if 'photo' in request.files:
            photo = request.files['photo']
            if photo and photo.filename:
                filename = save_tenant_upload(photo)
                if filename:
                    member.photo = filename
        
        db.session.add(member)
        db.session.flush()
        
        user = User(tontine_id=g.tenant_id, username=username, email=email, role=role,
                    member_id=member.id, is_active=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        log_activity(current_user.id, current_user.role, f"Ajout membre: {member.full_name}", request.remote_addr)
        flash('Membre ajouté avec succès !', 'success')
        return redirect(url_for('members'))
    
    # Si le formulaire n'est pas valide, afficher les erreurs
    for field, errors in form.errors.items():
        for error in errors:
            flash(f'Erreur dans le champ {getattr(form, field).label.text}: {error}', 'danger')
    
    return render_template('member_form.html', title="Ajouter un membre", form=form)


@app.route('/members/<int:member_id>/edit', methods=['GET', 'POST'])
@login_required
@president_required
def edit_member(member_id):
    member = db.get_or_404(Member, member_id)
    form = MemberEditForm(obj=member)
    
    if form.validate_on_submit() and email_taken(form.email.data, member.id):
        flash(f"L'email {form.email.data} est déjà utilisé par un autre membre de la tontine.", 'danger')
    elif form.validate_on_submit():
        member.first_name = form.first_name.data
        member.last_name = form.last_name.data
        member.email = form.email.data
        # Le compte de connexion garde le même email que la fiche (utilisé pour « mot de passe oublié »)
        account = User.query.filter_by(tontine_id=g.tenant_id, member_id=member.id).first()
        if account:
            account.email = form.email.data
        member.phone = form.phone.data
        member.address = form.address.data
        member.profession = form.profession.data
        member.city = form.city.data
        member.status = form.status.data
        
        if form.photo.data:
            filename = save_tenant_upload(form.photo.data)
            if filename:
                member.photo = filename
        
        db.session.commit()
        log_activity(current_user.id, current_user.role, f"Modification membre: {member.full_name}", request.remote_addr)
        flash('Membre modifié avec succès !', 'success')
        return redirect(url_for('member_detail', member_id=member.id))
    
    return render_template('member_form.html', form=form, member=member, title="Modifier membre")

@app.route('/members/<int:member_id>/delete', methods=['POST'])
@login_required
@president_required
def delete_member(member_id):
    member = db.get_or_404(Member, member_id)
    member.is_active = False
    
    user = User.query.filter_by(member_id=member.id).first()
    if user:
        user.is_active = False
    
    db.session.commit()
    log_activity(current_user.id, current_user.role, f"Désactivation membre: {member.full_name}", request.remote_addr)
    flash('Membre désactivé avec succès !', 'success')
    return redirect(url_for('members'))

@app.route('/members/<int:member_id>/activate', methods=['POST'])
@login_required
@role_required(['TRESORIER', 'PRESIDENT'])
def activate_member(member_id):
    member = db.get_or_404(Member, member_id)
    
    if member.status == 'PENDING':
        member.status = 'ACTIF'
        member.is_active = True
        
        user = User.query.filter_by(member_id=member.id).first()
        if user:
            user.is_active = True
        
        db.session.commit()
        log_activity(current_user.id, current_user.role, f"Activation membre: {member.full_name}", request.remote_addr)
        flash(f'Membre {member.full_name} activé avec succès !', 'success')
    else:
        flash('Ce membre n\'est pas en attente de validation.', 'warning')
    
    return redirect(url_for('members'))


# ============================================================
# GESTION DES MEMBRES
# ============================================================

# ... vos routes existantes ...

@app.route('/member/<int:member_id>/update_status', methods=['POST'])
@login_required
def update_status(member_id):
    """Mettre à jour le statut tontine d'un membre (VERT/ORANGE/ROUGE)"""
    if current_user.role not in ['SECRETAIRE', 'PRESIDENT', 'TRESORIER']:
        flash('Vous n\'avez pas les droits nécessaires.', 'danger')
        return redirect(url_for('member_detail', member_id=member_id))
    
    member = db.get_or_404(Member, member_id)
    new_status = request.form.get('tontine_status')
    
    if new_status and new_status in ['VERT', 'ORANGE', 'ROUGE']:
        member.tontine_status = new_status
        db.session.commit()
        log_activity(current_user.id, current_user.role, f"Statut tontine de {member.full_name} -> {new_status}", request.remote_addr)
        flash(f'Statut tontine de {member.full_name} mis à jour : {new_status}', 'success')
    else:
        flash('Statut invalide.', 'danger')
    
    return redirect(url_for('member_detail', member_id=member_id))


@app.route('/members/<int:member_id>/update_member_status', methods=['POST'])
@login_required
@role_required(['PRESIDENT', 'SECRETAIRE'])
def update_member_status(member_id):
    """Mettre à jour le statut général du membre (ACTIF/SUSPENDU/EXCLU)"""
    member = db.get_or_404(Member, member_id)
    new_status = request.form.get('status')
    valid_statuses = ['ACTIF', 'SUSPENDU', 'EXCLU']
    
    if new_status and new_status in valid_statuses:
        member.status = new_status
        db.session.commit()
        log_activity(current_user.id, current_user.role, f"Statut de {member.full_name} -> {new_status}", request.remote_addr)
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'status': new_status})
        
        flash(f'Statut de {member.full_name} mis à jour avec succès.', 'success')
    else:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Statut invalide'})
        flash('Statut invalide.', 'danger')
    
    return redirect(url_for('member_detail', member_id=member_id))


@app.route('/members/<int:member_id>/change-role', methods=['POST'])
@login_required
@president_required
def change_member_role(member_id):
    """Changer le rôle d'un membre (MEMBRE/PRESIDENT/SECRETAIRE/TRESORIER/CENSEUR/COMMUNICATION)"""
    member = db.get_or_404(Member, member_id)
    new_role = request.form.get('role')
    valid_roles = ['MEMBRE', 'PRESIDENT', 'SECRETAIRE', 'TRESORIER', 'CENSEUR', 'COMMUNICATION']
    
    if new_role not in valid_roles:
        flash('Rôle invalide.', 'danger')
        return redirect(url_for('member_detail', member_id=member_id))
    
    user = User.query.filter_by(member_id=member.id).first()
    if user:
        old_role = user.role
        user.role = new_role
        db.session.commit()
        log_activity(current_user.id, current_user.role, f"Changement rôle de {member.full_name}: {old_role} -> {new_role}", request.remote_addr)
        flash(f'Rôle de {member.full_name} modifié en {new_role}.', 'success')
    else:
        flash('Ce membre n\'a pas de compte utilisateur.', 'danger')
    
    return redirect(url_for('member_detail', member_id=member_id))


@app.route('/members/<int:member_id>/reactivate', methods=['POST'])
@login_required
@president_required
def reactivate_member(member_id):
    """Réactiver un membre désactivé"""
    member = db.get_or_404(Member, member_id)
    member.is_active = True
    
    user = User.query.filter_by(member_id=member.id).first()
    if user:
        user.is_active = True
    
    db.session.commit()
    log_activity(current_user.id, current_user.role, f"Réactivation membre: {member.full_name}", request.remote_addr)
    flash('Membre réactivé avec succès !', 'success')
    return redirect(url_for('members'))
# ============================================================
# GESTION DES TRANSACTIONS
# ============================================================

@app.route('/transactions')
@login_required
def transactions():
    if not current_user.is_admin() and request.args.get('member_id', type=int) != current_user.member_id:
        return redirect(url_for('transactions', member_id=current_user.member_id))

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    type_filter = request.args.get('type', '')
    date_debut = request.args.get('date_debut', '')
    date_fin = request.args.get('date_fin', '')
    member_id = request.args.get('member_id', type=int)
    
    query = Transaction.query
    
    if type_filter:
        query = query.filter_by(type=type_filter)
    def _date_or_none(value):
        try:
            return datetime.strptime(value, '%Y-%m-%d').date() if value else None
        except ValueError:
            return None
    start_filter, end_filter = _date_or_none(date_debut), _date_or_none(date_fin)
    if date_debut and not start_filter or date_fin and not end_filter:
        flash('Date de filtre invalide : elle a été ignorée.', 'warning')
    if start_filter:
        query = query.filter(Transaction.date >= start_filter)
    if end_filter:
        query = query.filter(Transaction.date <= end_filter)
    if member_id:
        query = query.filter_by(member_id=member_id)
    
    pagination = query.order_by(Transaction.date.desc()).paginate(page=page, per_page=per_page, error_out=False)
    pagination_data = get_pagination_data(pagination)
    
    summary = {}
    for t_type, total in db.session.query(Transaction.type, db.func.sum(Transaction.amount)).group_by(Transaction.type).all():
        summary[t_type] = total or 0
    total_in = sum(float(v) for k, v in summary.items() if not finance.is_outflow(k))
    total_out = sum(float(v) for k, v in summary.items() if finance.is_outflow(k))
    
    members_list = Member.query.filter_by(is_active=True).all() if current_user.is_admin() else []
    
    return render_template('transactions.html',
                           transactions=pagination_data['items'],
                           pagination=pagination_data,
                           summary=summary,
                           total_in=total_in,
                           total_out=total_out,
                           type_filter=type_filter,
                           members=members_list,
                           date_debut=date_debut,
                           date_fin=date_fin,
                           selected_member=member_id)

def _is_recent_duplicate(member_id, tx_type, amount, seconds=15):
    """Même membre, même nature, même montant, même auteur il y a moins de `seconds` secondes"""
    amount = _parse_decimal(amount, 0, 1_000_000_000_000)
    if amount is None:
        return False
    since = utcnow() - timedelta(seconds=seconds)
    return Transaction.query.filter(
        Transaction.member_id == member_id, Transaction.type == tx_type, Transaction.amount == amount,
        Transaction.created_by == current_user.id, Transaction.created_at >= since
    ).first() is not None


def _transaction_type_choices(current=None):
    codes = list(finance.MANUAL_TYPES)
    if current and current not in codes:
        codes.insert(0, current)
    return [(c, finance.type_label(c)) for c in codes]


def _selected_rubrique():
    rid = request.form.get('contribution_type_id', type=int)
    if not rid:
        return None
    return ContributionType.query.filter_by(id=rid, is_active=True).first()


@app.route('/transactions/add', methods=['GET', 'POST'])
@login_required
@role_required(['SECRETAIRE', 'PRESIDENT', 'TRESORIER'])
def add_transaction():
    ensure_contribution_types(current_tontine())
    form = TransactionForm()
    form.type.choices = _transaction_type_choices()
    form.payment_mode.choices = list(finance.PAYMENT_MODES.items())
    form.member_id.choices = [(0, 'Choisir un membre')] + [(m.id, m.full_name) for m in Member.query.filter_by(is_active=True).order_by(Member.last_name).all()]
    rubriques = ContributionType.query.filter_by(is_active=True).order_by(ContributionType.display_order).all()

    if form.validate_on_submit():
        if form.member_id.data == 0:
            flash('Veuillez sélectionner un membre valide.', 'danger')
            return render_template('transaction_form.html', form=form, title="Ajouter une transaction", rubriques=rubriques)

        rubrique = _selected_rubrique()
        if _is_recent_duplicate(form.member_id.data, rubrique.category if rubrique else form.type.data, form.amount.data):
            flash("Cette opération vient déjà d'être enregistrée (double clic ?). Vérifiez la liste des transactions.", 'warning')
            return redirect(url_for('transactions'))
        transaction = Transaction(
            member_id=form.member_id.data,
            # La rubrique choisie détermine la nature comptable de l'opération
            type=rubrique.category if rubrique else form.type.data,
            contribution_type_id=rubrique.id if rubrique else None,
            amount=Decimal(str(form.amount.data)),
            description=form.description.data,
            date=date.today(),
            created_by=current_user.id,
            payment_mode=form.payment_mode.data if hasattr(form, 'payment_mode') else 'ESPECE',
            payment_reference=_payment_reference_from_form(),
        )
        db.session.add(transaction)

        if transaction.type == 'TONTINE' and rubrique and not transaction.cycle_id:
            # Rattachement automatique au cycle en cours de ce niveau, si le membre y participe :
            # sinon la cotisation ne compterait pas dans l'état des cotisations du cycle
            cycles = [cy for cy in TontineCycleDetail.query.filter_by(contribution_type_id=rubrique.id, status='EN_COURS').all()
                      if any(p.member_id == form.member_id.data for p in cy.participants)]
            if len(cycles) == 1:
                transaction.cycle_id = cycles[0].id
                flash(f"Cotisation rattachée au {cycles[0].display_name}.", 'info')
            else:
                flash("Cette cotisation n'est rattachée à aucun cycle : pour un cycle, utilisez la feuille de séance "
                      "ou « Régulariser » sur la page du cycle.", 'warning')

        if transaction.type == 'TONTINE':
            member = db.session.get(Member, form.member_id.data)
            if member and not member.has_paid_fonds_caisse:
                fonds_caisse = Transaction(
                    member_id=member.id,
                    type='FONDS_CAISSE',
                    amount=Decimal(str(current_tontine().fonds_caisse_amount or 5000)),
                    description="Fonds de Caisse obligatoire lié à la Tontine",
                    date=date.today(),
                    created_by=current_user.id,
                    payment_mode='ESPECE'
                )
                db.session.add(fonds_caisse)
                flash('Fonds de caisse obligatoire enregistré !', 'info')
        
        db.session.commit()
        log_activity(current_user.id, current_user.role, f"Ajout transaction : {finance.type_label(transaction.type)} "
                     f"{transaction.amount:,.0f} FCFA", request.remote_addr)
        flash('Transaction enregistrée avec succès !', 'success')
        return redirect(url_for('transactions'))

    return render_template('transaction_form.html', form=form, title="Ajouter une transaction", rubriques=rubriques)


@app.route('/transactions/<int:transaction_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required(['TRESORIER', 'PRESIDENT'])
def edit_transaction(transaction_id):
    """Modifier une transaction existante"""
    transaction = db.get_or_404(Transaction, transaction_id)
    if transaction.is_system:
        flash(f"Cette écriture est générée par le module « {transaction.source_module} » : "
              "elle ne se modifie pas ici.", 'danger')
        return redirect(url_for('transactions'))
    form = TransactionForm(obj=transaction)
    form.type.choices = _transaction_type_choices(transaction.type)
    form.payment_mode.choices = list(finance.PAYMENT_MODES.items())
    rubriques = ContributionType.query.filter_by(is_active=True).order_by(ContributionType.display_order).all()

    # Remplir les choix du select
    form.member_id.choices = [(0, 'Choisir un membre')] + [(m.id, m.full_name) for m in Member.query.filter_by(is_active=True).order_by(Member.last_name).all()]
    
    if form.validate_on_submit():
        try:
            transaction.member_id = form.member_id.data
            rubrique = _selected_rubrique()
            transaction.type = rubrique.category if rubrique else form.type.data
            transaction.contribution_type_id = rubrique.id if rubrique else None
            transaction.amount = Decimal(str(form.amount.data))
            transaction.description = form.description.data
            transaction.payment_mode = form.payment_mode.data if hasattr(form, 'payment_mode') else transaction.payment_mode
            transaction.payment_reference = _payment_reference_from_form()
            
            db.session.commit()
            
            log_activity(current_user.id, current_user.role, f"Modification transaction #{transaction_id}", request.remote_addr)
            flash('Transaction modifiée avec succès !', 'success')
            return redirect(url_for('transactions'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la modification : {str(e)}', 'danger')
    
    return render_template('transaction_form.html', form=form, transaction=transaction, title="Modifier une transaction",
                           rubriques=rubriques)


@app.route('/transactions/<int:transaction_id>/delete', methods=['POST'])
@login_required
@role_required(['PRESIDENT'])
def delete_transaction(transaction_id):
    """Supprimer une transaction"""
    transaction = db.get_or_404(Transaction, transaction_id)
    if transaction.is_system:
        flash(f"Cette écriture est générée par le module « {transaction.source_module} » : "
              "la supprimer ici fausserait les soldes. Corrigez-la depuis ce module.", 'danger')
        return redirect(url_for('transactions'))
    
    try:
        db.session.delete(transaction)
        db.session.commit()
        
        log_activity(current_user.id, current_user.role, f"Suppression transaction #{transaction_id}", request.remote_addr)
        flash('Transaction supprimée avec succès !', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Erreur lors de la suppression : {str(e)}', 'danger')
    
    return redirect(url_for('transactions'))


@app.route('/transactions/<int:transaction_id>/view')
@login_required
def view_transaction(transaction_id):
    """Voir le détail d'une transaction"""
    transaction = db.get_or_404(Transaction, transaction_id)
    
    # Vérifier les droits d'accès
    if not current_user.is_admin() and transaction.member_id != current_user.member_id:
        flash('Vous n\'avez pas accès à cette transaction.', 'danger')
        return redirect(url_for('transactions'))
    
    return render_template('transaction_detail.html', transaction=transaction)

# ============================================================
# GESTION DES EMPRUNTS
# ============================================================

@app.route('/loans')
@login_required
def loans():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    status_filter = request.args.get('status', '')
    overdue_filter = request.args.get('overdue', '')
    search_query = request.args.get('search', '')
    sort_column = request.args.get('sort', 'id')
    sort_order = request.args.get('order', 'desc')
    
    query = Loan.query
    
    if not current_user.is_admin():
        query = query.filter_by(member_id=current_user.member_id)
    
    if status_filter:
        query = query.filter(Loan.status == status_filter)
        
    if overdue_filter == 'yes':
        query = query.filter(Loan.status.in_(['ACTIF', 'OVERDUE']), Loan.end_date < date.today())
    elif overdue_filter == 'no':
        query = query.filter(db.or_(
            Loan.status == 'REMBOURSE',
            db.and_(Loan.status == 'ACTIF', Loan.end_date >= date.today())
        ))
        
    if search_query and current_user.is_admin():
        query = query.join(Member).filter(
            db.or_(
                Member.first_name.ilike(f'%{search_query}%'), 
                Member.last_name.ilike(f'%{search_query}%')
            )
        )
        
    if sort_column == 'member_name':
        if not search_query:
            query = query.join(Member)
        if sort_order == 'asc':
            query = query.order_by(Member.first_name.asc(), Member.last_name.asc())
        else:
            query = query.order_by(Member.first_name.desc(), Member.last_name.desc())
    elif sort_column == 'amount':
        query = query.order_by(Loan.amount.asc() if sort_order == 'asc' else Loan.amount.desc())
    else:
        query = query.order_by(Loan.id.desc())
        
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    for loan in pagination.items:
        if loan.is_overdue and loan.status == 'ACTIF':
            loan.status = 'OVERDUE'
    
    db.session.commit()
    
    members_list = []
    if current_user.is_admin():
        members_list = Member.query.filter_by(is_active=True).all()
    else:
        if current_user.member:
            members_list = [current_user.member]

    # Candidats avalistes : membres actifs (l'emprunteur est exclu côté formulaire et serveur)
    guarantor_candidates = guarantor_choices(exclude_member_id=current_user.member_id)

    return render_template(
        'loans.html',
        loans=pagination.items,
        pagination=get_pagination_data(pagination),
        members=members_list,
        current_sort=sort_column,
        current_order=sort_order,
        guarantor_candidates=guarantor_candidates,
        required_guarantors=current_tontine().guarantors_min or 0,
        guarantee_threshold=float(current_tontine().guarantee_threshold or 0),
    )

@app.route('/loan/request', methods=['POST'])
@login_required
def loan_request():
    """Soumettre une demande d'emprunt"""
    member_id = request.form.get('member_id', type=int)
    amount_str = request.form.get('amount')
    duration_months = request.form.get('duration_months', type=int, default=3)
    purpose = request.form.get('purpose', 'Emprunt standard')

    # Vérifier les droits
    if not current_user.is_admin() and current_user.member_id != member_id:
        flash("Action non autorisée.", "danger")
        return redirect(url_for('loans'))

    member = db.get_or_404(Member, member_id)
    amount = _parse_decimal(amount_str or '0', 0, 1_000_000_000)
    if not amount or amount <= 0:
        flash("Montant d'emprunt invalide.", "danger")
        return redirect(url_for('loans'))
    if not duration_months or duration_months < 1 or duration_months > 24:
        duration_months = 3
    # Le taux est fixé par la tontine, jamais par le formulaire
    interest_rate = Decimal(str(current_tontine().loan_interest_rate or 5))
    
    # Vérifier l'éligibilité
    if hasattr(member, 'is_eligible_for_loan'):
        is_eligible, reason = member.is_eligible_for_loan(amount)
        if not is_eligible:
            flash(f"Échec d'éligibilité : {reason}", "danger")
            return redirect(url_for('loans'))
    
    # Calculer les intérêts
    interest = amount * (interest_rate / Decimal('100'))
    total_amount = amount + interest

    # Avalistes choisis par l'emprunteur
    guarantor_ids = []
    for raw in request.form.getlist('guarantor_ids'):
        try:
            gid = int(raw)
        except (TypeError, ValueError):
            continue
        if gid and gid not in guarantor_ids:
            guarantor_ids.append(gid)
    guarantors, problems = _validate_guarantors(member, guarantor_ids, amount)
    if problems:
        for msg in problems:
            flash(msg, 'danger')
        return redirect(url_for('loans'))
    required = required_guarantors_for(amount)
    if len(guarantors) < required:
        flash(f"Cet emprunt nécessite au moins {required} avaliste(s).", 'danger')
        return redirect(url_for('loans'))
        
    # Créer la demande d'emprunt
    loan = Loan(
        member_id=member.id,
        amount=amount,
        interest=interest,
        total_amount=total_amount,
        amount_paid=Decimal('0.00'),
        request_date=date.today(),
        approval_date=None,
        start_date=None,
        end_date=date.today() + timedelta(days=duration_months * 30),
        status='PENDING',
        description=purpose,
        approved_by=None,
        created_by=current_user.id,
        created_at=utcnow()
    )
    
    db.session.add(loan)
    for guarantor, share in zip(guarantors, _split_amount(total_amount, max(required, len(guarantors)), len(guarantors))):
        loan.guarantors.append(LoanGuarantor(member_id=guarantor.id, amount=share, status='EN_ATTENTE'))
    db.session.commit()

    log_activity(current_user.id, current_user.role, f"Demande d'emprunt de {amount:,.0f} FCFA", request.remote_addr)
    if guarantors:
        names = ', '.join(g.full_name for g in guarantors)
        flash(f"Demande d'emprunt de {amount:,.0f} FCFA envoyée. Elle attend l'accord de vos avalistes : {names}.", "success")
    else:
        flash(f"Demande d'emprunt de {amount:,.0f} FCFA soumise avec succès.", "success")
    return redirect(url_for('loans'))


@app.route('/loans/<int:loan_id>/approve', methods=['POST'])
@login_required
def approve_loan(loan_id):
    """Approuver une demande d'emprunt"""
    if getattr(current_user, 'role', None) not in ['PRESIDENT', 'TRESORIER']:
        abort(403)
    
    loan = db.get_or_404(Loan, loan_id)
    
    if loan.status != 'PENDING':
        flash("Cet emprunt n'est pas en attente.", "warning")
        return redirect(url_for('loans'))

    required = required_guarantors_for(loan.amount)
    accepted = len([g for g in loan.guarantors if g.status == 'ACCEPTE'])
    if accepted < required:
        flash(f"Impossible d'approuver : {accepted}/{required} aval(s) accordé(s). "
              "Attendez la réponse des avalistes ou demandez-en un autre.", "danger")
        return redirect(url_for('loans'))

    loan.status = 'ACTIF'
    loan.approval_date = date.today()
    loan.approved_by = current_user.id
    loan.start_date = date.today()
    
    # Créer la transaction de décaissement
    transaction = Transaction(
        member_id=loan.member_id,
        type='SORTIE_LOAN',
        amount=loan.amount,
        description=f"Décaissement emprunt #{loan.id}",
        date=date.today(),
        created_by=current_user.id,
        payment_mode='ESPECE'
    )
    db.session.add(transaction)
    db.session.commit()
    
    log_activity(current_user.id, current_user.role, f"Emprunt #{loan.id} approuvé", request.remote_addr)
    flash('Le prêt a été approuvé avec succès.', 'success')
    return redirect(url_for('loans'))


@app.route('/loans/<int:loan_id>/reject', methods=['POST'])
@login_required
def reject_loan(loan_id):
    """Rejeter une demande d'emprunt"""
    if getattr(current_user, 'role', None) not in ['PRESIDENT', 'TRESORIER']:
        abort(403)
    
    loan = db.get_or_404(Loan, loan_id)
    
    if loan.status != 'PENDING':
        flash("Impossible de rejeter un emprunt déjà traité.", "warning")
        return redirect(url_for('loans'))
    
    rejection_reason = request.form.get('rejection_reason', 'Refusé par le bureau')
    loan.status = 'REJECTED'
    loan.description = rejection_reason
    for guarantee in loan.guarantors:
        if guarantee.status in ('EN_ATTENTE', 'ACCEPTE'):
            guarantee.status = 'ANNULE'
    db.session.commit()
    
    log_activity(current_user.id, current_user.role, f"Emprunt #{loan.id} rejeté", request.remote_addr)
    flash('La demande d\'emprunt a été rejetée.', 'warning')
    return redirect(url_for('loans'))


@app.route('/loans/<int:loan_id>/repay', methods=['GET', 'POST'])
@login_required
def repay_loan(loan_id):
    """Rembourser un emprunt"""
    if getattr(current_user, 'role', None) not in ['SECRETAIRE', 'PRESIDENT', 'TRESORIER']:
        abort(403)
    
    loan = db.get_or_404(Loan, loan_id)
    
    if loan.status not in ['ACTIF', 'OVERDUE']:
        flash('Ce prêt n\'est pas actif ou est déjà soldé.', 'warning')
        return redirect(url_for('loans'))
    
    if request.method == 'GET':
        return render_template('loan_repay_form.html', loan=loan, title="Rembourser un emprunt")
    
    # Traitement POST
    payment_amount = _parse_decimal(request.form.get('amount') or '0', 0, 1_000_000_000)
    if not payment_amount or payment_amount <= 0:
        flash('Veuillez entrer un montant de remboursement valide.', 'danger')
        return redirect(url_for('loans'))
    expected_paid = _parse_decimal(request.form.get('expected_paid'), 0, 1_000_000_000_000) if request.form.get('expected_paid') else None
    if expected_paid is not None and expected_paid != Decimal(str(loan.amount_paid or 0)):
        flash("Ce remboursement a déjà été enregistré (double clic ou page ancienne).", 'warning')
        return redirect(url_for('loans'))
    remaining = loan.total_amount - loan.amount_paid
    
    if payment_amount > remaining:
        flash(f"Le montant saisi dépasse le solde restant dû ({remaining:,.0f} FCFA).", "danger")
        return redirect(url_for('loans'))
    
    loan.amount_paid += payment_amount

    if loan.amount_paid >= loan.total_amount:
        loan.status = 'REMBOURSE'
        _release_guarantors(loan)
        
    transaction = Transaction(
        member_id=loan.member_id,
        type='REMBOURSEMENT',
        amount=payment_amount,
        description=f"Remboursement emprunt #{loan.id}",
        date=date.today(),
        created_by=current_user.id,
        payment_mode=_payment_mode_from_form(),
        payment_reference=_payment_reference_from_form(),
    )
    db.session.add(transaction)
    db.session.commit()
    
    log_activity(current_user.id, current_user.role, f"Remboursement emprunt #{loan.id}", request.remote_addr)
    flash("Le remboursement a été enregistré.", "success")
    return redirect(url_for('loans'))


# ============================================================
# GESTION DES SANCTIONS
# ============================================================

# ============================================================
# GESTION DES SANCTIONS (AVEC VALIDATION)
# ============================================================

@app.route('/sanctions', methods=['GET'])
@login_required
def sanctions():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    status_filter = request.args.get('status', '')
    
    query = Sanction.query
    if not current_user.is_admin():
        query = query.filter_by(member_id=current_user.member_id)
    if status_filter:
        query = query.filter_by(status=status_filter)
        
    pagination = query.order_by(Sanction.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    pagination_data = get_pagination_data(pagination)
    
    members_list = (Member.query.filter_by(is_active=True, status='ACTIF').order_by(Member.last_name).all()
                    if current_user.is_admin() else [])
    
    # Créer le formulaire pour l'ajout
    form = SanctionForm()
    form.member_id.choices = [(m.id, m.full_name) for m in Member.query.filter_by(is_active=True, status='ACTIF').order_by(Member.last_name).all()]
    
    return render_template('sanctions.html',
                           sanctions=pagination_data['items'],
                           pagination=pagination_data,
                           members=members_list,
                           sanction_types=Sanction.TYPES,
                           can_add=current_user.role in ('CENSEUR', 'PRESIDENT', 'SECRETAIRE'),
                           can_edit=current_user.role in ('CENSEUR', 'PRESIDENT'),
                           can_pay=current_user.role in ('TRESORIER', 'PRESIDENT'),
                           status_filter=status_filter,
                           form=form)


@app.route('/sanctions/add', methods=['GET', 'POST'])
@login_required
@role_required(['CENSEUR', 'PRESIDENT', 'SECRETAIRE'])
def add_sanction():
    """Ajouter une nouvelle sanction avec validation"""
    form = SanctionForm()
    form.member_id.choices = [(m.id, m.full_name) for m in Member.query.filter_by(is_active=True, status='ACTIF').order_by(Member.last_name).all()]
    
    # Afficher le formulaire en GET
    if request.method == 'GET':
        return render_template('sanction_form.html', form=form, title="Ajouter une sanction")
    
    # Traitement POST avec validation
    if form.validate_on_submit():
        try:
            sanction = Sanction(
                member_id=form.member_id.data,
                type_sanction=form.type_sanction.data,
                amount=Decimal(str(form.amount.data)),
                description=form.description.data,
                sanction_date=form.sanction_date.data,
                status='PENDING'
            )
            db.session.add(sanction)
            db.session.commit()
            
            member = db.session.get(Member, form.member_id.data)
            log_activity(current_user.id, current_user.role, f"Sanction infligée à {member.full_name} : {form.amount.data} FCFA", request.remote_addr)
            flash(f"Amende de {form.amount.data:,.0f} FCFA enregistrée avec succès pour {member.full_name}.", "success")
            return redirect(url_for('sanctions'))
            
        except Exception as e:
            db.session.rollback()
            flash(f"Erreur lors de l'enregistrement : {str(e)}", "danger")
    else:
        # Afficher les erreurs de validation
        for field, errors in form.errors.items():
            for error in errors:
                field_label = getattr(form, field).label.text if hasattr(form, field) else field
                flash(f'Erreur dans le champ "{field_label}": {error}', 'danger')
    
    return render_template('sanction_form.html', form=form, title="Ajouter une sanction")


@app.route('/sanctions/<int:sanction_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required(['CENSEUR', 'PRESIDENT'])
def edit_sanction(sanction_id):
    """Modifier une sanction existante"""
    sanction = db.get_or_404(Sanction, sanction_id)
    
    if sanction.status == 'PAID':
        flash('Impossible de modifier une sanction déjà payée.', 'danger')
        return redirect(url_for('sanctions'))
    
    form = SanctionForm(obj=sanction)
    form.member_id.choices = [(m.id, m.full_name) for m in Member.query.filter_by(is_active=True).order_by(Member.last_name).all()]
    
    if form.validate_on_submit():
        try:
            sanction.member_id = form.member_id.data
            sanction.type_sanction = form.type_sanction.data
            sanction.amount = Decimal(str(form.amount.data))
            sanction.description = form.description.data
            sanction.sanction_date = form.sanction_date.data
            
            db.session.commit()
            
            log_activity(current_user.id, current_user.role, f"Modification sanction #{sanction_id}", request.remote_addr)
            flash('Sanction modifiée avec succès.', 'success')
            return redirect(url_for('sanctions'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur : {str(e)}', 'danger')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'Erreur: {error}', 'danger')
    
    return render_template('sanction_form.html', form=form, sanction=sanction, title="Modifier la sanction")


@app.route('/sanctions/<int:sanction_id>/pay', methods=['POST'])
@login_required
@role_required(['TRESORIER', 'PRESIDENT'])
def pay_sanction(sanction_id):
    """Payer une sanction"""
    sanction = db.get_or_404(Sanction, sanction_id)
    
    if sanction.status == 'PAID':
        flash('Cette amende a déjà été payée.', 'warning')
        return redirect(url_for('sanctions'))
    
    # Validation du mode de paiement
    payment_mode = request.form.get('payment_mode', 'ESPECE')
    valid_modes = ['ESPECE', 'ORANGE_MONEY', 'MTN_MOBILE', 'VIREMENT']
    if payment_mode not in valid_modes:
        payment_mode = 'ESPECE'
    
    sanction.status = 'PAID'
    
    transaction = Transaction(
        member_id=sanction.member_id,
        type='SANCTION',
        amount=sanction.amount,
        description=f"Paiement sanction #{sanction.id} - {sanction.description[:100]}",
        date=date.today(),
        created_by=current_user.id,
        payment_mode=payment_mode
    )
    db.session.add(transaction)
    db.session.commit()
    
    log_activity(current_user.id, current_user.role, f"Paiement sanction #{sanction.id} - {sanction.amount} FCFA", request.remote_addr)
    flash(f"Le paiement de l'amende de {sanction.amount:,.0f} FCFA a été encaissé.", "success")
    return redirect(url_for('sanctions'))


@app.route('/sanctions/<int:sanction_id>/delete', methods=['POST'])
@login_required
@role_required(['CENSEUR', 'PRESIDENT'])
def delete_sanction(sanction_id):
    """Supprimer une sanction (uniquement si non payée)"""
    sanction = db.get_or_404(Sanction, sanction_id)
    
    if sanction.status == 'PAID':
        flash('Impossible de supprimer une sanction déjà payée.', 'danger')
        return redirect(url_for('sanctions'))
    
    try:
        db.session.delete(sanction)
        db.session.commit()
        
        log_activity(current_user.id, current_user.role, f"Suppression sanction #{sanction_id}", request.remote_addr)
        flash('Sanction supprimée avec succès.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Erreur lors de la suppression : {str(e)}', 'danger')
    
    return redirect(url_for('sanctions'))
# ============================================================
# GESTION DES RÉUNIONS
# ============================================================

# ============================================================
# GESTION DES RÉUNIONS (CRUD COMPLET)
# ============================================================

# ============================================================
# GESTION DES RÉUNIONS (CRUD COMPLET AVEC VALIDATION)
# ============================================================

@app.template_filter('fcfa')
def fcfa_filter(value):
    """30000 -> « 30 000 » (montants affichés à la française)"""
    try:
        return f"{Decimal(str(value or 0)):,.0f}".replace(',', ' ')
    except (ArithmeticError, ValueError, TypeError):
        return '0'


_JOURS = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']
_MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre',
         'novembre', 'décembre']


@app.template_filter('date_longue')
def date_longue_filter(value):
    """Date en toutes lettres, en français, quelle que soit la langue du serveur : « Vendredi 9 octobre 2026 »"""
    if not value:
        return ''
    return f"{_JOURS[value.weekday()].capitalize()} {value.day} {_MOIS[value.month - 1]} {value.year}"


@app.template_filter('nl2br')
def nl2br_filter(text):
    """
    Convertit les sauts de ligne en balises HTML <br>
    Échappe d'abord le HTML pour éviter les injections XSS
    """
    if not text:
        return ''
    from markupsafe import Markup, escape
    # Échappe d'abord le HTML, puis insère les <br> (sur une chaîne simple : Markup.replace les échapperait)
    return Markup(str(escape(text)).replace('\n', '<br>\n'))

@app.route('/meetings')
@login_required
def meetings():
    """Liste des réunions"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    
    pagination = Announcement.query.filter(
        Announcement.announcement_type == 'REUNION'
    ).order_by(Announcement.event_date.desc().nullslast()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return render_template('meetings.html', 
                           meetings=pagination.items, 
                           pagination=pagination)


@app.route('/meetings/<int:meeting_id>')
@login_required
def meeting_detail(meeting_id):
    """Détail d'une réunion"""
    meeting = db.get_or_404(Announcement, meeting_id)
    agenda_items = AgendaItem.query.filter_by(announcement_id=meeting_id).all()
    beneficiaries = MeetingBeneficiary.query.filter_by(announcement_id=meeting_id).all()
    attendances = MeetingAttendanceDetail.query.filter_by(announcement_id=meeting_id).all()
    
    return render_template('meeting_detail.html', 
                          meeting=meeting, 
                          agenda_items=agenda_items, 
                          beneficiaries=beneficiaries, 
                          attendances=attendances)


@app.route('/meetings/add', methods=['GET', 'POST'])
@login_required
@role_required(['SECRETAIRE', 'PRESIDENT'])
def add_meeting():
    """Ajouter un nouveau PV de réunion"""
    form = MeetingAttendanceForm()
    set_member_choices(form)
    
    # UTILISER LA VALIDATION DU FORMULAIRE
    if form.validate_on_submit():
        try:
            # Créer la réunion avec les données validées
            meeting = Announcement(
                title=form.meeting_title.data,
                event_date=form.meeting_date.data,
                announcement_type='REUNION',
                is_active=True,
                created_at=utcnow(),
                created_by=current_user.id,
                content=form.content.data
            )
            db.session.add(meeting)
            db.session.flush()
            
            # Ajouter les points d'ordre du jour (validé)
            if form.agenda_items.data:
                agenda_items = form.agenda_items.data.split('\n')
                for item in agenda_items:
                    if item.strip():
                        agenda = AgendaItem(
                            announcement_id=meeting.id,
                            title=item.strip(),
                            is_completed=False
                        )
                        db.session.add(agenda)
            
            # Ajouter les bénéficiaires (validé)
            if form.beneficiary_member_id.data and form.beneficiary_member_id.data > 0:
                beneficiary = MeetingBeneficiary(
                    announcement_id=meeting.id,
                    member_id=form.beneficiary_member_id.data,
                    benefit_type='TONTINE',
                    amount=Decimal(str(form.benefit_amount.data)) if form.benefit_amount.data else Decimal('0')
                )
                db.session.add(beneficiary)
            
            db.session.commit()
            
            log_activity(current_user.id, current_user.role, f"Création PV réunion: {meeting.title}", request.remote_addr)
            flash('Procès-verbal enregistré avec succès !', 'success')
            return redirect(url_for('meeting_detail', meeting_id=meeting.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur : {str(e)}', 'danger')
    else:
        # Afficher les erreurs de validation
        for field, errors in form.errors.items():
            for error in errors:
                field_label = getattr(form, field).label.text if hasattr(form, field) else field
                flash(f'Erreur dans le champ "{field_label}": {error}', 'danger')
    
    return render_template('meeting_form.html', title="Rédiger un PV", form=form)


@app.route('/meetings/<int:meeting_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required(['SECRETAIRE', 'PRESIDENT'])
def edit_meeting(meeting_id):
    """Modifier un PV de réunion"""
    meeting = db.get_or_404(Announcement, meeting_id)
    form = MeetingAttendanceForm(obj=meeting)
    set_member_choices(form)
    
    # UTILISER LA VALIDATION DU FORMULAIRE
    if form.validate_on_submit():
        try:
            meeting.title = form.meeting_title.data
            meeting.event_date = form.meeting_date.data
            meeting.content = form.content.data
            
            # Mettre à jour l'ordre du jour
            AgendaItem.query.filter_by(announcement_id=meeting_id).delete()
            if form.agenda_items.data:
                agenda_items = form.agenda_items.data.split('\n')
                for item in agenda_items:
                    if item.strip():
                        agenda = AgendaItem(
                            announcement_id=meeting.id,
                            title=item.strip(),
                            is_completed=False
                        )
                        db.session.add(agenda)
            
            db.session.commit()
            
            log_activity(current_user.id, current_user.role, f"Modification PV réunion #{meeting_id}", request.remote_addr)
            flash('Procès-verbal modifié avec succès !', 'success')
            return redirect(url_for('meeting_detail', meeting_id=meeting.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur : {str(e)}', 'danger')
    else:
        # Afficher les erreurs de validation
        for field, errors in form.errors.items():
            for error in errors:
                field_label = getattr(form, field).label.text if hasattr(form, field) else field
                flash(f'Erreur dans le champ "{field_label}": {error}', 'danger')
    
    # Pré-remplir le formulaire pour la méthode GET
    if request.method == 'GET':
        form.meeting_title.data = meeting.title
        form.meeting_date.data = meeting.event_date
        form.content.data = meeting.content
        agenda_list = '\n'.join([item.title for item in meeting.agenda_items])
        form.agenda_items.data = agenda_list
    
    return render_template('meeting_form.html', title="Modifier le PV", form=form, meeting=meeting)


@app.route('/meetings/<int:meeting_id>/attendance', methods=['GET', 'POST'])
@login_required
@role_required(['SECRETAIRE', 'PRESIDENT'])
def manage_attendance(meeting_id):
    """Gérer les présences à une réunion"""
    meeting = db.get_or_404(Announcement, meeting_id)
    members = Member.query.filter_by(is_active=True, status='ACTIF').order_by(Member.last_name).all()
    
    if request.method == 'POST':
        try:
            # Supprimer les anciennes présences
            MeetingAttendanceDetail.query.filter_by(announcement_id=meeting_id).delete()
            
            # Enregistrer les nouvelles présences avec validation
            for member in members:
                status = request.form.get(f'attendance_{member.id}', 'ABSENT')
                # Validation du statut
                if status not in ['PRESENT', 'ABSENT', 'RETARD', 'EXCUSE']:
                    status = 'ABSENT'
                
                attendance = MeetingAttendanceDetail(
                    announcement_id=meeting_id,
                    member_id=member.id,
                    attendance_status=status
                )
                db.session.add(attendance)
            
            db.session.commit()
            flash('Présences enregistrées avec succès !', 'success')
            return redirect(url_for('meeting_detail', meeting_id=meeting_id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de l\'enregistrement des présences : {str(e)}', 'danger')
    
    # Récupérer les présences existantes
    existing_attendances = {
        a.member_id: a.attendance_status 
        for a in MeetingAttendanceDetail.query.filter_by(announcement_id=meeting_id).all()
    }
    
    return render_template('meeting_attendance.html', 
                           meeting=meeting, 
                           members=members, 
                           attendances=existing_attendances)


@app.route('/meetings/<int:meeting_id>/delete', methods=['POST'])
@login_required
@role_required(['SECRETAIRE', 'PRESIDENT'])
def delete_meeting(meeting_id):
    """Supprimer une réunion"""
    meeting = db.get_or_404(Announcement, meeting_id)
    
    # Vérifier le token CSRF
    csrf_token = request.form.get('csrf_token')
    if not csrf_token:
        flash('Token CSRF manquant.', 'danger')
        return redirect(url_for('meetings'))
    
    try:
        db.session.delete(meeting)
        db.session.commit()
        
        log_activity(current_user.id, current_user.role, f"Suppression réunion #{meeting_id}", request.remote_addr)
        flash('La réunion a été supprimée avec succès.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Erreur lors de la suppression : {str(e)}', 'danger')
    
    return redirect(url_for('meetings'))
# ============================================================
# GESTION DES ANNONCES
# ============================================================

@app.route('/annonces')
@login_required
def annonces():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    pagination = Announcement.query.filter(Announcement.announcement_type.in_(['INFO', 'URGENT', 'RAPPEL'])).order_by(Announcement.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    pagination_data = get_pagination_data(pagination)
    return render_template('annonces.html', annonces=pagination_data['items'], pagination=pagination_data)

@app.route('/annonces/add', methods=['GET', 'POST'])
@login_required
@role_required(['SECRETAIRE', 'PRESIDENT', 'COMMUNICATION'])
def add_annonce():
    form = AnnouncementForm()
    
    if form.validate_on_submit():
        try:
            annonce = Announcement(
                title=form.title.data,
                content=form.content.data,
                announcement_type=form.announcement_type.data,
                event_date=form.event_date.data,
                created_by=current_user.id,
                created_at=datetime.now(),
                is_active=True
            )
            
            db.session.add(annonce)
            db.session.commit()
            
            log_activity(current_user.id, current_user.role, f"Création: {annonce.title}", request.remote_addr)
            flash("L'annonce a été publiée avec succès !", "success")
            return redirect(url_for('annonces'))
            
        except Exception as e:
            db.session.rollback()
            flash(f"Erreur technique : {str(e)}", "danger")
    
    return render_template('annonce_form.html', form=form, title="Publier une annonce")
  


@app.route('/annonces/<int:annonce_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required(['SECRETAIRE', 'PRESIDENT', 'COMMUNICATION'])
def edit_annonce(annonce_id):
    """Modifier une annonce existante"""
    annonce = db.get_or_404(Announcement, annonce_id)
    form = AnnouncementForm(obj=annonce)
    
    if form.validate_on_submit():
        try:
            annonce.title = form.title.data
            annonce.content = form.content.data
            annonce.announcement_type = form.announcement_type.data
            annonce.event_date = form.event_date.data if form.event_date.data else None
            
            db.session.commit()
            
            log_activity(current_user.id, current_user.role, f"Modification annonce #{annonce_id}", request.remote_addr)
            flash("L'annonce a été modifiée avec succès !", "success")
            return redirect(url_for('annonces'))
            
        except Exception as e:
            db.session.rollback()
            flash(f"Erreur technique : {str(e)}", "danger")
    
    return render_template('annonce_form.html', form=form, annonce=annonce, title="Modifier l'annonce")


@app.route('/annonces/<int:annonce_id>/delete', methods=['POST'])
@login_required
@role_required(['SECRETAIRE', 'PRESIDENT'])
def delete_annonce(annonce_id):
    """Supprimer une annonce"""
    annonce = db.get_or_404(Announcement, annonce_id)
    
    try:
        db.session.delete(annonce)
        db.session.commit()
        
        log_activity(current_user.id, current_user.role, f"Suppression annonce #{annonce_id}", request.remote_addr)
        flash("L'annonce a été supprimée avec succès.", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"Erreur lors de la suppression : {str(e)}", "danger")
    
    return redirect(url_for('annonces'))
# ============================================================
# CYCLES DE TONTINE
# ============================================================
# Un cycle = une rotation sur un NIVEAU de cotisation (rubrique de catégorie
# TONTINE : 1 000, 10 000, 20 000 FCFA...). Plusieurs cycles peuvent tourner
# en parallèle (un par niveau). Chaque membre y prend une ou plusieurs
# « mains » (parts) : la taille du cycle est le nombre total de mains, et
# chaque main reçoit une fois la cagnotte (= montant x nombre de mains).
# Attribution : tirage au sort de l'ordre, ou enchères à chaque tour.

CYCLE_MANAGERS = ['PRESIDENT', 'SECRETAIRE', 'TRESORIER']
MAX_HANDS = 10


def tontine_levels(active_only=True):
    """Niveaux de cotisation tontine (rubriques de catégorie TONTINE)"""
    query = ContributionType.query.filter_by(category='TONTINE')
    if active_only:
        query = query.filter_by(is_active=True)
    return query.order_by(ContributionType.amount, ContributionType.id).all()


def _payment_mode_from_form():
    mode = request.form.get('payment_mode', 'ESPECE')
    return mode if mode in finance.PAYMENT_MODES else 'ESPECE'


def _payment_reference_from_form():
    return (request.form.get('payment_reference') or '').strip()[:60] or None


@app.route('/tontine-cycles')
@login_required
def tontine_cycles():
    cycles = TontineCycleDetail.query.order_by(TontineCycleDetail.start_date.desc(), TontineCycleDetail.id.desc()).all()
    active_cycles = [c for c in cycles if c.status == 'EN_COURS']
    past_cycles = [c for c in cycles if c.status != 'EN_COURS']
    my_parts = {}
    if current_user.member_id:
        for p in CycleParticipant.query.filter_by(member_id=current_user.member_id).all():
            my_parts.setdefault(p.cycle_id, []).append(p)
    return render_template('tontine_cycles.html', active_cycles=active_cycles, past_cycles=past_cycles,
                           my_parts=my_parts, can_manage=current_user.role in CYCLE_MANAGERS,
                           levels=tontine_levels())


@app.route('/tontine-cycles/add', methods=['GET', 'POST'])
@login_required
@role_required(['PRESIDENT', 'SECRETAIRE'])
def add_tontine_cycle():
    tontine = current_tontine()
    ensure_contribution_types(tontine)
    levels = tontine_levels()
    members_list = Member.query.filter_by(is_active=True, status='ACTIF').order_by(Member.last_name, Member.first_name).all()

    def form_page(form_data):
        return render_template('tontine_cycle_form.html', levels=levels, members_list=members_list,
                               modes=finance.CYCLE_MODES, form_data=form_data, max_hands=MAX_HANDS,
                               frequency_days=finance.FREQUENCY_DAYS, today=date.today().isoformat())

    if request.method == 'GET':
        return form_page({})

    f = request.form
    errors = []
    level = None
    level_id = f.get('contribution_type_id', type=int)
    if level_id:
        level = ContributionType.query.filter_by(id=level_id, category='TONTINE').first()
        if not level:
            errors.append('Niveau de cotisation introuvable.')
    amount = Decimal(str(level.amount)) if level and level.amount else _parse_decimal(f.get('custom_amount') or '0', 0, 100_000_000)
    if not amount or amount <= 0:
        errors.append('Choisissez un niveau de cotisation ou saisissez un montant.')
    mode = f.get('mode', 'TIRAGE')
    if mode not in finance.CYCLE_MODES:
        errors.append("Mode d'attribution invalide.")
    frequency_days = f.get('frequency_days', type=int) or (finance.FREQUENCY_DAYS.get(level.frequency, 14) if level else 14)
    if not 1 <= frequency_days <= 366:
        errors.append('Écart entre deux tours invalide (1 à 366 jours).')
    try:
        start_date = datetime.strptime(f.get('start_date') or date.today().isoformat(), '%Y-%m-%d').date()
    except ValueError:
        errors.append('Date de début invalide.')
        start_date = date.today()

    # Mains par membre (0 = ne participe pas). Les identifiants inconnus sont ignorés.
    hands = []
    for member in members_list:
        n = f.get(f'hands_{member.id}', type=int) or 0
        if n < 0 or n > MAX_HANDS:
            errors.append(f'{member.full_name} : nombre de mains entre 0 et {MAX_HANDS}.')
            continue
        if n:
            hands.append((member, n))
    total_parts = sum(n for _, n in hands)
    if total_parts < 2:
        errors.append('Il faut au moins 2 mains au total pour lancer un cycle.')
    if level and TontineCycleDetail.query.filter_by(status='EN_COURS', contribution_type_id=level.id).first():
        errors.append(f"Un cycle « {level.name} » est déjà en cours : terminez-le ou choisissez un autre niveau.")
    if errors:
        for e in errors:
            flash(e, 'danger')
        return form_page(f)

    last_cycle = TontineCycleDetail.query.order_by(TontineCycleDetail.cycle_number.desc()).first()
    cycle = TontineCycleDetail(
        cycle_number=(last_cycle.cycle_number + 1) if last_cycle else 1,
        group_type=str(total_parts)[:5],  # colonne historique : nombre de mains
        amount_per_member=amount,
        total_amount=amount * total_parts,
        start_date=start_date,
        end_date=start_date + timedelta(days=frequency_days * (total_parts - 1)),
        status='EN_COURS',
        created_by=current_user.id,
        contribution_type_id=level.id if level else None,
        mode=mode,
        frequency_days=frequency_days,
        label=(f.get('label') or '').strip()[:100] or None,
    )
    for member, n in hands:
        for hand in range(1, n + 1):
            cycle.participants.append(CycleParticipant(member_id=member.id, hand_number=hand))
    db.session.add(cycle)
    db.session.commit()
    log_activity(current_user.id, current_user.role,
                 f"Création {cycle.display_name} ({total_parts} mains, {amount:,.0f} FCFA)", request.remote_addr)
    flash(f"{cycle.display_name} créé : {total_parts} mains, cagnotte de {cycle.total_amount:,.0f} FCFA par tour.", 'success')

    if mode == 'TIRAGE' and f.get('draw_now') == 'on':
        draw = perform_draw(cycle, 'Tirage à la création du cycle')
        return redirect(url_for('tirage_cycle', cycle_id=cycle.id, reveal=draw.id))
    return redirect(url_for('tontine_cycle_detail', cycle_id=cycle.id))


def cycle_contribution_status(cycle, through_turn=None):
    """État des cotisations d'un cycle, membre par membre, jusqu'au tour `through_turn`
    (par défaut : le tour en cours, ou le dernier tour si le cycle est terminé).
    Chaque main doit avoir versé `amount_per_member` à chaque tour, rappel d'entrée compris."""
    if through_turn is None:
        through_turn = cycle.beneficiaries_count + (1 if cycle.status == 'EN_COURS' else 0)
    amount = Decimal(str(cycle.amount_per_member))
    hands = {}
    for p in cycle.participants:
        hands[p.member_id] = hands.get(p.member_id, 0) + 1
    # Payé = cotisations du cycle - avances déjà rendues (ou versées en épargne)
    paid = {}
    for member_id, typ, total in db.session.query(Transaction.member_id, Transaction.type, db.func.sum(Transaction.amount)).filter(
            Transaction.cycle_id == cycle.id, Transaction.type.in_(['TONTINE', 'RESTITUTION_TONTINE'])
    ).group_by(Transaction.member_id, Transaction.type).all():
        sign = -1 if typ == 'RESTITUTION_TONTINE' else 1
        paid[member_id] = paid.get(member_id, Decimal('0')) + sign * Decimal(str(total or 0))
    served = cycle.beneficiaries_count   # tours dont la cagnotte est déjà versée
    rows = []
    for member_id, n in hands.items():
        member = db.session.get(Member, member_id)
        expected = amount * n * through_turn
        got = paid.get(member_id, Decimal('0'))
        late = max(amount * n * min(served, through_turn) - got, Decimal('0'))   # tours déjà versés non payés
        rows.append({'member': member, 'hands': n, 'expected': expected, 'paid': got, 'gap': got - expected,
                     'late': late,                                                    # vrai retard
                     'current_due': max(expected - got, Decimal('0')) - late,         # reste du tour en cours
                     'advance': max(got - expected, Decimal('0'))})                   # payé en trop
    rows.sort(key=lambda r: (r['gap'] >= 0, r['member'].last_name.lower() if r['member'] else ''))
    missing = sum((-r['gap'] for r in rows if r['gap'] < 0), Decimal('0'))
    return {'turn': through_turn, 'rows': rows, 'missing': missing, 'served': served,
            'late_total': sum((r['late'] for r in rows), Decimal('0')),
            'current_total': sum((r['current_due'] for r in rows), Decimal('0')),
            'advance_total': sum((r['advance'] for r in rows), Decimal('0'))}


@app.route('/tontine-cycles/<int:cycle_id>/regulariser', methods=['POST'])
@login_required
@role_required(CYCLE_MANAGERS)
def regularize_cycle(cycle_id):
    """Régulariser l'écart d'un membre sur un cycle (en cours ou terminé) :
    - encaisser : rattrapage de cotisations en retard / du tour en cours ;
    - rendre : l'avance (payé en trop) est rendue au membre ;
    - epargne : l'avance est versée dans l'épargne du membre."""
    cycle = db.get_or_404(TontineCycleDetail, cycle_id)
    back = redirect(url_for('tontine_cycle_detail', cycle_id=cycle.id) + '#etatCotisations')
    member_id = request.form.get('member_id', type=int)
    row = next((r for r in cycle_contribution_status(cycle)['rows'] if r['member'] and r['member'].id == member_id), None)
    if row is None:
        flash("Ce membre ne participe pas à ce cycle.", 'danger')
        return back
    action = request.form.get('action')
    amount = _parse_decimal(request.form.get('amount') or '', 1, 100_000_000)
    limit = -row['gap'] if action == 'encaisser' else row['advance']
    if amount is None or limit <= 0 or amount > limit:
        flash(f"Montant invalide : il doit être compris entre 1 et {_fmt(max(limit, 0))} FCFA.", 'danger')
        return back
    payment_mode = _payment_mode_from_form()
    reference = _payment_reference_from_form()
    member = row['member']
    if action == 'encaisser':
        db.session.add(Transaction(member_id=member.id, type='TONTINE', amount=amount, date=date.today(), cycle_id=cycle.id,
                                   contribution_type_id=cycle.contribution_type_id, payment_mode=payment_mode,
                                   payment_reference=reference, created_by=current_user.id,
                                   description=f"Rattrapage de cotisations - {cycle.display_name}"))
        message = f"{_fmt(amount)} FCFA de cotisations encaissés pour {member.full_name}."
    elif action in ('rendre', 'epargne'):
        db.session.add(Transaction(member_id=member.id, type='RESTITUTION_TONTINE', amount=amount, date=date.today(),
                                   cycle_id=cycle.id, payment_mode=payment_mode, created_by=current_user.id,
                                   description=(f"Avance rendue - {cycle.display_name}" if action == 'rendre'
                                                else f"Avance versée en épargne - {cycle.display_name}")))
        if action == 'epargne':
            db.session.add(Transaction(member_id=member.id, type='EPARGNE', amount=amount, date=date.today(),
                                       payment_mode=payment_mode, created_by=current_user.id,
                                       description=f"Avance de tontine versée en épargne ({cycle.display_name})"))
            message = f"{_fmt(amount)} FCFA d'avance versés dans l'épargne de {member.full_name}."
        else:
            message = f"{_fmt(amount)} FCFA d'avance rendus à {member.full_name}."
    else:
        abort(400)
    db.session.commit()
    log_activity(current_user.id, current_user.role, f"Régularisation {cycle.display_name} : {message}", request.remote_addr)
    flash(message, 'success')
    return back


def cycle_next_steps(cycle, contrib):
    """Cycle terminé : étapes à faire ensuite, cochées automatiquement quand elles sont faites"""
    def total(types):
        return Decimal(str(db.session.query(db.func.sum(Transaction.amount)).filter(
            Transaction.cycle_id == cycle.id, Transaction.type.in_(types)).scalar() or 0))
    fund = total(['TONTINE']) - total(['RESTITUTION_TONTINE', 'BENEFICE_TONTINE'])
    member_ids = list({p.member_id for p in cycle.participants})
    fines = Decimal(str(db.session.query(db.func.sum(Sanction.amount)).filter(
        Sanction.member_id.in_(member_ids), Sanction.status == 'PENDING').scalar() or 0)) if member_ids else Decimal('0')
    next_cycle = TontineCycleDetail.query.filter(TontineCycleDetail.contribution_type_id == cycle.contribution_type_id,
                                                 TontineCycleDetail.cycle_number > cycle.cycle_number).first()
    late_and_advance = contrib['late_total'] + contrib['advance_total']
    return [
        {'done': late_and_advance == 0, 'title': 'Solder les cotisations du cycle',
         'detail': 'Tout le monde est à jour.' if late_and_advance == 0 else
         f"{_fmt(contrib['late_total'])} FCFA en retard et {_fmt(contrib['advance_total'])} FCFA d'avance à régulariser "
         "(bouton « Régulariser » dans l'état des cotisations).",
         'url': '#etatCotisations', 'link': "Voir l'état des cotisations"},
        {'done': fund == 0, 'title': 'Vérifier que la caisse du cycle est à 0',
         'detail': 'Tout ce qui est entré a été reversé aux bénéficiaires.' if fund == 0 else
         f"Solde de {_fmt(fund)} FCFA : " + ('des cotisations ont été versées sans être encaissées.' if fund < 0
                                            else "de l'argent reste à reverser ou à rendre."),
         'url': '#etatCotisations', 'link': 'Régulariser'},
        {'done': fines == 0, 'title': 'Encaisser les amendes des participants',
         'detail': 'Aucune amende en attente.' if fines == 0 else f"{_fmt(fines)} FCFA d'amendes encore à payer.",
         'url': url_for('sanctions'), 'link': 'Voir les sanctions'},
        {'done': next_cycle is not None, 'title': 'Lancer le cycle suivant',
         'detail': f"{next_cycle.display_name} a été créé." if next_cycle else
         'Même niveau ou un autre ; les mains peuvent changer et de nouveaux membres peuvent entrer. Faites ensuite le tirage.',
         'url': url_for('tontine_cycle_detail', cycle_id=next_cycle.id) if next_cycle else url_for('add_tontine_cycle'),
         'link': 'Ouvrir le nouveau cycle' if next_cycle else 'Nouveau cycle'},
    ]


@app.route('/tontine-cycles/<int:cycle_id>')
@login_required
def tontine_cycle_detail(cycle_id):
    cycle = db.get_or_404(TontineCycleDetail, cycle_id)
    beneficiaries = CycleBeneficiary.query.filter_by(cycle_id=cycle_id).order_by(CycleBeneficiary.position).all()
    next_participant = cycle.get_next_participant()
    pending_sanctions = Decimal('0')
    if next_participant:
        pending_sanctions = Decimal(str(db.session.query(db.func.sum(Sanction.amount)).filter(
            Sanction.member_id == next_participant.member_id, Sanction.status == 'PENDING').scalar() or 0))
    collected = Decimal(str(db.session.query(db.func.sum(Transaction.amount)).filter(
        Transaction.cycle_id == cycle.id, Transaction.type == 'TONTINE').scalar() or 0))
    # Regroupement des mains par membre
    holders = {}
    for p in cycle.participants:
        holders.setdefault(p.member_id, {'member': p.member, 'parts': []})['parts'].append(p)
    contrib = cycle_contribution_status(cycle)
    return render_template('tontine_cycle_detail.html', cycle=cycle, beneficiaries=beneficiaries,
                           next_steps=cycle_next_steps(cycle, contrib) if cycle.status == 'TERMINE' else None,
                           next_participant=next_participant, next_beneficiary=next_participant.member if next_participant else None,
                           pending_sanctions=pending_sanctions, collected=collected,
                           holders=sorted(holders.values(), key=lambda h: h['member'].last_name.lower()),
                           can_manage=current_user.role in CYCLE_MANAGERS, payment_modes=finance.PAYMENT_MODES,
                           join_candidates=Member.query.filter_by(is_active=True, status='ACTIF')
                           .order_by(Member.last_name, Member.first_name).all(),
                           hands_by_member={h['member'].id: len(h['parts']) for h in holders.values()},
                           max_hands=MAX_HANDS, contrib=contrib)


@app.route('/tontine-cycles/<int:cycle_id>/register-benefit', methods=['GET', 'POST'])
@login_required
@role_required(CYCLE_MANAGERS)
def register_benefit(cycle_id):
    """Verse la cagnotte du tour : au prochain de l'ordre tiré, ou au gagnant de l'enchère"""
    cycle = db.get_or_404(TontineCycleDetail, cycle_id)
    back = redirect(url_for('tontine_cycle_detail', cycle_id=cycle.id))
    if request.method == 'GET':
        return back

    # Versement fait depuis la feuille d'une séance : on y revient et les écritures y sont rattachées
    seance = None
    seance_id = request.form.get('seance_id', type=int)
    if seance_id:
        seance = Seance.query.filter_by(id=seance_id).first()
        if seance is None:
            abort(404)
        back = redirect(url_for('seance_detail', seance_id=seance.id) + '#cagnottes')
        if seance.is_closed:
            flash('Cette séance est clôturée : rouvrez-la pour verser une cagnotte.', 'warning')
            return back
        if f'c{cycle.id}' not in (seance.columns or '').split(','):
            flash("Ce cycle ne fait pas partie de cette séance.", 'danger')
            return back

    if cycle.status != 'EN_COURS':
        flash('Ce cycle est terminé.', 'warning')
        return back

    expected_turn = request.form.get('expected_turn', type=int)
    if expected_turn is not None and expected_turn != cycle.beneficiaries_count + 1:
        flash("Ce tour a déjà été enregistré (double clic ou page ancienne) : rien n'a été versé une seconde fois.", 'warning')
        return back

    gross = Decimal(str(cycle.total_amount))
    bid = Decimal('0')
    if cycle.is_auction:
        pid = request.form.get('participant_id', type=int)
        participant = CycleParticipant.query.filter_by(id=pid, cycle_id=cycle.id, served=False).first()
        if not participant:
            flash("Choisissez le gagnant de l'enchère parmi les mains qui n'ont pas encore reçu la cagnotte.", 'danger')
            return back
        bid = _parse_decimal(request.form.get('bid_amount') or '0', 0, gross)
        if bid is None or bid >= gross:
            flash("Mise invalide : elle doit être positive et inférieure à la cagnotte.", 'danger')
            return back
    else:
        participant = cycle.get_next_participant()
        if not participant:
            if cycle.needs_draw:
                flash("L'ordre de passage n'est pas encore tiré : faites d'abord le tirage au sort.", 'warning')
                return redirect(url_for('tirage_cycle', cycle_id=cycle.id))
            flash('Toutes les mains ont déjà reçu la cagnotte.', 'warning')
            return back

    member = participant.member
    payment_mode = _payment_mode_from_form()
    reference = _payment_reference_from_form()

    # Les cotisations du tour doivent être enregistrées avant de verser la cagnotte
    status = cycle_contribution_status(cycle)
    late = [r for r in status['rows'] if r['gap'] < 0]
    if late:
        if request.form.get('confirm_offline') != 'on':
            def fcfa(v):
                return f"{v:,.0f}".replace(',', ' ')
            names = ', '.join(f"{r['member'].full_name} : {fcfa(-r['gap'])}" for r in late[:6])
            flash(f"Cotisations non enregistrées jusqu'au tour {status['turn']} : {fcfa(status['missing'])} FCFA ({names}). "
                  "Encaissez-les d'abord (séance ou transaction), ou cochez « encaissées hors application ».", 'danger')
            return back
        for r in late:   # régularisation : les cotisations déclarées encaissées sont enregistrées
            db.session.add(Transaction(member_id=r['member'].id, type='TONTINE', amount=-r['gap'], date=date.today(),
                                       cycle_id=cycle.id, contribution_type_id=cycle.contribution_type_id,
                                       description=f"Régularisation {cycle.display_name} : cotisations jusqu'au tour "
                                                   f"{status['turn']} encaissées hors application",
                                       created_by=current_user.id, payment_mode=payment_mode,
                                       seance_id=seance.id if seance else None))

    # Retenue des amendes impayées (elles sont alors soldées), dans la limite de la cagnotte
    deducted = Decimal('0')
    if request.form.get('deduct_sanctions') == 'on':
        for sanction in Sanction.query.filter_by(member_id=member.id, status='PENDING').order_by(Sanction.sanction_date).all():
            amount = Decimal(str(sanction.amount))
            if bid + deducted + amount > gross:
                break
            sanction.status = 'PAID'
            deducted += amount
            db.session.add(Transaction(member_id=member.id, type='SANCTION', amount=amount, date=date.today(),
                                       description=f"Amende #{sanction.id} retenue sur la cagnotte ({cycle.display_name})",
                                       created_by=current_user.id, payment_mode=payment_mode, cycle_id=cycle.id,
                                       seance_id=seance.id if seance else None))
    net = gross - bid - deducted
    position = cycle.beneficiaries_count + 1 if cycle.is_auction else participant.position

    beneficiary = CycleBeneficiary(cycle_id=cycle.id, member_id=member.id, position=position or 0, gross_amount=gross,
                                   net_amount=net, sanctions_deducted=deducted, benefit_date=date.today(),
                                   payment_status='PAYE', payment_mode=payment_mode, transaction_id=reference,
                                   participant_id=participant.id, bid_amount=bid if bid > 0 else None)
    db.session.add(beneficiary)
    participant.served = True
    participant.served_at = date.today()
    if cycle.is_auction:
        participant.position = position

    # Comptabilité : la cagnotte brute sort du fonds tontine ; mise et amendes reviennent en caisse
    db.session.add(Transaction(member_id=member.id, type='BENEFICE_TONTINE', amount=gross, date=date.today(),
                               description=f"Cagnotte {cycle.display_name} - tour {position}",
                               created_by=current_user.id, payment_mode=payment_mode,
                               payment_reference=reference, cycle_id=cycle.id, seance_id=seance.id if seance else None))
    if bid > 0:
        db.session.add(Transaction(member_id=member.id, type='ENCHERE', amount=bid, date=date.today(),
                                   description=f"Mise d'enchère retenue - {cycle.display_name} - tour {position}",
                                   created_by=current_user.id, payment_mode=payment_mode, cycle_id=cycle.id,
                                   seance_id=seance.id if seance else None))

    if all(p.served for p in cycle.participants):
        cycle.status = 'TERMINE'
        cycle.end_date = date.today()
    db.session.commit()

    log_activity(current_user.id, current_user.role,
                 f"Cagnotte {cycle.display_name} tour {position} : {participant.label}, net {net:,.0f} FCFA", request.remote_addr)
    details = []
    if bid > 0:
        details.append(f"mise {bid:,.0f}")
    if deducted > 0:
        details.append(f"amendes {deducted:,.0f}")
    flash(f"Cagnotte du tour {position} versée à {participant.label} : {net:,.0f} FCFA à remettre"
          + (f" ({gross:,.0f} − {' − '.join(details)})" if details else '') + '.', 'success')
    return back


@app.route('/tontine-cycles/<int:cycle_id>/participants/add', methods=['POST'])
@login_required
@role_required(CYCLE_MANAGERS)
def add_cycle_participant(cycle_id):
    """Ajoute un membre (une ou plusieurs mains) à un cycle déjà commencé.
    Condition : il paie le RAPPEL, c'est-à-dire ce que chaque main a déjà cotisé
    (cotisation x mains x tours déjà versés). Par défaut le rappel est reversé
    aux mains déjà servies, qui avaient reçu une cagnotte sans sa part."""
    cycle = db.get_or_404(TontineCycleDetail, cycle_id)
    back = redirect(url_for('tontine_cycle_detail', cycle_id=cycle.id))
    if cycle.status != 'EN_COURS':
        flash("On ne peut rejoindre qu'un cycle en cours.", 'warning')
        return back

    member = db.session.get(Member, request.form.get('member_id', type=int) or 0)
    hands = request.form.get('hands', type=int) or 0
    if not member or not member.is_active or member.status != 'ACTIF':
        flash('Choisissez un membre actif.', 'danger')
        return back
    existing = [p for p in cycle.participants if p.member_id == member.id]
    if not 1 <= hands <= MAX_HANDS - len(existing):
        flash(f"Nombre de mains invalide (maximum {MAX_HANDS} mains par membre dans un cycle).", 'danger')
        return back

    amount = Decimal(str(cycle.amount_per_member))
    tours_done = cycle.beneficiaries_count
    include_current = request.form.get('include_current') == 'on'
    past_rappel = amount * hands * tours_done            # ce que chaque main a déjà versé
    current_share = amount * hands if include_current else Decimal('0')
    total_due = past_rappel + current_share
    expected = _parse_decimal(request.form.get('expected_total') or '', 0, 10 ** 12)
    if expected is not None and expected != total_due:
        flash("Le cycle a changé entre-temps (un tour vient d'être versé) : vérifiez le nouveau montant du rappel.", 'warning')
        return back
    if total_due > 0 and request.form.get('confirm_paid') != 'on':
        flash(f"Le rappel de {total_due:,.0f} FCFA doit être encaissé avant l'ajout : cochez la confirmation.".replace(',', ' '), 'danger')
        return back
    destination = request.form.get('destination', 'BENEFICIAIRES')
    if destination not in ('BENEFICIAIRES', 'CAISSE'):
        destination = 'BENEFICIAIRES'
    payment_mode = _payment_mode_from_form()
    reference = _payment_reference_from_form()

    # 1) Nouvelles mains : en mode tirage, elles passent après toutes les mains déjà inscrites
    positions = [p.position for p in cycle.participants if p.position is not None]
    next_position = (max(positions) + 1) if positions and not cycle.needs_draw and not cycle.is_auction else None
    first_hand = max([p.hand_number or 1 for p in existing], default=0) + 1
    for i in range(hands):
        cycle.participants.append(CycleParticipant(
            member_id=member.id, hand_number=first_hand + i,
            position=(next_position + i) if next_position is not None else None))

    # 2) Encaissement du rappel (et éventuellement de la cotisation du tour en cours)
    label = f"{hands} main(s)"
    if past_rappel > 0:
        db.session.add(Transaction(member_id=member.id, type='TONTINE', amount=past_rappel, date=date.today(),
                                   cycle_id=cycle.id, contribution_type_id=cycle.contribution_type_id,
                                   description=f"Rappel d'entrée {cycle.display_name} : {tours_done} tour(s) x {label}",
                                   created_by=current_user.id, payment_mode=payment_mode, payment_reference=reference))
    if current_share > 0:
        db.session.add(Transaction(member_id=member.id, type='TONTINE', amount=current_share, date=date.today(),
                                   cycle_id=cycle.id, contribution_type_id=cycle.contribution_type_id,
                                   description=f"Cotisation du tour {tours_done + 1} ({label}) - {cycle.display_name}",
                                   created_by=current_user.id, payment_mode=payment_mode, payment_reference=reference))

    # 3) Reversement du rappel : chaque main déjà servie reçoit la part qui manquait à sa cagnotte
    complement = amount * hands
    paid_back = Decimal('0')
    if past_rappel > 0 and destination == 'BENEFICIAIRES':
        for beneficiary in CycleBeneficiary.query.filter_by(cycle_id=cycle.id).order_by(CycleBeneficiary.position).all():
            beneficiary.gross_amount = Decimal(str(beneficiary.gross_amount)) + complement
            beneficiary.net_amount = Decimal(str(beneficiary.net_amount)) + complement
            db.session.add(Transaction(member_id=beneficiary.member_id, type='BENEFICE_TONTINE', amount=complement,
                                       date=date.today(), cycle_id=cycle.id,
                                       description=f"Complément de cagnotte (tour {beneficiary.position}) : rappel de {member.full_name}",
                                       created_by=current_user.id, payment_mode=payment_mode))
            paid_back += complement

    # 4) Le cycle grandit : cagnotte des prochains tours et date de fin recalculées
    parts = len(cycle.participants)
    cycle.group_type = str(parts)[:5]
    cycle.total_amount = amount * parts
    cycle.end_date = cycle.start_date + timedelta(days=(cycle.frequency_days or 14) * (parts - 1))
    db.session.commit()

    log_activity(current_user.id, current_user.role,
                 f"{member.full_name} rejoint {cycle.display_name} ({label}), rappel {total_due:,.0f} FCFA", request.remote_addr)
    message = f"{member.full_name} rejoint le cycle avec {label}. Rappel encaissé : {total_due:,.0f} FCFA."
    if paid_back:
        message += f" À reverser aux bénéficiaires déjà servis : {paid_back:,.0f} FCFA ({complement:,.0f} par main servie)."
    elif past_rappel:
        message += " Le rappel reste en caisse."
    flash(message.replace(',', ' '), 'success')
    return back


@app.route('/tontine-cycles/<int:cycle_id>/delete', methods=['POST'])
@login_required
@president_required
def delete_tontine_cycle(cycle_id):
    """Supprimer un cycle (uniquement si aucune cagnotte n'a encore été versée)"""
    cycle = db.get_or_404(TontineCycleDetail, cycle_id)
    if cycle.beneficiaries_count:
        flash("Impossible de supprimer un cycle dont une cagnotte a déjà été versée.", 'danger')
        return redirect(url_for('tontine_cycle_detail', cycle_id=cycle.id))
    for draw in TontineDraw.query.filter_by(cycle_id=cycle.id).all():
        db.session.delete(draw)
    name = cycle.display_name
    db.session.delete(cycle)
    db.session.commit()
    log_activity(current_user.id, current_user.role, f"Suppression {name}", request.remote_addr)
    flash(f'{name} supprimé.', 'success')
    return redirect(url_for('tontine_cycles'))

# ============================================================
# RAPPORTS
# ============================================================

EXPORT_MAX_AGE = 10 * 60  # le lien de téléchargement d'un rapport est valable 10 minutes
REPORT_ROLES = ['SECRETAIRE', 'PRESIDENT', 'TRESORIER']


def _export_serializer():
    return URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='ghelia-report-export')


@app.route('/reports/fichier/<token>')
@login_required
@role_required(REPORT_ROLES)
def report_download(token):
    """Génère le rapport demandé (adresse GET signée, liée à l'utilisateur, valable 10 min)"""
    try:
        data = _export_serializer().loads(token, max_age=EXPORT_MAX_AGE)
    except SignatureExpired:
        flash("Ce lien de rapport a expiré : générez-le de nouveau.", 'warning')
        return redirect(url_for('reports'))
    except BadSignature:
        abort(404)
    if data.get('u') != current_user.id or data.get('k') not in report_export.REPORT_TYPES:
        abort(404)
    start_date, end_date = date.fromisoformat(data['s']), date.fromisoformat(data['e'])
    export_format = data.get('f')
    report = report_export.build_report(data['k'], start_date, end_date)
    tontine_name = current_tontine().name
    filename = report_export.report_filename(data['k'], start_date, end_date)
    log_activity(current_user.id, current_user.role,
                 f"Export {export_format} : {report.title} ({report.period})", request.remote_addr)

    if export_format == 'PRINT':
        # Page web prête à imprimer : aucun fichier transféré, rien à intercepter
        return render_template('report_print.html', report=report, tontine_name=tontine_name,
                               fcfa=report_export._fcfa, cell=report_export._cell_text,
                               generated_by=current_user.member.full_name if current_user.member else current_user.username)
    if export_format == 'PDF':
        pdf = report_export.to_pdf(report, tontine_name, app.config['APP_NAME'],
                                   current_user.member.full_name if current_user.member else current_user.username)
        return send_file(io.BytesIO(pdf), mimetype='application/pdf', as_attachment=False,
                         download_name=f'{filename}.pdf')
    if export_format == 'CSV':
        return send_file(io.BytesIO(report_export.to_csv(report)), mimetype='text/csv; charset=utf-8',
                         as_attachment=True, download_name=f'{filename}.csv')
    return send_file(io.BytesIO(report_export.to_excel(report, tontine_name)),
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name=f'{filename}.xlsx')


@app.route('/reports', methods=['GET', 'POST'])
@login_required
@role_required(['SECRETAIRE', 'PRESIDENT', 'TRESORIER'])
def reports():
    form = ReportForm()
    
    if request.method == 'POST':
        report_type = request.form.get('report_type')
        export_format = (request.form.get('format') or '').upper()
        try:
            start_date = datetime.strptime(request.form.get('start_date') or '', '%Y-%m-%d').date()
            end_date = datetime.strptime(request.form.get('end_date') or '', '%Y-%m-%d').date()
        except ValueError:
            flash("Dates invalides.", "danger")
            return redirect(url_for('reports'))
        if start_date > end_date:
            flash("La date de début doit précéder la date de fin.", "danger")
            return redirect(url_for('reports'))
        if report_type not in report_export.REPORT_TYPES or export_format not in ('PDF', 'PRINT', 'CSV', 'EXCEL'):
            flash("Type de rapport ou format invalide.", "danger")
            return redirect(url_for('reports'))

        # Post/Redirect/Get : le fichier est servi par une adresse GET signée.
        # Les gestionnaires de téléchargement (IDM...) ne savent pas rejouer un POST.
        token = _export_serializer().dumps({'k': report_type, 'f': export_format, 's': start_date.isoformat(),
                                            'e': end_date.isoformat(), 'u': current_user.id})
        return redirect(url_for('report_download', token=token))

    total_members = Member.query.filter_by(is_active=True).count()
    total_transactions = Transaction.query.count()
    active_loans = Loan.query.filter_by(status='ACTIF').count()
    pending_loans = Loan.query.filter_by(status='PENDING').count()
    
    # Toutes les cotisations (tontine, présence, fonds de caisse, épargne, secours...)
    total_contributions = db.session.query(db.func.sum(Transaction.amount)).filter(
        Transaction.type.in_(finance.CONTRIBUTION_CATEGORIES)
    ).scalar() or 0
    total_sanctions = db.session.query(db.func.sum(Sanction.amount)).filter_by(status='PAID').scalar() or 0
    total_loans_given = db.session.query(db.func.sum(Loan.amount)).filter(Loan.status.in_(['ACTIF', 'REMBOURSE'])).scalar() or 0
    total_loans_repaid = db.session.query(db.func.sum(Transaction.amount)).filter_by(type='REMBOURSEMENT').scalar() or 0
    
    transactions_by_type = db.session.query(Transaction.type, db.func.sum(Transaction.amount), db.func.count(Transaction.id)).group_by(Transaction.type).all()
    
    top_contributors = db.session.query(
        Member.first_name, Member.last_name, db.func.sum(Transaction.amount).label('total')
    ).join(Transaction, Member.id == Transaction.member_id).filter(Transaction.type.in_(finance.CONTRIBUTION_CATEGORIES)).group_by(Member.id).order_by(db.text('total DESC')).limit(10).all()
     
    recent_transactions = Transaction.query.order_by(Transaction.date.desc()).limit(10).all()

    return render_template(
        'reports.html', 
        form=form, 
        total_members=total_members,
        total_transactions=total_transactions,
        active_loans=active_loans,
        pending_loans=pending_loans,
        total_contributions=total_contributions,
        total_sanctions=total_sanctions,
        total_loans_given=total_loans_given,
        total_loans_repaid=total_loans_repaid,
        transactions_by_type=transactions_by_type,
        top_contributors=top_contributors,
        recent_transactions=recent_transactions,
        now=datetime.now()
    )


    #============================================================
    #aides
    # ============================================================
# GESTION DES AIDES SOCIALES
# ============================================================

# ============================================================
# AIDES SOCIALES (CAISSE DE SECOURS)
# ============================================================
# Règles (réglables par tontine dans Paramètres) :
#  - membre actif, ancienneté minimale, fonds de caisse payé, à jour de la
#    caisse de secours, pas en statut rouge
#  - montant fixé par le barème de la tontine (montant libre plafonné pour « Autre »)
#  - justificatif obligatoire selon l'événement, déclaration dans un délai fixé
#  - plafond d'aides par an (global et par type), pas deux fois le même événement
#  - double validation président + trésorier ; on ne valide pas sa propre aide
#  - versement seulement si la caisse de secours a les fonds ; amendes retenues

AID_MANAGERS = ['PRESIDENT', 'TRESORIER']
AID_VIEWERS = ['PRESIDENT', 'TRESORIER', 'SECRETAIRE']
DOCUMENT_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'webp'}

DEFAULT_AID_TYPES = [
    ('DECES_MEMBRE', "Décès du membre (versé à l'ayant droit)", 100000, False, True, 0),
    ('DECES_FAMILLE', "Décès du conjoint ou d'un enfant", 50000, False, True, 0),
    ('DECES_PARENT', "Décès d'un parent (père, mère)", 25000, False, True, 0),
    ('MALADIE', 'Maladie / hospitalisation', 15000, False, True, 2),
    ('NAISSANCE', 'Naissance', 10000, False, True, 0),
    ('MARIAGE', 'Mariage', 15000, False, True, 1),
    ('AUTRE', 'Autre (incendie, sinistre...) : montant plafonné', 20000, True, True, 1),
]


def ensure_aid_types(tontine):
    """Crée le barème par défaut si la tontine n'en a pas encore"""
    if AidType.query.filter_by(tontine_id=tontine.id).count():
        return
    for order, (code, name, amount, free, doc, per_year) in enumerate(DEFAULT_AID_TYPES):
        db.session.add(AidType(tontine_id=tontine.id, code=code, name=name, amount=Decimal(amount), free_amount=free,
                               requires_document=doc, max_per_year=per_year, display_order=order))
    db.session.commit()


def aid_rules(tontine):
    """Règles de la tontine, avec les valeurs par défaut pour les tontines créées avant leur ajout"""
    def val(name, default):
        value = getattr(tontine, name)
        return default if value is None else value
    return {
        'seniority_days': val('aid_min_seniority_days', 90),
        'require_fonds_caisse': val('aid_require_fonds_caisse', True),
        'require_secours': val('aid_require_secours', True),
        'declaration_days': val('aid_declaration_days', 30),
        'double_validation': val('aid_double_validation', True),
        'deduct_sanctions': val('aid_deduct_sanctions', True),
        'max_per_year': tontine.max_aid_per_member if tontine.max_aid_per_member is not None else 2,
    }


def _member_paid(member, tx_type):
    return Decimal(str(db.session.query(db.func.sum(Transaction.amount)).filter(
        Transaction.member_id == member.id, Transaction.type == tx_type).scalar() or 0))


def secours_situation(member):
    """(à jour ?, payé, attendu) pour les cotisations de secours obligatoires"""
    rubriques = ContributionType.query.filter(ContributionType.category == 'SECOURS', ContributionType.is_active == True,
                                              ContributionType.is_mandatory == True, ContributionType.amount > 0).all()
    paid = _member_paid(member, 'SECOURS')
    if not rubriques:
        return True, paid, Decimal('0')
    today = date.today()
    expected = Decimal('0')
    for r in rubriques:
        since = max(member.registration_date or today, r.created_at.date() if r.created_at else today)
        if r.frequency == 'UNIQUE':
            periods = 1
        elif r.frequency == 'PAR_SEANCE':
            periods = Seance.query.filter(Seance.date >= since, Seance.date <= today).count()
        elif r.frequency in finance.FREQUENCY_DAYS:
            periods = max((today - since).days // finance.FREQUENCY_DAYS[r.frequency], 0)  # périodes échues
        else:
            periods = 0
        expected += Decimal(str(r.amount)) * periods
    return paid >= expected, paid, expected


def aid_eligibility(member, tontine):
    """Liste des conditions [(respectée ?, libellé, détail)]"""
    rules = aid_rules(tontine)
    checks = [(member.is_active and member.status == 'ACTIF', 'Membre actif',
               'oui' if member.is_active and member.status == 'ACTIF' else 'non')]
    seniority = (date.today() - (member.registration_date or date.today())).days
    checks.append((seniority >= rules['seniority_days'], f"Ancienneté d'au moins {rules['seniority_days']} jours",
                   f"{seniority} jour(s)"))
    if rules['require_fonds_caisse']:
        due = Decimal(str(tontine.fonds_caisse_amount or 0))
        paid = _member_paid(member, 'FONDS_CAISSE')
        checks.append((paid >= due and (due > 0 or paid > 0 or due == 0), 'Fonds de caisse payé',
                       f"{paid:,.0f} / {due:,.0f} FCFA".replace(',', ' ')))
    if rules['require_secours']:
        ok, paid, expected = secours_situation(member)
        checks.append((ok, 'À jour de la caisse de secours', f"{paid:,.0f} / {expected:,.0f} FCFA".replace(',', ' ')))
    checks.append((member.tontine_status != 'ROUGE', 'Pas en statut rouge (suspendu)',
                   {'VERT': 'en règle', 'ORANGE': 'avertissement', 'ROUGE': 'suspendu'}.get(member.tontine_status, 'en règle')))
    return checks


def _save_aid_document(file):
    """Justificatif rangé HORS du dossier public : instance/justificatifs/<tontine>/"""
    if not file or not file.filename:
        return None
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in DOCUMENT_EXTENSIONS:
        return None
    folder = os.path.join(BASE_DIR, 'instance', 'justificatifs', str(g.tenant_id))
    os.makedirs(folder, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext}"
    file.save(os.path.join(folder, name))
    return f"{g.tenant_id}/{name}"


def _secours_balance():
    rows = dict(db.session.query(Transaction.type, db.func.sum(Transaction.amount))
                .filter(Transaction.type.in_(['SECOURS', 'AIDE'])).group_by(Transaction.type).all())
    return Decimal(str(rows.get('SECOURS') or 0)) - Decimal(str(rows.get('AIDE') or 0))


@app.route('/aides')
@login_required
def aides():
    tontine = current_tontine()
    ensure_aid_types(tontine)
    rules = aid_rules(tontine)
    status_filter = request.args.get('status', '')
    is_bureau = current_user.role in AID_VIEWERS
    query = Aide.query
    if not is_bureau:
        query = query.filter_by(member_id=current_user.member_id)
    if status_filter == 'PAID':
        query = query.filter_by(is_paid=True)
    elif status_filter:
        query = query.filter_by(status=status_filter, is_paid=False)
    aid_list = query.order_by(Aide.request_date.desc(), Aide.id.desc()).all()
    types = AidType.query.filter_by(is_active=True).order_by(AidType.display_order).all()
    my_checks = aid_eligibility(current_user.member, tontine) if current_user.member else []
    members = (Member.query.filter_by(is_active=True).order_by(Member.last_name).all()
               if is_bureau else [current_user.member] if current_user.member else [])
    year = date.today().year
    used_this_year = Aide.query.filter(Aide.member_id == current_user.member_id, Aide.status != 'REJECTED',
                                       db.extract('year', Aide.request_date) == year).count() if current_user.member else 0
    return render_template('aides.html', aides=aid_list, types=types, rules=rules, my_checks=my_checks,
                           members=members, is_bureau=is_bureau, can_manage=current_user.role in AID_MANAGERS,
                           status_filter=status_filter, secours_balance=_secours_balance(),
                           used_this_year=used_this_year, today=date.today().isoformat(),
                           payment_modes=finance.PAYMENT_MODES)


@app.route('/aides/request', methods=['POST'])
@login_required
def request_aide():
    """Demande d'aide : toutes les règles de la tontine sont vérifiées ici"""
    tontine = current_tontine()
    ensure_aid_types(tontine)
    rules = aid_rules(tontine)
    is_bureau = current_user.role in AID_VIEWERS
    member_id = request.form.get('member_id', type=int) if is_bureau else current_user.member_id
    if not member_id:
        member_id = current_user.member_id  # le bureau peut aussi demander pour lui-même
    member = db.session.get(Member, member_id or 0)
    aid_type = AidType.query.filter_by(id=request.form.get('aid_type_id', type=int) or 0, is_active=True).first()
    back = redirect(url_for('aides'))
    if not member or not aid_type:
        flash("Choisissez le membre et l'événement.", 'danger')
        return back

    problems = []
    try:
        event_date = datetime.strptime(request.form.get('event_date') or '', '%Y-%m-%d').date()
    except ValueError:
        event_date = None
    if not event_date:
        problems.append("Indiquez la date de l'événement.")
    elif event_date > date.today():
        problems.append("La date de l'événement ne peut pas être dans le futur.")
    elif (date.today() - event_date).days > rules['declaration_days']:
        problems.append(f"Délai de déclaration dépassé : l'événement doit être déclaré dans les {rules['declaration_days']} jours.")

    if aid_type.free_amount:
        amount = _parse_decimal(request.form.get('amount') or '0', 1, aid_type.amount)
        if amount is None:
            problems.append(f"Montant demandé invalide : entre 1 et {aid_type.amount:,.0f} FCFA.".replace(',', ' '))
    else:
        amount = Decimal(str(aid_type.amount))

    year = date.today().year
    this_year = Aide.query.filter(Aide.member_id == member.id, Aide.status != 'REJECTED',
                                  db.extract('year', Aide.request_date) == year)
    if rules['max_per_year'] and this_year.count() >= rules['max_per_year']:
        problems.append(f"Plafond atteint : {rules['max_per_year']} aide(s) par an et par membre.")
    if aid_type.max_per_year and this_year.filter(Aide.aid_type_id == aid_type.id).count() >= aid_type.max_per_year:
        problems.append(f"Plafond atteint pour « {aid_type.name} » : {aid_type.max_per_year} par an.")
    if event_date and Aide.query.filter(Aide.member_id == member.id, Aide.aid_type_id == aid_type.id,
                                        Aide.event_date == event_date, Aide.status != 'REJECTED').first():
        problems.append('Une demande existe déjà pour ce même événement.')

    file = request.files.get('document')
    if aid_type.requires_document and not (file and file.filename):
        problems.append('Justificatif obligatoire pour cet événement (photo ou PDF).')
    elif file and file.filename and file.filename.rsplit('.', 1)[-1].lower() not in DOCUMENT_EXTENSIONS:
        problems.append('Justificatif : formats acceptés PDF, JPG, PNG, WEBP.')

    unmet = [label for ok, label, _ in aid_eligibility(member, tontine) if not ok]
    derogation = (request.form.get('derogation') or '').strip()
    if unmet and not (current_user.role == 'PRESIDENT' and derogation):
        problems.append('Conditions non remplies : ' + ', '.join(unmet) + '.')

    if problems:
        for msg in problems:
            flash(msg, 'danger')
        return back

    description = (request.form.get('description') or '').strip()[:1000]
    if unmet and derogation:
        description = f"[Dérogation du président : {derogation[:200]}] " + description
    aide = Aide(member_id=member.id, aide_type=aid_type.code, aid_type_id=aid_type.id, amount=amount,
                request_date=date.today(), event_date=event_date, status='PENDING', is_paid=False,
                description=description or None, document=_save_aid_document(file))
    db.session.add(aide)
    db.session.commit()
    log_activity(current_user.id, current_user.role, f"Demande d'aide #{aide.id} ({aid_type.name}) pour {member.full_name}",
                 request.remote_addr)
    flash(f"Demande d'aide « {aid_type.name} » de {amount:,.0f} FCFA enregistrée : elle attend la validation du bureau.".replace(',', ' '), 'success')
    return back


@app.route('/aides/<int:aide_id>/approve', methods=['POST'])
@login_required
@role_required(AID_MANAGERS)
def approve_aide(aide_id):
    aide = db.get_or_404(Aide, aide_id)
    if aide.status != 'PENDING':
        flash('Cette demande a déjà été traitée.', 'warning')
        return redirect(url_for('aides'))
    if aide.member_id == current_user.member_id:
        flash('Vous ne pouvez pas valider votre propre demande d\'aide.', 'danger')
        return redirect(url_for('aides'))
    if current_user.role == 'PRESIDENT':
        aide.president_approved_by = current_user.id
    else:
        aide.treasurer_approved_by = current_user.id
    rules = aid_rules(current_tontine())
    complete = (aide.president_approved_by and aide.treasurer_approved_by) if rules['double_validation'] else True
    if complete:
        aide.status = 'APPROVED'
        aide.approval_date = date.today()
        aide.approved_by = current_user.id
        flash('Aide approuvée : elle peut être versée.', 'success')
    else:
        waiting = 'du trésorier' if current_user.role == 'PRESIDENT' else 'du président'
        flash(f'Validation enregistrée (1/2). En attente de la validation {waiting}.', 'info')
    db.session.commit()
    log_activity(current_user.id, current_user.role, f"Validation aide #{aide_id}", request.remote_addr)
    return redirect(url_for('aides'))


@app.route('/aides/<int:aide_id>/reject', methods=['POST'])
@login_required
@role_required(AID_MANAGERS)
def reject_aide(aide_id):
    aide = db.get_or_404(Aide, aide_id)
    if aide.status != 'PENDING':
        flash('Cette demande a déjà été traitée.', 'warning')
        return redirect(url_for('aides'))
    aide.status = 'REJECTED'
    aide.rejection_reason = (request.form.get('reason') or '').strip()[:255] or 'Refusée par le bureau'
    db.session.commit()
    log_activity(current_user.id, current_user.role, f"Rejet aide #{aide_id}", request.remote_addr)
    flash('Demande d\'aide refusée.', 'warning')
    return redirect(url_for('aides'))


@app.route('/aides/<int:aide_id>/pay', methods=['POST'])
@login_required
@role_required(AID_MANAGERS)
def pay_aide(aide_id):
    """Versement : caisse de secours suffisante, amendes impayées retenues si la règle est active"""
    aide = db.get_or_404(Aide, aide_id)
    if aide.status != 'APPROVED':
        flash('Cette aide doit être approuvée avant d\'être versée.', 'danger')
        return redirect(url_for('aides'))
    if aide.is_paid:
        flash('Cette aide a déjà été versée.', 'warning')
        return redirect(url_for('aides'))
    gross = Decimal(str(aide.amount))
    balance = _secours_balance()
    if balance < gross:
        flash(f"Caisse de secours insuffisante ({balance:,.0f} FCFA disponibles pour {gross:,.0f} FCFA). "
              "Lancez une cotisation exceptionnelle de solidarité (rubrique Caisse de secours) avant de verser.".replace(',', ' '),
              'danger')
        return redirect(url_for('aides'))

    payment_mode = _payment_mode_from_form()
    deducted = Decimal('0')
    if aid_rules(current_tontine())['deduct_sanctions']:
        for sanction in Sanction.query.filter_by(member_id=aide.member_id, status='PENDING').order_by(Sanction.sanction_date).all():
            amount = Decimal(str(sanction.amount))
            if deducted + amount > gross:
                break
            sanction.status = 'PAID'
            deducted += amount
            db.session.add(Transaction(member_id=aide.member_id, type='SANCTION', amount=amount, date=date.today(),
                                       description=f"Amende #{sanction.id} retenue sur l'aide #{aide.id}",
                                       created_by=current_user.id, payment_mode=payment_mode))
    aide.is_paid = True
    aide.paid_at = date.today()
    aide.sanctions_deducted = deducted or None
    db.session.add(Transaction(member_id=aide.member_id, type='AIDE', amount=gross, date=date.today(),
                               description=f"Aide « {aide.get_type_display()} » (demande #{aide.id})",
                               created_by=current_user.id, payment_mode=payment_mode,
                               payment_reference=_payment_reference_from_form()))
    db.session.commit()
    log_activity(current_user.id, current_user.role, f"Versement aide #{aide_id} : {gross - deducted:,.0f} FCFA", request.remote_addr)
    message = f"Aide versée : {gross - deducted:,.0f} FCFA à remettre"
    if deducted:
        message += f" ({gross:,.0f} − {deducted:,.0f} d'amendes retenues)"
    flash((message + '.').replace(',', ' '), 'success')
    return redirect(url_for('aides'))


@app.route('/aides/<int:aide_id>/justificatif')
@login_required
def aid_document(aide_id):
    """Justificatif visible seulement du bureau et du membre concerné"""
    aide = db.get_or_404(Aide, aide_id)
    if not aide.document or (current_user.role not in AID_VIEWERS and aide.member_id != current_user.member_id):
        abort(404)
    root = os.path.realpath(os.path.join(BASE_DIR, 'instance', 'justificatifs'))
    path = os.path.realpath(os.path.join(root, aide.document))
    if not path.startswith(root + os.sep) or not os.path.isfile(path):
        abort(404)
    return send_file(path, as_attachment=False, download_name=f"justificatif_aide_{aide.id}{os.path.splitext(path)[1]}")


@app.route('/aides/<int:aide_id>/delete', methods=['POST'])
@login_required
@president_required
def delete_aide(aide_id):
    """Supprimer une demande d'aide (uniquement si elle n'est ni approuvée ni versée)"""
    aide = db.get_or_404(Aide, aide_id)
    if aide.status == 'APPROVED' or aide.is_paid:
        flash('Impossible de supprimer une aide approuvée ou versée.', 'danger')
        return redirect(url_for('aides'))
    if aide.document:
        try:
            os.remove(os.path.join(BASE_DIR, 'instance', 'justificatifs', aide.document))
        except OSError:
            pass
    db.session.delete(aide)
    db.session.commit()
    log_activity(current_user.id, current_user.role, f"Suppression aide #{aide_id}", request.remote_addr)
    flash('Demande d\'aide supprimée.', 'success')
    return redirect(url_for('aides'))


@app.route('/parametres/aides', methods=['POST'])
@login_required
@president_required
def aid_settings():
    """Règles et barème des aides (Paramètres > Aides sociales)"""
    tontine = current_tontine()
    f = request.form
    if f.get('section') == 'rules':
        numbers = {k: f.get(k, type=int) for k in ('aid_min_seniority_days', 'aid_declaration_days', 'max_aid_per_member')}
        if any(v is None or not 0 <= v <= 3650 for v in numbers.values()):
            flash('Valeurs invalides (nombres entre 0 et 3650).', 'danger')
            return redirect(url_for('tontine_settings') + '#aides')
        tontine.aid_min_seniority_days = numbers['aid_min_seniority_days']
        tontine.aid_declaration_days = numbers['aid_declaration_days']
        tontine.max_aid_per_member = numbers['max_aid_per_member']
        for flag in ('aid_require_fonds_caisse', 'aid_require_secours', 'aid_double_validation', 'aid_deduct_sanctions'):
            setattr(tontine, flag, f.get(flag) == 'on')
        flash('Règles des aides enregistrées.', 'success')
    elif f.get('section') == 'type':
        type_id = f.get('type_id', type=int)
        aid_type = db.session.get(AidType, type_id) if type_id else AidType(code='PERSO', display_order=99)
        if type_id and not aid_type:
            abort(404)
        name = (f.get('name') or '').strip()
        amount = _parse_decimal(f.get('amount') or '', 1, 100_000_000)
        per_year = f.get('max_per_year', type=int)
        if not name or len(name) > 80 or amount is None or per_year is None or not 0 <= per_year <= 50:
            flash("Événement invalide : nom, montant (> 0) et limite annuelle (0 à 50) requis.", 'danger')
            return redirect(url_for('tontine_settings') + '#aides')
        aid_type.name, aid_type.amount, aid_type.max_per_year = name, amount, per_year
        aid_type.free_amount = f.get('free_amount') == 'on'
        aid_type.requires_document = f.get('requires_document') == 'on'
        aid_type.is_active = (f.get('is_active') == 'on') if type_id else True  # case décochée = désactivé
        if not type_id:
            db.session.add(aid_type)
        flash(f"Événement « {name} » enregistré.", 'success')
    db.session.commit()
    log_activity(current_user.id, current_user.role, 'Modification des règles des aides', request.remote_addr)
    return redirect(url_for('tontine_settings') + '#aides')


    #===========================================================
#audit logs
# ============================================================
# MODULE : AUDIT LOGS
# ============================================================

@app.route('/audit-logs')
@login_required
@role_required(['PRESIDENT', 'SECRETAIRE'])
def audit_logs():
    """Journal d'audit des actions des utilisateurs"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    user_id = request.args.get('user_id', type=int)
    action_filter = request.args.get('action', '')
    
    query = AuditLog.query
    if user_id:
        query = query.filter_by(user_id=user_id)
    if action_filter:
        query = query.filter(AuditLog.action.ilike(f'%{action_filter}%'))
    
    pagination = query.order_by(AuditLog.timestamp.desc()).paginate(page=page, per_page=per_page, error_out=False)
    pagination_data = get_pagination_data(pagination)
    users = User.query.filter_by(tontine_id=g.tenant_id).all()
    
    return render_template('audit_logs.html', 
                          logs=pagination_data['items'], 
                          pagination=pagination_data,
                          users=users, 
                          action_filter=action_filter, 
                          selected_user=user_id)
# ============================================================
# PROFIL UTILISATEUR
# ============================================================

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    form = ProfileEditForm()
    
    if form.validate_on_submit() and email_taken(form.email.data, current_user.member_id):
        flash(f"L'email {form.email.data} est déjà utilisé par un autre membre de la tontine.", 'danger')
        return render_template('profile.html', form=form)
    if form.validate_on_submit():
        user = current_user
        user.email = form.email.data
        
        if current_user.member_id:
            member = current_user.member
            member.email = form.email.data
            member.first_name = form.first_name.data
            member.last_name = form.last_name.data
            member.phone = form.phone.data
            if form.photo.data:
                filename = save_tenant_upload(form.photo.data)
                if filename:
                    member.photo = filename
        
        db.session.commit()
        flash('Profil mis à jour !', 'success')
        return redirect(url_for('profile'))
    
    if current_user.member_id:
        member = current_user.member
        form.first_name.data = member.first_name
        form.last_name.data = member.last_name
        form.phone.data = member.phone
    form.email.data = current_user.email
    
    return render_template('profile.html', form=form)

# ============================================================
# VOTES (SCRUTINS)
# ============================================================

POLL_MANAGERS = ['PRESIDENT', 'SECRETAIRE', 'COMMUNICATION']


@app.route('/votes')
@login_required
def votes():
    polls = Poll.query.order_by(Poll.created_at.desc()).all()
    member_id = current_user.member_id
    voted_ids = {v.poll_id for v in PollVote.query.filter_by(member_id=member_id).all()}
    return render_template('votes.html', polls=polls, voted_ids=voted_ids,
                           can_manage=current_user.role in POLL_MANAGERS)


@app.route('/votes/add', methods=['GET', 'POST'])
@login_required
@role_required(POLL_MANAGERS)
def add_vote():
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        description = (request.form.get('description') or '').strip()
        labels = [l.strip() for l in (request.form.get('options') or '').splitlines() if l.strip()]
        labels = list(dict.fromkeys(labels))  # supprime les doublons en gardant l'ordre
        end_date_str = request.form.get('end_date')

        if not title or len(title) > 200:
            flash('Le titre est obligatoire (200 caractères max).', 'danger')
            return render_template('vote_form.html', form_data=request.form)
        if len(labels) < 2:
            flash('Il faut au moins deux choix différents.', 'danger')
            return render_template('vote_form.html', form_data=request.form)

        end_date = None
        if end_date_str:
            try:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%dT%H:%M')
            except ValueError:
                flash('Date de clôture invalide.', 'danger')
                return render_template('vote_form.html', form_data=request.form)
            if end_date <= datetime.now():
                flash('La date de clôture doit être dans le futur.', 'danger')
                return render_template('vote_form.html', form_data=request.form)

        poll = Poll(
            title=title,
            description=description or None,
            is_anonymous=request.form.get('is_anonymous') == 'on',
            end_date=end_date,
            status='OUVERT',
            created_by=current_user.id
        )
        for i, label in enumerate(labels):
            poll.options.append(PollOption(label=label[:200], display_order=i))
        db.session.add(poll)
        db.session.commit()

        log_activity(current_user.id, current_user.role, f"Création vote #{poll.id}: {poll.title}", request.remote_addr)
        flash('Le vote a été ouvert aux membres.', 'success')
        return redirect(url_for('vote_detail', poll_id=poll.id))

    return render_template('vote_form.html', form_data={})


@app.route('/votes/<int:poll_id>')
@login_required
def vote_detail(poll_id):
    poll = db.get_or_404(Poll, poll_id)
    my_vote = poll.vote_of(current_user.member_id)
    member = current_user.member
    can_vote = (poll.is_open and my_vote is None and member is not None
                and member.status == 'ACTIF' and member.is_active)
    can_manage = current_user.role in POLL_MANAGERS
    # Résultats visibles après avoir voté, à la clôture, ou pour le bureau
    show_results = my_vote is not None or not poll.is_open or can_manage
    voters = []
    if show_results and not poll.is_anonymous:
        voters = poll.votes.order_by(PollVote.voted_at).all()
    eligible = Member.query.filter_by(status='ACTIF', is_active=True).count()
    return render_template('vote_detail.html', poll=poll, my_vote=my_vote, can_vote=can_vote,
                           can_manage=can_manage, show_results=show_results,
                           voters=voters, eligible=eligible)


@app.route('/votes/<int:poll_id>/vote', methods=['POST'])
@login_required
def cast_vote(poll_id):
    poll = db.get_or_404(Poll, poll_id)
    member = current_user.member

    if not poll.is_open:
        flash('Ce vote est clos.', 'warning')
        return redirect(url_for('vote_detail', poll_id=poll.id))
    if not member or member.status != 'ACTIF' or not member.is_active:
        flash('Seuls les membres actifs peuvent voter.', 'danger')
        return redirect(url_for('vote_detail', poll_id=poll.id))
    if poll.has_voted(member.id):
        flash('Vous avez déjà voté.', 'warning')
        return redirect(url_for('vote_detail', poll_id=poll.id))

    option_id = request.form.get('option_id', type=int)
    option = PollOption.query.filter_by(id=option_id, poll_id=poll.id).first()
    if not option:
        flash('Choix invalide.', 'danger')
        return redirect(url_for('vote_detail', poll_id=poll.id))

    try:
        db.session.add(PollVote(poll_id=poll.id, option_id=option.id, member_id=member.id))
        db.session.commit()
    except Exception:
        # Contrainte d'unicité (double clic / double soumission)
        db.session.rollback()
        flash('Vous avez déjà voté.', 'warning')
        return redirect(url_for('vote_detail', poll_id=poll.id))

    log_activity(current_user.id, current_user.role, f"Vote enregistré (scrutin #{poll.id})", request.remote_addr)
    flash('Votre vote a été enregistré. Merci !', 'success')
    return redirect(url_for('vote_detail', poll_id=poll.id))


@app.route('/votes/<int:poll_id>/close', methods=['POST'])
@login_required
@role_required(['PRESIDENT', 'SECRETAIRE'])
def close_vote(poll_id):
    poll = db.get_or_404(Poll, poll_id)
    if poll.status == 'CLOS':
        flash('Ce vote est déjà clos.', 'info')
    else:
        poll.status = 'CLOS'
        poll.closed_at = utcnow()
        db.session.commit()
        log_activity(current_user.id, current_user.role, f"Clôture vote #{poll.id}", request.remote_addr)
        flash('Le vote est clos. Les résultats sont visibles par tous.', 'success')
    return redirect(url_for('vote_detail', poll_id=poll.id))


@app.route('/votes/<int:poll_id>/delete', methods=['POST'])
@login_required
@president_required
def delete_vote(poll_id):
    poll = db.get_or_404(Poll, poll_id)
    title = poll.title
    db.session.delete(poll)
    db.session.commit()
    log_activity(current_user.id, current_user.role, f"Suppression vote #{poll_id}: {title}", request.remote_addr)
    flash('Vote supprimé.', 'success')
    return redirect(url_for('votes'))


# ============================================================
# TIRAGE AU SORT DE L'ORDRE DES BÉNÉFICIAIRES
# ============================================================

DRAW_MANAGERS = ['PRESIDENT', 'SECRETAIRE', 'TRESORIER']


def perform_draw(cycle, notes=None):
    """Classe au hasard les mains qui n'ont pas encore reçu la cagnotte.
    Les mains déjà servies gardent leur position ; générateur cryptographique."""
    remaining = [p for p in cycle.participants if not p.served]
    secrets.SystemRandom().shuffle(remaining)
    start_position = cycle.beneficiaries_count + 1
    draw = TontineDraw(cycle_id=cycle.id, drawn_by=current_user.id, notes=(notes or '')[:255] or None)
    for offset, participant in enumerate(remaining):
        participant.position = start_position + offset
        draw.results.append(TontineDrawResult(member_id=participant.member_id, position=participant.position))
    db.session.add(draw)
    db.session.commit()
    log_activity(current_user.id, current_user.role,
                 f"Tirage au sort {cycle.display_name} ({len(remaining)} mains)", request.remote_addr)
    return draw


@app.route('/tirages')
@login_required
def tirages():
    draws = TontineDraw.query.order_by(TontineDraw.drawn_at.desc()).all()
    cycles = [c for c in TontineCycleDetail.query.filter_by(status='EN_COURS').all() if not c.is_auction]
    return render_template('tirages.html', draws=draws, cycles=cycles,
                           can_draw=current_user.role in DRAW_MANAGERS)


@app.route('/tontine-cycles/<int:cycle_id>/tirage', methods=['GET', 'POST'])
@login_required
def tirage_cycle(cycle_id):
    cycle = db.get_or_404(TontineCycleDetail, cycle_id)
    can_draw = current_user.role in DRAW_MANAGERS

    if request.method == 'POST':
        if not can_draw:
            abort(403)
        if cycle.status != 'EN_COURS':
            flash('Le tirage est possible uniquement sur un cycle en cours.', 'danger')
            return redirect(url_for('tirage_cycle', cycle_id=cycle.id))
        if cycle.is_auction:
            flash("Ce cycle fonctionne aux enchères : pas de tirage au sort.", 'warning')
            return redirect(url_for('tontine_cycle_detail', cycle_id=cycle.id))
        if len(cycle.remaining_participants) < 2:
            flash('Il faut au moins deux mains restantes pour faire un tirage.', 'warning')
            return redirect(url_for('tirage_cycle', cycle_id=cycle.id))
        draw = perform_draw(cycle, (request.form.get('notes') or '').strip())
        return redirect(url_for('tirage_cycle', cycle_id=cycle.id, reveal=draw.id))

    draws = cycle.draws.order_by(TontineDraw.drawn_at.desc()).all()
    reveal_draw = None
    reveal_id = request.args.get('reveal', type=int)
    if reveal_id:
        reveal_draw = TontineDraw.query.filter_by(id=reveal_id, cycle_id=cycle.id).first()
    beneficiaries = CycleBeneficiary.query.filter_by(cycle_id=cycle.id).order_by(CycleBeneficiary.position).all()
    return render_template('tirage.html', cycle=cycle, remaining=cycle.remaining_participants, draws=draws,
                           reveal_draw=reveal_draw, beneficiaries=beneficiaries, can_draw=can_draw)


# ============================================================
# GALERIE PHOTOS DE LA PAGE D'ACCUEIL
# ============================================================

GALLERY_MANAGERS = ['PRESIDENT', 'SECRETAIRE', 'COMMUNICATION']


@app.route('/galerie')
@login_required
@role_required(GALLERY_MANAGERS)
def gallery_admin():
    photos = GalleryPhoto.query.order_by(GalleryPhoto.display_order, GalleryPhoto.created_at.desc()).all()
    return render_template('gallery_admin.html', photos=photos)


@app.route('/galerie/upload', methods=['POST'])
@login_required
@role_required(GALLERY_MANAGERS)
def gallery_upload():
    files = [f for f in request.files.getlist('photos') if f and f.filename]
    if not files:
        flash('Choisissez au moins une photo.', 'danger')
        return redirect(url_for('gallery_admin'))

    caption = (request.form.get('caption') or '').strip()[:200] or None
    make_hero = request.form.get('is_hero') == 'on'
    saved = 0
    for f in files:
        filename = save_tenant_upload(f)
        if not filename:
            flash(f'Fichier refusé (format non autorisé) : {f.filename}', 'warning')
            continue
        is_hero = make_hero and saved == 0
        if is_hero:
            GalleryPhoto.query.filter_by(is_hero=True).update({'is_hero': False})
        db.session.add(GalleryPhoto(filename=filename, caption=caption, is_hero=is_hero,
                                    created_by=current_user.id))
        saved += 1
    db.session.commit()

    if saved:
        log_activity(current_user.id, current_user.role, f"Ajout de {saved} photo(s) à la galerie", request.remote_addr)
        flash(f'{saved} photo(s) ajoutée(s).', 'success')
    return redirect(url_for('gallery_admin'))


@app.route('/galerie/<int:photo_id>/update', methods=['POST'])
@login_required
@role_required(GALLERY_MANAGERS)
def gallery_update(photo_id):
    photo = db.get_or_404(GalleryPhoto, photo_id)
    photo.caption = (request.form.get('caption') or '').strip()[:200] or None
    photo.display_order = request.form.get('display_order', type=int) or 0
    if request.form.get('is_hero') == 'on' and not photo.is_hero:
        GalleryPhoto.query.filter_by(is_hero=True).update({'is_hero': False})
        photo.is_hero = True
    elif request.form.get('is_hero') != 'on':
        photo.is_hero = False
    db.session.commit()
    flash('Photo mise à jour.', 'success')
    return redirect(url_for('gallery_admin'))


@app.route('/galerie/<int:photo_id>/delete', methods=['POST'])
@login_required
@role_required(GALLERY_MANAGERS)
def gallery_delete(photo_id):
    photo = db.get_or_404(GalleryPhoto, photo_id)
    path = os.path.join(app.config['UPLOAD_FOLDER'], photo.filename)
    db.session.delete(photo)
    db.session.commit()
    # Ne supprime le fichier que s'il n'est pas aussi utilisé comme photo de profil
    if not Member.query.filter_by(photo=photo.filename).first() and os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass
    log_activity(current_user.id, current_user.role, f"Suppression photo galerie #{photo_id}", request.remote_addr)
    flash('Photo supprimée.', 'success')
    return redirect(url_for('gallery_admin'))


# ============================================================
# AVALISTES (GARANTS DES EMPRUNTS)
# ============================================================
# Pratique courante dans les tontines africaines : tout emprunt doit être
# « avalisé » par un ou plusieurs membres qui s'engagent à payer si
# l'emprunteur fait défaut. Cycle de vie d'un aval :
#   EN_ATTENTE -> ACCEPTE / REFUSE (réponse de l'avaliste)
#   ACCEPTE -> LIBERE (prêt soldé) | APPELE (le bureau fait payer l'avaliste)
#   APPELE -> REGLE (l'emprunteur a remboursé son avaliste)
#   EN_ATTENTE / ACCEPTE -> ANNULE (demande de prêt rejetée)

AVAL_MANAGERS = ['PRESIDENT', 'TRESORIER']
BUREAU_ROLES = ['PRESIDENT', 'SECRETAIRE', 'TRESORIER', 'CENSEUR']
MAX_GUARANTORS = 5


def required_guarantors_for(amount):
    """Nombre d'avalistes exigés pour un emprunt de ce montant (règles de la tontine)"""
    tontine = current_tontine()
    minimum = tontine.guarantors_min or 0
    threshold = Decimal(str(tontine.guarantee_threshold or 0))
    return minimum if Decimal(str(amount)) > threshold else 0


def _split_amount(total, divisor, count):
    """Répartit `total` en parts égales (au centime) ; la dernière part absorbe l'arrondi"""
    divisor = max(divisor, 1)
    share = (Decimal(str(total)) / divisor).quantize(Decimal('0.01'))
    shares = [share] * count
    if count and divisor == count:
        shares[-1] = Decimal(str(total)) - share * (count - 1)
    return shares


# Règles pour avaliser (garantir) l'emprunt d'un autre membre :
#   1. être à jour en réunion : pas d'amende impayée, fonds de caisse payé, aucune
#      cotisation de tontine en retard sur les tours déjà versés, pas en statut rouge ;
#   2. avoir une épargne au moins égale au tiers de la somme demandée par l'emprunteur
#      (l'épargne déjà engagée pour d'autres avals en cours n'est pas comptée deux fois) ;
#   3. ne pas avoir soi-même de dette d'emprunt (prêt en cours ou demandé, aval appelé non réglé).
GUARANTEE_SAVINGS_RATIO = Decimal('3')
_OPEN_LOAN_STATUSES = ('PENDING', 'ACTIF', 'OVERDUE')


def _fmt(value):
    return f"{value:,.0f}".replace(',', ' ')


def aval_standing(member, ignore_guarantee_id=None):
    """Situation d'un membre comme avaliste : (problèmes bloquants, épargne disponible)"""
    problems = []
    if not member.is_active or member.status != 'ACTIF':
        problems.append("n'est pas un membre actif")
    if member.tontine_status == 'ROUGE':
        problems.append("est en statut rouge")
    pending_fines = member.total_sanctions_pending
    if pending_fines > 0:
        problems.append(f"n'est pas à jour : {_fmt(pending_fines)} FCFA d'amendes impayées")
    if not member.has_paid_fonds_caisse:
        problems.append("n'est pas à jour : fonds de caisse non payé")
    for cycle in {p.cycle for p in CycleParticipant.query.filter_by(member_id=member.id).all()}:
        if cycle.beneficiaries_count == 0:   # cycle en cours ou terminé : tours déjà versés
            continue
        status = cycle_contribution_status(cycle, through_turn=cycle.beneficiaries_count)
        late = sum((-r['gap'] for r in status['rows'] if r['member'] and r['member'].id == member.id and r['gap'] < 0),
                   Decimal('0'))
        if late > 0:
            problems.append(f"n'est pas à jour : {_fmt(late)} FCFA de cotisations en retard ({cycle.display_name})")
    if any(l.status in _OPEN_LOAN_STATUSES for l in member.loans):
        problems.append("a lui-même un emprunt en cours")
    if member.unsettled_guarantor_debts:
        problems.append("doit encore rembourser un avaliste qui a payé pour lui")

    committed = Decimal('0')
    for g in LoanGuarantor.query.filter(LoanGuarantor.member_id == member.id,
                                        LoanGuarantor.status.in_(['EN_ATTENTE', 'ACCEPTE', 'APPELE'])).all():
        if g.id != ignore_guarantee_id and g.loan and g.loan.status in _OPEN_LOAN_STATUSES:
            committed += Decimal(str(g.loan.amount)) / GUARANTEE_SAVINGS_RATIO
    available = max(member.savings_balance - committed, Decimal('0'))
    return problems, available


def aval_problems(member, loan_amount, ignore_guarantee_id=None):
    """Raisons pour lesquelles `member` ne peut pas avaliser un emprunt de `loan_amount` (vide = éligible)"""
    problems, available = aval_standing(member, ignore_guarantee_id)
    needed = (Decimal(str(loan_amount)) / GUARANTEE_SAVINGS_RATIO).quantize(Decimal('1'))
    if available < needed:
        problems.append(f"n'a pas assez d'épargne : {_fmt(needed)} FCFA exigés (le tiers de la somme demandée), "
                        f"{_fmt(available)} FCFA disponibles")
    return problems


def _validate_guarantors(borrower, guarantor_ids, loan_amount):
    guarantors, problems = [], []
    if len(guarantor_ids) > MAX_GUARANTORS:
        return [], [f"{MAX_GUARANTORS} avalistes maximum."]
    for gid in guarantor_ids:
        candidate = db.session.get(Member, gid)
        if candidate is None:
            problems.append("Avaliste introuvable.")
        elif candidate.id == borrower.id:
            problems.append("Un membre ne peut pas être son propre avaliste.")
        else:
            reasons = aval_problems(candidate, loan_amount)
            if reasons:
                problems.append(f"{candidate.full_name} ne peut pas avaliser : {' ; '.join(reasons)}.")
            else:
                guarantors.append(candidate)
    return guarantors, problems


def guarantor_choices(exclude_member_id=None):
    """Membres proposés comme avalistes, avec leur capacité (3 x épargne disponible) ou la raison du refus"""
    choices = []
    for m in Member.query.filter_by(is_active=True, status='ACTIF').order_by(Member.last_name, Member.first_name).all():
        if m.id == exclude_member_id:
            continue
        problems, available = aval_standing(m)
        choices.append({'member': m, 'problems': problems, 'max_loan': available * GUARANTEE_SAVINGS_RATIO})
    return choices


def _release_guarantors(loan):
    """Prêt soldé : les avalistes sont libérés de leur engagement"""
    for guarantee in loan.guarantors:
        if guarantee.status == 'ACCEPTE':
            guarantee.status = 'LIBERE'
        elif guarantee.status == 'EN_ATTENTE':
            guarantee.status = 'ANNULE'


@app.route('/avals')
@login_required
def avals():
    member_id = current_user.member_id
    my_requests = LoanGuarantor.query.filter_by(member_id=member_id).order_by(LoanGuarantor.id.desc()).all()
    my_loans = Loan.query.filter(Loan.member_id == member_id,
                                 Loan.status.in_(['PENDING', 'ACTIF', 'OVERDUE'])).order_by(Loan.id.desc()).all()
    is_bureau = current_user.role in BUREAU_ROLES
    all_guarantees = []
    if is_bureau:
        status = request.args.get('status', '')
        query = LoanGuarantor.query
        if status:
            query = query.filter_by(status=status)
        all_guarantees = query.order_by(LoanGuarantor.id.desc()).all()
    candidates = guarantor_choices(exclude_member_id=member_id)
    me = current_user.member
    my_aval = None
    if me:
        problems, available = aval_standing(me)
        my_aval = {'problems': problems, 'max_loan': available * GUARANTEE_SAVINGS_RATIO,
                   'engaged': max(me.savings_balance - available, Decimal('0'))}
    return render_template('avals.html', my_requests=my_requests, my_loans=my_loans, is_bureau=is_bureau, my_aval=my_aval,
                           all_guarantees=all_guarantees, candidates=candidates, me=me,
                           can_manage=current_user.role in AVAL_MANAGERS,
                           statuses=LoanGuarantor.STATUSES, status_filter=request.args.get('status', ''))


@app.route('/avals/<int:guarantee_id>/respond', methods=['POST'])
@login_required
def respond_aval(guarantee_id):
    guarantee = db.get_or_404(LoanGuarantor, guarantee_id)
    if guarantee.member_id != current_user.member_id:
        abort(403)
    if guarantee.status != 'EN_ATTENTE' or guarantee.loan.status != 'PENDING':
        flash("Cette demande d'aval n'attend plus de réponse.", 'warning')
        return redirect(url_for('avals'))

    action = request.form.get('action')
    note = (request.form.get('note') or '').strip()[:255] or None
    if action == 'accept':
        # La situation a pu changer depuis la demande : les règles sont vérifiées à nouveau
        reasons = aval_problems(guarantee.member, guarantee.loan.amount, ignore_guarantee_id=guarantee.id)
        if reasons:
            flash("Vous ne pouvez pas avaliser cet emprunt : vous " + ' ; '.join(reasons) + '.', 'danger')
            return redirect(url_for('avals'))
        guarantee.status = 'ACCEPTE'
        message = f"Vous avalisez l'emprunt de {guarantee.loan.member_name} à hauteur de {guarantee.amount:,.0f} FCFA."
    elif action == 'refuse':
        guarantee.status = 'REFUSE'
        message = "Vous avez refusé cette demande d'aval."
    else:
        abort(400)
    guarantee.response_note = note
    guarantee.responded_at = utcnow()
    db.session.commit()
    log_activity(current_user.id, current_user.role,
                 f"Aval #{guarantee.id} {'accordé' if action == 'accept' else 'refusé'} (emprunt #{guarantee.loan_id})",
                 request.remote_addr)
    flash(message, 'success' if action == 'accept' else 'info')
    return redirect(url_for('avals'))


@app.route('/loans/<int:loan_id>/guarantors/add', methods=['POST'])
@login_required
def add_loan_guarantor(loan_id):
    loan = db.get_or_404(Loan, loan_id)
    if loan.member_id != current_user.member_id and current_user.role not in BUREAU_ROLES:
        abort(403)
    back = redirect(url_for('avals') if request.form.get('back') == 'avals' else url_for('loans'))
    if loan.status != 'PENDING':
        flash("On ne peut ajouter un avaliste qu'à une demande en attente.", 'warning')
        return back

    gid = request.form.get('guarantor_id', type=int)
    if any(g.member_id == gid for g in loan.guarantors):
        flash('Ce membre a déjà été sollicité pour cet emprunt.', 'warning')
        return back
    if len([g for g in loan.guarantors if g.status in ('EN_ATTENTE', 'ACCEPTE')]) >= MAX_GUARANTORS:
        flash(f"{MAX_GUARANTORS} avalistes maximum.", 'warning')
        return back
    guarantors, problems = _validate_guarantors(loan.member, [gid] if gid else [], loan.amount)
    if problems or not guarantors:
        for msg in problems or ['Choisissez un avaliste.']:
            flash(msg, 'danger')
        return back

    required = max(required_guarantors_for(loan.amount), 1)
    share = _split_amount(loan.total_amount, required, 1)[0]
    loan.guarantors.append(LoanGuarantor(member_id=guarantors[0].id, amount=share, status='EN_ATTENTE'))
    db.session.commit()
    log_activity(current_user.id, current_user.role,
                 f"Avaliste {guarantors[0].full_name} sollicité (emprunt #{loan.id})", request.remote_addr)
    flash(f"Demande d'aval envoyée à {guarantors[0].full_name}.", 'success')
    return back


@app.route('/avals/<int:guarantee_id>/call', methods=['POST'])
@login_required
@role_required(AVAL_MANAGERS)
def call_aval(guarantee_id):
    """Appel en garantie : l'avaliste paie à la place de l'emprunteur défaillant"""
    guarantee = db.get_or_404(LoanGuarantor, guarantee_id)
    loan = guarantee.loan
    if loan.status not in ('ACTIF', 'OVERDUE') or guarantee.status not in ('ACCEPTE', 'APPELE'):
        flash("Cet aval ne peut pas être appelé.", 'warning')
        return redirect(url_for('avals'))

    expected_called = _parse_decimal(request.form.get('expected_called'), 0, 1_000_000_000_000) if request.form.get('expected_called') else None
    if expected_called is not None and expected_called != Decimal(str(guarantee.called_amount or 0)):
        flash("Cet appel a déjà été enregistré (double clic ou page ancienne).", 'warning')
        return redirect(url_for('avals'))
    maximum = min(guarantee.remaining_guarantee, loan.remaining_amount)
    try:
        amount = Decimal(request.form.get('amount') or '0')
    except ArithmeticError:
        amount = Decimal('0')
    if amount <= 0 or amount > maximum:
        flash(f"Montant invalide : maximum {maximum:,.0f} FCFA (reste garanti et reste dû).", 'danger')
        return redirect(url_for('avals'))

    payment_mode = request.form.get('payment_mode', 'ESPECE')
    if payment_mode not in ('ESPECE', 'ORANGE_MONEY', 'MTN_MOBILE', 'VIREMENT'):
        payment_mode = 'ESPECE'
    db.session.add(Transaction(
        member_id=guarantee.member_id, type='REMBOURSEMENT', amount=amount, date=date.today(),
        description=f"Paiement en tant qu'avaliste de {loan.member_name} (emprunt #{loan.id})",
        created_by=current_user.id, payment_mode=payment_mode,
    ))
    loan.amount_paid = Decimal(str(loan.amount_paid or 0)) + amount
    guarantee.called_amount = Decimal(str(guarantee.called_amount or 0)) + amount
    guarantee.status = 'APPELE'
    if loan.amount_paid >= loan.total_amount:
        loan.status = 'REMBOURSE'
        _release_guarantors(loan)
    db.session.commit()
    log_activity(current_user.id, current_user.role,
                 f"Appel en garantie : {guarantee.member.full_name} paie {amount:,.0f} FCFA (emprunt #{loan.id})",
                 request.remote_addr)
    flash(f"{amount:,.0f} FCFA encaissés auprès de l'avaliste {guarantee.member.full_name}.", 'success')
    return redirect(url_for('avals'))


@app.route('/avals/<int:guarantee_id>/settle', methods=['POST'])
@login_required
@role_required(AVAL_MANAGERS)
def settle_aval(guarantee_id):
    """L'emprunteur a remboursé son avaliste (règlement entre membres, hors caisse)"""
    guarantee = db.get_or_404(LoanGuarantor, guarantee_id)
    if guarantee.status != 'APPELE':
        flash("Seul un aval appelé peut être marqué comme réglé.", 'warning')
        return redirect(url_for('avals'))
    guarantee.status = 'REGLE'
    guarantee.response_note = f"Réglé le {date.today():%d/%m/%Y}"
    db.session.commit()
    log_activity(current_user.id, current_user.role, f"Dette envers l'avaliste réglée (aval #{guarantee.id})",
                 request.remote_addr)
    flash("Dette envers l'avaliste marquée comme réglée.", 'success')
    return redirect(url_for('avals'))


# ============================================================
# COTISATIONS : RUBRIQUES, ÉTAT PAR MEMBRE, SITUATION DES FONDS
# ============================================================

RUBRIQUE_MANAGERS = ['PRESIDENT', 'TRESORIER', 'SECRETAIRE']


@app.route('/cotisations')
@login_required
def cotisations():
    tontine = current_tontine()
    ensure_contribution_types(tontine)
    year = _year_arg(request.args)
    start, end = date(year, 1, 1), date(year, 12, 31)
    is_bureau = current_user.is_admin()

    rubriques = ContributionType.query.order_by(ContributionType.is_active.desc(),
                                                ContributionType.display_order, ContributionType.id).all()
    in_year = [Transaction.date >= start, Transaction.date <= end]

    # Totaux de l'année par rubrique et par catégorie
    by_rubrique = dict(db.session.query(Transaction.contribution_type_id, db.func.sum(Transaction.amount))
                       .filter(*in_year, Transaction.contribution_type_id.isnot(None))
                       .group_by(Transaction.contribution_type_id).all())
    by_type = dict(db.session.query(Transaction.type, db.func.sum(Transaction.amount))
                   .filter(*in_year).group_by(Transaction.type).all())

    # Situation des fonds (depuis l'origine)
    all_time = dict(db.session.query(Transaction.type, db.func.sum(Transaction.amount)).group_by(Transaction.type).all())
    funds = []
    for code, label in finance.FUNDS.items():
        entrees = sum(float(v or 0) for t, v in all_time.items() if finance.fund_of(t) == code and not finance.is_outflow(t))
        sorties = sum(float(v or 0) for t, v in all_time.items() if finance.fund_of(t) == code and finance.is_outflow(t))
        funds.append({'code': code, 'label': label, 'in': entrees, 'out': sorties, 'balance': entrees - sorties})
    total_balance = sum(f['balance'] for f in funds)

    # État par membre (catégories de cotisation) pour l'année
    categories = [c for c in finance.CONTRIBUTION_CATEGORIES
                  if any(r.category == c and r.is_active for r in rubriques) or by_type.get(c)]
    members_q = Member.query.filter_by(is_active=True).order_by(Member.last_name)
    if not is_bureau:
        members_q = members_q.filter(Member.id == current_user.member_id)
    members_list = members_q.all()
    ids = [mm.id for mm in members_list]
    matrix = {}
    if ids:
        for mid, ttype, total in (db.session.query(Transaction.member_id, Transaction.type, db.func.sum(Transaction.amount))
                                  .filter(*in_year, Transaction.member_id.in_(ids), Transaction.type.in_(categories))
                                  .group_by(Transaction.member_id, Transaction.type).all()):
            matrix.setdefault(mid, {})[ttype] = float(total or 0)

    # Cotisations uniques obligatoires (adhésion, fonds de caisse) : qui ne les a pas encore payées ?
    unique_required = [r for r in rubriques if r.is_active and r.is_mandatory and r.frequency == 'UNIQUE']
    missing = {}
    if ids and unique_required:
        paid = {(mid, t): float(v or 0) for mid, t, v in
                db.session.query(Transaction.member_id, Transaction.type, db.func.sum(Transaction.amount))
                .filter(Transaction.member_id.in_(ids), Transaction.type.in_([r.category for r in unique_required]))
                .group_by(Transaction.member_id, Transaction.type).all()}
        for mm in members_list:
            gaps = [r for r in unique_required if paid.get((mm.id, r.category), 0) < float(r.amount or 0)]
            if gaps:
                missing[mm.id] = gaps

    years = list(range(date.today().year, date.today().year - 5, -1))
    return render_template('cotisations.html', rubriques=rubriques, by_rubrique=by_rubrique, by_type=by_type,
                           funds=funds, total_balance=total_balance, categories=categories, members=members_list,
                           matrix=matrix, missing=missing, year=year, years=years, is_bureau=is_bureau,
                           can_manage=current_user.role in RUBRIQUE_MANAGERS,
                           category_choices=[(c, finance.type_label(c)) for c in finance.CONTRIBUTION_CATEGORIES],
                           frequency_choices=list(finance.FREQUENCIES.items()))


def _rubriques_back():
    return safe_next_url(request.form.get('next')) or url_for('cotisations')


def _rubrique_from_form(rubrique=None):
    f = request.form
    name = (f.get('name') or '').strip()
    category = f.get('category')
    frequency = f.get('frequency') or 'BIMENSUEL'
    amount = _parse_decimal(f.get('amount') or '0', 0, 1_000_000_000)
    errors = []
    if not name and category == 'TONTINE' and amount and amount > 0:
        name = 'Tontine ' + f"{amount:,.0f}".replace(',', ' ')
    if not name or len(name) > 80:
        errors.append('Nom de rubrique obligatoire (80 caractères max).')
    if category not in finance.CONTRIBUTION_CATEGORIES:
        errors.append('Catégorie invalide.')
    if category == 'TONTINE' and (not amount or amount <= 0):
        errors.append('Un niveau de cotisation tontine doit avoir un montant.')
    elif category == 'TONTINE' and not rubrique and ContributionType.query.filter_by(
            category='TONTINE', amount=amount, is_active=True).first():
        errors.append(f"Le niveau {amount:,.0f} FCFA existe déjà.".replace(',', ' '))
    if frequency not in finance.FREQUENCIES:
        errors.append('Périodicité invalide.')
    if amount is None:
        errors.append('Montant invalide.')
    late_fine = None
    if 'late_fine' in f:   # les ajouts rapides (niveaux dans Paramètres) n'envoient pas ce champ
        late_fine = _parse_decimal(f.get('late_fine') or '0', 0, 100_000_000)
        if late_fine is None:
            errors.append("Amende de retard invalide.")
    if errors:
        return None, errors
    rubrique = rubrique or ContributionType()
    rubrique.name = name
    rubrique.category = category
    rubrique.frequency = frequency
    rubrique.amount = amount
    rubrique.is_mandatory = f.get('is_mandatory') == 'on'
    rubrique.description = (f.get('description') or '').strip()[:255] or None
    rubrique.display_order = f.get('display_order', type=int) or 0
    if late_fine is not None:
        rubrique.late_fine = late_fine
    elif rubrique.late_fine is None:
        rubrique.late_fine = Decimal('0')
    return rubrique, []


@app.route('/cotisations/rubriques/add', methods=['POST'])
@login_required
@role_required(RUBRIQUE_MANAGERS)
def add_rubrique():
    rubrique, errors = _rubrique_from_form()
    if errors:
        for e in errors:
            flash(e, 'danger')
        return redirect(_rubriques_back())
    rubrique.is_active = True
    db.session.add(rubrique)
    db.session.commit()
    log_activity(current_user.id, current_user.role, f"Création rubrique de cotisation « {rubrique.name} »", request.remote_addr)
    flash(f"Rubrique « {rubrique.name} » créée.", 'success')
    return redirect(_rubriques_back())


@app.route('/cotisations/rubriques/<int:rubrique_id>', methods=['POST'])
@login_required
@role_required(RUBRIQUE_MANAGERS)
def update_rubrique(rubrique_id):
    rubrique = db.get_or_404(ContributionType, rubrique_id)
    if request.form.get('action') == 'toggle':
        rubrique.is_active = not rubrique.is_active
        db.session.commit()
        flash(f"Rubrique « {rubrique.name} » {'réactivée' if rubrique.is_active else 'désactivée'}.", 'success')
        return redirect(_rubriques_back())
    _, errors = _rubrique_from_form(rubrique)
    if errors:
        db.session.rollback()
        for e in errors:
            flash(e, 'danger')
        return redirect(_rubriques_back())
    db.session.commit()
    log_activity(current_user.id, current_user.role, f"Modification rubrique « {rubrique.name} »", request.remote_addr)
    flash(f"Rubrique « {rubrique.name} » mise à jour.", 'success')
    return redirect(_rubriques_back())


# ============================================================
# SÉANCES : FEUILLE DE COTISATION PAR RÉUNION
# ============================================================
# À chaque réunion, le trésorier coche ce que chaque membre a payé :
# rubriques (présence, secours, épargne...) et parts des cycles en cours
# (montant x nombre de mains). Les transactions sont créées en une fois
# et rattachées à la séance.

SEANCE_MANAGERS = ['PRESIDENT', 'TRESORIER', 'SECRETAIRE']


def _seance_columns(seance):
    """Colonnes de la feuille : rubriques ('r<id>') et cycles ('c<id>')"""
    columns = []
    for key in (seance.columns or '').split(','):
        key = key.strip()
        if not key[1:].isdigit():
            continue
        if key[0] == 'r':
            rubrique = db.session.get(ContributionType, int(key[1:]))
            if rubrique:
                columns.append({'key': key, 'label': rubrique.name, 'rubrique': rubrique, 'cycle': None,
                                'fund': rubrique.fund_display})
        elif key[0] == 'c':
            cycle = db.session.get(TontineCycleDetail, int(key[1:]))
            if cycle:
                columns.append({'key': key, 'label': cycle.display_name, 'rubrique': None, 'cycle': cycle,
                                'fund': 'Tontine'})
    return columns


def _expected_amount(column, member, hands):
    if column['cycle']:
        n = hands.get((column['cycle'].id, member.id), 0)
        return Decimal(str(column['cycle'].amount_per_member)) * n if n else None  # None = ne participe pas
    return Decimal(str(column['rubrique'].amount or 0))


@app.route('/seances')
@login_required
@role_required(SEANCE_MANAGERS + ['CENSEUR'])
def seances():
    ensure_contribution_types(current_tontine())
    seance_list = Seance.query.order_by(Seance.date.desc(), Seance.id.desc()).all()
    rubriques = ContributionType.query.filter(ContributionType.is_active == True,
                                              ContributionType.category != 'TONTINE').order_by(ContributionType.display_order).all()
    cycles = TontineCycleDetail.query.filter_by(status='EN_COURS').all()
    return render_template('seances.html', seances=seance_list, rubriques=rubriques, cycles=cycles,
                           can_manage=current_user.role in SEANCE_MANAGERS, today=date.today().isoformat())


@app.route('/seances/add', methods=['POST'])
@login_required
@role_required(SEANCE_MANAGERS)
def add_seance():
    try:
        seance_date = datetime.strptime(request.form.get('date') or date.today().isoformat(), '%Y-%m-%d').date()
    except ValueError:
        flash('Date invalide.', 'danger')
        return redirect(url_for('seances'))
    keys = []
    for raw in request.form.getlist('columns'):
        if raw[:1] == 'r' and raw[1:].isdigit() and ContributionType.query.filter_by(id=int(raw[1:])).first():
            keys.append(raw)
        elif raw[:1] == 'c' and raw[1:].isdigit() and TontineCycleDetail.query.filter_by(id=int(raw[1:])).first():
            keys.append(raw)
    if not keys:
        flash('Choisissez au moins une cotisation à encaisser pendant la séance.', 'danger')
        return redirect(url_for('seances'))
    seance = Seance(date=seance_date, title=(request.form.get('title') or '').strip()[:120] or None,
                    columns=','.join(keys)[:500], created_by=current_user.id)
    db.session.add(seance)
    db.session.commit()
    log_activity(current_user.id, current_user.role, f"Ouverture {seance.display_name}", request.remote_addr)
    return redirect(url_for('seance_detail', seance_id=seance.id))


@app.route('/seances/<int:seance_id>', methods=['GET', 'POST'])
@login_required
@role_required(SEANCE_MANAGERS + ['CENSEUR'])
def seance_detail(seance_id):
    seance = db.get_or_404(Seance, seance_id)
    columns = _seance_columns(seance)
    members_list = Member.query.filter_by(is_active=True, status='ACTIF').order_by(Member.last_name, Member.first_name).all()
    cycle_ids = [c['cycle'].id for c in columns if c['cycle']]
    hands = {}
    if cycle_ids:
        for cid, mid, n in (db.session.query(CycleParticipant.cycle_id, CycleParticipant.member_id, db.func.count(CycleParticipant.id))
                            .filter(CycleParticipant.cycle_id.in_(cycle_ids))
                            .group_by(CycleParticipant.cycle_id, CycleParticipant.member_id).all()):
            hands[(cid, mid)] = n

    # Paiements déjà enregistrés pendant cette séance : (membre, colonne) -> montant
    paid = {}
    for tx in Transaction.query.filter_by(seance_id=seance.id).all():
        key = f"c{tx.cycle_id}" if tx.cycle_id and tx.type == 'TONTINE' else (f"r{tx.contribution_type_id}" if tx.contribution_type_id else None)
        if key:
            paid[(tx.member_id, key)] = paid.get((tx.member_id, key), Decimal('0')) + Decimal(str(tx.amount))

    if request.method == 'POST':
        if current_user.role not in SEANCE_MANAGERS:
            abort(403)
        if seance.is_closed:
            flash('Cette séance est clôturée.', 'warning')
            return redirect(url_for('seance_detail', seance_id=seance.id))
        payment_mode = _payment_mode_from_form()
        created, total = 0, Decimal('0')
        for member in members_list:
            reference = (request.form.get(f'ref_{member.id}') or '').strip()[:60] or None
            for col in columns:
                if request.form.get(f'pay_{member.id}_{col["key"]}') != 'on' or (member.id, col['key']) in paid:
                    continue
                if col['cycle'] and not hands.get((col['cycle'].id, member.id)):
                    continue
                amount = _parse_decimal(request.form.get(f'amt_{member.id}_{col["key"]}') or '0', 0, 100_000_000)
                if not amount:
                    continue
                if col['cycle']:
                    tx = Transaction(member_id=member.id, type='TONTINE', amount=amount, cycle_id=col['cycle'].id,
                                     contribution_type_id=col['cycle'].contribution_type_id,
                                     description=f"{col['cycle'].display_name} - {seance.display_name}")
                else:
                    tx = Transaction(member_id=member.id, type=col['rubrique'].category, amount=amount,
                                     contribution_type_id=col['rubrique'].id,
                                     description=f"{col['rubrique'].name} - {seance.display_name}")
                tx.date = seance.date
                tx.seance_id = seance.id
                tx.payment_mode = payment_mode
                tx.payment_reference = reference
                tx.created_by = current_user.id
                db.session.add(tx)
                created += 1
                total += amount
        db.session.commit()
        if created:
            log_activity(current_user.id, current_user.role,
                         f"{seance.display_name} : {created} paiement(s), {total:,.0f} FCFA", request.remote_addr)
            flash(f"{created} paiement(s) enregistré(s) pour {total:,.0f} FCFA.".replace(',', ' '), 'success')
        else:
            flash('Aucun nouveau paiement coché.', 'info')
        return redirect(url_for('seance_detail', seance_id=seance.id))

    rows = []
    for member in members_list:
        cells = []
        for col in columns:
            expected = _expected_amount(col, member, hands)
            cells.append({'col': col, 'expected': expected, 'paid': paid.get((member.id, col['key']))})
        rows.append({'member': member, 'cells': cells})
    totals = {col['key']: sum((v for (mid, k), v in paid.items() if k == col['key']), Decimal('0')) for col in columns}

    # Cagnottes du tour pour chaque cycle de la séance : bénéficiaire prévu et versements déjà faits
    payouts = []
    for col in columns:
        cycle = col['cycle']
        if not cycle:
            continue
        nxt = cycle.get_next_participant() if cycle.status == 'EN_COURS' else None
        pending = Decimal('0')
        if nxt:
            pending = Decimal(str(db.session.query(db.func.sum(Sanction.amount)).filter(
                Sanction.member_id == nxt.member_id, Sanction.status == 'PENDING').scalar() or 0))
        done = (Transaction.query.filter_by(seance_id=seance.id, cycle_id=cycle.id, type='BENEFICE_TONTINE')
                .order_by(Transaction.id).all())
        status = cycle_contribution_status(cycle) if cycle.status == 'EN_COURS' else None
        payouts.append({'cycle': cycle, 'collected': totals[col['key']], 'next': nxt, 'pending_sanctions': pending,
                        'done': done, 'turn': cycle.beneficiaries_count + 1,
                        'missing': status['missing'] if status else Decimal('0'),
                        'late': [r for r in status['rows'] if r['gap'] < 0] if status else []})
    return render_template('seance_detail.html', seance=seance, columns=columns, rows=rows, totals=totals,
                           grand_total=sum(totals.values(), Decimal('0')), payouts=payouts,
                           late_fines=seance_late_fines(seance) if not seance.is_closed else [],
                           seance_fines=Sanction.query.filter(Sanction.origin_key.like(f"seance{seance.id}:%"))
                           .order_by(Sanction.id).all(),
                           can_manage=current_user.role in SEANCE_MANAGERS and not seance.is_closed,
                           can_pay_out=current_user.role in CYCLE_MANAGERS and not seance.is_closed)


# ------------------------------------------------------------
# AMENDES DE RETARD DE COTISATION
# ------------------------------------------------------------
# Chaque cotisation (rubrique ou niveau de tontine) a un champ « Amende si retard ».
# À la clôture d'une séance, chaque membre qui devait payer une cotisation de la
# feuille et ne l'a pas fait reçoit cette amende (une seule fois par cotisation et
# par séance). Rouvrir la séance annule les amendes non encore payées ; elles sont
# recalculées à la clôture suivante.
_PERIOD_DAYS = {'HEBDOMADAIRE': 7, 'BIMENSUEL': 14}


def _rubrique_paid_in_period(member, rubrique, seance):
    """Le membre a-t-il déjà payé cette rubrique pour la période de la séance ?"""
    q = Transaction.query.filter(Transaction.member_id == member.id)
    if rubrique.frequency == 'UNIQUE':   # payée une fois pour toutes (fonds de caisse, adhésion...)
        return q.filter(db.or_(Transaction.contribution_type_id == rubrique.id,
                               db.and_(Transaction.contribution_type_id.is_(None),
                                       Transaction.type == rubrique.category))).first() is not None
    q = q.filter(Transaction.contribution_type_id == rubrique.id)
    if rubrique.frequency == 'PAR_SEANCE':
        return q.filter(Transaction.seance_id == seance.id).first() is not None
    if rubrique.frequency in _PERIOD_DAYS:
        start = seance.date - timedelta(days=_PERIOD_DAYS[rubrique.frequency] - 1)
    elif rubrique.frequency == 'MENSUEL':
        start = seance.date.replace(day=1)
    else:   # ANNUEL
        start = seance.date.replace(month=1, day=1)
    return q.filter(db.or_(Transaction.seance_id == seance.id,
                           db.and_(Transaction.date >= start, Transaction.date <= seance.date))).first() is not None


def seance_late_fines(seance):
    """Amendes de retard que la clôture de la séance va infliger : liste de dicts
    {member, label, amount, key, reason}"""
    fines = []
    members = [mb for mb in Member.query.filter_by(is_active=True, status='ACTIF').order_by(Member.last_name).all()
               if not mb.registration_date or mb.registration_date <= seance.date]
    for col in _seance_columns(seance):
        key = f"seance{seance.id}:{col['key']}"
        cycle = col['cycle']
        if cycle:
            rubrique = cycle.contribution_type
            fine = Decimal(str(rubrique.late_fine or 0)) if rubrique else Decimal('0')
            if fine <= 0 or cycle.status not in ('EN_COURS', 'TERMINE'):
                continue
            paid_out_here = Transaction.query.filter_by(seance_id=seance.id, cycle_id=cycle.id,
                                                        type='BENEFICE_TONTINE').first() is not None
            turn = cycle.beneficiaries_count + (0 if paid_out_here or cycle.status == 'TERMINE' else 1)
            if turn <= 0:
                continue
            for row in cycle_contribution_status(cycle, through_turn=turn)['rows']:
                if row['gap'] < 0 and row['member'] and row['member'].is_active and row['member'].status == 'ACTIF':
                    fines.append({'member': row['member'], 'label': cycle.display_name, 'amount': fine, 'key': key,
                                  'reason': f"cotisation du tour {turn} non payée (manque {_fmt(-row['gap'])} FCFA)"})
            continue
        rubrique = col['rubrique']
        fine = Decimal(str(rubrique.late_fine or 0))
        if (fine <= 0 or not rubrique.is_mandatory or rubrique.frequency == 'LIBRE'
                or not rubrique.amount or rubrique.amount <= 0):
            continue
        for member in members:
            if not _rubrique_paid_in_period(member, rubrique, seance):
                fines.append({'member': member, 'label': rubrique.name, 'amount': fine, 'key': key,
                              'reason': f"{rubrique.name} non payé(e)"})
    # Une amende déjà infligée (payée ou non) pour la même cotisation et la même séance n'est pas refaite
    existing = {(s.member_id, s.origin_key) for s in
                Sanction.query.filter(Sanction.origin_key.like(f"seance{seance.id}:%")).all()}
    return [f for f in fines if (f['member'].id, f['key']) not in existing]


@app.route('/seances/<int:seance_id>/close', methods=['POST'])
@login_required
@role_required(['PRESIDENT', 'TRESORIER'])
def close_seance(seance_id):
    seance = db.get_or_404(Seance, seance_id)
    back = redirect(url_for('seance_detail', seance_id=seance.id))
    if not seance.is_closed:
        fines = seance_late_fines(seance)
        for f in fines:
            db.session.add(Sanction(member_id=f['member'].id, type_sanction='RETARD_COTISATION', amount=f['amount'],
                                    sanction_date=seance.date, status='PENDING', origin_key=f['key'],
                                    description=f"Retard de cotisation : {f['reason']} - {seance.display_name}"))
        seance.is_closed = True
        db.session.commit()
        total = sum((f['amount'] for f in fines), Decimal('0'))
        log_activity(current_user.id, current_user.role,
                     f"Clôture {seance.display_name} : {len(fines)} amende(s) de retard, {_fmt(total)} FCFA", request.remote_addr)
        flash(f"Séance clôturée. {len(fines)} amende(s) de retard infligée(s) pour {_fmt(total)} FCFA."
              if fines else 'Séance clôturée. Aucun retard de cotisation.', 'success')
        return back
    # Réouverture : les amendes automatiques non payées sont annulées (recalculées à la prochaine clôture)
    cancelled = Sanction.query.filter(Sanction.origin_key.like(f"seance{seance.id}:%"), Sanction.status == 'PENDING').all()
    for s in cancelled:
        db.session.delete(s)
    seance.is_closed = False
    db.session.commit()
    log_activity(current_user.id, current_user.role,
                 f"Réouverture {seance.display_name} : {len(cancelled)} amende(s) de retard annulée(s)", request.remote_addr)
    flash('Séance rouverte.' + (f" {len(cancelled)} amende(s) de retard non payée(s) annulée(s) : elles seront "
                                "recalculées à la clôture." if cancelled else ''), 'info')
    return back


# ============================================================
# FIN D'EXERCICE : RESTITUTION DE L'ÉPARGNE ET PARTAGE DES BÉNÉFICES
# ============================================================
# Pratique courante : en fin d'année, chaque membre récupère son épargne et
# reçoit une part des bénéfices de la caisse (mises d'enchères, intérêts
# d'emprunts, éventuellement amendes), au prorata de son épargne.

def _exercise_preview(year, include_sanctions, override_amount=None):
    start, end = date(year, 1, 1), date(year, 12, 31)

    def year_sum(types):
        return Decimal(str(db.session.query(db.func.sum(Transaction.amount)).filter(
            Transaction.type.in_(types), Transaction.date >= start, Transaction.date <= end).scalar() or 0))

    auctions = year_sum(['ENCHERE'])
    interests = Decimal(str(db.session.query(db.func.sum(Loan.interest)).filter(
        Loan.status == 'REMBOURSE', Loan.request_date >= start, Loan.request_date <= end).scalar() or 0))
    sanctions_total = year_sum(['SANCTION']) if include_sanctions else Decimal('0')
    proposed = auctions + interests + sanctions_total
    pool = override_amount if override_amount is not None else proposed

    savers = []
    for member in Member.query.filter_by(is_active=True).order_by(Member.last_name).all():
        balance = member.savings_balance
        if balance > 0:
            savers.append({'member': member, 'savings': balance})
    total_savings = sum((s['savings'] for s in savers), Decimal('0'))
    for s in savers:
        share = (pool * s['savings'] / total_savings).quantize(Decimal('1'), rounding='ROUND_DOWN') if total_savings else Decimal('0')
        s['ratio'] = float(s['savings'] / total_savings * 100) if total_savings else 0
        s['profit'] = share
        s['total'] = s['savings'] + share
    caisse = sum((Decimal(str(v or 0)) * (-1 if finance.is_outflow(t) else 1)
                  for t, v in db.session.query(Transaction.type, db.func.sum(Transaction.amount)).group_by(Transaction.type).all()
                  if finance.fund_of(t) == 'CAISSE'), Decimal('0'))
    return {'auctions': auctions, 'interests': interests, 'sanctions': sanctions_total, 'proposed': proposed,
            'pool': pool, 'savers': savers, 'total_savings': total_savings,
            'distributed': sum((s['profit'] for s in savers), Decimal('0')), 'caisse_balance': caisse}


@app.route('/exercice', methods=['GET', 'POST'])
@login_required
@role_required(['PRESIDENT', 'TRESORIER', 'SECRETAIRE'])
def exercise():
    year = _year_arg(request.values)
    include_sanctions = request.values.get('include_sanctions') == 'on'
    override = None
    if request.values.get('pool_amount') not in (None, ''):
        override = _parse_decimal(request.values.get('pool_amount'), 0, 1_000_000_000)
    preview = _exercise_preview(year, include_sanctions, override)
    closure = ExerciseClosure.query.filter_by(year=year).first()

    if request.method == 'POST' and request.form.get('action') == 'execute':
        if current_user.role not in ('PRESIDENT', 'TRESORIER'):
            abort(403)
        if closure:
            flash(f"L'exercice {year} est déjà clôturé.", 'warning')
            return redirect(url_for('exercise', year=year))
        if not preview['savers']:
            flash("Aucun membre n'a d'épargne à restituer.", 'warning')
            return redirect(url_for('exercise', year=year))
        if preview['distributed'] > max(preview['caisse_balance'], Decimal('0')):
            flash(f"La caisse générale ({preview['caisse_balance']:,.0f} FCFA) ne suffit pas pour distribuer "
                  f"{preview['distributed']:,.0f} FCFA de bénéfices.".replace(',', ' '), 'danger')
            return redirect(url_for('exercise', year=year))
        payment_mode = _payment_mode_from_form()
        for s in preview['savers']:
            db.session.add(Transaction(member_id=s['member'].id, type='RETRAIT_EPARGNE', amount=s['savings'], date=date.today(),
                                       description=f"Restitution de l'épargne - exercice {year}",
                                       created_by=current_user.id, payment_mode=payment_mode))
            if s['profit'] > 0:
                db.session.add(Transaction(member_id=s['member'].id, type='PARTAGE', amount=s['profit'], date=date.today(),
                                           description=f"Part des bénéfices - exercice {year} ({s['ratio']:.1f} %)",
                                           created_by=current_user.id, payment_mode=payment_mode))
        db.session.add(ExerciseClosure(year=year, savings_returned=preview['total_savings'],
                                       profit_distributed=preview['distributed'], beneficiaries=len(preview['savers']),
                                       executed_by=current_user.id,
                                       notes=(request.form.get('notes') or '').strip()[:255] or None))
        db.session.commit()
        log_activity(current_user.id, current_user.role,
                     f"Clôture exercice {year} : épargne {preview['total_savings']:,.0f}, bénéfices {preview['distributed']:,.0f} FCFA",
                     request.remote_addr)
        flash(f"Exercice {year} clôturé : {len(preview['savers'])} membre(s) remboursé(s).", 'success')
        return redirect(url_for('exercise', year=year))

    years = list(range(date.today().year, date.today().year - 5, -1))
    return render_template('exercice.html', year=year, years=years, preview=preview, closure=closure,
                           include_sanctions=include_sanctions, override=override,
                           can_execute=current_user.role in ('PRESIDENT', 'TRESORIER'))


# ============================================================
# PARAMÈTRES DE LA TONTINE (Président)
# ============================================================

def _parse_decimal(value, minimum, maximum):
    """Montant saisi -> Decimal fini compris entre minimum et maximum, sinon None.
    Refuse NaN / Infinity / texte (Decimal les accepte mais ils font planter les comparaisons)."""
    try:
        number = Decimal(str(value).replace(',', '.').replace(' ', '').replace(' ', ''))
    except (ArithmeticError, ValueError, TypeError):
        return None
    if not number.is_finite():
        return None
    return number if Decimal(str(minimum)) <= number <= Decimal(str(maximum)) else None


def _year_arg(source):
    """Année d'exercice lue dans la requête, bornée à des valeurs plausibles"""
    year = source.get('year', type=int)
    return year if year and 2000 <= year <= 2100 else date.today().year


@app.route('/parametres', methods=['GET', 'POST'])
@login_required
@president_required
def tontine_settings():
    tontine = current_tontine()
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        presence = _parse_decimal(request.form.get('presence_amount'), 0, 10_000_000)
        fonds = _parse_decimal(request.form.get('fonds_caisse_amount'), 0, 10_000_000)
        rate = _parse_decimal(request.form.get('loan_interest_rate'), 0, 100)
        max_aids = request.form.get('max_aid_per_member', type=int)
        # Champs d'aval absents (ancien formulaire, client externe) : on garde les valeurs actuelles
        threshold = (_parse_decimal(request.form.get('guarantee_threshold') or '0', 0, 1_000_000_000)
                     if 'guarantee_threshold' in request.form else Decimal(str(tontine.guarantee_threshold or 0)))
        guarantors_min = (request.form.get('guarantors_min', type=int)
                          if 'guarantors_min' in request.form else (tontine.guarantors_min or 0))

        errors = []
        if not name or len(name) > 120:
            errors.append('Le nom est obligatoire (120 caractères max).')
        if presence is None or fonds is None:
            errors.append('Montants invalides.')
        if rate is None:
            errors.append("Le taux d'intérêt doit être compris entre 0 et 100 %.")
        if max_aids is None or not 0 <= max_aids <= 50:
            errors.append("Le nombre maximum d'aides doit être compris entre 0 et 50.")
        if threshold is None:
            errors.append("Seuil d'aval invalide.")
        if guarantors_min is None or not 0 <= guarantors_min <= 5:
            errors.append("Le nombre d'avalistes exigés doit être compris entre 0 et 5.")
        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('tontine_settings.html', tontine=tontine, form_data=request.form, levels=tontine_levels(False), frequency_choices=list(finance.FREQUENCIES.items()),
                           aid_types=AidType.query.order_by(AidType.display_order, AidType.id).all(), aid_rule_values=aid_rules(tontine))

        tontine.name = name
        tontine.tagline = (request.form.get('tagline') or '').strip()[:200] or None
        tontine.location = (request.form.get('location') or '').strip()[:120] or None
        tontine.contact_phone = (request.form.get('contact_phone') or '').strip()[:30] or None
        tontine.contact_email = (request.form.get('contact_email') or '').strip()[:120] or None
        whatsapp = (request.form.get('whatsapp_link') or '').strip()[:200]
        tontine.whatsapp_link = whatsapp if whatsapp.startswith('https://') else None
        tontine.presence_amount = presence
        tontine.fonds_caisse_amount = fonds
        tontine.loan_interest_rate = rate
        tontine.max_aid_per_member = max_aids
        tontine.guarantee_threshold = threshold
        tontine.guarantors_min = guarantors_min
        db.session.commit()

        log_activity(current_user.id, current_user.role, "Modification des paramètres de la tontine", request.remote_addr)
        flash('Paramètres enregistrés.', 'success')
        return redirect(url_for('tontine_settings'))

    ensure_contribution_types(tontine)
    ensure_aid_types(tontine)
    return render_template('tontine_settings.html', tontine=tontine, form_data=None, levels=tontine_levels(False), frequency_choices=list(finance.FREQUENCIES.items()),
                           aid_types=AidType.query.order_by(AidType.display_order, AidType.id).all(), aid_rule_values=aid_rules(tontine))


# ============================================================
# SUPER-ADMIN : GESTION DES TONTINES DE LA PLATEFORME
# ============================================================

SLUG_RE = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,48}[a-z0-9])?$')


def superadmin_required(f):
    from functools import wraps

    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_superadmin:
            abort(403)
        return f(*args, **kwargs)
    return wrapper


@app.route('/superadmin')
@login_required
@superadmin_required
def superadmin():
    tontines = Tontine.query.order_by(Tontine.created_at.desc()).all()
    counts = {}
    with tenant_bypass():
        for t in tontines:
            counts[t.id] = {
                'members': Member.query.filter_by(tontine_id=t.id, is_active=True).count(),
                'users': User.query.filter_by(tontine_id=t.id).count(),
                'cycles': TontineCycleDetail.query.filter_by(tontine_id=t.id).count(),
            }
    return _superadmin_render(tontines, counts, {})


def _superadmin_render(tontines, counts, form_data):
    with tenant_bypass():
        billing_info = {t.id: billing.status(t, active_members_count(t.id)) for t in tontines}
        pending = BillingPayment.query.filter_by(status='EN_ATTENTE').order_by(BillingPayment.declared_at).all()
        recent = BillingPayment.query.filter(BillingPayment.status != 'EN_ATTENTE').order_by(
            BillingPayment.validated_at.desc()).limit(10).all()
        due_total = sum(i['monthly'] for i in billing_info.values() if i['plan'] == 'PAYANT')
        return render_template('superadmin.html', tontines=tontines, counts=counts, form_data=form_data,
                               billing_info=billing_info, pending_payments=pending, recent_payments=recent,
                               monthly_total=due_total)


EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def create_tontine_with_president(form):
    """Crée une tontine et son premier compte (président).
    Retourne (tontine, user, erreurs). Ne commite pas si erreurs."""
    name = (form.get('name') or '').strip()
    slug = (form.get('slug') or '').strip().lower()
    username = (form.get('username') or '').strip()
    password = form.get('password') or ''
    first_name = (form.get('first_name') or '').strip()
    last_name = (form.get('last_name') or '').strip()
    email = (form.get('email') or '').strip().lower()
    phone = (form.get('phone') or '').strip()

    errors = []
    if not name or len(name) > 120:
        errors.append('Le nom de la tontine est obligatoire (120 caractères max).')
    if not SLUG_RE.match(slug):
        errors.append("Adresse web invalide : lettres minuscules, chiffres et tirets (ex. tontine-des-amis).")
    elif Tontine.query.filter_by(slug=slug).first():
        errors.append(f"L'adresse « {slug} » est déjà prise, choisissez-en une autre.")
    if not (first_name and last_name and phone and username):
        errors.append('Prénom, nom, téléphone et identifiant sont obligatoires.')
    if len(first_name) > 50 or len(last_name) > 50 or len(phone) > 20 or len(username) > 80:
        errors.append('Un des champs est trop long.')
    if (first_name and len(first_name) < 2) or (last_name and len(last_name) < 2):
        errors.append('Le prénom et le nom doivent contenir au moins 2 caractères.')
    if not EMAIL_RE.match(email) or len(email) > 120:
        errors.append('Adresse email invalide.')
    if not re.match(r'^[A-Za-z0-9_.-]{3,80}$', username or ''):
        errors.append("L'identifiant doit faire au moins 3 caractères (lettres, chiffres, . _ -).")
    if len(password) < 8:
        errors.append('Le mot de passe doit contenir au moins 8 caractères.')
    if 'password_confirm' in form and form.get('password_confirm') != password:
        errors.append('Les deux mots de passe ne correspondent pas.')
    if errors:
        return None, None, errors

    tontine = Tontine(
        name=name, slug=slug,
        location=(form.get('location') or '').strip()[:120] or None,
        contact_phone=phone[:30], contact_email=email[:120],
        presence_amount=app.config['PRESENCE_AMOUNT'],
        fonds_caisse_amount=app.config['FONDS_CAISSE_AMOUNT'],
        loan_interest_rate=app.config['LOAN_INTEREST_RATE_NORMAL'],
        max_aid_per_member=app.config['MAX_AID_PER_MEMBER'],
        is_active=True,
    )
    db.session.add(tontine)
    db.session.flush()

    president = Member(
        tontine_id=tontine.id, first_name=first_name, last_name=last_name, email=email, phone=phone,
        registration_date=date.today(), status='ACTIF', is_active=True, tontine_status='VERT',
        consecutive_failures=0, credit_balance=Decimal('0.00'), debit_balance=Decimal('0.00'),
        amount_to_receive=Decimal('0.00'), has_received_benefit=False,
    )
    db.session.add(president)
    db.session.flush()

    user = User(tontine_id=tontine.id, username=username, email=email, role='PRESIDENT',
                member_id=president.id, is_active=True)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    ensure_contribution_types(tontine)
    ensure_aid_types(tontine)
    return tontine, user, []


def _superadmin_page(form_data):
    tontines = Tontine.query.order_by(Tontine.created_at.desc()).all()
    with tenant_bypass():
        counts = {t.id: {'members': Member.query.filter_by(tontine_id=t.id, is_active=True).count(),
                         'users': User.query.filter_by(tontine_id=t.id).count(),
                         'cycles': TontineCycleDetail.query.filter_by(tontine_id=t.id).count()}
                  for t in tontines}
    return _superadmin_render(tontines, counts, form_data)


@app.route('/superadmin/tontines/add', methods=['POST'])
@login_required
@superadmin_required
def superadmin_add_tontine():
    tontine, user, errors = create_tontine_with_president(request.form)
    if errors:
        for e in errors:
            flash(e, 'danger')
        return _superadmin_page(request.form)

    log_activity(current_user.id, current_user.role, f"Création tontine « {tontine.name} » ({tontine.slug})", request.remote_addr)
    flash(f"Tontine « {tontine.name} » créée. Le président peut se connecter avec l'identifiant « {user.username} ».", 'success')
    return redirect(url_for('superadmin'))


@app.route('/inscription', methods=['GET', 'POST'])
def signup():
    """Création libre d'une nouvelle tontine par son fondateur (qui en devient président)"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if not app.config['ALLOW_PUBLIC_SIGNUP']:
        flash("La création de tontine se fait sur demande auprès de l'administrateur.", 'info')
        return redirect(url_for('index'))

    if request.method == 'POST':
        # Champ piège invisible : rempli uniquement par les robots
        if request.form.get('website'):
            return redirect(url_for('index'))
        tontine, user, errors = create_tontine_with_president(request.form)
        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('signup.html', form_data=request.form)

        set_current_tenant(tontine.id)
        log_activity(user.id, user.role, f"Création de la tontine « {tontine.name} » (inscription en ligne)", request.remote_addr)
        if app.config['REQUIRE_EMAIL_CONFIRMATION']:
            tontine.pending_confirmation = True
            db.session.commit()
            sent, link = send_confirmation_email(tontine, user)
            if not sent and _is_local_request():
                session['local_confirmation_link'] = link   # poste local sans e-mail configuré : lien affiché
            return redirect(url_for('signup_pending', slug=tontine.slug))
        login_user(user)
        flash(f"Bienvenue ! Votre tontine « {tontine.name} » est prête. Suivez les premiers pas ci-dessous.", 'success')
        return redirect(url_for('dashboard'))

    return render_template('signup.html', form_data={})


# ------------------------------------------------------------
# CONFIRMATION DE L'E-MAIL À L'INSCRIPTION
# ------------------------------------------------------------
# La tontine créée en ligne reste invisible et inaccessible tant que son fondateur
# n'a pas cliqué sur le lien reçu par e-mail. Passé EMAIL_CONFIRMATION_HOURS (3 h),
# elle est supprimée avec tout son contenu : il faut la recréer.
CONFIRM_SALT = 'ghelia-email-confirm'
_last_purge = [0.0]


def _confirm_serializer():
    return URLSafeTimedSerializer(app.config['SECRET_KEY'], salt=CONFIRM_SALT)


def _is_local_request():
    return (request.host or '').split(':')[0] in ('127.0.0.1', 'localhost')


def send_email(to, subject, body):
    """Envoie un e-mail texte via le serveur SMTP configuré (variables MAIL_*). Sans configuration
    (poste local, tests), le message est gardé dans app.extensions['outbox'] et noté dans le journal."""
    import smtplib
    from email.message import EmailMessage
    cfg = app.config
    if not to:
        return False
    if cfg.get('MAIL_SUPPRESS_SEND') or not (cfg.get('MAIL_USERNAME') and cfg.get('MAIL_PASSWORD')):
        app.extensions.setdefault('outbox', []).append({'to': to, 'subject': subject, 'body': body})
        app.logger.warning("E-mail non envoyé (serveur d'envoi non configuré) à %s : %s", to, subject)
        return False
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = cfg.get('MAIL_DEFAULT_SENDER') or cfg['MAIL_USERNAME']
    msg['To'] = to
    msg.set_content(body)
    try:
        with smtplib.SMTP(cfg['MAIL_SERVER'], cfg['MAIL_PORT'], timeout=20) as smtp:
            if cfg.get('MAIL_USE_TLS', True):
                smtp.starttls()
            smtp.login(cfg['MAIL_USERNAME'], cfg['MAIL_PASSWORD'])
            smtp.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        app.logger.error("Échec d'envoi d'e-mail à %s : %s", to, exc)
        return False


def send_confirmation_email(tontine, user):
    """Envoie le lien de confirmation ; retourne (envoyé ?, lien)"""
    token = _confirm_serializer().dumps({'t': tontine.id, 'u': user.id, 'e': user.email})
    link = url_for('confirm_signup', token=token, _external=True)
    hours = app.config['EMAIL_CONFIRMATION_HOURS']
    deadline = (tontine.created_at or utcnow()) + timedelta(hours=hours)
    body = (f"Bonjour,\n\n"
            f"Vous venez de créer la tontine « {tontine.name} » sur {app.config['APP_NAME']}.\n"
            f"Pour l'activer, confirmez votre adresse e-mail en ouvrant ce lien :\n\n{link}\n\n"
            f"Ce lien est valable {hours} heures (jusqu'au {deadline:%d/%m/%Y à %H:%M} UTC). Sans confirmation, "
            f"la tontine sera supprimée et il faudra la recréer.\n\n"
            f"Votre identifiant de connexion : {user.username}\n\n"
            f"Si vous n'êtes pas à l'origine de cette inscription, ignorez ce message.\n\n"
            f"{app.config['APP_NAME']}")
    return send_email(user.email, f"Confirmez votre tontine « {tontine.name} »", body), link


def delete_tontine_completely(tontine_id):
    """Supprime une tontine et TOUT son contenu (toutes les tables qui ont tontine_id), ses fichiers
    et les lignes sans tontine_id qui pointent vers ses comptes ou ses membres."""
    import shutil
    with tenant_bypass():
        user_ids = [u.id for u in User.query.filter_by(tontine_id=tontine_id).all()]
        member_ids = [mb.id for mb in Member.query.filter_by(tontine_id=tontine_id).all()]
        for table in reversed(db.metadata.sorted_tables):
            if table.name == 'tontines':
                continue
            if 'tontine_id' in table.c:
                db.session.execute(table.delete().where(table.c.tontine_id == tontine_id))
                continue
            for fk in table.foreign_keys:   # ex. journal d'audit rattaché à un compte de la tontine
                target = fk.column.table.name
                ids = user_ids if target == 'users' else member_ids if target == 'members' else None
                if ids:
                    db.session.execute(table.delete().where(fk.parent.in_(ids)))
        db.session.execute(Tontine.__table__.delete().where(Tontine.__table__.c.id == tontine_id))
        db.session.commit()
    for folder in (os.path.join(app.config['UPLOAD_FOLDER'], str(tontine_id)),
                   os.path.join(BASE_DIR, 'instance', 'justificatifs', str(tontine_id))):
        shutil.rmtree(folder, ignore_errors=True)


def purge_unconfirmed_tontines(force=False):
    """Supprime les tontines non confirmées depuis plus de EMAIL_CONFIRMATION_HOURS (au plus toutes les 5 min)"""
    now = time.time()
    if not force and now - _last_purge[0] < 300:
        return 0
    _last_purge[0] = now
    cutoff = utcnow() - timedelta(hours=app.config['EMAIL_CONFIRMATION_HOURS'])
    with tenant_bypass():
        expired = [t.id for t in Tontine.query.filter(Tontine.pending_confirmation == True,  # noqa: E712
                                                      Tontine.created_at < cutoff).all()]
    for tid in expired:
        delete_tontine_completely(tid)
        app.logger.info("Tontine %s supprimée : e-mail non confirmé dans le délai", tid)
    return len(expired)


@app.before_request
def _purge_unconfirmed_signups():
    if request.endpoint and request.endpoint != 'static':
        try:
            purge_unconfirmed_tontines()
        except Exception as exc:   # le nettoyage ne doit jamais bloquer une page
            db.session.rollback()
            app.logger.error("Nettoyage des inscriptions non confirmées impossible : %s", exc)


@app.route('/inscription/en-attente/<slug>', methods=['GET', 'POST'])
def signup_pending(slug):
    """Page « vérifiez votre e-mail » ; POST = renvoyer le lien"""
    with tenant_bypass():
        tontine = Tontine.query.filter_by(slug=slug, pending_confirmation=True).first()
        if tontine is None:
            flash("Cette inscription n'existe plus : le délai de confirmation est dépassé ou elle est déjà confirmée.", 'info')
            return redirect(url_for('login'))
        president = User.query.filter_by(tontine_id=tontine.id, role='PRESIDENT').first()
        deadline = (tontine.created_at or utcnow()) + timedelta(hours=app.config['EMAIL_CONFIRMATION_HOURS'])
        if request.method == 'POST' and president:
            if is_rate_limited('confirm', slug):   # 5 renvois max par inscription et par adresse IP
                flash('Trop de demandes. Réessayez plus tard.', 'danger')
            else:
                _record_failure(('confirm', request.remote_addr or '?', slug.lower()), ('confirm', request.remote_addr or '?'))
                sent, link = send_confirmation_email(tontine, president)
                if not sent and _is_local_request():
                    session['local_confirmation_link'] = link
                flash('Un nouveau lien vient d\'être envoyé.' if sent else "L'e-mail n'a pas pu être envoyé.",
                      'success' if sent else 'warning')
            return redirect(url_for('signup_pending', slug=slug))
        email = president.email if president else ''
    masked = re.sub(r'(?<=^.)[^@]*(?=[^@]@)', lambda mo: '•' * len(mo.group(0)), email) if email else ''
    return render_template('signup_pending.html', tontine=tontine, email=masked, deadline=deadline,
                           hours=app.config['EMAIL_CONFIRMATION_HOURS'],
                           local_link=session.pop('local_confirmation_link', None))


@app.route('/inscription/confirmer/<token>')
def confirm_signup(token):
    try:
        data = _confirm_serializer().loads(token, max_age=app.config['EMAIL_CONFIRMATION_HOURS'] * 3600)
    except SignatureExpired:
        purge_unconfirmed_tontines(force=True)
        flash("Ce lien a expiré : la tontine n'a pas été confirmée à temps et a été supprimée. Recréez-la.", 'warning')
        return redirect(url_for('signup'))
    except BadSignature:
        abort(404)
    with tenant_bypass():
        tontine = db.session.get(Tontine, data.get('t'))
        user = db.session.get(User, data.get('u'))
        if not tontine or not user or user.tontine_id != tontine.id or user.email != data.get('e'):
            flash("Cette inscription n'existe plus. Recréez votre tontine.", 'warning')
            return redirect(url_for('signup'))
        if not tontine.pending_confirmation:
            flash('Votre adresse e-mail est déjà confirmée : connectez-vous.', 'info')
            return redirect(url_for('login', t=tontine.slug))
        tontine.pending_confirmation = False
        tontine.confirmed_at = utcnow()
        db.session.commit()
    set_current_tenant(tontine.id)
    log_activity(user.id, user.role, f"Adresse e-mail confirmée : tontine « {tontine.name} » activée", request.remote_addr)
    login_user(user)
    flash(f"Adresse e-mail confirmée. Bienvenue ! Votre tontine « {tontine.name} » est prête. "
          "Suivez les premiers pas ci-dessous.", 'success')
    return redirect(url_for('dashboard'))


# ------------------------------------------------------------
# ABONNEMENT : page du président / trésorier
# ------------------------------------------------------------
@app.route('/abonnement', methods=['GET', 'POST'])
@login_required
@role_required(BILLING_MANAGERS + ['SECRETAIRE'])
def abonnement():
    tontine = current_tontine()
    info = g.get('billing') or tontine_billing(tontine)
    if request.method == 'POST':
        if current_user.role not in BILLING_MANAGERS:
            abort(403)
        months = request.form.get('months', type=int) or 0
        reference = (request.form.get('reference') or '').strip()
        if not 1 <= months <= billing.MAX_MONTHS:
            flash(f"Choisissez entre 1 et {billing.MAX_MONTHS} mois.", 'danger')
        elif not info['monthly']:
            flash("Votre tontine ne paie rien actuellement : aucun paiement à déclarer.", 'info')
        elif not re.match(r'^[A-Za-z0-9._\-/]{4,80}$', reference):
            flash("Référence SasPay invalide (lettres, chiffres, . _ - /, 4 caractères minimum).", 'danger')
        elif BillingPayment.query.filter(db.func.lower(BillingPayment.reference) == reference.lower()).first():
            flash("Cette référence a déjà été déclarée.", 'warning')
        else:
            amount = Decimal(info['monthly']) * months
            db.session.add(BillingPayment(months=months, members_count=info['members'],
                                          monthly_amount=Decimal(info['monthly']), amount=amount, provider='SASPAY',
                                          reference=reference, status='EN_ATTENTE', declared_by=current_user.id))
            db.session.commit()
            log_activity(current_user.id, current_user.role,
                         f"Paiement d'abonnement déclaré : {_fmt(amount)} FCFA ({months} mois), réf. {reference}",
                         request.remote_addr)
            flash(f"Paiement de {_fmt(amount)} FCFA déclaré. Il sera validé après vérification par l'administrateur "
                  "de la plateforme.", 'success')
        return redirect(url_for('abonnement'))
    payments = BillingPayment.query.order_by(BillingPayment.id.desc()).all()
    pay_url = app.config.get('SASPAY_PAYMENT_URL') or ''
    if pay_url:
        pay_url = pay_url.replace('{montant}', str(int(info['monthly']))).replace('{reference}', tontine.slug)
    return render_template('abonnement.html', info=info, payments=payments, pay_url=pay_url, max_months=billing.MAX_MONTHS,
                           can_pay=current_user.role in BILLING_MANAGERS)


# ------------------------------------------------------------
# ABONNEMENT : actions du super-admin
# ------------------------------------------------------------
@app.route('/superadmin/paiements/<int:payment_id>', methods=['POST'])
@login_required
@superadmin_required
def superadmin_billing_payment(payment_id):
    with tenant_bypass():
        payment = db.get_or_404(BillingPayment, payment_id)
        tontine = db.session.get(Tontine, payment.tontine_id)
        if payment.status != 'EN_ATTENTE':
            flash('Ce paiement a déjà été traité.', 'warning')
            return redirect(url_for('superadmin'))
        action = request.form.get('action')
        if action == 'valider':
            start, end = billing.next_period(tontine, payment.months)
            payment.status, payment.period_start, payment.period_end = 'VALIDE', start, end
            payment.validated_at = utcnow()
            tontine.paid_until = end
            message = f"Paiement validé : « {tontine.name} » payée jusqu'au {end:%d/%m/%Y}."
        elif action == 'refuser':
            payment.status = 'REFUSE'
            payment.validated_at = utcnow()
            payment.note = (request.form.get('note') or '').strip()[:255] or 'Paiement introuvable'
            message = f"Paiement de « {tontine.name} » refusé."
        else:
            abort(400)
        db.session.commit()
    log_activity(current_user.id, current_user.role, message, request.remote_addr)
    flash(message, 'success' if action == 'valider' else 'info')
    return redirect(url_for('superadmin'))


@app.route('/superadmin/tontines/<int:tontine_id>/abonnement', methods=['POST'])
@login_required
@superadmin_required
def superadmin_billing_offer(tontine_id):
    """Offrir la version payante (sans limite), offrir des mois gratuits, ou retirer l'offre"""
    tontine = db.get_or_404(Tontine, tontine_id)
    action = request.form.get('action')
    if action == 'offrir_illimite':
        tontine.billing_offered = True
        message = f"Version payante offerte sans limite de durée à « {tontine.name} »."
    elif action == 'retirer_illimite':
        tontine.billing_offered = False
        message = f"Offre illimitée retirée à « {tontine.name} » : la facturation normale reprend."
    elif action == 'offrir_mois':
        months = request.form.get('months', type=int) or 0
        if not 1 <= months <= 36:
            flash('Nombre de mois invalide (1 à 36).', 'danger')
            return redirect(url_for('superadmin'))
        start, end = billing.next_period(tontine, months)
        tontine.free_until = end
        message = f"{months} mois offert(s) à « {tontine.name} » : gratuit jusqu'au {end:%d/%m/%Y}."
    elif action == 'annuler_mois':
        tontine.free_until = None
        message = f"Mois offerts annulés pour « {tontine.name} »."
    else:
        abort(400)
    db.session.commit()
    log_activity(current_user.id, current_user.role, message, request.remote_addr)
    flash(message, 'success')
    return redirect(url_for('superadmin'))


@app.route('/superadmin/tontines/<int:tontine_id>/supprimer', methods=['POST'])
@login_required
@superadmin_required
def superadmin_delete_tontine(tontine_id):
    """Suppression définitive d'une tontine (nom à retaper ; sauvegarde de la base avant)"""
    tontine = db.get_or_404(Tontine, tontine_id)
    if (request.form.get('confirm_name') or '').strip() != tontine.name:
        flash(f"Suppression annulée : tapez exactement le nom « {tontine.name} » pour confirmer.", 'danger')
        return redirect(url_for('superadmin'))
    name, slug = tontine.name, tontine.slug
    uri = app.config['SQLALCHEMY_DATABASE_URI']
    if uri.startswith('sqlite:///'):   # copie de sécurité de toute la base avant suppression
        import shutil
        src = uri[len('sqlite:///'):]
        folder = app.config.get('BACKUP_FOLDER') or os.path.join(BASE_DIR, 'backups')
        os.makedirs(folder, exist_ok=True)
        db.session.commit()
        shutil.copy2(src, os.path.join(folder, f"avant-suppression-{slug}-{datetime.now():%Y%m%d-%H%M%S}.db"))
    delete_tontine_completely(tontine_id)
    log_activity(current_user.id, current_user.role, f"Tontine « {name} » ({slug}) supprimée définitivement", request.remote_addr)
    flash(f"Tontine « {name} » supprimée définitivement (une copie de sauvegarde de la base a été faite).", 'success')
    return redirect(url_for('superadmin'))


@app.route('/superadmin/tontines/<int:tontine_id>/toggle', methods=['POST'])
@login_required
@superadmin_required
def superadmin_toggle_tontine(tontine_id):
    tontine = db.get_or_404(Tontine, tontine_id)
    tontine.is_active = not tontine.is_active
    db.session.commit()
    state = 'réactivée' if tontine.is_active else 'désactivée'
    log_activity(current_user.id, current_user.role, f"Tontine {tontine.slug} {state}", request.remote_addr)
    flash(f'Tontine « {tontine.name} » {state}.', 'success' if tontine.is_active else 'warning')
    return redirect(url_for('superadmin'))


# ============================================================
# MOT DE PASSE OUBLIÉ
# ============================================================
# Lien de réinitialisation signé, valable 24 h et à usage unique (il contient
# une empreinte du mot de passe actuel : il devient invalide dès que le mot de
# passe change). Envoi par email si un serveur SMTP est configuré ; sinon la
# demande apparaît au bureau, qui transmet le lien par WhatsApp / SMS.

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from urllib.parse import quote

RESET_MAX_AGE = 24 * 3600
PASSWORD_MANAGERS = ['PRESIDENT', 'SECRETAIRE']


def _reset_serializer():
    return URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='hl-password-reset')


def make_reset_url(user):
    token = _reset_serializer().dumps({'u': user.id, 'h': user.password_hash[-16:]})
    return url_for('reset_password', token=token, _external=True)


def _load_reset_user(token):
    try:
        data = _reset_serializer().loads(token, max_age=RESET_MAX_AGE)
    except SignatureExpired:
        return None, "Ce lien a expiré (valable 24 h). Faites une nouvelle demande."
    except BadSignature:
        return None, "Lien de réinitialisation invalide."
    with tenant_bypass():
        user = db.session.get(User, data.get('u'))
    if not user or not user.is_active or user.password_hash[-16:] != data.get('h'):
        return None, "Ce lien a déjà été utilisé ou n'est plus valide."
    return user, None


def whatsapp_url(phone, text):
    """Lien de partage WhatsApp (destinataire pré-rempli si le numéro est international)"""
    raw = (phone or '').strip()
    digits = re.sub(r'\D', '', raw)
    if raw.startswith('00'):
        digits = digits[2:]
    if (raw.startswith('+') or raw.startswith('00')) and len(digits) >= 10:
        return f"https://wa.me/{digits}?text={quote(text)}"
    return f"https://wa.me/?text={quote(text)}"


def _password_is_strong(pwd):
    return len(pwd) >= 8 and re.search(r'[A-Za-z]', pwd) and re.search(r'\d', pwd)


@app.route('/mot-de-passe-oublie', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    tontines = _active_tontines()
    selected = request.form.get('tontine') or request.args.get('t', '')
    if not selected and len(tontines) == 1:
        selected = tontines[0].slug

    if request.method == 'POST':
        identifier = (request.form.get('identifier') or '').strip()
        # Limite les demandes répétées (évite d'inonder le bureau ou de sonder les comptes)
        if is_rate_limited('forgot', identifier):
            flash('Trop de demandes. Réessayez dans 15 minutes.', 'danger')
            return redirect(url_for('forgot_password', t=selected) if selected else url_for('forgot_password'))
        _record_failure(('forgot', request.remote_addr or '?', identifier.lower()), ('forgot', request.remote_addr or '?'))
        tontine = _public_tontines().filter_by(slug=selected).first() if selected else None
        if tontine and identifier:
            with tenant_bypass():
                user = User.query.filter(
                    User.tontine_id == tontine.id, User.is_active == True,
                    db.or_(User.username == identifier, db.func.lower(User.email) == identifier.lower())
                ).first()
            if user:
                set_current_tenant(tontine.id)
                sent = send_email(
                    user.email, f"[{app.config['APP_NAME']}] Réinitialisation de votre mot de passe",
                    f"Bonjour,\n\nPour choisir un nouveau mot de passe sur {tontine.name}, ouvrez ce lien (valable 24 h) :\n"
                    f"{make_reset_url(user)}\n\nSi vous n'êtes pas à l'origine de cette demande, ignorez ce message."
                )
                pending = PasswordResetRequest.query.filter_by(user_id=user.id, status='EN_ATTENTE').first()
                if pending:
                    pending.email_sent = pending.email_sent or sent
                else:
                    db.session.add(PasswordResetRequest(user_id=user.id, email_sent=sent, ip_address=request.remote_addr))
                db.session.commit()
                log_activity(user.id, user.role, "Demande de réinitialisation du mot de passe", request.remote_addr)
        # Même réponse que le compte existe ou non (on ne révèle pas les identifiants)
        flash("Si un compte correspond, vous allez recevoir un lien de réinitialisation : par email, "
              "ou transmis par le bureau de votre tontine (WhatsApp / SMS).", 'info')
        return redirect(url_for('login', t=selected) if selected else url_for('login'))

    return render_template('forgot_password.html', tontines=tontines, selected=selected,
                           selected_tontine=next((t for t in tontines if t.slug == selected), None))


@app.route('/reinitialiser/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user, error = _load_reset_user(token)
    if error:
        flash(error, 'danger')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password') or ''
        if not _password_is_strong(password):
            flash('Le mot de passe doit contenir au moins 8 caractères, avec des lettres et des chiffres.', 'danger')
        elif password != request.form.get('password_confirm'):
            flash('Les deux mots de passe ne correspondent pas.', 'danger')
        else:
            user.set_password(password)
            if user.tontine_id:
                set_current_tenant(user.tontine_id)
                PasswordResetRequest.query.filter_by(user_id=user.id, status='EN_ATTENTE').update(
                    {'status': 'TRAITEE', 'handled_at': utcnow()})
            db.session.commit()
            log_activity(user.id, user.role, "Mot de passe réinitialisé par lien", request.remote_addr)
            flash('Votre mot de passe a été modifié. Vous pouvez vous connecter.', 'success')
            return redirect(url_for('login', t=user.tontine.slug if user.tontine else PLATFORM_LOGIN))

    return render_template('reset_password.html', user=user)


def _reset_link_page(user, member, back_url):
    link = make_reset_url(user)
    tontine_name = user.tontine.name if user.tontine else app.config['APP_NAME']
    message = (f"Bonjour {member.first_name if member else user.username}, voici votre lien pour choisir un nouveau "
               f"mot de passe sur {tontine_name} (identifiant : {user.username}). Il est valable 24 h : {link}")
    return render_template('reset_link.html', user=user, member=member, link=link, back_url=back_url,
                           whatsapp=whatsapp_url(member.phone if member else '', message),
                           sms=f"sms:{(member.phone if member else '') or ''}?body={quote(message)}")


@app.route('/demandes-mot-de-passe')
@login_required
@role_required(PASSWORD_MANAGERS)
def password_requests():
    pending = PasswordResetRequest.query.filter_by(status='EN_ATTENTE').order_by(PasswordResetRequest.created_at.desc()).all()
    handled = (PasswordResetRequest.query.filter_by(status='TRAITEE')
               .order_by(PasswordResetRequest.handled_at.desc()).limit(20).all())
    return render_template('password_requests.html', pending=pending, handled=handled)


@app.route('/members/<int:member_id>/reset-link', methods=['POST'])
@login_required
@role_required(PASSWORD_MANAGERS)
def member_reset_link(member_id):
    member = db.get_or_404(Member, member_id)
    user = User.query.filter_by(tontine_id=g.tenant_id, member_id=member.id).first()
    if not user:
        flash("Ce membre n'a pas de compte de connexion.", 'warning')
        return redirect(url_for('member_detail', member_id=member.id))
    if user.role == 'PRESIDENT' and current_user.role != 'PRESIDENT':
        flash("Seul le président (ou l'administrateur de la plateforme) peut réinitialiser le mot de passe du président.", 'danger')
        return redirect(url_for('member_detail', member_id=member.id))
    PasswordResetRequest.query.filter_by(user_id=user.id, status='EN_ATTENTE').update(
        {'status': 'TRAITEE', 'handled_at': utcnow(), 'handled_by': current_user.id})
    db.session.commit()
    log_activity(current_user.id, current_user.role, f"Lien de réinitialisation généré pour {member.full_name}", request.remote_addr)
    return _reset_link_page(user, member, url_for('password_requests'))


@app.route('/superadmin/tontines/<int:tontine_id>/reset-president', methods=['POST'])
@login_required
@superadmin_required
def superadmin_reset_president(tontine_id):
    tontine = db.get_or_404(Tontine, tontine_id)
    with tenant_bypass():
        user = User.query.filter_by(tontine_id=tontine.id, role='PRESIDENT', is_active=True).first()
        member = db.session.get(Member, user.member_id) if user and user.member_id else None
    if not user:
        flash("Cette tontine n'a pas de président actif.", 'warning')
        return redirect(url_for('superadmin'))
    log_activity(current_user.id, current_user.role, f"Lien de réinitialisation du président de {tontine.slug}", request.remote_addr)
    return _reset_link_page(user, member, url_for('superadmin'))


# ============================================================
# GESTION DES ERREURS
# ============================================================

from sqlalchemy.exc import IntegrityError


@app.errorhandler(IntegrityError)
def integrity_error(error):
    """Filet de sécurité : doublon ou référence invalide refusé par la base"""
    db.session.rollback()
    app.logger.warning(f"Contrainte d'intégrité sur {request.path} : {error.orig}")
    flash("Opération refusée : cette donnée existe déjà ou n'est plus valide.", 'danger')
    return redirect(safe_next_url(request.referrer and '/' + request.referrer.split('/', 3)[-1]) or url_for('index')), 303


@app.errorhandler(OverflowError)
def overflow_error(error):
    """Identifiant ou nombre démesuré envoyé dans un formulaire / une URL"""
    db.session.rollback()
    app.logger.warning(f"Valeur hors limites sur {request.path} : {error}")
    flash('Une valeur saisie est hors limites. Vérifiez le formulaire.', 'danger')
    return redirect(safe_next_url(request.referrer and '/' + request.referrer.split('/', 3)[-1]) or url_for('index')), 303


@app.errorhandler(413)
def too_large_error(error):
    flash('Fichier trop volumineux (5 Mo maximum).', 'danger')
    return redirect(safe_next_url(request.referrer and '/' + request.referrer.split('/', 3)[-1]) or url_for('index')), 303


@app.errorhandler(403)
def forbidden_error(error):
    return render_template('403.html'), 403

@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500

# ============================================================
# POINT D'ENTRÉE
# ============================================================

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
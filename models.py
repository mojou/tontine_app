from flask_login import UserMixin
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from werkzeug.security import generate_password_hash, check_password_hash
from decimal import Decimal
from extensions import db, utcnow
from tenancy import TenantMixin
import finance


# ============================================================
# TABLE TONTINE (une ligne par association / client)
# ============================================================
class Tontine(db.Model):
    __tablename__ = 'tontines'

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    tagline = db.Column(db.String(200), nullable=True)
    location = db.Column(db.String(120), nullable=True)
    contact_phone = db.Column(db.String(30), nullable=True)
    contact_email = db.Column(db.String(120), nullable=True)
    whatsapp_link = db.Column(db.String(200), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    # Paramètres propres à chaque tontine (remplacent les constantes de config.py)
    presence_amount = db.Column(db.Numeric(10, 2), default=Decimal('1050.00'))
    fonds_caisse_amount = db.Column(db.Numeric(10, 2), default=Decimal('5000.00'))
    loan_interest_rate = db.Column(db.Numeric(5, 2), default=Decimal('5.00'))
    max_aid_per_member = db.Column(db.Integer, default=3)
    # Avalistes : un aval est exigé au-delà de ce montant (0 = toujours)
    guarantee_threshold = db.Column(db.Numeric(10, 2), default=Decimal('0.00'))
    guarantors_min = db.Column(db.Integer, default=1)
    # Aides sociales (caisse de secours) : règles votées par la tontine
    aid_min_seniority_days = db.Column(db.Integer, default=90)      # ancienneté minimale
    aid_require_fonds_caisse = db.Column(db.Boolean, default=True)  # fonds de caisse payé
    aid_require_secours = db.Column(db.Boolean, default=True)       # à jour de la caisse de secours
    aid_declaration_days = db.Column(db.Integer, default=30)        # délai pour déclarer l'événement
    aid_double_validation = db.Column(db.Boolean, default=True)     # président ET trésorier
    aid_deduct_sanctions = db.Column(db.Boolean, default=True)      # amendes impayées retenues


# ============================================================
# TABLE USER
# ============================================================
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    __table_args__ = (
        db.UniqueConstraint('tontine_id', 'username', name='uq_user_tontine_username'),
        db.UniqueConstraint('tontine_id', 'email', name='uq_user_tontine_email'),
    )

    id = db.Column(db.Integer, primary_key=True)
    # NULL uniquement pour le super-admin de la plateforme
    tontine_id = db.Column(db.Integer, db.ForeignKey('tontines.id'), nullable=True, index=True)
    username = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='MEMBRE')
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    last_login = db.Column(db.DateTime, nullable=True)

    member = db.relationship('Member', backref='user_account', uselist=False, foreign_keys=[member_id])
    tontine = db.relationship('Tontine', foreign_keys=[tontine_id])

    @property
    def is_superadmin(self):
        return self.role == 'SUPERADMIN'

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_admin(self):
        return self.role in ['PRESIDENT', 'SECRETAIRE', 'TRESORIER', 'CENSEUR', 'COMMUNICATION']
    
    def is_bureau_member(self):
        return self.is_admin()

    def get_role_display(self):
        roles = {
            'SECRETAIRE': 'Secrétaire',
            'PRESIDENT': 'Président',
            'TRESORIER': 'Trésorier',
            'CENSEUR': 'Censeur',
            'COMMUNICATION': 'Communication',
            'MEMBRE': 'Membre',
            'SUPERADMIN': 'Super-admin'
        }
        return roles.get(self.role, self.role)

    @property
    def member_name(self):
        return self.member.full_name if self.member else "N/A"


# ============================================================
# TABLE MEMBER
# ============================================================
class Member(TenantMixin, db.Model):
    __tablename__ = 'members'
    __table_args__ = (db.UniqueConstraint('tontine_id', 'email', name='uq_member_tontine_email'),)

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    address = db.Column(db.String(200))
    profession = db.Column(db.String(100))
    city = db.Column(db.String(100))
    photo = db.Column(db.String(200))

    registration_date = db.Column(db.Date, default=date.today)
    status = db.Column(db.String(20), default='ACTIF')
    is_active = db.Column(db.Boolean, default=True)

    tontine_status = db.Column(db.String(20), default='VERT')
    consecutive_failures = db.Column(db.Integer, default=0)

    credit_balance = db.Column(db.Numeric(10, 2), default=Decimal('0.00'))
    debit_balance = db.Column(db.Numeric(10, 2), default=Decimal('0.00'))
    amount_to_receive = db.Column(db.Numeric(10, 2), default=Decimal('0.00'))

    group_type = db.Column(db.String(5), nullable=True)
    position_in_group = db.Column(db.Integer, nullable=True)
    has_received_benefit = db.Column(db.Boolean, default=False)
    expected_benefit_date = db.Column(db.Date, nullable=True)
    chosen_tontine_amount = db.Column(db.Numeric(10, 2), nullable=True)

    # Relations
    transactions = db.relationship('Transaction', back_populates='member', lazy='dynamic', cascade='all, delete-orphan')
    loans = db.relationship('Loan', back_populates='member', lazy=True, cascade='all, delete-orphan')
    sanctions = db.relationship('Sanction', back_populates='member', lazy='dynamic')
    attendance_records = db.relationship('Attendance', back_populates='member', lazy='dynamic', cascade='all, delete-orphan')
    tontine_positions = db.relationship('TontinePosition', back_populates='member', lazy='dynamic')
    cycle_benefits = db.relationship('CycleBeneficiary', back_populates='member', lazy='dynamic')
    aides = db.relationship('Aide', back_populates='member', lazy='dynamic')
    meeting_attendances = db.relationship('MeetingAttendanceDetail', back_populates='member', lazy='dynamic')
    contributions_planning = db.relationship('ContributionPlanning', back_populates='member', lazy='dynamic')

    # Propriétés existantes
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def role(self):
        return self.user_account.role if self.user_account else 'MEMBRE'

    @property
    def is_bureau_member(self):
        return bool(self.user_account and self.user_account.is_admin())

    @property
    def total_savings(self):
        result = db.session.query(db.func.sum(Transaction.amount)).filter(
            Transaction.member_id == self.id,
            Transaction.type == 'TONTINE'
        ).scalar()
        return Decimal(str(result or 0))

    @property
    def total_presence_paid(self):
        result = db.session.query(db.func.sum(Transaction.amount)).filter(
            Transaction.member_id == self.id,
            Transaction.type == 'PRESENCE'
        ).scalar()
        return Decimal(str(result or 0))

    @property
    def total_sanctions_pending(self):
        result = db.session.query(db.func.sum(Sanction.amount)).filter(
            Sanction.member_id == self.id,
            Sanction.status == 'PENDING'
        ).scalar()
        return Decimal(str(result or 0))

    @property
    def has_paid_fonds_caisse(self):
        return self.transactions.filter_by(type='FONDS_CAISSE').count() > 0

    # NOUVELLES PROPRIÉTÉS ET MÉTHODES AJOUTÉES
    @property
    def total_sanctions_paid(self):
        result = db.session.query(db.func.sum(Sanction.amount)).filter(
            Sanction.member_id == self.id,
            Sanction.status == 'PAID'
        ).scalar()
        return Decimal(str(result or 0))

    @property
    def participation_score(self):
        total_meetings = self.attendance_records.count()
        if total_meetings == 0:
            return 100
        presents = self.attendance_records.filter_by(status='PRESENT').count()
        return round((presents / total_meetings) * 100, 2)

    @property
    def total_active_debt(self):
        result = db.session.query(db.func.sum(Loan.total_amount - Loan.amount_paid)).filter(
            Loan.member_id == self.id,
            Loan.status.in_(['ACTIF', 'OVERDUE'])
        ).scalar()
        return Decimal(str(result or 0))

    @property
    def current_balance(self):
        return self.credit_balance - self.debit_balance

    def _sum_types(self, types):
        result = db.session.query(db.func.sum(Transaction.amount)).filter(
            Transaction.member_id == self.id, Transaction.type.in_(types)
        ).scalar()
        return Decimal(str(result or 0))

    @property
    def savings_balance(self):
        """Épargne nette (dépôts - restitutions)"""
        return self._sum_types(['EPARGNE']) - self._sum_types(['RETRAIT_EPARGNE'])

    @property
    def assets(self):
        """Avoirs dans la tontine : cotisations tontine + épargne nette + fonds de caisse"""
        return self.total_savings + self.savings_balance + self._sum_types(['FONDS_CAISSE'])

    @property
    def guarantee_exposure(self):
        """Montant encore garanti pour d'autres (avals accordés ou appelés sur des prêts non soldés)"""
        total = Decimal('0')
        for g in LoanGuarantor.query.filter(LoanGuarantor.member_id == self.id,
                                            LoanGuarantor.status.in_(['ACCEPTE', 'APPELE'])).all():
            if g.loan and g.loan.status in ('PENDING', 'ACTIF', 'OVERDUE'):
                total += g.remaining_guarantee
        return total

    @property
    def guarantee_capacity(self):
        """Capacité d'aval restante (indicative) : avoirs - engagements en cours"""
        return self.assets - self.guarantee_exposure

    @property
    def unsettled_guarantor_debts(self):
        """Avals appelés pour CE membre (emprunteur) et pas encore réglés envers l'avaliste"""
        return LoanGuarantor.query.join(Loan, LoanGuarantor.loan_id == Loan.id).filter(
            Loan.member_id == self.id, LoanGuarantor.status == 'APPELE'
        ).all()

    def update_tontine_status(self):
        if self.consecutive_failures >= 2:
            self.tontine_status = 'ROUGE'
        elif self.consecutive_failures == 1:
            self.tontine_status = 'ORANGE'
        else:
            self.tontine_status = 'VERT'
        db.session.commit()

    def calculate_net_benefit(self, cycle_total_amount):
        net_amount = (
            Decimal(str(cycle_total_amount))
            - self.total_sanctions_pending
            - Decimal(str(self.debit_balance))
        )
        return max(Decimal('0.00'), net_amount)

    def is_eligible_for_loan(self, requested_amount=0):
        if self.status != 'ACTIF' or not self.is_active:
            return False, "Le statut du membre n'est pas actif."
        if not self.has_paid_fonds_caisse:
            return False, "Le fonds de caisse obligatoire n'a pas été payé."
        if self.tontine_status == 'ROUGE':
            return False, "Membre en statut ROUGE."
        if self.debit_balance > 0:
            return False, f"Dette de {self.debit_balance:,.0f} FCFA."
        active_loans = [l for l in self.loans if l.status in ('PENDING', 'ACTIF', 'OVERDUE')]
        if active_loans:
            return False, "Un emprunt est déjà en cours."
        if self.unsettled_guarantor_debts:
            return False, "Un avaliste a payé à votre place : réglez d'abord cette dette."
        # Plafond : 3 fois les avoirs du membre (cotisations tontine + épargne + fonds de caisse)
        max_allowed = self.assets * 3
        requested = Decimal(str(requested_amount))
        if requested > max_allowed:
            return False, f"Maximum autorisé: {max_allowed:,.0f} FCFA (3 fois vos avoirs)."
        return True, "Éligible."

    def get_status_color(self):
        colors = {'ACTIF': 'success', 'SUSPENDU': 'warning', 'EXCLU': 'danger', 'PENDING': 'warning'}
        return colors.get(self.status, 'secondary')


# ============================================================
# TABLE TRANSACTION
# ============================================================
class Transaction(TenantMixin, db.Model):
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=False)
    member = db.relationship('Member', back_populates='transactions', foreign_keys=[member_id])

    type = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    description = db.Column(db.String(200))
    payment_mode = db.Column(db.String(20), default='ESPECE')
    date = db.Column(db.Date, nullable=False, default=date.today)

    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=utcnow)
    creator = db.relationship('User', foreign_keys=[created_by], backref='transactions_created')

    # Rubrique de cotisation (facultative : les anciennes transactions n'en ont pas)
    contribution_type_id = db.Column(db.Integer, db.ForeignKey('contribution_types.id'), nullable=True)
    contribution_type = db.relationship('ContributionType')
    # Cycle de tontine concerné (cotisation d'un tour / cagnotte versée)
    cycle_id = db.Column(db.Integer, db.ForeignKey('tontine_cycle_details.id'), nullable=True)
    # Séance de réunion pendant laquelle le paiement a été encaissé
    seance_id = db.Column(db.Integer, db.ForeignKey('seances.id'), nullable=True)
    # Référence du paiement mobile (Orange Money, MTN MoMo, Wave...)
    payment_reference = db.Column(db.String(60), nullable=True)

    @property
    def is_outflow(self):
        return finance.is_outflow(self.type)

    @property
    def is_system(self):
        """Écriture générée par un module (emprunt, cagnotte, sanction, aide, partage...) :
        la modifier ou la supprimer à la main désynchroniserait les soldes."""
        return self.type not in finance.MANUAL_TYPES

    @property
    def source_module(self):
        return {
            'SORTIE_LOAN': 'Emprunts', 'REMBOURSEMENT': 'Emprunts / Avals', 'BENEFICE_TONTINE': 'Cycles de tontine',
            'ENCHERE': 'Cycles de tontine', 'SANCTION': 'Sanctions', 'AIDE': 'Aides sociales', 'PARTAGE': "Fin d'exercice",
        }.get(self.type, 'Transactions')

    @property
    def fund(self):
        return finance.fund_of(self.type)

    @property
    def member_name(self):
        return self.member.full_name if self.member else "N/A"

    @property
    def creator_name(self):
        return self.creator.username if self.creator else "Système"

    @property
    def validator_name(self):
        return "N/A"

    def get_type_display(self):
        if self.contribution_type:
            return self.contribution_type.name
        return finance.type_label(self.type)


# ============================================================
# TABLE LOAN
# ============================================================
class Loan(TenantMixin, db.Model):
    __tablename__ = 'loans'

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=False)
    member = db.relationship('Member', back_populates='loans', foreign_keys=[member_id])

    amount = db.Column(db.Numeric(10, 2), nullable=False)
    interest = db.Column(db.Numeric(10, 2), nullable=False, default=Decimal('0.00'))
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    amount_paid = db.Column(db.Numeric(10, 2), default=Decimal('0.00'))

    request_date = db.Column(db.Date, nullable=False, default=date.today)
    approval_date = db.Column(db.Date, nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)

    status = db.Column(db.String(20), default='PENDING')
    description = db.Column(db.Text, nullable=True)

    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    approver = db.relationship('User', foreign_keys=[approved_by], backref='approved_loans')
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_loans')
    guarantors = db.relationship('LoanGuarantor', back_populates='loan', cascade='all, delete-orphan',
                                 order_by='LoanGuarantor.id')

    @property
    def accepted_guarantors(self):
        return [g for g in self.guarantors if g.status in ('ACCEPTE', 'APPELE', 'REGLE', 'LIBERE')]

    @property
    def pending_guarantors(self):
        return [g for g in self.guarantors if g.status == 'EN_ATTENTE']

    @property
    def guaranteed_amount(self):
        return sum((Decimal(str(g.amount or 0)) for g in self.accepted_guarantors), Decimal('0'))

    @property
    def member_name(self):
        return self.member.full_name if self.member else "N/A"

    @property
    def remaining_amount(self):
        return Decimal(str(self.total_amount)) - Decimal(str(self.amount_paid))

    @property
    def remaining_to_pay(self):
        return self.remaining_amount

    @property
    def is_overdue(self):
        if self.status != 'ACTIF' or not self.end_date:
            return False
        return date.today() > self.end_date

    @property
    def penalty_amount(self):
        return self.remaining_amount * Decimal('0.05') if self.is_overdue else Decimal('0.00')

    @property
    def progress_percentage(self):
        if self.total_amount == 0:
            return 0
        return float((self.amount_paid / self.total_amount) * 100)

    # NOUVELLES MÉTHODES AJOUTÉES
    def get_status_display(self):
        statuses = {
            'PENDING': 'En attente',
            'ACTIF': 'En cours',
            'OVERDUE': 'En retard',
            'REMBOURSE': 'Remboursé',
            'REJECTED': 'Rejeté',
        }
        return statuses.get(self.status, self.status)

    def get_status_color(self):
        colors = {
            'PENDING': 'warning',
            'ACTIF': 'primary',
            'OVERDUE': 'danger',
            'REMBOURSE': 'success',
            'REJECTED': 'secondary',
        }
        return colors.get(self.status, 'secondary')


# ============================================================
# TABLE SANCTION
# ============================================================
class Sanction(TenantMixin, db.Model):
    __tablename__ = 'sanctions'

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=False)
    member = db.relationship('Member', back_populates='sanctions', foreign_keys=[member_id])

    type_sanction = db.Column(db.String(50), nullable=False, default='AUTRE')
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    description = db.Column(db.Text, nullable=False)
    sanction_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='PENDING')
    created_at = db.Column(db.DateTime, default=utcnow)

    @property
    def member_name(self):
        return self.member.full_name if self.member else "N/A"

    @property
    def is_paid(self):
        return self.status == 'PAID'

    # NOUVELLES MÉTHODES AJOUTÉES
    # Liste unique des types de sanction (formulaires, pages, rapports)
    TYPES = [
        ('RETARD_PAIEMENT', 'Retard de paiement'),
        ('NON_PAIEMENT', 'Non-paiement'),
        ('ABSENCE', 'Absence non justifiée'),
        ('RETARD_REUNION', 'Retard à la réunion'),
        ('RETARD_EMPRUNT', 'Retard de remboursement'),
        ('ECHEC_COTISATION', 'Échec de cotisation'),
        ('COMPORTEMENT', 'Mauvais comportement'),
        ('AUTRE', 'Autre'),
    ]

    def get_type_display(self):
        return dict(self.TYPES).get(self.type_sanction, self.type_sanction)

    @property
    def type_display(self):
        return self.get_type_display()

    def mark_as_paid(self):
        self.status = 'PAID'
        db.session.commit()


# ============================================================
# TABLE ATTENDANCE
# ============================================================
class Attendance(TenantMixin, db.Model):
    __tablename__ = 'attendances'

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=False)
    member = db.relationship('Member', back_populates='attendance_records', foreign_keys=[member_id])
    date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='PRESENT')


# ============================================================
# TABLE TONTINE_CYCLE (ancien)
# ============================================================
class TontineCycle(TenantMixin, db.Model):
    __tablename__ = 'tontine_cycles'

    id = db.Column(db.Integer, primary_key=True)
    cycle_number = db.Column(db.Integer, nullable=False)
    group_type = db.Column(db.String(5), nullable=False)
    amount_per_member = db.Column(db.Numeric(10, 2), nullable=False)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default='EN_COURS')
    current_fortnight = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))


# ============================================================
# TABLE TONTINE_POSITION
# ============================================================
class TontinePosition(TenantMixin, db.Model):
    __tablename__ = 'tontine_positions'

    id = db.Column(db.Integer, primary_key=True)
    cycle_id = db.Column(db.Integer, db.ForeignKey('tontine_cycles.id'), nullable=False)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=False)
    position = db.Column(db.Integer, nullable=False)
    is_drawn = db.Column(db.Boolean, default=False)
    draw_date = db.Column(db.Date, nullable=True)
    amount_received = db.Column(db.Numeric(10, 2), nullable=False)

    member = db.relationship('Member', back_populates='tontine_positions', foreign_keys=[member_id])

    @property
    def member_name(self):
        return self.member.full_name if self.member else "N/A"


# ============================================================
# TABLE TONTINE_CYCLE_DETAIL
# ============================================================
class TontineCycleDetail(TenantMixin, db.Model):
    __tablename__ = 'tontine_cycle_details'

    id = db.Column(db.Integer, primary_key=True)
    cycle_number = db.Column(db.Integer, nullable=False)
    group_type = db.Column(db.String(5), nullable=False)
    amount_per_member = db.Column(db.Numeric(10, 2), nullable=False)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default='EN_COURS')
    created_at = db.Column(db.DateTime, default=utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    # Niveau de cotisation (rubrique de catégorie TONTINE : 1 000, 10 000, 20 000...)
    contribution_type_id = db.Column(db.Integer, db.ForeignKey('contribution_types.id'), nullable=True)
    contribution_type = db.relationship('ContributionType')
    mode = db.Column(db.String(20), nullable=True)             # TIRAGE / ENCHERE (NULL = TIRAGE)
    frequency_days = db.Column(db.Integer, nullable=True)      # écart entre deux tours
    label = db.Column(db.String(100), nullable=True)

    benefits = db.relationship('CycleBeneficiary', back_populates='cycle_detail', lazy='dynamic', foreign_keys='CycleBeneficiary.cycle_id')
    reports = db.relationship('CycleReport', back_populates='cycle_detail', lazy='dynamic')
    participants = db.relationship('CycleParticipant', back_populates='cycle', cascade='all, delete-orphan',
                                   order_by='CycleParticipant.id')

    @property
    def cycle_mode(self):
        return self.mode or 'TIRAGE'

    @property
    def is_auction(self):
        return self.cycle_mode == 'ENCHERE'

    @property
    def display_name(self):
        level = self.label or (self.contribution_type.name if self.contribution_type else None)
        return f"Cycle #{self.cycle_number}" + (f" · {level}" if level else '')

    @property
    def total_members(self):
        """Nombre de parts (« mains ») du cycle : chaque part reçoit une fois la cagnotte"""
        if self.participants:
            return len(self.participants)
        try:
            return int(self.group_type)
        except (TypeError, ValueError):
            return 0

    @property
    def members_count(self):
        """Nombre de personnes distinctes (un membre peut détenir plusieurs mains)"""
        return len({p.member_id for p in self.participants})

    @property
    def remaining_participants(self):
        return sorted([p for p in self.participants if not p.served],
                      key=lambda p: (p.position is None, p.position or 0, p.id))

    @property
    def needs_draw(self):
        return not self.is_auction and any(p.position is None for p in self.participants if not p.served)

    def get_next_participant(self):
        if self.is_auction:
            return None
        remaining = [p for p in self.remaining_participants if p.position is not None]
        return remaining[0] if remaining else None

    @property
    def next_round_date(self):
        if not self.start_date:
            return None
        from datetime import timedelta
        return self.start_date + timedelta(days=(self.frequency_days or 14) * self.beneficiaries_count)

    @property
    def beneficiaries_count(self):
        return self.benefits.count()

    @property
    def is_complete(self):
        return self.beneficiaries_count >= self.total_members

    @property
    def progress_percentage(self):
        if self.total_members == 0:
            return 0
        return (self.beneficiaries_count / self.total_members) * 100

    def get_next_beneficiary(self):
        """Membre du prochain tour (None en mode enchères ou si l'ordre n'est pas encore tiré)"""
        participant = self.get_next_participant()
        return participant.member if participant else None


# ============================================================
# TABLE CYCLE_BENEFICIARY
# ============================================================
class CycleBeneficiary(TenantMixin, db.Model):
    __tablename__ = 'cycle_beneficiaries'

    id = db.Column(db.Integer, primary_key=True)
    cycle_id = db.Column(db.Integer, db.ForeignKey('tontine_cycle_details.id'), nullable=False)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=False)
    member = db.relationship('Member', back_populates='cycle_benefits', foreign_keys=[member_id])

    position = db.Column(db.Integer, nullable=False)
    gross_amount = db.Column(db.Numeric(10, 2), nullable=False)
    net_amount = db.Column(db.Numeric(10, 2), nullable=False)
    sanctions_deducted = db.Column(db.Numeric(10, 2), default=Decimal('0.00'))
    benefit_date = db.Column(db.Date, nullable=False)
    payment_status = db.Column(db.String(20), default='PAYE')
    payment_mode = db.Column(db.String(50), nullable=True)
    transaction_id = db.Column(db.String(100), nullable=True)
    participant_id = db.Column(db.Integer, db.ForeignKey('cycle_participants.id'), nullable=True)
    bid_amount = db.Column(db.Numeric(10, 2), nullable=True)   # mise d'enchère retenue

    cycle_detail = db.relationship('TontineCycleDetail', back_populates='benefits', foreign_keys=[cycle_id])

    @property
    def member_name(self):
        return self.member.full_name if self.member else "N/A"


# ============================================================
# TABLE AIDE
# ============================================================
class Aide(TenantMixin, db.Model):
    __tablename__ = 'aides'

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=False)
    member = db.relationship('Member', back_populates='aides', foreign_keys=[member_id])

    aide_type = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    request_date = db.Column(db.Date, default=date.today)
    approval_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default='PENDING')
    is_paid = db.Column(db.Boolean, default=False)
    description = db.Column(db.Text, nullable=True)
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    approver = db.relationship('User', foreign_keys=[approved_by], backref='approved_aides')

    aid_type_id = db.Column(db.Integer, db.ForeignKey('aid_types.id'), nullable=True)
    aid_type = db.relationship('AidType')
    event_date = db.Column(db.Date, nullable=True)
    document = db.Column(db.String(200), nullable=True)            # justificatif (stockage privé)
    president_approved_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    treasurer_approved_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    rejection_reason = db.Column(db.String(255), nullable=True)
    sanctions_deducted = db.Column(db.Numeric(10, 2), nullable=True)
    paid_at = db.Column(db.Date, nullable=True)

    @property
    def member_name(self):
        return self.member.full_name if self.member else "N/A"

    LEGACY_TYPES = {'MALADIE': 'Maladie', 'DECES': 'Décès', 'MARIAGE': 'Mariage', 'NAISSANCE': 'Naissance', 'AUTRE': 'Autre'}

    def get_type_display(self):
        if self.aid_type:
            return self.aid_type.name
        return self.LEGACY_TYPES.get(self.aide_type, self.aide_type)

    @property
    def status_display(self):
        if self.is_paid:
            return 'Versée'
        return {'PENDING': 'En attente de validation', 'APPROVED': 'Approuvée, à verser',
                'REJECTED': 'Refusée'}.get(self.status, self.status)

    @property
    def status_color(self):
        if self.is_paid:
            return 'success'
        return {'PENDING': 'warning', 'APPROVED': 'primary', 'REJECTED': 'secondary'}.get(self.status, 'secondary')


# ============================================================
# TABLE ANNOUNCEMENT
# ============================================================
class Announcement(TenantMixin, db.Model):
    __tablename__ = 'announcements'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    announcement_type = db.Column(db.String(20), default='INFO')
    event_date = db.Column(db.Date, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=utcnow)
    is_active = db.Column(db.Boolean, default=True)

    creator = db.relationship('User', foreign_keys=[created_by], backref='announcements')
    agenda_items = db.relationship('AgendaItem', backref='announcement', cascade='all, delete-orphan')
    beneficiaries = db.relationship('MeetingBeneficiary', backref='announcement', cascade='all, delete-orphan')
    attendance_details = db.relationship('MeetingAttendanceDetail', backref='announcement', cascade='all, delete-orphan')

    @property
    def type_display(self):
        types = {
            'INFO': 'Information',
            'URGENT': 'Urgent',
            'REUNION': 'Réunion',
            'RAPPEL': 'Rappel',
        }
        return types.get(self.announcement_type, self.announcement_type)

    @property
    def created_by_name(self):
        return self.creator.username if self.creator else "Système"

    @property
    def formatted_date(self):
        return self.created_at.strftime('%d/%m/%Y à %H:%M') if self.created_at else ""


class AgendaItem(TenantMixin, db.Model):
    __tablename__ = 'agenda_items'

    id = db.Column(db.Integer, primary_key=True)
    announcement_id = db.Column(db.Integer, db.ForeignKey('announcements.id', ondelete='CASCADE'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    is_completed = db.Column(db.Boolean, default=False)


class MeetingBeneficiary(TenantMixin, db.Model):
    __tablename__ = 'meeting_beneficiaries'

    id = db.Column(db.Integer, primary_key=True)
    announcement_id = db.Column(db.Integer, db.ForeignKey('announcements.id', ondelete='CASCADE'), nullable=False)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id', ondelete='CASCADE'), nullable=False)
    benefit_type = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=True)

    member = db.relationship('Member', foreign_keys=[member_id], backref='meeting_benefits')


class MeetingAttendanceDetail(TenantMixin, db.Model):
    __tablename__ = 'meeting_attendance_details'

    id = db.Column(db.Integer, primary_key=True)
    announcement_id = db.Column(db.Integer, db.ForeignKey('announcements.id', ondelete='CASCADE'), nullable=False)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id', ondelete='CASCADE'), nullable=False)
    attendance_status = db.Column(db.String(20), default='PRESENT')
    arrival_time = db.Column(db.Time, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    member = db.relationship('Member', back_populates='meeting_attendances', foreign_keys=[member_id])

    # NOUVELLES PROPRIÉTÉS AJOUTÉES
    @property
    def status_color(self):
        colors = {
            'PRESENT': 'success',
            'ABSENT': 'danger',
            'RETARD': 'warning',
            'EXCUSE': 'info'
        }
        return colors.get(self.attendance_status, 'secondary')

    @property
    def status_display(self):
        statuses = {
            'PRESENT': 'Présent',
            'ABSENT': 'Absent',
            'RETARD': 'En retard',
            'EXCUSE': 'Excusé'
        }
        return statuses.get(self.attendance_status, self.attendance_status)


# ============================================================
# TABLE AUDIT_LOG
# ============================================================
class AuditLog(TenantMixin, db.Model):
    __tablename__ = 'audit_logs'
    __tenant_optional__ = True

    tontine_id = db.Column(db.Integer, db.ForeignKey('tontines.id'), nullable=True, index=True)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    user_role = db.Column(db.String(20))
    action = db.Column(db.String(200), nullable=False)
    ip_address = db.Column(db.String(45))
    status = db.Column(db.String(20), default='SUCCESS')
    timestamp = db.Column(db.DateTime, default=utcnow)

    user = db.relationship('User', foreign_keys=[user_id], backref='audit_logs')

    @property
    def user_name(self):
        return self.user.username if self.user else "Système"

    @property
    def formatted_date(self):
        return self.timestamp.strftime('%d/%m/%Y à %H:%M')


# ============================================================
# TABLE CONTRIBUTION_PLANNING
# ============================================================
class ContributionPlanning(TenantMixin, db.Model):
    __tablename__ = 'contribution_planning'

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    fortnight_number = db.Column(db.Integer, nullable=True)
    contribution_type = db.Column(db.String(20), nullable=False)
    expected_amount = db.Column(db.Numeric(10, 2), nullable=False)
    expected_date = db.Column(db.Date, nullable=False)
    is_paid = db.Column(db.Boolean, default=False)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.id'), nullable=True)

    member = db.relationship('Member', back_populates='contributions_planning', foreign_keys=[member_id])


# ============================================================
# TABLE CYCLE_REPORT
# ============================================================
class CycleReport(TenantMixin, db.Model):
    __tablename__ = 'cycle_reports'

    id = db.Column(db.Integer, primary_key=True)
    cycle_id = db.Column(db.Integer, db.ForeignKey('tontine_cycle_details.id'), nullable=False)
    report_type = db.Column(db.String(20), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer, default=0)
    generated_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    generated_at = db.Column(db.DateTime, default=utcnow)

    total_collected = db.Column(db.Numeric(10, 2), default=Decimal('0.00'))
    total_sanctions = db.Column(db.Numeric(10, 2), default=Decimal('0.00'))
    total_distributed = db.Column(db.Numeric(10, 2), default=Decimal('0.00'))
    caisse_balance = db.Column(db.Numeric(10, 2), default=Decimal('0.00'))

    generator = db.relationship('User', foreign_keys=[generated_by], backref='generated_reports')
    cycle_detail = db.relationship('TontineCycleDetail', back_populates='reports', foreign_keys=[cycle_id])


# ============================================================
# TABLE CAISSE_BALANCE
# ============================================================
class CaisseBalance(TenantMixin, db.Model):
    __tablename__ = 'caisse_balances'

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, default=date.today)
    total_entrees = db.Column(db.Numeric(10, 2), default=Decimal('0.00'))
    total_sorties = db.Column(db.Numeric(10, 2), default=Decimal('0.00'))
    balance = db.Column(db.Numeric(10, 2), default=Decimal('0.00'))
    calculated_at = db.Column(db.DateTime, default=utcnow)

    @classmethod
    def calculate_current_balance(cls):
        entrees = db.session.query(db.func.sum(Transaction.amount)).filter(
            Transaction.type.in_(finance.INFLOW_TYPES)
        ).scalar() or Decimal('0.00')
        sorties = db.session.query(db.func.sum(Transaction.amount)).filter(
            Transaction.type.in_(finance.OUTFLOW_TYPES)
        ).scalar() or Decimal('0.00')
        return Decimal(str(entrees)) - Decimal(str(sorties))

# ============================================================
# VOTES (SCRUTINS)
# ============================================================
class Poll(TenantMixin, db.Model):
    __tablename__ = 'polls'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_anonymous = db.Column(db.Boolean, default=True)
    status = db.Column(db.String(20), default='OUVERT')  # OUVERT / CLOS
    end_date = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=utcnow)
    closed_at = db.Column(db.DateTime, nullable=True)

    creator = db.relationship('User', foreign_keys=[created_by], backref='polls_created')
    options = db.relationship('PollOption', backref='poll', cascade='all, delete-orphan',
                              order_by='PollOption.display_order')
    votes = db.relationship('PollVote', backref='poll', cascade='all, delete-orphan', lazy='dynamic')

    @property
    def is_open(self):
        if self.status != 'OUVERT':
            return False
        # end_date est saisie et stockée en heure locale
        if self.end_date and datetime.now() > self.end_date:
            return False
        return True

    @property
    def total_votes(self):
        return self.votes.count()

    def has_voted(self, member_id):
        return self.votes.filter_by(member_id=member_id).first() is not None

    def vote_of(self, member_id):
        return self.votes.filter_by(member_id=member_id).first()

    def results(self):
        """Liste de (option, nb_votes, pourcentage) triée par ordre d'affichage"""
        total = self.total_votes
        rows = []
        for option in self.options:
            count = self.votes.filter_by(option_id=option.id).count()
            pct = round(count * 100 / total, 1) if total else 0
            rows.append((option, count, pct))
        return rows

    def winners(self):
        rows = self.results()
        if not rows or self.total_votes == 0:
            return []
        best = max(r[1] for r in rows)
        return [r[0] for r in rows if r[1] == best]


class PollOption(TenantMixin, db.Model):
    __tablename__ = 'poll_options'

    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey('polls.id', ondelete='CASCADE'), nullable=False)
    label = db.Column(db.String(200), nullable=False)
    display_order = db.Column(db.Integer, default=0)


class PollVote(TenantMixin, db.Model):
    __tablename__ = 'poll_votes'
    __table_args__ = (db.UniqueConstraint('poll_id', 'member_id', name='uq_poll_member'),)

    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey('polls.id', ondelete='CASCADE'), nullable=False)
    option_id = db.Column(db.Integer, db.ForeignKey('poll_options.id', ondelete='CASCADE'), nullable=False)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=False)
    voted_at = db.Column(db.DateTime, default=utcnow)

    option = db.relationship('PollOption')
    member = db.relationship('Member')


# ============================================================
# TIRAGES AU SORT (ordre des bénéficiaires d'un cycle)
# ============================================================
class TontineDraw(TenantMixin, db.Model):
    __tablename__ = 'tontine_draws'

    id = db.Column(db.Integer, primary_key=True)
    cycle_id = db.Column(db.Integer, db.ForeignKey('tontine_cycle_details.id'), nullable=False)
    drawn_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    drawn_at = db.Column(db.DateTime, default=utcnow)
    notes = db.Column(db.String(255), nullable=True)

    cycle = db.relationship('TontineCycleDetail', backref=db.backref('draws', lazy='dynamic'))
    drawer = db.relationship('User', foreign_keys=[drawn_by])
    results = db.relationship('TontineDrawResult', backref='draw', cascade='all, delete-orphan',
                              order_by='TontineDrawResult.position')


class TontineDrawResult(TenantMixin, db.Model):
    __tablename__ = 'tontine_draw_results'

    id = db.Column(db.Integer, primary_key=True)
    draw_id = db.Column(db.Integer, db.ForeignKey('tontine_draws.id', ondelete='CASCADE'), nullable=False)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=False)
    position = db.Column(db.Integer, nullable=False)

    member = db.relationship('Member')


# ============================================================
# GALERIE PHOTOS (page d'accueil)
# ============================================================
class GalleryPhoto(TenantMixin, db.Model):
    __tablename__ = 'gallery_photos'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    caption = db.Column(db.String(200), nullable=True)
    is_hero = db.Column(db.Boolean, default=False)
    display_order = db.Column(db.Integer, default=0)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=utcnow)


# ============================================================
# RUBRIQUES DE COTISATION (catalogue propre à chaque tontine)
# ============================================================
class ContributionType(TenantMixin, db.Model):
    __tablename__ = 'contribution_types'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    category = db.Column(db.String(30), nullable=False)       # code de finance.CONTRIBUTION_CATEGORIES
    amount = db.Column(db.Numeric(10, 2), default=Decimal('0.00'))  # 0 = montant libre
    frequency = db.Column(db.String(20), default='PAR_SEANCE')
    is_mandatory = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True)
    description = db.Column(db.String(255), nullable=True)
    display_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=utcnow)

    @property
    def category_display(self):
        return finance.type_label(self.category)

    @property
    def frequency_display(self):
        return finance.FREQUENCIES.get(self.frequency, self.frequency)

    @property
    def fund_display(self):
        return finance.FUNDS.get(finance.fund_of(self.category), '')


# ============================================================
# AVALISTES (garants des emprunts)
# ============================================================
class LoanGuarantor(TenantMixin, db.Model):
    __tablename__ = 'loan_guarantors'
    __table_args__ = (db.UniqueConstraint('loan_id', 'member_id', name='uq_loan_guarantor'),)

    STATUSES = {
        'EN_ATTENTE': ('En attente de réponse', 'warning'),
        'ACCEPTE': ('Aval accordé', 'success'),
        'REFUSE': ('Aval refusé', 'danger'),
        'APPELE': ('Appelé à payer', 'danger'),
        'REGLE': ("Dette envers l'avaliste réglée", 'info'),
        'LIBERE': ('Libéré (prêt soldé)', 'secondary'),
        'ANNULE': ('Annulé', 'secondary'),
    }

    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey('loans.id', ondelete='CASCADE'), nullable=False)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)                  # part du prêt garantie
    called_amount = db.Column(db.Numeric(10, 2), default=Decimal('0.00'))  # déjà payé par l'avaliste
    status = db.Column(db.String(20), default='EN_ATTENTE')
    response_note = db.Column(db.String(255), nullable=True)
    requested_at = db.Column(db.DateTime, default=utcnow)
    responded_at = db.Column(db.DateTime, nullable=True)

    loan = db.relationship('Loan', back_populates='guarantors')
    member = db.relationship('Member')

    @property
    def status_display(self):
        return self.STATUSES.get(self.status, (self.status, 'secondary'))[0]

    @property
    def status_color(self):
        return self.STATUSES.get(self.status, (self.status, 'secondary'))[1]

    @property
    def remaining_guarantee(self):
        return Decimal(str(self.amount or 0)) - Decimal(str(self.called_amount or 0))


# ============================================================
# PARTICIPATION À UN CYCLE (une ligne = une « main » / part)
# ============================================================
class CycleParticipant(TenantMixin, db.Model):
    __tablename__ = 'cycle_participants'

    id = db.Column(db.Integer, primary_key=True)
    cycle_id = db.Column(db.Integer, db.ForeignKey('tontine_cycle_details.id', ondelete='CASCADE'), nullable=False)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=False)
    hand_number = db.Column(db.Integer, default=1)        # 1, 2, 3... si le membre a plusieurs mains
    position = db.Column(db.Integer, nullable=True)       # ordre de passage (NULL = pas encore tiré)
    served = db.Column(db.Boolean, default=False)
    served_at = db.Column(db.Date, nullable=True)

    cycle = db.relationship('TontineCycleDetail', back_populates='participants')
    member = db.relationship('Member')

    @property
    def label(self):
        hands = len([p for p in self.cycle.participants if p.member_id == self.member_id]) if self.cycle else 1
        name = self.member.full_name if self.member else 'N/A'
        return f"{name} (main {self.hand_number})" if hands > 1 else name


# ============================================================
# SÉANCES (réunions où les cotisations sont encaissées)
# ============================================================
class Seance(TenantMixin, db.Model):
    __tablename__ = 'seances'

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, default=date.today)
    title = db.Column(db.String(120), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    columns = db.Column(db.String(500), nullable=True)   # colonnes de la feuille : "r12,c3,..." (rubriques / cycles)
    is_closed = db.Column(db.Boolean, default=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=utcnow)

    transactions = db.relationship('Transaction', backref='seance', lazy='dynamic')

    @property
    def display_name(self):
        return self.title or f"Séance du {self.date.strftime('%d/%m/%Y')}"

    @property
    def total_collected(self):
        result = db.session.query(db.func.sum(Transaction.amount)).filter(Transaction.seance_id == self.id).scalar()
        return Decimal(str(result or 0))


# ============================================================
# CLÔTURE D'EXERCICE (partage de fin d'année)
# ============================================================
class ExerciseClosure(TenantMixin, db.Model):
    __tablename__ = 'exercise_closures'
    __table_args__ = (db.UniqueConstraint('tontine_id', 'year', name='uq_closure_year'),)

    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    savings_returned = db.Column(db.Numeric(12, 2), default=Decimal('0.00'))
    profit_distributed = db.Column(db.Numeric(12, 2), default=Decimal('0.00'))
    beneficiaries = db.Column(db.Integer, default=0)
    executed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    executed_at = db.Column(db.DateTime, default=utcnow)
    notes = db.Column(db.String(255), nullable=True)


# ============================================================
# DEMANDES DE RÉINITIALISATION DE MOT DE PASSE
# ============================================================
class PasswordResetRequest(TenantMixin, db.Model):
    __tablename__ = 'password_reset_requests'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(20), default='EN_ATTENTE')   # EN_ATTENTE / TRAITEE
    email_sent = db.Column(db.Boolean, default=False)
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    handled_at = db.Column(db.DateTime, nullable=True)
    handled_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    user = db.relationship('User', foreign_keys=[user_id])


# ============================================================
# TENTATIVES DE CONNEXION ÉCHOUÉES (protection contre la force brute)
# ============================================================
class LoginAttempt(db.Model):
    """Volontairement hors tontine : la protection s'applique avant de savoir qui se connecte."""
    __tablename__ = 'login_attempts'

    id = db.Column(db.Integer, primary_key=True)
    scope = db.Column(db.String(20), nullable=False)        # 'login' / 'forgot'
    ip_address = db.Column(db.String(45), nullable=False)
    identifier = db.Column(db.String(200), nullable=False)  # tontine:identifiant (en minuscules)
    created_at = db.Column(db.DateTime, default=utcnow, index=True)


# ============================================================
# BARÈME DES AIDES SOCIALES (propre à chaque tontine)
# ============================================================
class AidType(TenantMixin, db.Model):
    __tablename__ = 'aid_types'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)     # montant fixe (plafond si montant libre)
    free_amount = db.Column(db.Boolean, default=False)        # montant proposé, plafonné (ex. « Autre »)
    requires_document = db.Column(db.Boolean, default=True)
    max_per_year = db.Column(db.Integer, default=0)           # 0 = pas de limite propre à ce type
    is_active = db.Column(db.Boolean, default=True)
    display_order = db.Column(db.Integer, default=0)

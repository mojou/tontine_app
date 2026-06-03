from flask_login import UserMixin
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from werkzeug.security import generate_password_hash, check_password_hash
from decimal import Decimal
from extensions import db


# ============================================================
# TABLE USER
# ============================================================
class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='MEMBRE')
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)

    member = db.relationship('Member', backref='user_account', uselist=False, foreign_keys=[member_id])

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
            'MEMBRE': 'Membre'
        }
        return roles.get(self.role, self.role)

    @property
    def member_name(self):
        return self.member.full_name if self.member else "N/A"


# ============================================================
# TABLE MEMBER
# ============================================================
class Member(db.Model):
    __tablename__ = 'members'

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
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
        max_allowed = self.total_savings * 3
        requested = Decimal(str(requested_amount))
        if requested > max_allowed:
            return False, f"Maximum autorisé: {max_allowed:,.0f} FCFA."
        return True, "Éligible."

    def get_status_color(self):
        colors = {'ACTIF': 'success', 'SUSPENDU': 'warning', 'EXCLU': 'danger', 'PENDING': 'warning'}
        return colors.get(self.status, 'secondary')


# ============================================================
# TABLE TRANSACTION
# ============================================================
class Transaction(db.Model):
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    creator = db.relationship('User', foreign_keys=[created_by], backref='transactions_created')

    @property
    def member_name(self):
        return self.member.full_name if self.member else "N/A"

    @property
    def creator_name(self):
        return self.creator.username if self.creator else "Système"

    @property
    def validator_name(self):
        return "N/A"

    # NOUVELLE MÉTHODE AJOUTÉE
    def get_type_display(self):
        types = {
            'TONTINE': 'Tontine',
            'PRESENCE': 'Cotisation Présence',
            'SANCTION': 'Sanction',
            'REMBOURSEMENT': 'Remboursement',
            'AIDE': 'Aide Sociale',
            'FONDS_CAISSE': 'Fonds de Caisse',
            'SORTIE_LOAN': 'Décaissement',
            'BENEFICE_TONTINE': 'Bénéfice Tontine',
        }
        return types.get(self.type, self.type)


# ============================================================
# TABLE LOAN
# ============================================================
class Loan(db.Model):
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    approver = db.relationship('User', foreign_keys=[approved_by], backref='approved_loans')
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_loans')

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
class Sanction(db.Model):
    __tablename__ = 'sanctions'

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=False)
    member = db.relationship('Member', back_populates='sanctions', foreign_keys=[member_id])

    type_sanction = db.Column(db.String(50), nullable=False, default='AUTRE')
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    description = db.Column(db.Text, nullable=False)
    sanction_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='PENDING')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def member_name(self):
        return self.member.full_name if self.member else "N/A"

    @property
    def is_paid(self):
        return self.status == 'PAID'

    # NOUVELLES MÉTHODES AJOUTÉES
    def get_type_display(self):
        types = {
            'RETARD_PAIEMENT': 'Retard de paiement',
            'NON_PAIEMENT': 'Non-paiement',
            'ABSENCE': 'Absence non justifiée',
            'RETARD_REUNION': 'Retard à la réunion',
            'RETARD_EMPRUNT': 'Retard remboursement',
            'ECHEC_COTISATION': 'Échec de cotisation',
            'AUTRE': 'Autre'
        }
        return types.get(self.type_sanction, self.type_sanction)

    def mark_as_paid(self):
        self.status = 'PAID'
        db.session.commit()


# ============================================================
# TABLE ATTENDANCE
# ============================================================
class Attendance(db.Model):
    __tablename__ = 'attendances'

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=False)
    member = db.relationship('Member', back_populates='attendance_records', foreign_keys=[member_id])
    date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='PRESENT')


# ============================================================
# TABLE TONTINE_CYCLE (ancien)
# ============================================================
class TontineCycle(db.Model):
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))


# ============================================================
# TABLE TONTINE_POSITION
# ============================================================
class TontinePosition(db.Model):
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
class TontineCycleDetail(db.Model):
    __tablename__ = 'tontine_cycle_details'

    id = db.Column(db.Integer, primary_key=True)
    cycle_number = db.Column(db.Integer, nullable=False)
    group_type = db.Column(db.String(5), nullable=False)
    amount_per_member = db.Column(db.Numeric(10, 2), nullable=False)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default='EN_COURS')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    benefits = db.relationship('CycleBeneficiary', back_populates='cycle_detail', lazy='dynamic', foreign_keys='CycleBeneficiary.cycle_id')
    reports = db.relationship('CycleReport', back_populates='cycle_detail', lazy='dynamic')

    @property
    def total_members(self):
        try:
            return int(self.group_type)
        except ValueError:
            return 100

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
        benefited_ids = [b.member_id for b in self.benefits.all()]
        return Member.query.filter(
            Member.group_type == self.group_type,
            Member.is_active == True,
            Member.id.notin_(benefited_ids),
        ).order_by(Member.position_in_group).first()


# ============================================================
# TABLE CYCLE_BENEFICIARY
# ============================================================
class CycleBeneficiary(db.Model):
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

    cycle_detail = db.relationship('TontineCycleDetail', back_populates='benefits', foreign_keys=[cycle_id])

    @property
    def member_name(self):
        return self.member.full_name if self.member else "N/A"


# ============================================================
# TABLE AIDE
# ============================================================
class Aide(db.Model):
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

    @property
    def member_name(self):
        return self.member.full_name if self.member else "N/A"

    # NOUVELLE MÉTHODE AJOUTÉE
    def get_type_display(self):
        types = {
            'MALADIE': 'Maladie',
            'DECES': 'Décès',
            'MARIAGE': 'Mariage',
            'NAISSANCE': 'Naissance',
            'AUTRE': 'Autre'
        }
        return types.get(self.aide_type, self.aide_type)


# ============================================================
# TABLE ANNOUNCEMENT
# ============================================================
class Announcement(db.Model):
    __tablename__ = 'announcements'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    announcement_type = db.Column(db.String(20), default='INFO')
    event_date = db.Column(db.Date, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
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


class AgendaItem(db.Model):
    __tablename__ = 'agenda_items'

    id = db.Column(db.Integer, primary_key=True)
    announcement_id = db.Column(db.Integer, db.ForeignKey('announcements.id', ondelete='CASCADE'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    is_completed = db.Column(db.Boolean, default=False)


class MeetingBeneficiary(db.Model):
    __tablename__ = 'meeting_beneficiaries'

    id = db.Column(db.Integer, primary_key=True)
    announcement_id = db.Column(db.Integer, db.ForeignKey('announcements.id', ondelete='CASCADE'), nullable=False)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id', ondelete='CASCADE'), nullable=False)
    benefit_type = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=True)

    member = db.relationship('Member', foreign_keys=[member_id], backref='meeting_benefits')


class MeetingAttendanceDetail(db.Model):
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
class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    user_role = db.Column(db.String(20))
    action = db.Column(db.String(200), nullable=False)
    ip_address = db.Column(db.String(45))
    status = db.Column(db.String(20), default='SUCCESS')
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

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
class ContributionPlanning(db.Model):
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
class CycleReport(db.Model):
    __tablename__ = 'cycle_reports'

    id = db.Column(db.Integer, primary_key=True)
    cycle_id = db.Column(db.Integer, db.ForeignKey('tontine_cycle_details.id'), nullable=False)
    report_type = db.Column(db.String(20), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer, default=0)
    generated_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)

    total_collected = db.Column(db.Numeric(10, 2), default=Decimal('0.00'))
    total_sanctions = db.Column(db.Numeric(10, 2), default=Decimal('0.00'))
    total_distributed = db.Column(db.Numeric(10, 2), default=Decimal('0.00'))
    caisse_balance = db.Column(db.Numeric(10, 2), default=Decimal('0.00'))

    generator = db.relationship('User', foreign_keys=[generated_by], backref='generated_reports')
    cycle_detail = db.relationship('TontineCycleDetail', back_populates='reports', foreign_keys=[cycle_id])


# ============================================================
# TABLE CAISSE_BALANCE
# ============================================================
class CaisseBalance(db.Model):
    __tablename__ = 'caisse_balances'

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, default=date.today)
    total_entrees = db.Column(db.Numeric(10, 2), default=Decimal('0.00'))
    total_sorties = db.Column(db.Numeric(10, 2), default=Decimal('0.00'))
    balance = db.Column(db.Numeric(10, 2), default=Decimal('0.00'))
    calculated_at = db.Column(db.DateTime, default=datetime.utcnow)

    @classmethod
    def calculate_current_balance(cls):
        entrees = db.session.query(db.func.sum(Transaction.amount)).filter(
            Transaction.type.in_(['TONTINE', 'PRESENCE', 'SANCTION', 'REMBOURSEMENT', 'FONDS_CAISSE'])
        ).scalar() or Decimal('0.00')
        sorties = db.session.query(db.func.sum(Transaction.amount)).filter(
            Transaction.type.in_(['SORTIE_LOAN', 'BENEFICE_TONTINE', 'AIDE'])
        ).scalar() or Decimal('0.00')
        return Decimal(str(entrees)) - Decimal(str(sorties))
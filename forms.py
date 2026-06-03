from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import (StringField, PasswordField, SubmitField, BooleanField, 
                     SelectField, TextAreaField, FloatField, DateField, 
                     IntegerField, SelectMultipleField, DecimalField)
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError, NumberRange, Optional, Regexp
from datetime import datetime, date
import re

# ============================================================
# VALIDATEURS PERSONNALISÉS POUR LA SÉCURITÉ
# ============================================================

def no_html_tags(message=None):
    """Empêche l'injection de code HTML/JavaScript"""
    if message is None:
        message = 'Le code HTML/JavaScript n\'est pas autorisé'
    
    def _no_html_tags(form, field):
        if field.data and isinstance(field.data, str):
            # Recherche des balises HTML
            if re.search(r'<[^>]*>', field.data):
                raise ValidationError(message)
            # Recherche des événements JavaScript
            if re.search(r'on\w+\s*=', field.data, re.IGNORECASE):
                raise ValidationError(message)
            # Recherche des scripts
            if re.search(r'<script', field.data, re.IGNORECASE):
                raise ValidationError(message)
            # Recherche des expressions JavaScript
            if re.search(r'javascript:', field.data, re.IGNORECASE):
                raise ValidationError(message)
    return _no_html_tags


def no_special_characters(message=None):
    """Bloque les caractères spéciaux dangereux"""
    if message is None:
        message = 'Caractères interdits: < > " \' & / \\ ; $ % ` = ( ) { } [ ] |'
    
    def _no_special_characters(form, field):
        if field.data and isinstance(field.data, str):
            # Caractères interdits
            forbidden = r'[<>"\'&;/\\$%`=\(\)\{\}\[\]|]'
            if re.search(forbidden, field.data):
                raise ValidationError(message)
    return _no_special_characters


def safe_text(message=None):
    """Autorise uniquement les caractères sécurisés pour les textes"""
    if message is None:
        message = 'Utilisez uniquement des lettres, chiffres, espaces, accents, tirets, apostrophes, points et virgules'
    
    def _safe_text(form, field):
        if field.data and isinstance(field.data, str):
            # Autorise: lettres (accents inclus), chiffres, espaces, tirets, apostrophes, points, virgules
            if not re.match(r'^[a-zA-ZÀ-ÿ0-9\s\-_\'\.\,]+$', field.data):
                raise ValidationError(message)
    return _safe_text


def safe_username(message=None):
    """Valide un nom d'utilisateur sécurisé"""
    if message is None:
        message = 'Le nom d\'utilisateur ne peut contenir que des lettres, chiffres, underscores et points (3-80 caractères)'
    
    def _safe_username(form, field):
        if field.data:
            if not re.match(r'^[a-zA-Z0-9_.]{3,80}$', field.data):
                raise ValidationError(message)
    return _safe_username


def safe_phone(message=None):
    """Valide un numéro de téléphone sécurisé"""
    if message is None:
        message = 'Numéro de téléphone invalide (ex: 612345678)'
    
    def _safe_phone(form, field):
        if field.data:
            # Nettoie le numéro pour vérification
            cleaned = re.sub(r'[\s\-\(\)\+]', '', field.data)
            if not re.match(r'^[0-9]{9,15}$', cleaned):
                raise ValidationError(message)
    return _safe_phone


def safe_amount(message=None):
    """Valide un montant sécurisé"""
    if message is None:
        message = 'Montant invalide'
    
    def _safe_amount(form, field):
        if field.data:
            try:
                amount = float(field.data)
                if amount < 0:
                    raise ValidationError('Le montant ne peut pas être négatif')
                if amount > 999999999:
                    raise ValidationError('Montant trop élevé')
            except (ValueError, TypeError):
                raise ValidationError(message)
    return _safe_amount


# ============================================================
# FORMULAIRES D'AUTHENTIFICATION
# ============================================================

class LoginForm(FlaskForm):
    username = StringField('Nom d\'utilisateur', validators=[
        DataRequired(), 
        Length(min=3, max=80),
        safe_username(),
        no_html_tags()
    ])
    password = PasswordField('Mot de passe', validators=[DataRequired()])
    remember = BooleanField('Se souvenir de moi')
    submit = SubmitField('Se connecter')


# ============================================================
# FORMULAIRES D'INSCRIPTION (PUBLIC)
# ============================================================

class MemberRegistrationForm(FlaskForm):
    """Formulaire d'inscription pour les nouveaux membres (page publique)"""
    
    first_name = StringField('Prénom', validators=[
        DataRequired(), 
        Length(min=2, max=50),
        safe_text(),
        no_html_tags(),
        no_special_characters()
    ])
    last_name = StringField('Nom', validators=[
        DataRequired(), 
        Length(min=2, max=50),
        safe_text(),
        no_html_tags(),
        no_special_characters()
    ])
    email = StringField('Email', validators=[
        DataRequired(), 
        Email(), 
        Length(max=120),
        no_html_tags(),
        no_special_characters()
    ])
    phone = StringField('Téléphone', validators=[
        DataRequired(), 
        Length(max=20),
        safe_phone(),
        no_html_tags()
    ])
    address = StringField('Adresse', validators=[
        Optional(), 
        Length(max=200),
        safe_text(),
        no_html_tags(),
        no_special_characters()
    ])
    profession = StringField('Profession', validators=[
        Optional(), 
        Length(max=100),
        safe_text(),
        no_html_tags(),
        no_special_characters()
    ])
    city = StringField('Ville', validators=[
        Optional(), 
        Length(max=100),
        safe_text(),
        no_html_tags(),
        no_special_characters()
    ])
    
    cotisation_type = SelectField(
        'Type de cotisation', 
        choices=[
            ('', '-- Sélectionnez un type --'),
            ('PRESENCE', 'Présence (1 050 FCFA/semaine)'),
            ('TONTINE', 'Tontine (5 100 - 20 200 FCFA/14 jours)')
        ], 
        validators=[DataRequired()]
    )
    
    tontine_amount = SelectField(
        'Montant Tontine', 
        choices=[
            ('', '-- Sélectionnez un montant --'),
            ('5100', '5 100 FCFA/14 jours'),
            ('10200', '10 200 FCFA/14 jours'),
            ('20200', '20 200 FCFA/14 jours')
        ], 
        default='', 
        coerce=str
    )
    
    username = StringField('Nom d\'utilisateur', validators=[
        DataRequired(), 
        Length(min=3, max=80),
        safe_username(),
        no_html_tags()
    ])
    password = PasswordField('Mot de passe', validators=[
        DataRequired(), 
        Length(min=6),
        Regexp(r'^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{6,}$', 
               message='Le mot de passe doit contenir au moins 6 caractères avec lettres et chiffres')
    ])
    confirm_password = PasswordField('Confirmer le mot de passe', 
                                      validators=[DataRequired(), EqualTo('password')])
    
    submit = SubmitField('Soumettre ma candidature')
    
    def validate(self, extra_validators=None):
        if not super().validate(extra_validators):
            return False
        if self.cotisation_type.data == 'TONTINE' and (not self.tontine_amount.data or self.tontine_amount.data == ''):
            self.tontine_amount.errors.append('Veuillez sélectionner un montant pour la tontine')
            return False
        return True


# ============================================================
# FORMULAIRES MEMBRES (ADMIN)
# ============================================================

class MemberForm(FlaskForm):
    first_name = StringField('Prénom', validators=[
        DataRequired(), 
        Length(min=2, max=50),
        safe_text(),
        no_html_tags(),
        no_special_characters()
    ])
    last_name = StringField('Nom', validators=[
        DataRequired(), 
        Length(min=2, max=50),
        safe_text(),
        no_html_tags(),
        no_special_characters()
    ])
    email = StringField('Email', validators=[
        DataRequired(), 
        Email(), 
        Length(max=120),
        no_html_tags(),
        no_special_characters()
    ])
    phone = StringField('Téléphone', validators=[
        DataRequired(), 
        Length(max=20),
        safe_phone(),
        no_html_tags()
    ])
    address = StringField('Adresse', validators=[
        Optional(), 
        Length(max=200),
        safe_text(),
        no_html_tags(),
        no_special_characters()
    ])
    profession = StringField('Profession', validators=[
        Optional(), 
        Length(max=100),
        safe_text(),
        no_html_tags(),
        no_special_characters()
    ])
    city = StringField('Ville', validators=[
        Optional(), 
        Length(max=100),
        safe_text(),
        no_html_tags(),
        no_special_characters()
    ])
    photo = FileField('Photo', validators=[
        Optional(), 
        FileAllowed(['jpg', 'png', 'jpeg', 'gif'], 'Images uniquement!')
    ])
    
    group_type = SelectField('Type de groupe', choices=[
        ('100', 'Groupe de 100 membres'),
        ('200', 'Groupe de 200 membres')
    ], validators=[Optional()])
    position_in_group = IntegerField('Position dans le groupe', validators=[
        Optional(), 
        NumberRange(min=1, max=200)
    ])
    chosen_tontine_amount = SelectField('Montant tontine', choices=[
        ('5100', '5 100 FCFA'),
        ('10200', '10 200 FCFA'),
        ('20200', '20 200 FCFA')
    ], validators=[Optional()], coerce=str)
    
    username = StringField('Nom d\'utilisateur', validators=[
        DataRequired(), 
        Length(min=3, max=80),
        safe_username(),
        no_html_tags()
    ])
    password = PasswordField('Mot de passe', validators=[
        DataRequired(), 
        Length(min=6)
    ])
    confirm_password = PasswordField('Confirmer le mot de passe', 
                                      validators=[DataRequired(), EqualTo('password')])
    
    role = SelectField('Rôle', choices=[
        ('MEMBRE', 'Membre'),
        ('SECRETAIRE', 'Secrétaire'),
        ('PRESIDENT', 'Président'),
        ('TRESORIER', 'Trésorier'),
        ('CENSEUR', 'Censeur'),
        ('COMMUNICATION', 'Communication')
    ], default='MEMBRE', validators=[DataRequired()])
    
    submit = SubmitField('Enregistrer')


class MemberEditForm(FlaskForm):
    first_name = StringField('Prénom', validators=[
        DataRequired(), 
        Length(min=2, max=50),
        safe_text(),
        no_html_tags(),
        no_special_characters()
    ])
    last_name = StringField('Nom', validators=[
        DataRequired(), 
        Length(min=2, max=50),
        safe_text(),
        no_html_tags(),
        no_special_characters()
    ])
    email = StringField('Email', validators=[
        DataRequired(), 
        Email(), 
        Length(max=120),
        no_html_tags(),
        no_special_characters()
    ])
    phone = StringField('Téléphone', validators=[
        DataRequired(), 
        Length(max=20),
        safe_phone(),
        no_html_tags()
    ])
    address = StringField('Adresse', validators=[
        Optional(), 
        Length(max=200),
        safe_text(),
        no_html_tags(),
        no_special_characters()
    ])
    profession = StringField('Profession', validators=[
        Optional(), 
        Length(max=100),
        safe_text(),
        no_html_tags(),
        no_special_characters()
    ])
    city = StringField('Ville', validators=[
        Optional(), 
        Length(max=100),
        safe_text(),
        no_html_tags(),
        no_special_characters()
    ])
    status = SelectField('Statut', choices=[
        ('ACTIF', 'Actif'),
        ('SUSPENDU', 'Suspendu'),
        ('EXCLU', 'Exclu'),
        ('PENDING', 'En attente')
    ], validators=[DataRequired()])
    photo = FileField('Photo', validators=[
        Optional(), 
        FileAllowed(['jpg', 'png', 'jpeg', 'gif'], 'Images uniquement!')
    ])
    submit = SubmitField('Mettre à jour')


class ProfileEditForm(FlaskForm):
    first_name = StringField('Prénom', validators=[
        DataRequired(), 
        Length(min=2, max=50),
        safe_text(),
        no_html_tags(),
        no_special_characters()
    ])
    last_name = StringField('Nom', validators=[
        DataRequired(), 
        Length(min=2, max=50),
        safe_text(),
        no_html_tags(),
        no_special_characters()
    ])
    email = StringField('Email', validators=[
        DataRequired(), 
        Email(), 
        Length(max=120),
        no_html_tags(),
        no_special_characters()
    ])
    phone = StringField('Téléphone', validators=[
        DataRequired(), 
        Length(max=20),
        safe_phone(),
        no_html_tags()
    ])
    photo = FileField('Photo', validators=[
        Optional(), 
        FileAllowed(['jpg', 'png', 'jpeg', 'gif'], 'Images uniquement!')
    ])
    submit = SubmitField('Mettre à jour')


# ============================================================
# FORMULAIRES TRANSACTIONS
# ============================================================

class TransactionForm(FlaskForm):
    member_id = SelectField('Membre', coerce=int, validators=[DataRequired()])
    type = SelectField('Type de transaction', choices=[
        ('TONTINE', 'Tontine'),
        ('PRESENCE', 'Cotisation Présence'),
        ('SANCTION', 'Sanction'),
        ('REMBOURSEMENT', 'Remboursement'),
        ('AIDE', 'Aide'),
        ('FONDS_CAISSE', 'Fonds de Caisse'),
        ('SORTIE_LOAN', 'Prêt accordé'),
    ], validators=[DataRequired()])
    amount = FloatField('Montant (FCFA)', validators=[
        DataRequired(), 
        NumberRange(min=0, max=999999999),
        safe_amount()
    ])
    description = TextAreaField('Description', validators=[
        Optional(), 
        Length(max=200),
        no_html_tags(),
        no_special_characters()
    ])
    payment_mode = SelectField('Mode de paiement', choices=[
        ('ORANGE_MONEY', 'Orange Money'),
        ('MTN_MOBILE', 'MTN Mobile'),
        ('ESPECE', 'Espèce')
    ], default='ESPECE', validators=[Optional()])
    submit = SubmitField('Enregistrer')


class PresenceTransactionForm(FlaskForm):
    member_id = SelectField('Membre', coerce=int, validators=[DataRequired()])
    week_number = IntegerField('Numéro de semaine', validators=[
        DataRequired(), 
        NumberRange(min=1, max=52)
    ])
    year = IntegerField('Année', validators=[
        DataRequired(), 
        NumberRange(min=2020, max=2030)
    ])
    payment_mode = SelectField('Mode de paiement', choices=[
        ('ORANGE_MONEY', 'Orange Money'),
        ('MTN_MOBILE', 'MTN Mobile'),
        ('ESPECE', 'Espèce')
    ], default='ESPECE', validators=[Optional()])
    submit = SubmitField('Enregistrer')


class TontineTransactionForm(FlaskForm):
    member_id = SelectField('Membre', coerce=int, validators=[DataRequired()])
    fortnight_number = IntegerField('Numéro de quinzaine (1 ou 2)', validators=[
        DataRequired(), 
        NumberRange(min=1, max=2)
    ])
    month = IntegerField('Mois', validators=[
        DataRequired(), 
        NumberRange(min=1, max=12)
    ])
    year = IntegerField('Année', validators=[
        DataRequired(), 
        NumberRange(min=2020, max=2030)
    ])
    amount = SelectField('Montant', choices=[
        ('5100', '5 100 FCFA'),
        ('10200', '10 200 FCFA'),
        ('20200', '20 200 FCFA')
    ], validators=[DataRequired()], coerce=str)
    payment_mode = SelectField('Mode de paiement', choices=[
        ('ORANGE_MONEY', 'Orange Money'),
        ('MTN_MOBILE', 'MTN Mobile'),
        ('ESPECE', 'Espèce')
    ], default='ESPECE', validators=[Optional()])
    submit = SubmitField('Enregistrer')


# ============================================================
# FORMULAIRES EMPRUNTS
# ============================================================

class LoanRequestForm(FlaskForm):
    amount = FloatField('Montant du prêt (FCFA)', validators=[
        DataRequired(), 
        NumberRange(min=1000, max=999999999),
        safe_amount()
    ])
    duration_months = SelectField('Durée (mois)', choices=[
        (1, '1 mois'),
        (2, '2 mois'),
        (3, '3 mois')
    ], validators=[DataRequired()])
    interest_rate = FloatField("Taux d'intérêt (%)", default=5.0, validators=[
        NumberRange(min=0, max=100)
    ])
    purpose = TextAreaField('Motif du prêt', validators=[
        Optional(), 
        Length(max=200),
        no_html_tags(),
        no_special_characters()
    ])
    submit = SubmitField('Soumettre')


class LoanRepaymentForm(FlaskForm):
    amount = FloatField('Montant à rembourser (FCFA)', validators=[
        DataRequired(), 
        NumberRange(min=0, max=999999999),
        safe_amount()
    ])
    payment_mode = SelectField('Mode de paiement', choices=[
        ('ORANGE_MONEY', 'Orange Money'),
        ('MTN_MOBILE', 'MTN Mobile'),
        ('ESPECE', 'Espèce')
    ], default='ESPECE', validators=[Optional()])
    submit = SubmitField('Rembourser')


class LoanApprovalForm(FlaskForm):
    action = SelectField('Action', choices=[
        ('approve', 'Approuver'),
        ('reject', 'Rejeter')
    ], validators=[DataRequired()])
    rejection_reason = TextAreaField('Raison du rejet', validators=[
        Optional(), 
        Length(max=500),
        no_html_tags(),
        no_special_characters()
    ])
    submit = SubmitField('Confirmer')


# ============================================================
# FORMULAIRES SANCTIONS
# ============================================================

class SanctionForm(FlaskForm):
    member_id = SelectField('Membre', coerce=int, validators=[DataRequired()])
    type_sanction = SelectField('Type de sanction', choices=[
        ('RETARD_PAIEMENT', 'Retard de paiement'),
        ('NON_PAIEMENT', 'Non-paiement'),
        ('ABSENCE', 'Absence non justifiée'),
        ('RETARD_REUNION', 'Retard réunion'),
        ('RETARD_EMPRUNT', 'Retard remboursement'),
        ('ECHEC_COTISATION', 'Échec de cotisation'),
        ('AUTRE', 'Autre')
    ], validators=[DataRequired()])
    amount = FloatField('Montant (FCFA)', validators=[
        DataRequired(), 
        NumberRange(min=0, max=999999999),
        safe_amount()
    ])
    description = TextAreaField('Description', validators=[
        DataRequired(), 
        Length(max=500),
        no_html_tags(),
        no_special_characters()
    ])
    sanction_date = DateField('Date de la sanction', default=date.today, format='%Y-%m-%d')
    submit = SubmitField('Appliquer')


# ============================================================
# FORMULAIRES RÉUNIONS ET ANNONCES
# ============================================================

class AnnouncementForm(FlaskForm):
    title = StringField('Titre', validators=[
        DataRequired(), 
        Length(max=200),
        safe_text(),
        no_html_tags(),
        no_special_characters()
    ])
    announcement_type = SelectField('Type', choices=[
        ('INFO', 'Information'),
        ('URGENT', 'Urgent'),
        ('REUNION', 'Réunion'),
        ('RAPPEL', 'Rappel')
    ], validators=[DataRequired()])
    event_date = DateField('Date de l\'événement', format='%Y-%m-%d', validators=[Optional()])
    content = TextAreaField('Contenu', validators=[
        DataRequired(),
        no_html_tags(),
        no_special_characters()
    ])
    submit = SubmitField('Publier')


class MeetingAttendanceForm(FlaskForm):
    """Formulaire pour les procès-verbaux de réunion"""
    
    meeting_title = StringField('Titre de la réunion', validators=[
        DataRequired(), 
        Length(max=200),
        safe_text(),
        no_html_tags(),
        no_special_characters()
    ])
    meeting_date = DateField('Date de la réunion', validators=[DataRequired()], format='%Y-%m-%d')
    content = TextAreaField('Contenu du PV', validators=[
        DataRequired(),
        no_html_tags(),
        no_special_characters()
    ])
    
    agenda_items = TextAreaField('Ordre du jour', validators=[
        Optional(),
        no_html_tags(),
        no_special_characters()
    ], render_kw={"rows": 5, "placeholder": "Point 1\nPoint 2\nPoint 3"})
    resolutions = TextAreaField('Résolutions', validators=[
        Optional(),
        no_html_tags(),
        no_special_characters()
    ], render_kw={"rows": 4, "placeholder": "Résolutions prises lors de la réunion..."})
    next_meeting_date = DateField('Date de la prochaine réunion', validators=[Optional()], format='%Y-%m-%d')
    
    beneficiary_member_id = SelectField('Bénéficiaire Tontine', coerce=int, validators=[Optional()])
    benefit_amount = FloatField('Montant du bénéfice (FCFA)', validators=[
        Optional(), 
        NumberRange(min=0, max=999999999),
        safe_amount()
    ])
    benefit_cycle_number = IntegerField('Numéro du cycle', validators=[
        Optional(), 
        NumberRange(min=1, max=999)
    ])
    payment_mode = SelectField('Mode de paiement', choices=[
        ('', '-- Sélectionnez --'),
        ('ESPECE', 'Espèce'),
        ('ORANGE_MONEY', 'Orange Money'),
        ('MTN_MOBILE', 'MTN Mobile'),
        ('VIREMENT', 'Virement Bancaire')
    ], validators=[Optional()])
    
    loan_member_id = SelectField('Membre bénéficiaire du prêt', coerce=int, validators=[Optional()])
    loan_amount = FloatField('Montant du prêt (FCFA)', validators=[
        Optional(), 
        NumberRange(min=0, max=999999999),
        safe_amount()
    ])
    loan_duration = IntegerField('Durée (mois)', validators=[
        Optional(), 
        NumberRange(min=1, max=36)
    ])
    loan_interest_rate = FloatField("Taux d'intérêt (%)", validators=[
        Optional(), 
        NumberRange(min=0, max=100)
    ], default=5.0)
    
    aid_member_id = SelectField('Bénéficiaire de l\'aide', coerce=int, validators=[Optional()])
    aid_type = SelectField('Type d\'aide', choices=[
        ('', '-- Sélectionnez --'),
        ('MALADIE', 'Maladie'),
        ('DECES', 'Décès'),
        ('MARIAGE', 'Mariage'),
        ('NAISSANCE', 'Naissance'),
        ('AUTRE', 'Autre')
    ], validators=[Optional()])
    aid_amount = FloatField('Montant de l\'aide (FCFA)', validators=[
        Optional(), 
        NumberRange(min=0, max=999999999),
        safe_amount()
    ])
    aid_description = TextAreaField('Description de l\'aide', validators=[
        Optional(), 
        Length(max=500),
        no_html_tags(),
        no_special_characters()
    ])
    
    sanction_member_id = SelectField('Membre sanctionné', coerce=int, validators=[Optional()])
    sanction_type = SelectField('Type de sanction', choices=[
        ('', '-- Sélectionnez --'),
        ('RETARD_PAIEMENT', 'Retard de paiement'),
        ('ABSENCE', 'Absence non justifiée'),
        ('RETARD_REUNION', 'Retard à la réunion'),
        ('NON_PAIEMENT', 'Non-paiement'),
        ('AUTRE', 'Autre')
    ], validators=[Optional()])
    sanction_amount = FloatField('Montant de la sanction (FCFA)', validators=[
        Optional(), 
        NumberRange(min=0, max=999999999),
        safe_amount()
    ])
    sanction_description = TextAreaField('Description de la sanction', validators=[
        Optional(), 
        Length(max=500),
        no_html_tags(),
        no_special_characters()
    ])
    
    submit = SubmitField('Enregistrer le PV')


# ============================================================
# FORMULAIRES TONTINE ET CYCLES
# ============================================================

class TontineCycleForm(FlaskForm):
    amount_per_member = SelectField('Montant par membre', choices=[
        ('5100', '5 100 FCFA'),
        ('10200', '10 200 FCFA'),
        ('20200', '20 200 FCFA')
    ], validators=[DataRequired()], coerce=str)
    
    group_type = SelectField('Capacité du groupe', choices=[
        ('50', 'Groupe de 50 membres'),
        ('100', 'Groupe de 100 membres'),
        ('200', 'Groupe de 200 membres')
    ], validators=[DataRequired()], coerce=str)
    
    members = SelectMultipleField('Membres participants', coerce=int, validators=[DataRequired()])
    random_order = BooleanField('Tirage au sort aléatoire')
    submit = SubmitField('Démarrer le cycle')
    
    def validate_members(self, field):
        if not field.data:
            raise ValidationError('Sélectionnez au moins un membre.')
        max_capacity = int(self.group_type.data) if self.group_type.data else 200
        if len(field.data) > max_capacity:
            raise ValidationError(f'Maximum {max_capacity} membres autorisés.')


class TontineBenefitForm(FlaskForm):
    member_id = SelectField('Bénéficiaire', coerce=int, validators=[DataRequired()])
    cycle_id = SelectField('Cycle', coerce=int, validators=[DataRequired()])
    payment_mode = SelectField('Mode de paiement', choices=[
        ('ORANGE_MONEY', 'Orange Money'),
        ('MTN_MOBILE', 'MTN Mobile'),
        ('ESPECE', 'Espèce'),
        ('VIREMENT', 'Virement')
    ], default='ESPECE', validators=[DataRequired()])
    submit = SubmitField('Valider')


# ============================================================
# FORMULAIRES AIDES SOCIALES
# ============================================================

class AideForm(FlaskForm):
    member_id = SelectField('Membre', coerce=int, validators=[DataRequired()])
    aide_type = SelectField('Type d\'aide', choices=[
        ('MALADIE', 'Maladie'),
        ('DECES', 'Décès'),
        ('MARIAGE', 'Mariage'),
        ('NAISSANCE', 'Naissance'),
        ('AUTRE', 'Autre')
    ], validators=[DataRequired()])
    amount = FloatField('Montant (FCFA)', validators=[
        DataRequired(), 
        NumberRange(min=0, max=999999999),
        safe_amount()
    ])
    description = TextAreaField('Description', validators=[
        Optional(), 
        Length(max=500),
        no_html_tags(),
        no_special_characters()
    ])
    submit = SubmitField('Demander')


class AideApprovalForm(FlaskForm):
    action = SelectField('Action', choices=[
        ('approve', 'Approuver'),
        ('reject', 'Rejeter')
    ], validators=[DataRequired()])
    rejection_reason = TextAreaField('Raison du rejet', validators=[
        Optional(), 
        Length(max=500),
        no_html_tags(),
        no_special_characters()
    ])
    submit = SubmitField('Confirmer')


# ============================================================
# FORMULAIRES RAPPORTS
# ============================================================

class ReportForm(FlaskForm):
    report_type = SelectField('Type de rapport', choices=[
        ('cotisations', 'Cotisations'),
        ('loans', 'Emprunts'),
        ('sanctions', 'Sanctions'),
        ('members', 'Membres'),
        ('financial', 'Financier')
    ], validators=[DataRequired()])
    start_date = DateField('Date début', format='%Y-%m-%d', validators=[DataRequired()])
    end_date = DateField('Date fin', format='%Y-%m-%d', validators=[DataRequired()])
    format = SelectField('Format', choices=[
        ('PDF', 'PDF'),
        ('EXCEL', 'Excel')
    ], validators=[DataRequired()])
    submit = SubmitField('Générer')


# ============================================================
# FORMULAIRES FILTRES
# ============================================================

class MemberFilterForm(FlaskForm):
    status = SelectField('Statut', choices=[
        ('', 'Tous'),
        ('ACTIF', 'Actif'),
        ('SUSPENDU', 'Suspendu'),
        ('EXCLU', 'Exclu'),
        ('PENDING', 'En attente')
    ], validators=[Optional()])
    tontine_status = SelectField('Statut tontine', choices=[
        ('', 'Tous'),
        ('VERT', 'Vert'),
        ('ORANGE', 'Orange'),
        ('ROUGE', 'Rouge')
    ], validators=[Optional()])
    group_type = SelectField('Type de groupe', choices=[
        ('', 'Tous'),
        ('100', '100 membres'),
        ('200', '200 membres')
    ], validators=[Optional()])
    search = StringField('Recherche', validators=[
        Optional(), 
        Length(max=100),
        safe_text(),
        no_html_tags(),
        no_special_characters()
    ])
    submit = SubmitField('Filtrer')


class TransactionFilterForm(FlaskForm):
    type = SelectField('Type', choices=[
        ('', 'Tous'),
        ('TONTINE', 'Tontine'),
        ('PRESENCE', 'Présence'),
        ('SANCTION', 'Sanction'),
        ('REMBOURSEMENT', 'Remboursement'),
        ('AIDE', 'Aide'),
        ('FONDS_CAISSE', 'Fonds de caisse')
    ], validators=[Optional()])
    start_date = DateField('Date début', format='%Y-%m-%d', validators=[Optional()])
    end_date = DateField('Date fin', format='%Y-%m-%d', validators=[Optional()])
    submit = SubmitField('Filtrer')
#!/usr/bin/env python3
"""
Script de correction automatique de models.py
À exécuter une seule fois pour corriger les relations
"""

import re
import sys
import shutil
from datetime import datetime

# Configuration
MODELS_FILE = 'models.py'
BACKUP_SUFFIX = f'.backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}'

def backup_file(filepath):
    """Crée une copie de sauvegarde du fichier"""
    backup_path = filepath + BACKUP_SUFFIX
    try:
        shutil.copy2(filepath, backup_path)
        print(f"✅ Sauvegarde créée: {backup_path}")
        return True
    except Exception as e:
        print(f"❌ Erreur lors de la sauvegarde: {e}")
        return False

def read_file(filepath):
    """Lit le contenu du fichier"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"❌ Erreur de lecture: {e}")
        return None

def write_file(filepath, content):
    """Écrit le contenu dans le fichier"""
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    except Exception as e:
        print(f"❌ Erreur d'écriture: {e}")
        return False

def fix_imports(content):
    """Corrige les imports manquants"""
    required_imports = [
        'from datetime import datetime, date',
        'from decimal import Decimal'
    ]
    
    for imp in required_imports:
        if imp not in content:
            # Ajouter après les imports existants
            lines = content.split('\n')
            insert_pos = 0
            for i, line in enumerate(lines):
                if line.startswith('from ') or line.startswith('import '):
                    insert_pos = i + 1
            lines.insert(insert_pos, imp)
            content = '\n'.join(lines)
            print(f"✅ Import ajouté: {imp}")
    
    return content

def fix_member_relationships(content):
    """Corrige les relations dans la classe Member"""
    
    # Pattern pour trouver la classe Member
    member_class_pattern = r'(class Member\(db\.Model\):(.*?)(?=\nclass |\Z))'
    
    def fix_member(match):
        class_content = match.group(0)
        
        # Liste des relations attendues
        expected_relations = {
            'transactions': "db.relationship('Transaction', backref='member', lazy='dynamic', foreign_keys='Transaction.member_id')",
            'loans': "db.relationship('Loan', backref='member', lazy='dynamic', foreign_keys='Loan.member_id')",
            'sanctions': "db.relationship('Sanction', backref='member', lazy='dynamic', foreign_keys='Sanction.member_id')",
            'attendances': "db.relationship('Attendance', backref='member', lazy='dynamic', foreign_keys='Attendance.member_id')",
            'tontine_positions': "db.relationship('TontinePosition', backref='member', lazy='dynamic', foreign_keys='TontinePosition.member_id')",
            'cycle_benefits': "db.relationship('CycleBeneficiary', backref='member', lazy='dynamic', foreign_keys='CycleBeneficiary.member_id')",
            'aides': "db.relationship('Aide', backref='member', lazy='dynamic', foreign_keys='Aide.member_id')",
            'user': "db.relationship('User', backref='member', uselist=False, foreign_keys='User.member_id')"
        }
        
        # Vérifier chaque relation
        for rel_name, rel_def in expected_relations.items():
            if f"{rel_name} = db.relationship" not in class_content:
                # Trouver l'indentation
                lines = class_content.split('\n')
                indent = "    "
                
                # Trouver l'endroit pour insérer (après les colonnes)
                insert_pos = len(lines) - 1
                for i, line in enumerate(lines):
                    if 'db.Column' in line and i > insert_pos:
                        insert_pos = i
                
                # Insérer la relation
                lines.insert(insert_pos + 1, f"{indent}{rel_name} = {rel_def}")
                class_content = '\n'.join(lines)
                print(f"✅ Relation Member.{rel_name} ajoutée")
        
        return class_content
    
    content = re.sub(member_class_pattern, fix_member, content, flags=re.DOTALL)
    return content

def fix_sanction_relationships(content):
    """Corrige les relations dans la classe Sanction"""
    
    sanction_class_pattern = r'(class Sanction\(db\.Model\):(.*?)(?=\nclass |\Z))'
    
    def fix_sanction(match):
        class_content = match.group(0)
        
        # Vérifier la relation member
        if "member = db.relationship" not in class_content:
            lines = class_content.split('\n')
            indent = "    "
            
            # Trouver l'endroit pour insérer
            for i, line in enumerate(lines):
                if 'member_id = db.Column' in line:
                    lines.insert(i + 1, f"{indent}member = db.relationship('Member', backref='sanction_member', foreign_keys=[member_id])")
                    break
            
            class_content = '\n'.join(lines)
            print("✅ Relation Sanction.member ajoutée")
        
        return class_content
    
    content = re.sub(sanction_class_pattern, fix_sanction, content, flags=re.DOTALL)
    return content

def fix_transaction_relationships(content):
    """Corrige les relations dans la classe Transaction"""
    
    transaction_class_pattern = r'(class Transaction\(db\.Model\):(.*?)(?=\nclass |\Z))'
    
    def fix_transaction(match):
        class_content = match.group(0)
        
        # Vérifier la relation member
        if "member = db.relationship" not in class_content:
            lines = class_content.split('\n')
            indent = "    "
            
            for i, line in enumerate(lines):
                if 'member_id = db.Column' in line:
                    lines.insert(i + 1, f"{indent}member = db.relationship('Member', backref='transaction_member', foreign_keys=[member_id])")
                    break
            
            class_content = '\n'.join(lines)
            print("✅ Relation Transaction.member ajoutée")
        
        return class_content
    
    content = re.sub(transaction_class_pattern, fix_transaction, content, flags=re.DOTALL)
    return content

def fix_loan_relationships(content):
    """Corrige les relations dans la classe Loan"""
    
    loan_class_pattern = r'(class Loan\(db\.Model\):(.*?)(?=\nclass |\Z))'
    
    def fix_loan(match):
        class_content = match.group(0)
        
        # Vérifier la relation member
        if "member = db.relationship" not in class_content:
            lines = class_content.split('\n')
            indent = "    "
            
            for i, line in enumerate(lines):
                if 'member_id = db.Column' in line:
                    lines.insert(i + 1, f"{indent}member = db.relationship('Member', backref='loan_member', foreign_keys=[member_id])")
                    break
            
            class_content = '\n'.join(lines)
            print("✅ Relation Loan.member ajoutée")
        
        return class_content
    
    content = re.sub(loan_class_pattern, fix_loan, content, flags=re.DOTALL)
    return content

def fix_tontine_relationships(content):
    """Corrige les relations dans les classes Tontine"""
    
    # Fix TontineCycleDetail
    cycle_detail_pattern = r'(class TontineCycleDetail\(db\.Model\):(.*?)(?=\nclass |\Z))'
    
    def fix_cycle_detail(match):
        class_content = match.group(0)
        
        if "benefits = db.relationship" not in class_content:
            lines = class_content.split('\n')
            indent = "    "
            
            for i, line in enumerate(lines):
                if 'status = db.Column' in line:
                    lines.insert(i + 1, f"{indent}benefits = db.relationship('CycleBeneficiary', backref='cycle', lazy='dynamic')")
                    lines.insert(i + 2, f"{indent}reports = db.relationship('CycleReport', backref='cycle', lazy='dynamic')")
                    break
            
            class_content = '\n'.join(lines)
            print("✅ Relations TontineCycleDetail ajoutées")
        
        return class_content
    
    content = re.sub(cycle_detail_pattern, fix_cycle_detail, content, flags=re.DOTALL)
    
    # Fix CycleBeneficiary
    beneficiary_pattern = r'(class CycleBeneficiary\(db\.Model\):(.*?)(?=\nclass |\Z))'
    
    def fix_beneficiary(match):
        class_content = match.group(0)
        
        if "member = db.relationship" not in class_content:
            lines = class_content.split('\n')
            indent = "    "
            
            for i, line in enumerate(lines):
                if 'member_id = db.Column' in line:
                    lines.insert(i + 1, f"{indent}member = db.relationship('Member', backref='beneficiary_records', foreign_keys=[member_id])")
                    break
            
            class_content = '\n'.join(lines)
            print("✅ Relation CycleBeneficiary.member ajoutée")
        
        return class_content
    
    content = re.sub(beneficiary_pattern, fix_beneficiary, content, flags=re.DOTALL)
    
    return content

def fix_user_relationship(content):
    """Corrige la relation dans la classe User"""
    
    user_class_pattern = r'(class User\(UserMixin, db\.Model\):(.*?)(?=\nclass |\Z))'
    
    def fix_user(match):
        class_content = match.group(0)
        
        # Vérifier la relation member
        if "member = db.relationship" not in class_content:
            lines = class_content.split('\n')
            indent = "    "
            
            for i, line in enumerate(lines):
                if 'member_id = db.Column' in line:
                    lines.insert(i + 1, f"{indent}member = db.relationship('Member', backref='user_account', uselist=False, foreign_keys=[member_id])")
                    break
            
            class_content = '\n'.join(lines)
            print("✅ Relation User.member ajoutée")
        
        return class_content
    
    content = re.sub(user_class_pattern, fix_user, content, flags=re.DOTALL)
    return content

def fix_aide_relationships(content):
    """Corrige les relations dans la classe Aide"""
    
    aide_class_pattern = r'(class Aide\(db\.Model\):(.*?)(?=\nclass |\Z))'
    
    def fix_aide(match):
        class_content = match.group(0)
        
        # Vérifier la relation member
        if "member = db.relationship" not in class_content:
            lines = class_content.split('\n')
            indent = "    "
            
            for i, line in enumerate(lines):
                if 'member_id = db.Column' in line:
                    lines.insert(i + 1, f"{indent}member = db.relationship('Member', backref='aide_member', foreign_keys=[member_id])")
                    break
            
            class_content = '\n'.join(lines)
            print("✅ Relation Aide.member ajoutée")
        
        if "approver = db.relationship" not in class_content:
            lines = class_content.split('\n')
            indent = "    "
            
            for i, line in enumerate(lines):
                if 'approved_by = db.Column' in line:
                    lines.insert(i + 1, f"{indent}approver = db.relationship('User', backref='approved_aides', foreign_keys=[approved_by])")
                    break
            
            class_content = '\n'.join(lines)
            print("✅ Relation Aide.approver ajoutée")
        
        return class_content
    
    content = re.sub(aide_class_pattern, fix_aide, content, flags=re.DOTALL)
    return content

def add_missing_properties(content):
    """Ajoute les propriétés manquantes dans la classe Member"""
    
    member_class_pattern = r'(class Member\(db\.Model\):.*?)(?=\n    @property|\n    def |\nclass |\Z)'
    
    def add_properties(match):
        class_content = match.group(1)
        
        properties_to_add = [
            '''
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"
    ''',
            '''
    @property
    def has_paid_fonds_caisse(self):
        """Vérifie si le membre a payé le fonds de caisse"""
        from models import Transaction
        count = Transaction.query.filter_by(member_id=self.id, type='FONDS_CAISSE').count()
        return count > 0
    ''',
            '''
    @property
    def total_savings(self):
        """Total des cotisations tontine"""
        from models import Transaction
        result = db.session.query(db.func.sum(Transaction.amount)).filter(
            Transaction.member_id == self.id,
            Transaction.type == 'TONTINE'
        ).scalar()
        return Decimal(result or 0)
    ''',
            '''
    @property
    def total_sanctions_pending(self):
        """Total des sanctions non payées"""
        from models import Sanction
        result = db.session.query(db.func.sum(Sanction.amount)).filter(
            Sanction.member_id == self.id,
            Sanction.status == 'PENDING'
        ).scalar()
        return Decimal(result or 0)
    '''
        ]
        
        # Vérifier et ajouter les propriétés manquantes
        for prop in properties_to_add:
            prop_name = prop.strip().split('\n')[0].replace('@property', '').strip()
            if prop_name not in class_content:
                # Trouver l'endroit pour insérer (après les colonnes)
                lines = class_content.split('\n')
                insert_pos = len(lines) - 1
                for i, line in enumerate(lines):
                    if 'db.Column' in line and i > 10:
                        insert_pos = i
                        break
                
                lines.insert(insert_pos + 1, prop)
                class_content = '\n'.join(lines)
                print(f"✅ Propriété Member.{prop_name} ajoutée")
        
        return class_content
    
    content = re.sub(member_class_pattern, add_properties, content, flags=re.DOTALL)
    return content

def fix_import_circular(content):
    """Corrige les imports circulaires en déplaçant les imports à l'intérieur des méthodes"""
    
    # Déplacer les imports de modèles dans les méthodes
    patterns = [
        (r'from models import (.*?)\n(.*?)(?=\n    def )', r'\2'),
        (r'import models\n', ''),
    ]
    
    for pattern, replacement in patterns:
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    
    return content

def main():
    """Fonction principale"""
    print("=" * 60)
    print("🔧 CORRECTION AUTOMATIQUE DE MODELS.PY")
    print("=" * 60)
    
    # 1. Sauvegarder le fichier original
    if not backup_file(MODELS_FILE):
        print("❌ Impossible de continuer sans sauvegarde")
        sys.exit(1)
    
    # 2. Lire le fichier
    content = read_file(MODELS_FILE)
    if not content:
        print("❌ Impossible de lire le fichier")
        sys.exit(1)
    
    print("\n📝 Application des corrections...")
    
    # 3. Appliquer les corrections
    content = fix_imports(content)
    content = fix_member_relationships(content)
    content = fix_sanction_relationships(content)
    content = fix_transaction_relationships(content)
    content = fix_loan_relationships(content)
    content = fix_tontine_relationships(content)
    content = fix_user_relationship(content)
    content = fix_aide_relationships(content)
    content = add_missing_properties(content)
    content = fix_import_circular(content)
    
    # 4. Écrire le fichier corrigé
    if write_file(MODELS_FILE, content):
        print("\n" + "=" * 60)
        print("✅ models.py corrigé avec succès!")
        print("=" * 60)
        print("\n📌 Prochaines étapes:")
        print("   1. Vérifiez qu'il n'y a pas d'erreurs: python -m py_compile models.py")
        print("   2. Redémarrez l'application: python run.py")
        print("   3. Si des erreurs persistent, restaurez la sauvegarde:")
        print(f"      cp {MODELS_FILE}{BACKUP_SUFFIX} {MODELS_FILE}")
    else:
        print("❌ Erreur lors de l'écriture du fichier")
        sys.exit(1)

if __name__ == "__main__":
    main()
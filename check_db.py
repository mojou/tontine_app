# check_db.py
from app import app, db
from sqlalchemy import inspect

with app.app_context():
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    
    print("=" * 60)
    print("📊 TABLES DANS LA BASE DE DONNÉES")
    print("=" * 60)
    
    required_tables = [
        'users', 'members', 'transactions', 'loans', 'loan_repayments',
        'sanctions', 'attendances', 'announcements', 'agenda_items',
        'meeting_beneficiaries', 'meeting_attendance_details', 'aides',
        'tontine_cycles', 'tontine_positions', 'tontine_cycle_details',
        'cycle_beneficiaries', 'contribution_planning', 'cycle_reports',
        'caisse_balances', 'audit_logs'
    ]
    
    for table in required_tables:
        if table in tables:
            columns = inspector.get_columns(table)
            print(f"\n✅ Table '{table}' : {len(columns)} colonnes")
            for col in columns[:5]:  # Affiche les 5 premières colonnes
                print(f"   - {col['name']}: {col['type']}")
            if len(columns) > 5:
                print(f"   ... et {len(columns) - 5} autres colonnes")
        else:
            print(f"\n❌ Table '{table}' MANQUANTE !")
    
    print("\n" + "=" * 60)
    print(f"✅ Total: {len(tables)} tables trouvées")
# ============================================================
# MISE À NIVEAU LÉGÈRE DU SCHÉMA (SQLite)
# ============================================================
# db.create_all() crée les tables manquantes mais n'ajoute jamais de colonne
# à une table existante. Cette fonction ajoute les colonnes FACULTATIVES
# (nullable) déclarées dans les modèles et absentes de la base.
# Elle ne supprime ni ne modifie jamais rien ; une colonne obligatoire
# manquante provoque une erreur explicite (migration manuelle nécessaire).

from sqlalchemy import inspect, text


def add_missing_columns(engine, metadata, log=print):
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    added = []
    with engine.begin() as conn:
        for table in metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            present = {c['name'] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in present:
                    continue
                if not column.nullable:
                    raise RuntimeError(
                        f"Colonne obligatoire manquante {table.name}.{column.name} : migration manuelle nécessaire."
                    )
                col_type = column.type.compile(dialect=engine.dialect)
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'
                fks = list(column.foreign_keys)
                if fks:
                    target = fks[0].column
                    ddl += f' REFERENCES "{target.table.name}" ("{target.name}")'
                conn.execute(text(ddl))
                added.append(f'{table.name}.{column.name}')
    if added:
        log(f"[INFO] Colonnes ajoutées à la base : {', '.join(added)}")
    return added

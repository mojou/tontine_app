# extensions.py
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def utcnow():
    """Date-heure UTC « naïve » (même valeur qu'auparavant), sans l'API dépréciée datetime.utcnow()"""
    return datetime.now(timezone.utc).replace(tzinfo=None)

# ============================================================
# MULTI-TENANT : isolation des données par tontine
# ============================================================
#
# Chaque table métier porte une colonne `tontine_id` (via TenantMixin).
# Pendant une requête HTTP, la tontine courante est stockée dans `g.tenant_id`
# (posée par app.before_request à partir de l'utilisateur connecté, ou de
# l'URL /t/<slug> pour les pages publiques).
#
#  - Toute lecture ORM (Model.query..., db.session.query(...), get(), relations,
#    UPDATE/DELETE en masse) reçoit automatiquement le filtre
#    `tontine_id == g.tenant_id`.
#  - Tout nouvel objet reçoit automatiquement `tontine_id = g.tenant_id`.
#
# Pendant une requête sans tontine (visiteur anonyme, super-admin), le filtre
# devient `tontine_id == -1` : aucune donnée métier n'est visible (fermé par défaut).
# Hors requête (scripts, démarrage), aucun filtre n'est appliqué.
# Pour lire volontairement toutes les tontines : `with tenant_bypass(): ...`

from contextlib import contextmanager

from flask import g, has_request_context
from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from extensions import db

NO_TENANT = -1


class TenantMixin:
    """À hériter par tous les modèles dont les données appartiennent à une tontine."""

    # Si True, un objet peut être créé sans tontine (ex. journal d'audit du super-admin)
    __tenant_optional__ = False

    @db.declared_attr
    def tontine_id(cls):
        return db.Column(db.Integer, db.ForeignKey('tontines.id'), nullable=False, index=True)


def current_tenant_id():
    """Tontine courante : int, NO_TENANT (requête sans tontine) ou None (pas de filtre)."""
    if not has_request_context():
        return None
    if g.get('tenant_bypass'):
        return None
    tid = g.get('tenant_id')
    return tid if tid else NO_TENANT


def set_current_tenant(tontine_id):
    g.tenant_id = tontine_id


@contextmanager
def tenant_bypass():
    """Désactive temporairement le filtrage (super-admin, statistiques globales)."""
    previous = g.get('tenant_bypass', False)
    g.tenant_bypass = True
    try:
        yield
    finally:
        g.tenant_bypass = previous


@event.listens_for(Session, 'do_orm_execute')
def _add_tenant_criteria(execute_state):
    if not (execute_state.is_select or execute_state.is_update or execute_state.is_delete):
        return
    # Les chargements de relations / colonnes héritent déjà du critère de la requête
    # d'origine (propagation de with_loader_criteria) : motif recommandé par SQLAlchemy.
    if execute_state.is_column_load or execute_state.is_relationship_load:
        return
    tid = current_tenant_id()
    if tid is None:
        return
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            TenantMixin,
            lambda cls: cls.tontine_id == tid,
            include_aliases=True,
        )
    )


@event.listens_for(Session, 'before_flush')
def _assign_tenant(session, flush_context, instances):
    tid = current_tenant_id()
    for obj in session.new:
        if not isinstance(obj, TenantMixin) or obj.tontine_id is not None:
            continue
        if tid is None or tid == NO_TENANT:
            if obj.__tenant_optional__:
                continue
            raise RuntimeError(
                f"Impossible d'enregistrer {type(obj).__name__} sans tontine : "
                "aucune tontine courante (définissez tontine_id explicitement)."
            )
        obj.tontine_id = tid

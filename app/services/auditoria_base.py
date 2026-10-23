"""Consulta del historial automatico de cambios a la base (migrations/0092).

Los triggers de la base registran TODO cambio a dinero y stock; lo que importa para el negocio
son los hechos por fuera de la aplicacion (Excel, SSMS, cualquier programa conectado con la clave
de la base), que se saltan permisos y auditoria de la app. Este servicio los cuenta/lista para la
campana de notificaciones y la revision de un administrador.
"""

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import AuditoriaCambioDB
from app.services.permisos import require_permiso


class AuditoriaBaseService:
    @staticmethod
    def contar_cambios_fuera_de_la_app(session: Session, horas: int = 24) -> int:
        """Sin require_permiso: solo la usa la campana, que ya filtra por 'auditoria'/'ver'."""
        desde = datetime.now() - timedelta(hours=horas)
        return (
            session.query(func.count(AuditoriaCambioDB.id_cambio))
            .filter(AuditoriaCambioDB.fuera_de_la_app == True, AuditoriaCambioDB.fecha >= desde)  # noqa: E712 -- BIT
            .scalar()
            or 0
        )

    @staticmethod
    def listar_cambios(
        session: Session,
        id_usuario: int | None,
        solo_fuera_de_la_app: bool = False,
        tabla: str | None = None,
        limite: int = 200,
    ) -> list[AuditoriaCambioDB]:
        require_permiso(session, id_usuario, "auditoria", "ver")
        query = session.query(AuditoriaCambioDB)
        if solo_fuera_de_la_app:
            query = query.filter(AuditoriaCambioDB.fuera_de_la_app == True)  # noqa: E712 -- BIT
        if tabla:
            query = query.filter(AuditoriaCambioDB.tabla == tabla)
        return query.order_by(AuditoriaCambioDB.fecha.desc(), AuditoriaCambioDB.id_cambio.desc()).limit(limite).all()

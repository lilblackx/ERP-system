import json
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.db.models import Auditoria

# Modulos/acciones esperados para los eventos criticos descritos en la tarea; el campo
# es VARCHAR libre en la BD, esta lista es solo una guia para mantener consistencia.
MODULOS_SUGERIDOS = {"AUTH", "CAJAS", "VENTAS", "TASAS"}


class AuditoriaService:
    @staticmethod
    def registrar_evento(
        session: Session,
        id_usuario: int | None,
        accion: str,
        modulo: str,
        detalle: str | dict | None = None,
    ) -> Auditoria:
        if not accion:
            raise ValueError("accion es requerida")
        if not modulo:
            raise ValueError("modulo es requerido")

        detalle_texto = json.dumps(detalle, default=str, ensure_ascii=False) if isinstance(detalle, dict) else detalle

        evento = Auditoria(
            id_usuario=id_usuario,
            accion=accion,
            modulo=modulo,
            detalle=detalle_texto,
            fecha_evento=datetime.now(),
        )
        session.add(evento)
        session.commit()
        session.refresh(evento)
        return evento

    @staticmethod
    def consultar_auditoria(
        session: Session,
        fecha_desde: date | datetime | None = None,
        fecha_hasta: date | datetime | None = None,
        id_usuario: int | None = None,
        modulo: str | None = None,
        accion: str | None = None,
        pagina: int = 1,
        por_pagina: int = 50,
        id_usuario_actor: int | None = None,
    ) -> dict:
        # Import diferido (no al tope del modulo) para evitar un ciclo: permisos.py
        # importa AuditoriaService para loguear sus propios eventos, asi que
        # auditoria.py no puede importar permisos.py al cargar el modulo.
        from app.services.permisos import require_permiso

        require_permiso(session, id_usuario_actor, "auditoria", "ver")
        query = session.query(Auditoria)
        if fecha_desde:
            query = query.filter(Auditoria.fecha_evento >= fecha_desde)
        if fecha_hasta:
            query = query.filter(Auditoria.fecha_evento <= fecha_hasta)
        if id_usuario:
            query = query.filter(Auditoria.id_usuario == id_usuario)
        if modulo:
            query = query.filter(Auditoria.modulo == modulo)
        if accion:
            query = query.filter(Auditoria.accion == accion)

        total = query.count()
        eventos = (
            query.order_by(Auditoria.fecha_evento.desc()).offset((pagina - 1) * por_pagina).limit(por_pagina).all()
        )
        return {"items": eventos, "total": total, "pagina": pagina, "por_pagina": por_pagina}

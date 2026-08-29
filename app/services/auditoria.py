import json
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.db.models import Auditoria, Usuario

# Modulos que efectivamente llaman a registrar_evento() hoy (grep de `modulo="..."` en
# app/services/*.py). El campo es VARCHAR libre en la BD -- este set no se enforce alli --
# pero AuditoriaPanel (app/ui/auditoria_panel.py) lo usa para poblar el combo de filtro
# "Modulo", asi que hay que mantenerlo en sync si se agrega un modulo nuevo.
MODULOS_SUGERIDOS = {
    "AUTH",
    "BANCOS",
    "CAJAS",
    "CLIENTES",
    "COMISIONES",
    "COMPRAS",
    "EMPRESA",
    "INVENTARIO",
    "NOTAS_CREDITO",
    "OTROS_MOVIMIENTOS",
    "PERMISOS",
    "PROVEEDORES",
    "TASAS",
    "TESORERIA",
    "USUARIOS",
    "VENDEDORES",
    "VENTAS",
}


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
        texto_busqueda: str | None = None,
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
        if texto_busqueda:
            # Busqueda libre para AuditoriaPanel (app/ui/auditoria_panel.py): antes la
            # barra de busqueda solo filtraba `accion` con coincidencia exacta (habia que
            # saber de memoria el string "LOGIN"/"CREAR_CLIENTE"/etc, inutilizable para un
            # usuario que no conoce el modelo de datos -- hallazgo del usuario, 2026-08-28).
            # `accion`/`modulo` siguen disponibles arriba para filtros exactos (los combos
            # del panel), esto es un OR parcial case-insensitive sobre accion/modulo/detalle
            # y el nombre de usuario. `Auditoria.usuario.has(...)` genera un EXISTS
            # correlacionado -- funciona bien con id_usuario NULL (eventos de sistema) sin
            # necesitar un JOIN explicito que duplicaria filas.
            patron = f"%{texto_busqueda}%"
            query = query.filter(
                Auditoria.accion.ilike(patron)
                | Auditoria.modulo.ilike(patron)
                | Auditoria.detalle.ilike(patron)
                | Auditoria.usuario.has(Usuario.nombre_usuario.ilike(patron))
            )

        total = query.count()
        eventos = (
            query.order_by(Auditoria.fecha_evento.desc()).offset((pagina - 1) * por_pagina).limit(por_pagina).all()
        )
        return {"items": eventos, "total": total, "pagina": pagina, "por_pagina": por_pagina}

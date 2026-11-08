import json
from datetime import date, datetime

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.db.models import Auditoria, Usuario
from app.services.busqueda_sql import contiene, patron_contiene
from app.services.paginacion import paginar

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
            # y el nombre de usuario. Los usuarios que coinciden se resuelven UNA vez (tabla chica) y se
            # compara por id_usuario: un EXISTS correlacionado (`Auditoria.usuario.has(...)`) se evaluaba por
            # cada fila de la bitacora, que es la tabla que mas crece. id_usuario NULL (eventos de sistema)
            # simplemente no coincide por esa rama.
            patron = patron_contiene(texto_busqueda)
            usuarios_que_coinciden = session.query(Usuario.id_usuario).filter(
                contiene(session, Usuario.nombre_usuario, patron)
            )
            query = query.filter(
                contiene(session, Auditoria.accion, patron)
                | contiene(session, Auditoria.modulo, patron)
                | contiene(session, Auditoria.detalle, patron)
                | Auditoria.id_usuario.in_(usuarios_que_coinciden)
            )

        return paginar(query, pagina, por_pagina, Auditoria.fecha_evento.desc(), Auditoria.id_auditoria.desc())

    @staticmethod
    def consultar_auditoria_producto(
        session: Session,
        producto_id: int | None = None,
        accion: str | None = None,
        texto: str | None = None,
        fecha_desde: date | datetime | None = None,
        fecha_hasta: date | datetime | None = None,
        pagina: int = 1,
        por_pagina: int = 50,
    ) -> dict:
        """Eventos de auditoria del modulo INVENTARIO (los que muestra ProductoAuditoriaDialog), paginados, mas
        `por_accion` con el conteo de TODO lo que cumple los filtros (no solo la pagina) para el resumen. El filtro
        por producto compara el `"id_producto": N` del detalle con su terminador (`,` o `}`): sin el, buscar el
        producto 12 traia tambien los eventos del 123. `texto` filtra por coincidencia en el detalle (donde viene el
        nombre del producto) en la base: antes se traia todo y se filtraba en Python."""
        query = session.query(Auditoria).filter(Auditoria.modulo == "INVENTARIO")
        if producto_id:
            id_producto = int(producto_id)
            query = query.filter(
                or_(
                    Auditoria.detalle.like(f'%"id_producto": {id_producto},%'),
                    Auditoria.detalle.like(f'%"id_producto": {id_producto}}}%'),
                    Auditoria.detalle.like(f"%(ID: {id_producto})%"),
                )
            )
        if accion:
            query = query.filter(Auditoria.accion == accion)
        if texto:
            query = query.filter(contiene(session, Auditoria.detalle, patron_contiene(texto)))
        if fecha_desde:
            query = query.filter(Auditoria.fecha_evento >= fecha_desde)
        if fecha_hasta:
            query = query.filter(Auditoria.fecha_evento <= fecha_hasta)

        conteos = (
            query.with_entities(Auditoria.accion, func.count(Auditoria.id_auditoria))
            .group_by(Auditoria.accion)
            .order_by(None)
            .all()
        )
        resultado = paginar(
            query.options(joinedload(Auditoria.usuario)),
            pagina,
            por_pagina,
            Auditoria.fecha_evento.desc(),
            Auditoria.id_auditoria.desc(),
        )
        resultado["por_accion"] = {nombre: cantidad for nombre, cantidad in conteos}
        return resultado

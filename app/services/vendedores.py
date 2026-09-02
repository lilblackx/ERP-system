from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Cliente, FacturaVenta, Ruta, Vendedor
from app.services.auditoria import AuditoriaService
from app.services.permisos import require_permiso

ESTADOS_VALIDOS = {"ACTIVO", "INACTIVO"}


def _validar_unico(session: Session, campo: str, valor: str, excluir_id: int | None = None) -> None:
    query = session.query(Vendedor).filter(getattr(Vendedor, campo) == valor)
    if excluir_id is not None:
        query = query.filter(Vendedor.id_vendedor != excluir_id)
    if query.first() is not None:
        raise ValueError(f"Ya existe un vendedor con {campo}='{valor}'")


def _validar_ruta_activa(session: Session, id_ruta: int) -> None:
    """El combo de VendedorFormDialog solo ofrece rutas ACTIVO, pero eso no protege un
    llamado directo al servicio (script, futura integracion) -- sin esto se podia asignar
    un vendedor a una ruta ya desactivada sin ningun aviso (hallazgo de auditoria,
    2026-09-02)."""
    ruta = session.get(Ruta, id_ruta)
    if ruta is None:
        raise ValueError(f"id_ruta={id_ruta} no corresponde a una ruta existente")
    if (ruta.estado_ruta or "ACTIVO") != "ACTIVO":
        raise ValueError(f"La ruta '{ruta.nombre_ruta}' esta INACTIVA y no puede asignarse a un vendedor")


class VendedorService:
    @staticmethod
    def obtener(session: Session, id_vendedor: int, id_usuario: int | None = None) -> Vendedor | None:
        require_permiso(session, id_usuario, "vendedores", "ver")
        return session.get(Vendedor, id_vendedor)

    @staticmethod
    def listar(
        session: Session,
        texto_busqueda: str | None = None,
        id_usuario: int | None = None,
        estado_vendedor: str | None = None,
        pagina: int = 1,
        por_pagina: int = 20,
    ) -> dict:
        """D-01, mismo patron que ClienteService.list_clientes(): paginado real (antes
        devolvia un list[Vendedor] plano) para no traer todo el equipo de ventas a
        memoria a medida que crece -- hallazgo de auditoria Vendedores/Clientes,
        2026-08-27."""
        require_permiso(session, id_usuario, "vendedores", "ver")
        query = session.query(Vendedor)
        if texto_busqueda:
            like = f"%{texto_busqueda}%"
            query = query.filter(
                Vendedor.nombre_vendedor.ilike(like)
                | Vendedor.identificacion_vendedor.ilike(like)
                | Vendedor.codigo_vendedor.ilike(like)
            )
        if estado_vendedor:
            query = query.filter(Vendedor.estado_vendedor == estado_vendedor)
        query = query.order_by(Vendedor.nombre_vendedor)

        total = query.count()
        vendedores = query.offset((pagina - 1) * por_pagina).limit(por_pagina).all()
        return {"items": vendedores, "total": total, "pagina": pagina, "por_pagina": por_pagina}

    @staticmethod
    def crear(session: Session, **datos) -> Vendedor:
        require_permiso(session, datos.get("creado_por"), "vendedores", "crear")
        if not datos.get("nombre_vendedor"):
            raise ValueError("nombre_vendedor es requerido")
        # codigo_vendedor/identificacion_vendedor pasaron a ser obligatorios (decision del
        # usuario, 2026-09-01) -- mismo criterio que Cliente/Proveedor. El indice unico
        # filtrado de migrations/0031 (WHERE campo IS NOT NULL) sigue siendo valido aunque
        # ya no se esperen NULLs: no hace falta tocar el schema, el servicio es quien
        # garantiza que nunca lleguen vacios, igual que ya hacia ClienteService.
        if not datos.get("codigo_vendedor"):
            raise ValueError("codigo_vendedor es requerido")
        if not datos.get("identificacion_vendedor"):
            raise ValueError("identificacion_vendedor es requerido")
        # id_ruta obligatorio por decision de producto (2026-09-01): un vendedor siempre
        # pertenece a una ruta de reparto/cobranza. La columna sigue siendo NULLABLE en BD
        # (migrations/0038, mismo motivo que codigo_vendedor/identificacion_vendedor) --
        # este servicio es quien garantiza que nunca llegue vacio en una creacion nueva.
        if not datos.get("id_ruta"):
            raise ValueError("id_ruta es requerido")
        _validar_ruta_activa(session, datos["id_ruta"])
        _validar_unico(session, "codigo_vendedor", datos["codigo_vendedor"])
        _validar_unico(session, "identificacion_vendedor", datos["identificacion_vendedor"])

        vendedor = Vendedor(**datos)
        session.add(vendedor)
        session.commit()
        session.refresh(vendedor)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=vendedor.creado_por,
            accion="CREAR_VENDEDOR",
            modulo="VENDEDORES",
            detalle={"id_vendedor": vendedor.id_vendedor, "nombre_vendedor": vendedor.nombre_vendedor},
        )
        return vendedor

    @staticmethod
    def actualizar(session: Session, id_vendedor: int, id_usuario: int | None = None, **datos) -> Vendedor:
        require_permiso(session, id_usuario, "vendedores", "editar")
        vendedor = session.get(Vendedor, id_vendedor)
        if vendedor is None:
            raise ValueError("Vendedor no encontrado")

        if "nombre_vendedor" in datos and not datos["nombre_vendedor"]:
            raise ValueError("nombre_vendedor es requerido")
        if "codigo_vendedor" in datos and not datos["codigo_vendedor"]:
            raise ValueError("codigo_vendedor es requerido")
        if "identificacion_vendedor" in datos and not datos["identificacion_vendedor"]:
            raise ValueError("identificacion_vendedor es requerido")
        if "id_ruta" in datos and not datos["id_ruta"]:
            raise ValueError("id_ruta es requerido")
        if datos.get("id_ruta"):
            _validar_ruta_activa(session, datos["id_ruta"])

        nuevo_codigo = datos.get("codigo_vendedor")
        if nuevo_codigo and nuevo_codigo != vendedor.codigo_vendedor:
            _validar_unico(session, "codigo_vendedor", nuevo_codigo, excluir_id=id_vendedor)

        nueva_identificacion = datos.get("identificacion_vendedor")
        if nueva_identificacion and nueva_identificacion != vendedor.identificacion_vendedor:
            _validar_unico(session, "identificacion_vendedor", nueva_identificacion, excluir_id=id_vendedor)

        for campo, valor in datos.items():
            setattr(vendedor, campo, valor)
        session.commit()
        session.refresh(vendedor)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="ACTUALIZAR_VENDEDOR",
            modulo="VENDEDORES",
            detalle={"id_vendedor": vendedor.id_vendedor, "campos": list(datos.keys())},
        )
        return vendedor

    # Un vendedor nunca se borra fisicamente: FK_factura_venta_id_vendedor y
    # FK_usuarios_id_vendedor_usuario (ambas ON DELETE NO ACTION) hacen que borrar uno
    # con facturas asignadas o vinculado a un usuario reviente con un IntegrityError
    # crudo de pyodbc -- y aunque no tenga ninguna todavia, podria tenerlas despues, asi
    # que la politica es no permitir el DELETE nunca. Usar cambiar_estado(...,
    # "INACTIVO") para retirarlo de circulacion preservando el historial (la columna
    # estado_vendedor ya existia, pero nada la usaba). Decision de producto 2026-08-22
    # (hallazgo de auditoria del mismo dia).
    @staticmethod
    def eliminar(session: Session, id_vendedor: int, id_usuario: int | None = None) -> None:
        require_permiso(session, id_usuario, "vendedores", "eliminar")
        raise ValueError(
            "No se puede eliminar un vendedor para proteger la integridad de los datos. "
            "Use VendedorService.cambiar_estado() para desactivarlo."
        )

    @staticmethod
    def cambiar_estado(
        session: Session, id_vendedor: int, nuevo_estado: str, id_usuario: int | None = None
    ) -> Vendedor:
        require_permiso(session, id_usuario, "vendedores", "eliminar")
        if nuevo_estado not in ESTADOS_VALIDOS:
            raise ValueError(f"nuevo_estado debe ser uno de {ESTADOS_VALIDOS}")
        vendedor = session.get(Vendedor, id_vendedor)
        if vendedor is None:
            raise ValueError("Vendedor no encontrado")

        vendedor.estado_vendedor = nuevo_estado
        session.commit()
        session.refresh(vendedor)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="CAMBIAR_ESTADO_VENDEDOR",
            modulo="VENDEDORES",
            detalle={"id_vendedor": vendedor.id_vendedor, "nuevo_estado": nuevo_estado},
        )
        return vendedor

    @staticmethod
    def obtener_desempeno_mes(
        session: Session, id_vendedor: int, anio: int, mes: int, id_usuario: int | None = None
    ) -> dict:
        require_permiso(session, id_usuario, "vendedores", "ver")
        vendedor = session.get(Vendedor, id_vendedor)
        if vendedor is None:
            raise ValueError("Vendedor no encontrado")

        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)

        filtros_periodo = (
            FacturaVenta.id_vendedor == id_vendedor,
            FacturaVenta.fecha_emision >= fecha_inicio,
            FacturaVenta.fecha_emision < fecha_fin,
            FacturaVenta.estado_factura != "ANULADA",
        )

        total_vendido = (
            session.query(func.coalesce(func.sum(FacturaVenta.total_venta), 0)).filter(*filtros_periodo).scalar()
        )

        cantidad_facturas = session.query(func.count(FacturaVenta.id_factura)).filter(*filtros_periodo).scalar()

        total_clientes_asignados = (
            session.query(func.count(Cliente.id_cliente)).filter(Cliente.vendedor_cliente == id_vendedor).scalar()
        )

        return {
            "id_vendedor": id_vendedor,
            "nombre_vendedor": vendedor.nombre_vendedor,
            "estado_vendedor": vendedor.estado_vendedor,
            "anio": anio,
            "mes": mes,
            "total_vendido": total_vendido,
            "cantidad_facturas": cantidad_facturas,
            "total_clientes_asignados": total_clientes_asignados,
        }

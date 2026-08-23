from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Cliente, FacturaVenta, Vendedor
from app.services.auditoria import AuditoriaService
from app.services.permisos import require_permiso

ESTADOS_VALIDOS = {"ACTIVO", "INACTIVO"}


class VendedorService:
    @staticmethod
    def obtener(session: Session, id_vendedor: int, id_usuario: int | None = None) -> Vendedor | None:
        require_permiso(session, id_usuario, "vendedores", "ver")
        return session.get(Vendedor, id_vendedor)

    @staticmethod
    def listar(session: Session, texto_busqueda: str | None = None, id_usuario: int | None = None) -> list[Vendedor]:
        require_permiso(session, id_usuario, "vendedores", "ver")
        query = session.query(Vendedor)
        if texto_busqueda:
            like = f"%{texto_busqueda}%"
            query = query.filter(
                Vendedor.nombre_vendedor.ilike(like)
                | Vendedor.identificacion_vendedor.ilike(like)
                | Vendedor.codigo_vendedor.ilike(like)
            )
        return query.order_by(Vendedor.nombre_vendedor).all()

    @staticmethod
    def crear(session: Session, **datos) -> Vendedor:
        require_permiso(session, datos.get("creado_por"), "vendedores", "crear")
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

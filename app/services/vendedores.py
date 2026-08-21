from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Cliente, FacturaVenta, Vendedor
from app.services.auditoria import AuditoriaService


class VendedorService:
    @staticmethod
    def obtener(session: Session, id_vendedor: int) -> Vendedor | None:
        return session.get(Vendedor, id_vendedor)

    @staticmethod
    def listar(session: Session, texto_busqueda: str | None = None) -> list[Vendedor]:
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

    @staticmethod
    def eliminar(session: Session, id_vendedor: int, id_usuario: int | None = None) -> None:
        vendedor = session.get(Vendedor, id_vendedor)
        if vendedor is None:
            return
        detalle = {"id_vendedor": vendedor.id_vendedor, "nombre_vendedor": vendedor.nombre_vendedor}
        session.delete(vendedor)
        session.commit()

        AuditoriaService.registrar_evento(
            session, id_usuario=id_usuario, accion="ELIMINAR_VENDEDOR", modulo="VENDEDORES", detalle=detalle
        )

    @staticmethod
    def obtener_desempeno_mes(session: Session, id_vendedor: int, anio: int, mes: int) -> dict:
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

        total_vendido = session.query(func.coalesce(func.sum(FacturaVenta.total_venta), 0)).filter(
            *filtros_periodo
        ).scalar()

        cantidad_facturas = session.query(func.count(FacturaVenta.id_factura)).filter(*filtros_periodo).scalar()

        total_clientes_asignados = (
            session.query(func.count(Cliente.id_cliente))
            .filter(Cliente.vendedor_cliente == id_vendedor)
            .scalar()
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

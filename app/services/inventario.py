from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import Inventario, ProductoPrecio
from app.services.auditoria import AuditoriaService

TIPOS_PRECIO_VALIDOS = {"DETAL", "MAYOR", "ESPECIAL"}


class ProductoService:
    @staticmethod
    def _validar_codigo_unico(session: Session, cod_producto: str, excluir_id: int | None = None) -> None:
        query = session.query(Inventario).filter(Inventario.cod_producto == cod_producto)
        if excluir_id is not None:
            query = query.filter(Inventario.id_producto != excluir_id)
        if query.first() is not None:
            raise ValueError(f"El codigo de producto '{cod_producto}' ya esta en uso")

    @staticmethod
    def obtener(session: Session, id_producto: int) -> Inventario | None:
        return session.get(Inventario, id_producto)

    @staticmethod
    def crear(session: Session, **datos) -> Inventario:
        cod_producto = datos.get("cod_producto")
        if not cod_producto:
            raise ValueError("cod_producto es requerido")
        ProductoService._validar_codigo_unico(session, cod_producto)
        producto = Inventario(**datos)
        session.add(producto)
        session.commit()
        session.refresh(producto)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=producto.creado_por,
            accion="CREAR_PRODUCTO",
            modulo="INVENTARIO",
            detalle={"id_producto": producto.id_producto, "cod_producto": producto.cod_producto},
        )
        return producto

    @staticmethod
    def actualizar(session: Session, id_producto: int, id_usuario: int | None = None, **datos) -> Inventario:
        producto = session.get(Inventario, id_producto)
        if producto is None:
            raise ValueError("Producto no encontrado")
        nuevo_codigo = datos.get("cod_producto")
        if nuevo_codigo and nuevo_codigo != producto.cod_producto:
            ProductoService._validar_codigo_unico(session, nuevo_codigo, excluir_id=id_producto)
        for campo, valor in datos.items():
            setattr(producto, campo, valor)
        session.commit()
        session.refresh(producto)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="ACTUALIZAR_PRODUCTO",
            modulo="INVENTARIO",
            detalle={"id_producto": producto.id_producto, "campos": list(datos.keys())},
        )
        return producto

    @staticmethod
    def eliminar(session: Session, id_producto: int, id_usuario: int | None = None) -> None:
        producto = session.get(Inventario, id_producto)
        if producto is None:
            return
        detalle = {"id_producto": producto.id_producto, "cod_producto": producto.cod_producto}
        session.delete(producto)
        session.commit()

        AuditoriaService.registrar_evento(
            session, id_usuario=id_usuario, accion="ELIMINAR_PRODUCTO", modulo="INVENTARIO", detalle=detalle
        )

    @staticmethod
    def buscar(
        session: Session,
        codigo: str | None = None,
        nombre: str | None = None,
        id_categoria: int | None = None,
        solo_con_stock: bool = False,
    ) -> list[Inventario]:
        query = session.query(Inventario)
        if codigo:
            query = query.filter(Inventario.cod_producto.ilike(f"%{codigo}%"))
        if nombre:
            query = query.filter(Inventario.nombre_producto.ilike(f"%{nombre}%"))
        if id_categoria:
            query = query.filter(Inventario.id_categoria == id_categoria)
        if solo_con_stock:
            query = query.filter(Inventario.cantidad_unidad > 0)
        return query.order_by(Inventario.nombre_producto).all()

    @staticmethod
    def obtener_alertas_stock(
        session: Session, limite_minimo: int = 10, dias_vencimiento: int = 30
    ) -> dict[str, list[Inventario]]:
        hoy = date.today()
        limite_fecha = hoy + timedelta(days=dias_vencimiento)
        bajo_stock = (
            session.query(Inventario)
            .filter(Inventario.cantidad_unidad <= limite_minimo)
            .order_by(Inventario.cantidad_unidad)
            .all()
        )
        proximos_vencer = (
            session.query(Inventario)
            .filter(Inventario.fecha_vencimiento.isnot(None), Inventario.fecha_vencimiento <= limite_fecha)
            .order_by(Inventario.fecha_vencimiento)
            .all()
        )
        return {"bajo_stock": bajo_stock, "proximos_vencer": proximos_vencer}


class PrecioService:
    @staticmethod
    def _calcular_margen(costo: Decimal, precio_venta: Decimal) -> Decimal:
        if not costo:
            return Decimal("0.00")
        margen = (precio_venta - costo) / costo * Decimal("100")
        return margen.quantize(Decimal("0.01"))

    @staticmethod
    def listar_precios(session: Session, id_producto: int) -> list[ProductoPrecio]:
        return (
            session.query(ProductoPrecio)
            .filter(ProductoPrecio.id_producto == id_producto)
            .order_by(ProductoPrecio.tipo_precio)
            .all()
        )

    @staticmethod
    def establecer_precio(
        session: Session, id_producto: int, tipo_precio: str, precio_venta, id_usuario: int | None = None
    ) -> ProductoPrecio:
        if tipo_precio not in TIPOS_PRECIO_VALIDOS:
            raise ValueError(f"tipo_precio invalido: {tipo_precio}")
        producto = session.get(Inventario, id_producto)
        if producto is None:
            raise ValueError("Producto no encontrado")

        precio_venta = Decimal(str(precio_venta))
        margen = PrecioService._calcular_margen(producto.costo_producto, precio_venta)

        precio = (
            session.query(ProductoPrecio)
            .filter(ProductoPrecio.id_producto == id_producto, ProductoPrecio.tipo_precio == tipo_precio)
            .first()
        )
        if precio is None:
            precio = ProductoPrecio(
                id_producto=id_producto,
                tipo_precio=tipo_precio,
                precio_venta=precio_venta,
                porcentaje_ganancia=margen,
            )
            session.add(precio)
        else:
            precio.precio_venta = precio_venta
            precio.porcentaje_ganancia = margen

        session.commit()
        session.refresh(precio)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="CAMBIO_PRECIO",
            modulo="INVENTARIO",
            detalle={
                "id_producto": id_producto,
                "tipo_precio": tipo_precio,
                "precio_venta": str(precio.precio_venta),
                "porcentaje_ganancia": str(precio.porcentaje_ganancia),
            },
        )
        return precio

    @staticmethod
    def eliminar_precio(session: Session, id_producto_precio: int, id_usuario: int | None = None) -> None:
        precio = session.get(ProductoPrecio, id_producto_precio)
        if precio is None:
            return
        detalle = {"id_producto": precio.id_producto, "tipo_precio": precio.tipo_precio}
        session.delete(precio)
        session.commit()

        AuditoriaService.registrar_evento(
            session, id_usuario=id_usuario, accion="ELIMINAR_PRECIO", modulo="INVENTARIO", detalle=detalle
        )

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import Inventario, ProductoPrecio
from app.services.auditoria import AuditoriaService
from app.services.permisos import require_permiso

TIPOS_PRECIO_VALIDOS = {"DETAL", "MAYOR", "ESPECIAL"}
ESTADOS_VALIDOS = {"ACTIVO", "INACTIVO"}


class ProductoService:
    @staticmethod
    def _validar_codigo_unico(session: Session, cod_producto: str, excluir_id: int | None = None) -> None:
        query = session.query(Inventario).filter(Inventario.cod_producto == cod_producto)
        if excluir_id is not None:
            query = query.filter(Inventario.id_producto != excluir_id)
        if query.first() is not None:
            raise ValueError(f"El codigo de producto '{cod_producto}' ya esta en uso")

    @staticmethod
    def obtener(session: Session, id_producto: int, id_usuario: int | None = None) -> Inventario | None:
        require_permiso(session, id_usuario, "inventario", "ver")
        return session.get(Inventario, id_producto)

    @staticmethod
    def crear(session: Session, **datos) -> Inventario:
        require_permiso(session, datos.get("creado_por"), "inventario", "crear")
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
        require_permiso(session, id_usuario, "inventario", "editar")
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

    # Un producto nunca se borra fisicamente: FK_factura_detalle_id_producto_factura,
    # FK_compra_detalle_id_producto_compra y FK_producto_precios_id_producto (todas
    # ON DELETE NO ACTION) hacen que borrar uno ya vendido/comprado reviente con un
    # IntegrityError crudo de pyodbc -- y aunque no tenga movimientos todavia, podria
    # tenerlos despues, asi que la politica es no permitir el DELETE nunca. Usar
    # cambiar_estado(..., "INACTIVO") para retirarlo de circulacion preservando el
    # historial. Decision de producto 2026-08-22 (hallazgo de auditoria del mismo dia).
    @staticmethod
    def eliminar(session: Session, id_producto: int, id_usuario: int | None = None) -> None:
        require_permiso(session, id_usuario, "inventario", "eliminar")
        raise ValueError(
            "No se puede eliminar un producto para proteger la integridad de los datos. "
            "Use ProductoService.cambiar_estado() para desactivarlo."
        )

    @staticmethod
    def cambiar_estado(
        session: Session, id_producto: int, nuevo_estado: str, id_usuario: int | None = None
    ) -> Inventario:
        require_permiso(session, id_usuario, "inventario", "eliminar")
        if nuevo_estado not in ESTADOS_VALIDOS:
            raise ValueError(f"nuevo_estado debe ser uno de {ESTADOS_VALIDOS}")
        producto = session.get(Inventario, id_producto)
        if producto is None:
            raise ValueError("Producto no encontrado")

        producto.estado_producto = nuevo_estado
        session.commit()
        session.refresh(producto)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="CAMBIAR_ESTADO_PRODUCTO",
            modulo="INVENTARIO",
            detalle={"id_producto": producto.id_producto, "nuevo_estado": nuevo_estado},
        )
        return producto

    @staticmethod
    def buscar(
        session: Session,
        codigo: str | None = None,
        nombre: str | None = None,
        id_categoria: int | None = None,
        solo_con_stock: bool = False,
        id_usuario: int | None = None,
    ) -> list[Inventario]:
        require_permiso(session, id_usuario, "inventario", "ver")
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
        session: Session, limite_minimo: int = 10, dias_vencimiento: int = 30, id_usuario: int | None = None
    ) -> dict[str, list[Inventario]]:
        require_permiso(session, id_usuario, "inventario", "ver")
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
    def listar_precios(session: Session, id_producto: int, id_usuario: int | None = None) -> list[ProductoPrecio]:
        require_permiso(session, id_usuario, "inventario", "ver")
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
        require_permiso(session, id_usuario, "inventario", "editar")
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
        require_permiso(session, id_usuario, "inventario", "eliminar")
        precio = session.get(ProductoPrecio, id_producto_precio)
        if precio is None:
            return
        detalle = {"id_producto": precio.id_producto, "tipo_precio": precio.tipo_precio}
        session.delete(precio)
        session.commit()

        AuditoriaService.registrar_evento(
            session, id_usuario=id_usuario, accion="ELIMINAR_PRECIO", modulo="INVENTARIO", detalle=detalle
        )

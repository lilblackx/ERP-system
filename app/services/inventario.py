from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db.models import Inventario, ProductoPrecio
from app.services.auditoria import AuditoriaService
from app.services.permisos import require_permiso
from app.utils.decimal_utils import to_decimal

ESTADOS_VALIDOS = {"ACTIVO", "INACTIVO"}
# C14: un solo precio de lista por producto (antes hasta 3, DETAL/MAYOR/ESPECIAL) -- ver
# migrations/0011_consolidar_producto_precios.sql. tipo_precio se conserva en el schema
# con este unico valor fijo en vez de borrar la columna (append-only, no se edita el
# schema ya creado).
TIPO_PRECIO_UNICO = "UNICO"


def _escapar_like(texto: str) -> str:
    """Escapa caracteres especiales en búsquedas LIKE: % y _ son wildcards,
    necesitan escape para búsquedas literales. Sin esto, una búsqueda de '%' devuelve
    todos los registros, '%_' devuelve cualquier registro con N caracteres, etc."""
    return texto.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


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
        if not datos.get("nombre_producto"):
            raise ValueError("nombre_producto es requerido")
        if not datos.get("id_categoria"):
            raise ValueError("id_categoria es requerido")
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
        if "nombre_producto" in datos and not datos["nombre_producto"]:
            raise ValueError("nombre_producto es requerido")
        if "id_categoria" in datos and not datos["id_categoria"]:
            raise ValueError("id_categoria es requerido")
        nuevo_codigo = datos.get("cod_producto")
        if nuevo_codigo and nuevo_codigo != producto.cod_producto:
            ProductoService._validar_codigo_unico(session, nuevo_codigo, excluir_id=id_producto)

        # Capturar todos los valores anteriores antes de la actualización
        campos_auditoria = [
            "nombre_producto",
            "descripcion_producto",
            "cantidad_unidad",
            "cantidad_caja",
            "cantidad_minima",
            "costo_producto",
        ]
        valores_anteriores = {}
        for campo in campos_auditoria:
            if campo in datos:
                valores_anteriores[campo] = getattr(producto, campo, None)

        for campo, valor in datos.items():
            setattr(producto, campo, valor)
        session.commit()
        session.refresh(producto)

        # Registrar cambios específicos - solo lo que realmente cambió
        cambios_relevantes = []
        cambios_stock = []
        cambios_descripcion = []
        cambios_nombre = []

        for campo in datos.keys():
            if campo in campos_auditoria:
                valor_anterior = valores_anteriores.get(campo)
                valor_nuevo = datos[campo]

                # Solo registrar si realmente cambió
                if valor_anterior != valor_nuevo:
                    cambio = {
                        "campo": campo,
                        "valor_anterior": str(valor_anterior) if valor_anterior is not None else "None",
                        "valor_nuevo": str(valor_nuevo) if valor_nuevo is not None else "None",
                    }
                    cambios_relevantes.append(cambio)

                    # Movimientos de stock
                    if campo in ["cantidad_unidad", "cantidad_caja"]:
                        try:
                            valor_anterior_num = float(valor_anterior) if valor_anterior else 0
                            valor_nuevo_num = float(valor_nuevo) if valor_nuevo else 0
                            diferencia = valor_nuevo_num - valor_anterior_num
                            tipo_movimiento = "AUMENTO" if diferencia > 0 else "DISMINUCIÓN"

                            cambios_stock.append(
                                {
                                    "campo": campo,
                                    "valor_anterior": str(valor_anterior),
                                    "valor_nuevo": str(valor_nuevo),
                                    "diferencia": str(diferencia),
                                    "tipo_movimiento": tipo_movimiento,
                                }
                            )
                        except (ValueError, TypeError):
                            pass

                    # Cambios de descripción
                    elif campo == "descripcion_producto":
                        cambios_descripcion.append(
                            {
                                "campo": campo,
                                "valor_anterior": str(valor_anterior) if valor_anterior else "Sin descripción",
                                "valor_nuevo": str(valor_nuevo) if valor_nuevo else "Sin descripción",
                            }
                        )

                    # Cambios de nombre
                    elif campo == "nombre_producto":
                        cambios_nombre.append(
                            {"campo": campo, "valor_anterior": str(valor_anterior), "valor_nuevo": str(valor_nuevo)}
                        )

        # Registrar eventos específicos solo si hay cambios
        if cambios_stock:
            AuditoriaService.registrar_evento(
                session,
                id_usuario=id_usuario,
                accion="MOVIMIENTO_STOCK",
                modulo="INVENTARIO",
                detalle={
                    "id_producto": producto.id_producto,
                    "cod_producto": producto.cod_producto,
                    "movimientos": cambios_stock,
                },
            )

        if cambios_descripcion:
            AuditoriaService.registrar_evento(
                session,
                id_usuario=id_usuario,
                accion="CAMBIO_DESCRIPCION",
                modulo="INVENTARIO",
                detalle={
                    "id_producto": producto.id_producto,
                    "cod_producto": producto.cod_producto,
                    "cambios": cambios_descripcion,
                },
            )

        if cambios_nombre:
            AuditoriaService.registrar_evento(
                session,
                id_usuario=id_usuario,
                accion="CAMBIO_NOMBRE",
                modulo="INVENTARIO",
                detalle={
                    "id_producto": producto.id_producto,
                    "cod_producto": producto.cod_producto,
                    "cambios": cambios_nombre,
                },
            )

        # Registrar la actualización general solo con los campos que realmente cambiaron
        if cambios_relevantes:
            campos_modificados = [c["campo"] for c in cambios_relevantes]
            AuditoriaService.registrar_evento(
                session,
                id_usuario=id_usuario,
                accion="ACTUALIZAR_PRODUCTO",
                modulo="INVENTARIO",
                detalle={
                    "id_producto": producto.id_producto,
                    "campos": campos_modificados,
                    "cambios_relevantes": cambios_relevantes,
                },
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
        texto: str | None = None,
        codigo: str | None = None,
        nombre: str | None = None,
        id_categoria: int | None = None,
        solo_con_stock: bool = False,
        pagina: int = 1,
        por_pagina: int = 20,
        id_usuario: int | None = None,
    ) -> dict:
        """D-01: paginado igual que VentaService.listar_facturas() -- el catalogo puede
        crecer sin cota. `texto` busca por codigo O nombre a la vez (una sola caja de
        busqueda en la UI); `codigo`/`nombre` quedan aparte para filtros estructurados que
        SI deban acotar por columna especifica, no se pisan entre si."""
        require_permiso(session, id_usuario, "inventario", "ver")
        # joinedload(categoria): InventarioPanel muestra/exporta el nombre de categoria por
        # fila (auditoria de Productos 2026-08-28) -- sin esto cada fila dispara su propio
        # SELECT lazy al acceder a producto.categoria.nombre (N+1), agravado en la
        # exportacion (hasta 1_000_000 filas en una sola llamada).
        query = session.query(Inventario).options(joinedload(Inventario.categoria))
        if texto:
            like = f"%{_escapar_like(texto)}%"
            query = query.filter(
                Inventario.cod_producto.ilike(like, escape="\\") | Inventario.nombre_producto.ilike(like, escape="\\")
            )
        if codigo:
            query = query.filter(Inventario.cod_producto.ilike(f"%{_escapar_like(codigo)}%", escape="\\"))
        if nombre:
            query = query.filter(Inventario.nombre_producto.ilike(f"%{_escapar_like(nombre)}%", escape="\\"))
        if id_categoria:
            query = query.filter(Inventario.id_categoria == id_categoria)
        if solo_con_stock:
            query = query.filter(Inventario.cantidad_unidad > 0)

        total = query.count()
        productos = query.order_by(Inventario.nombre_producto).offset((pagina - 1) * por_pagina).limit(por_pagina).all()
        return {"items": productos, "total": total, "pagina": pagina, "por_pagina": por_pagina}

    @staticmethod
    def obtener_alertas_stock(
        session: Session, dias_vencimiento: int = 30, id_usuario: int | None = None
    ) -> dict[str, list[Inventario]]:
        require_permiso(session, id_usuario, "inventario", "ver")
        hoy = date.today()
        limite_fecha = hoy + timedelta(days=dias_vencimiento)
        # Un producto INACTIVO (descontinuado) no deberia seguir generando alertas para
        # siempre (C21) -- a diferencia de un listado general (buscar()), que si muestra
        # inactivos porque el usuario puede estar buscandolos a proposito.
        #
        # cantidad_minima=0 (default del producto) significa "sin minimo configurado" --
        # mismo criterio que ReporteService.stock_bajo_minimo (app/services/reportes.py):
        # antes esta funcion usaba un umbral fijo (10 unidades) igual para todos los
        # productos, ignorando por completo el "Stock Minimo" que se configura por
        # producto en producto_form_dialog.py -- un producto con minimo=5 y 37 en
        # existencia nunca deberia alertar, pero con el umbral fijo cualquiera con 10 o
        # menos unidades alertaba igual sin importar su propio minimo.
        bajo_stock = (
            session.query(Inventario)
            .filter(
                Inventario.cantidad_minima > 0,
                Inventario.cantidad_unidad < Inventario.cantidad_minima,
                Inventario.estado_producto == "ACTIVO",
            )
            .order_by(Inventario.cantidad_unidad)
            .all()
        )
        proximos_vencer = (
            session.query(Inventario)
            .filter(
                Inventario.fecha_vencimiento.isnot(None),
                Inventario.fecha_vencimiento <= limite_fecha,
                Inventario.estado_producto == "ACTIVO",
            )
            .order_by(Inventario.fecha_vencimiento)
            .all()
        )
        return {"bajo_stock": bajo_stock, "proximos_vencer": proximos_vencer}


class PrecioService:
    @staticmethod
    def _calcular_margen(costo: Decimal, precio_venta: Decimal) -> Decimal:
        costo = to_decimal(costo)
        precio_venta = to_decimal(precio_venta)
        if not costo:
            return Decimal("0.00")
        margen = (precio_venta - costo) / costo * Decimal("100")
        return margen.quantize(Decimal("0.01"))

    @staticmethod
    def establecer_precio(
        session: Session,
        id_producto: int,
        precio_1: float | Decimal | str,
        precio_2: float | Decimal | str | None = None,
        precio_3: float | Decimal | str | None = None,
        id_usuario: int | None = None,
    ) -> ProductoPrecio:
        require_permiso(session, id_usuario, "inventario", "editar")
        producto = session.get(Inventario, id_producto)
        if producto is None:
            raise ValueError("Producto no encontrado")
        if producto.estado_producto != "ACTIVO":
            raise ValueError(f"El producto '{producto.nombre_producto}' esta inactivo, no se puede modificar su precio")

        precio_1 = to_decimal(precio_1)
        precio_2 = to_decimal(precio_2) if precio_2 is not None else Decimal("0.00")
        precio_3 = to_decimal(precio_3) if precio_3 is not None else Decimal("0.00")
        margen = PrecioService._calcular_margen(producto.costo_producto, precio_1)

        # WITH (UPDLOCK, ROWLOCK): sin esto, dos ediciones de precio concurrentes sobre el
        # mismo producto pueden ambas ver "no existe fila" y ambas insertar -- dejando dos
        # filas para el mismo id_producto (la UNIQUE de migrations/0036 evitaria la
        # corrupcion silenciosa, pero la segunda terminaria en un IntegrityError crudo en
        # vez de aplicarse como el UPDATE que el usuario esperaba). Mismo patron que
        # pagos.py/ventas.py (C1/C18).
        precio = session.execute(
            select(ProductoPrecio)
            .where(ProductoPrecio.id_producto == id_producto)
            .with_hint(ProductoPrecio, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
        ).scalar_one_or_none()

        # Capturar valor anterior si existe
        precio_anterior = None
        precio_2_anterior = None
        precio_3_anterior = None
        margen_anterior = None
        es_nuevo = False
        if precio is not None:
            precio_anterior = precio.precio_1
            precio_2_anterior = precio.precio_2
            precio_3_anterior = precio.precio_3
            margen_anterior = precio.porcentaje_ganancia
        else:
            es_nuevo = True

        if precio is None:
            precio = ProductoPrecio(
                id_producto=id_producto,
                tipo_precio=TIPO_PRECIO_UNICO,
                precio_1=to_decimal(precio_1),
                precio_2=to_decimal(precio_2),
                precio_3=to_decimal(precio_3),
                porcentaje_ganancia=to_decimal(margen),
            )
            session.add(precio)
        else:
            # Solo actualizar si realmente cambió
            if (
                precio.precio_1 != precio_1
                or precio.precio_2 != precio_2
                or precio.precio_3 != precio_3
                or precio.porcentaje_ganancia != margen
            ):
                precio.precio_1 = to_decimal(precio_1)
                precio.precio_2 = to_decimal(precio_2)
                precio.precio_3 = to_decimal(precio_3)
                precio.porcentaje_ganancia = to_decimal(margen)
            else:
                # Si no hubo cambios, no registrar nada
                return precio

        session.commit()
        session.refresh(precio)

        # Registrar solo si hubo cambios reales
        cambios_precio = {}
        if es_nuevo:
            # Nuevo precio (creación) - registrar todos los valores
            cambios_precio["precio_1"] = {"anterior": None, "nuevo": str(precio.precio_1)}
            cambios_precio["precio_2"] = {"anterior": None, "nuevo": str(precio.precio_2)}
            cambios_precio["precio_3"] = {"anterior": None, "nuevo": str(precio.precio_3)}
            cambios_precio["margen"] = {"anterior": None, "nuevo": str(precio.porcentaje_ganancia)}
        else:
            # Actualización - registrar solo lo que cambió
            if precio_anterior is not None and precio_anterior != precio_1:
                cambios_precio["precio_1"] = {"anterior": str(precio_anterior), "nuevo": str(precio.precio_1)}
            if precio_2_anterior is not None and precio_2_anterior != precio_2:
                cambios_precio["precio_2"] = {"anterior": str(precio_2_anterior), "nuevo": str(precio.precio_2)}
            if precio_3_anterior is not None and precio_3_anterior != precio_3:
                cambios_precio["precio_3"] = {"anterior": str(precio_3_anterior), "nuevo": str(precio.precio_3)}
            if margen_anterior != margen:
                cambios_precio["margen"] = {"anterior": str(margen_anterior), "nuevo": str(precio.porcentaje_ganancia)}

        if cambios_precio:
            detalle = {
                "id_producto": id_producto,
                "cod_producto": producto.cod_producto,
                "cambios_precio": cambios_precio,
            }
            AuditoriaService.registrar_evento(
                session,
                id_usuario=id_usuario,
                accion="CAMBIO_PRECIO",
                modulo="INVENTARIO",
                detalle=detalle,
            )

        return precio

    @staticmethod
    def obtener_precio(session: Session, id_producto: int, id_usuario: int | None = None) -> ProductoPrecio | None:
        """Reemplaza el listar_precios() de antes de C14 -- a lo sumo 1 fila por producto
        ahora (ver TIPO_PRECIO_UNICO)."""
        require_permiso(session, id_usuario, "inventario", "ver")
        return session.query(ProductoPrecio).filter(ProductoPrecio.id_producto == id_producto).first()

    @staticmethod
    def establecer_precio_simple(
        session: Session, id_producto: int, precio_venta, id_usuario: int | None = None
    ) -> ProductoPrecio:
        """Método simple para compatibilidad con código existente - solo actualiza precio_1."""
        precio = PrecioService.obtener_precio(session, id_producto, id_usuario)
        if precio:
            precio_2_float = float(precio.precio_2) if precio.precio_2 is not None else None
            precio_3_float = float(precio.precio_3) if precio.precio_3 is not None else None
            return PrecioService.establecer_precio(
                session, id_producto, precio_venta, precio_2_float, precio_3_float, id_usuario
            )
        else:
            return PrecioService.establecer_precio(session, id_producto, precio_venta, None, None, id_usuario)

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

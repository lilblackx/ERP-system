from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.db.models import (
    BancoMovimiento,
    CajaMovimiento,
    ComisionFactura,
    CuentaPorCobrar,
    FacturaDetalle,
    FacturaVenta,
    NotaCreditoCliente,
    PagoCobro,
)
from app.services.empresa import EmpresaService
from app.services.pagos import PagoService
from app.services.permisos import PermisoDenegadoError
from app.services.tasas import TasaService
from app.services.tesoreria import CajaService
from app.services.ventas import VentaService
from tests.factories import (
    asignar_permiso,
    crear_caja,
    crear_cliente,
    crear_cuenta_bancaria,
    crear_permiso,
    crear_precio_producto,
    crear_producto,
    crear_rol,
    crear_usuario,
    crear_usuario_admin,
    crear_vendedor,
    pago_contado,
)


def test_emitir_factura_contado_descuenta_stock_y_calcula_total(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "20.00")
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db_session),
        items=[{"id_producto": producto.id_producto, "cantidad": 5, "precio_unitario": "20.00"}],
    )

    db_session.refresh(producto)
    assert producto.cantidad_unidad == Decimal("45.00")
    assert factura.total_venta == Decimal("100.00")


def test_emitir_factura_sin_usuario_autorizado_falla(db_session):
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    with pytest.raises(PermisoDenegadoError):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=None,
            id_vendedor=None,
            condicion_pago="contado",
            pagos=pago_contado(db_session),
            items=[{"id_producto": producto.id_producto, "cantidad": 5, "precio_unitario": "20.00"}],
        )


def test_emitir_factura_contado_sin_permiso_pagos_falla(db_session):
    """N4 (auditoria de facturacion 2026-08-25): emitir_factura() de contado exige
    'pagos'/'crear' ademas de 'ventas'/'crear' (ventas.py, linea del `if pagos:
    require_permiso(...)`) porque liquida la cuenta por cobrar en la misma transaccion --
    un vendedor sin ese permiso no puede facturar de contado aunque si pueda de credito."""
    rol = crear_rol(db_session)
    permiso_ventas = crear_permiso(db_session, recurso="ventas", accion="crear")
    asignar_permiso(db_session, rol, permiso_ventas)
    vendedor_usuario = crear_usuario(db_session, id_rol=rol.id_rol)

    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    with pytest.raises(PermisoDenegadoError):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=vendedor_usuario.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            pagos=pago_contado(db_session),
            items=[{"id_producto": producto.id_producto, "cantidad": 5, "precio_unitario": "20.00"}],
        )


def test_emitir_factura_contado_abre_y_liquida_cuenta_por_cobrar_con_un_pago(db_session):
    """Desde migrations/0024: una factura de contado tambien abre una cuenta por cobrar
    (igual que credito) pero queda liquidada en la MISMA transaccion con el/los pagos
    provistos -- termina en estado='pagada', saldo 0, con su PagoCobro real."""
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "20.00")
    cliente = crear_cliente(db_session)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
        pagos=[
            {
                "metodo_pago": "efectivo",
                "moneda": "USD",
                "monto_moneda_origen": Decimal("20.00"),
                "id_caja": caja.id_caja,
            }
        ],
    )

    cxc = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).one()
    assert cxc.saldo_pendiente == Decimal("0.00")
    assert cxc.estado == "pagada"
    pago = db_session.query(PagoCobro).filter_by(id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar).one()
    assert pago.monto == Decimal("20.00")
    assert pago.moneda == "USD"
    assert pago.metodo_pago == "efectivo"
    assert pago.id_caja == caja.id_caja


def test_emitir_factura_contado_multiples_formas_de_pago_multimoneda(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "100.00")
    cliente = crear_cliente(db_session)
    cuenta = crear_cuenta_bancaria(db_session)
    TasaService.registrar_tasa(db_session, tasa_bcv="40.00", creado_por=admin.id_usuario)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
        pagos=[
            {
                "metodo_pago": "transferencia",
                "moneda": "USD",
                "monto_moneda_origen": Decimal("60.00"),
                "id_cuenta_bancaria": cuenta.id_cuenta,
            },
            {
                "metodo_pago": "transferencia",
                "moneda": "VES",
                "monto_moneda_origen": Decimal("1600.00"),  # 1600 / 40 = 40 USD
                "id_cuenta_bancaria": cuenta.id_cuenta,
            },
        ],
    )

    cxc = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).one()
    assert cxc.saldo_pendiente == Decimal("0.00")
    assert cxc.estado == "pagada"
    pagos = db_session.query(PagoCobro).filter_by(id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar).all()
    assert len(pagos) == 2
    assert sum(p.monto for p in pagos) == Decimal("100.00")


def test_emitir_factura_contado_pago_insuficiente_falla_y_no_deja_nada(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "100.00")
    cliente = crear_cliente(db_session)
    cuenta = crear_cuenta_bancaria(db_session)

    with pytest.raises(ValueError, match="no cubren el total"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
            pagos=[
                {
                    "metodo_pago": "transferencia",
                    "moneda": "USD",
                    "monto_moneda_origen": Decimal("50.00"),
                    "id_cuenta_bancaria": cuenta.id_cuenta,
                }
            ],
        )

    assert db_session.query(FacturaVenta).filter_by(id_cliente_factura=cliente.id_cliente).first() is None


def test_emitir_factura_contado_sin_pagos_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="al menos una forma de pago"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
        )


def test_emitir_factura_contado_pago_con_caja_sin_turno_abierto_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "20.00")
    cliente = crear_cliente(db_session)
    caja = crear_caja(db_session)  # nunca se abrio

    with pytest.raises(ValueError, match="no tiene un turno abierto"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
            pagos=[
                {
                    "metodo_pago": "efectivo",
                    "moneda": "USD",
                    "monto_moneda_origen": Decimal("20.00"),
                    "id_caja": caja.id_caja,
                }
            ],
        )


def test_emitir_factura_credito_no_admite_pagos(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session, limite_credito=1000)
    cuenta = crear_cuenta_bancaria(db_session)

    with pytest.raises(ValueError, match="no admite pagos"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="credito",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
            pagos=[
                {
                    "metodo_pago": "transferencia",
                    "moneda": "USD",
                    "monto_moneda_origen": Decimal("20.00"),
                    "id_cuenta_bancaria": cuenta.id_cuenta,
                }
            ],
        )


def test_emitir_factura_credito_abre_cuenta_por_cobrar(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "30.00")
    cliente = crear_cliente(db_session, limite_credito=1000)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "30.00"}],
    )

    cxc = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).first()
    assert cxc is not None
    assert cxc.saldo_pendiente == Decimal("60.00")
    assert cxc.estado == "pendiente"


def test_emitir_factura_credito_excede_limite(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "30.00")
    cliente = crear_cliente(db_session, limite_credito=50)

    with pytest.raises(ValueError, match="limite de credito"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="credito",
            items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "30.00"}],
        )


def test_emitir_factura_credito_acumula_deuda_de_facturas_previas(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "30.00")
    cliente = crear_cliente(db_session, limite_credito=100)

    VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "30.00"}],
    )

    with pytest.raises(ValueError, match="limite de credito"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="credito",
            items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "30.00"}],
        )


def test_emitir_factura_stock_insuficiente(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=3)
    crear_precio_producto(db_session, producto, "20.00")
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="Stock insuficiente"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            pagos=pago_contado(db_session),
            items=[{"id_producto": producto.id_producto, "cantidad": 10, "precio_unitario": "20.00"}],
        )

    db_session.refresh(producto)
    assert producto.cantidad_unidad == Decimal("3.00")


def test_emitir_factura_cliente_inactivo_falla(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session, estado_cliente="INACTIVO")

    with pytest.raises(ValueError, match="inactivo"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=None,
            condicion_pago="contado",
            pagos=pago_contado(db_session),
            items=[{"id_producto": producto.id_producto, "cantidad": 5, "precio_unitario": "20.00"}],
        )


def test_emitir_factura_vendedor_inactivo_falla(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)
    vendedor = crear_vendedor(db_session, estado_vendedor="INACTIVO")

    with pytest.raises(ValueError, match="inactivo"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            pagos=pago_contado(db_session),
            items=[{"id_producto": producto.id_producto, "cantidad": 5, "precio_unitario": "20.00"}],
        )


def test_emitir_factura_vendedor_inexistente_falla(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="Vendedor no encontrado"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=999999,
            condicion_pago="contado",
            pagos=pago_contado(db_session),
            items=[{"id_producto": producto.id_producto, "cantidad": 5, "precio_unitario": "20.00"}],
        )


def test_emitir_factura_producto_inactivo_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50, estado_producto="INACTIVO")
    crear_precio_producto(db_session, producto, "20.00")
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="inactivo"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            pagos=pago_contado(db_session),
            items=[{"id_producto": producto.id_producto, "cantidad": 5, "precio_unitario": "20.00"}],
        )


def test_emitir_factura_producto_inexistente_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="no encontrado"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            pagos=pago_contado(db_session),
            items=[{"id_producto": 999999, "cantidad": 1, "precio_unitario": "20.00"}],
        )


def test_emitir_factura_agrupa_items_repetidos_para_validar_stock(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=5)
    crear_precio_producto(db_session, producto, "20.00")
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="Stock insuficiente"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            pagos=pago_contado(db_session),
            items=[
                {"id_producto": producto.id_producto, "cantidad": 3, "precio_unitario": "20.00"},
                {"id_producto": producto.id_producto, "cantidad": 3, "precio_unitario": "20.00"},
            ],
        )


def test_emitir_factura_bloquea_stock_con_updlock_rowlock_concurrente(db_session, test_engine):
    """N3 (auditoria de facturacion 2026-08-25): el WITH (UPDLOCK, ROWLOCK) sobre
    Inventario (ventas.py, validacion de stock) solo estaba verificado leyendo el codigo,
    nunca ejercitado con dos conexiones reales compitiendo por el mismo producto -- este
    test abre una segunda sesion real sobre test_engine (db_session no sirve para esto:
    una Session de SQLAlchemy no es segura para compartir entre threads) que sostiene el
    lock manualmente sobre la fila del producto y comprueba que un emitir_factura()
    concurrente sobre ESE MISMO producto de verdad se queda bloqueado esperando el lock
    (no lee un stock stale) hasta que la primera transaccion lo libera."""
    import threading

    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from app.db.models import Inventario

    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=10)
    crear_precio_producto(db_session, producto, "10.00")
    cliente = crear_cliente(db_session, limite_credito=Decimal("10000.00"))
    id_producto, id_cliente, id_vendedor, id_usuario = (
        producto.id_producto,
        cliente.id_cliente,
        vendedor.id_vendedor,
        admin.id_usuario,
    )

    session_factory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    sesion_bloqueadora = session_factory()
    resultado: dict = {}

    try:
        sesion_bloqueadora.execute(
            select(Inventario)
            .where(Inventario.id_producto == id_producto)
            .with_hint(Inventario, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
        ).scalar_one()

        def _emitir_en_thread():
            sesion_hilo = session_factory()
            try:
                factura = VentaService.emitir_factura(
                    sesion_hilo,
                    id_cliente=id_cliente,
                    id_usuario=id_usuario,
                    id_vendedor=id_vendedor,
                    condicion_pago="credito",
                    items=[{"id_producto": id_producto, "cantidad": 3, "precio_unitario": "10.00"}],
                )
                resultado["id_factura"] = factura.id_factura
            finally:
                sesion_hilo.close()

        hilo = threading.Thread(target=_emitir_en_thread)
        hilo.start()

        # El lock sigue sostenido: emitir_factura debe seguir esperando, no adelantarse.
        hilo.join(timeout=1.5)
        assert hilo.is_alive(), "emitir_factura no se bloqueo por el UPDLOCK/ROWLOCK esperado sobre Inventario"

        # Libera el lock (rollback: esta sesion solo leyo, no debe dejar nada escrito).
        sesion_bloqueadora.rollback()

        hilo.join(timeout=10)
        assert not hilo.is_alive(), "emitir_factura no continuo tras liberarse el lock"
        assert "id_factura" in resultado
    finally:
        sesion_bloqueadora.close()

    db_session.refresh(producto)
    assert producto.cantidad_unidad == Decimal("7.00")


def test_emitir_factura_sin_items(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session)
    with pytest.raises(ValueError, match="al menos un item"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=None,
            condicion_pago="contado",
            pagos=pago_contado(db_session),
            items=[],
        )


def test_emitir_factura_observaciones_supera_255_caracteres_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)
    with pytest.raises(ValueError, match="observaciones no puede superar 255 caracteres"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            pagos=pago_contado(db_session),
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
            observaciones="x" * 256,
        )


def test_emitir_factura_condicion_pago_invalida(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session)
    cliente = crear_cliente(db_session)
    with pytest.raises(ValueError, match="condicion_pago"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="otra",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
        )


def test_emitir_factura_cliente_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session)
    with pytest.raises(ValueError, match="Cliente no encontrado"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=999999,
            id_usuario=admin.id_usuario,
            id_vendedor=None,
            condicion_pago="contado",
            pagos=pago_contado(db_session),
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
        )


def test_anular_factura_contado_repone_stock(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "20.00")
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db_session),
        items=[{"id_producto": producto.id_producto, "cantidad": 5, "precio_unitario": "20.00"}],
    )

    VentaService.anular_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario, motivo="Error de carga")

    db_session.refresh(factura)
    db_session.refresh(producto)
    assert factura.estado_factura == "ANULADA"
    assert producto.cantidad_unidad == Decimal("50.00")  # se repone
    assert factura.total_venta == Decimal("0.00")
    assert db_session.query(FacturaDetalle).filter_by(id_factura=factura.id_factura).count() == 0


def test_anular_factura_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "20.00")
    cliente = crear_cliente(db_session)
    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db_session),
        items=[{"id_producto": producto.id_producto, "cantidad": 5, "precio_unitario": "20.00"}],
    )

    with pytest.raises(PermisoDenegadoError):
        VentaService.anular_factura(db_session, factura.id_factura, id_usuario=None, motivo="Error de carga")


def test_anular_factura_credito_repone_stock_y_cierra_cxc(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "20.00")
    cliente = crear_cliente(db_session, limite_credito=1000)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 3, "precio_unitario": "20.00"}],
    )
    cxc = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).one()

    VentaService.anular_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario, motivo="Error de carga")

    db_session.refresh(producto)
    assert producto.cantidad_unidad == Decimal("50.00")
    assert db_session.get(CuentaPorCobrar, cxc.id_cuenta_por_cobrar) is None

    # anular una factura credito ya cerrada no debe volver a abrir cupo con el cliente
    otra = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "999.00"}],
    )
    assert otra.total_venta == Decimal("999.00")


def test_anular_factura_con_pago_aplicado_genera_nota_de_credito(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "20.00")
    cliente = crear_cliente(db_session, limite_credito=1000)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "20.00"}],
    )
    cxc = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).one()
    pago = PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto=Decimal("10.00"),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )
    id_pago_cobro = pago.id_pago_cobro

    VentaService.anular_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario, motivo="Error de carga")

    db_session.refresh(factura)
    db_session.refresh(producto)
    assert factura.estado_factura == "ANULADA"
    assert producto.cantidad_unidad == Decimal("50.00")  # stock repuesto

    # la cuenta por cobrar NO se borra (se conserva el vinculo con el pago ya aplicado):
    # queda anulada, sin saldo pendiente
    db_session.refresh(cxc)
    assert cxc.estado == "anulada"
    assert cxc.saldo_pendiente == Decimal("0.00")

    # el pago original y su movimiento de caja quedan intactos, sin revertir
    assert db_session.query(PagoCobro).filter_by(id_pago_cobro=id_pago_cobro).one().monto == Decimal("10.00")
    assert db_session.query(CajaMovimiento).filter_by(id_pago_cobro=id_pago_cobro).first() is not None

    # y la plata ya cobrada queda como nota de credito a favor del cliente
    nota = db_session.query(NotaCreditoCliente).filter_by(id_factura_origen=factura.id_factura).one()
    assert nota.id_cliente == cliente.id_cliente
    assert nota.numero_nota_credito.startswith("NC-")
    assert nota.monto == Decimal("10.00")
    assert nota.saldo_disponible == Decimal("10.00")
    assert nota.estado == "disponible"

    # no revive la deuda: emitir_factura no cuenta la cxc anulada como deuda vigente
    otra = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "999.00"}],
    )
    assert otra.total_venta == Decimal("999.00")


def test_anular_factura_con_comision_pendiente_borra_comision_y_anula(db_session):
    """C14: una comision 'pendiente' (el vendedor todavia no cobro nada) no bloquea la
    anulacion -- se borra junto con el resto de la reversion."""
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "20.00")
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db_session),
        items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "20.00"}],
    )
    detalle = db_session.query(FacturaDetalle).filter_by(id_factura=factura.id_factura).first()
    id_factura_detalle = detalle.id_factura_detalle  # capturado antes de que anular_factura borre la fila
    db_session.add(
        ComisionFactura(
            id_factura_detalle=id_factura_detalle,
            id_vendedor=vendedor.id_vendedor,
            monto_venta_comision=Decimal("40.00"),
            monto_comision=Decimal("4.00"),
            estado_pago="pendiente",
        )
    )
    db_session.commit()

    VentaService.anular_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario, motivo="Error de carga")

    db_session.refresh(factura)
    db_session.refresh(producto)
    assert factura.estado_factura == "ANULADA"
    assert producto.cantidad_unidad == Decimal("50.00")  # stock repuesto
    assert db_session.query(ComisionFactura).filter_by(id_factura_detalle=id_factura_detalle).first() is None


def test_anular_factura_con_comision_pagada_bloqueada(db_session):
    """Si la comision ya se pago (el vendedor ya cobro ese dinero real), la anulacion
    sigue bloqueada -- no hay forma de revertir un pago ya hecho."""
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "20.00")
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db_session),
        items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "20.00"}],
    )
    detalle = db_session.query(FacturaDetalle).filter_by(id_factura=factura.id_factura).first()
    db_session.add(
        ComisionFactura(
            id_factura_detalle=detalle.id_factura_detalle,
            id_vendedor=vendedor.id_vendedor,
            monto_venta_comision=Decimal("40.00"),
            monto_comision=Decimal("4.00"),
            estado_pago="pagada",
        )
    )
    db_session.commit()

    with pytest.raises(ValueError, match="comisiones ya pagadas"):
        VentaService.anular_factura(
            db_session, factura.id_factura, id_usuario=admin.id_usuario, motivo="Error de carga"
        )

    db_session.refresh(factura)
    db_session.refresh(producto)
    assert factura.estado_factura != "ANULADA"
    assert producto.cantidad_unidad == Decimal("48.00")  # stock intacto, no se repuso


# --- ComisionService.calcular_comisiones_factura (llamada desde emitir_factura, C14) ---


def test_emitir_factura_con_vendedor_calcula_comision_sobre_diferencia(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "1.00")
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db_session),
        items=[{"id_producto": producto.id_producto, "cantidad": 3, "precio_unitario": "2.00"}],
    )

    detalle = db_session.query(FacturaDetalle).filter_by(id_factura=factura.id_factura).first()
    comision = db_session.query(ComisionFactura).filter_by(id_factura_detalle=detalle.id_factura_detalle).one()
    assert comision.id_vendedor == vendedor.id_vendedor
    assert comision.monto_base_comision == Decimal("3.00")  # 1.00 (lista) * 3
    assert comision.monto_venta_comision == Decimal("6.00")  # 2.00 (real) * 3
    assert comision.monto_comision == Decimal("3.00")  # diferencia
    assert comision.estado_pago == "liberada"  # contado: se cobra completo al emitir


def test_emitir_factura_precio_igual_al_de_lista_comision_cero(db_session):
    """Vender exactamente al precio de lista no genera comisión (monto_comision == 0)
    -- no se crea ComisionFactura en ese caso."""
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "5.00")
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db_session),
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "5.00"}],
    )

    detalle = db_session.query(FacturaDetalle).filter_by(id_factura=factura.id_factura).first()
    comisiones = db_session.query(ComisionFactura).filter_by(id_factura_detalle=detalle.id_factura_detalle).all()
    assert len(comisiones) == 0  # no crea comisión si monto es 0


def test_emitir_factura_precio_menor_al_de_lista_requiere_autorizacion_y_comision_cero(db_session):
    """Vender por debajo del precio de lista es un descuento implicito (hallazgo #4/#5
    del audit de facturacion): requiere motivo + autorizador con permiso
    'descuentos'/'crear', igual que un monto_descuento explicito."""
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "5.00")
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db_session),
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "3.00"}],
        motivo_descuento="Cliente frecuente",
        id_autorizador_descuento=admin.id_usuario,
    )

    assert factura.autorizado_por_descuento == admin.id_usuario
    assert factura.motivo_descuento == "Cliente frecuente"
    detalle = db_session.query(FacturaDetalle).filter_by(id_factura=factura.id_factura).first()
    comisiones = db_session.query(ComisionFactura).filter_by(id_factura_detalle=detalle.id_factura_detalle).all()
    assert len(comisiones) == 0  # no crea comisión si precio < precio_lista (monto <= 0)


def test_emitir_factura_precio_menor_al_de_lista_sin_autorizacion_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "5.00")
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="requiere un motivo"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            pagos=pago_contado(db_session),
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "3.00"}],
        )

    with pytest.raises(ValueError, match="requiere autorizacion de un supervisor"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            pagos=pago_contado(db_session),
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "3.00"}],
            motivo_descuento="Cliente frecuente",
        )


def test_emitir_factura_precio_menor_al_de_lista_autorizador_sin_permiso_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "5.00")
    cliente = crear_cliente(db_session)

    with pytest.raises(PermisoDenegadoError):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            pagos=pago_contado(db_session),
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "3.00"}],
            motivo_descuento="Cliente frecuente",
            id_autorizador_descuento=999999,
        )


def test_emitir_factura_sin_precio_de_lista_falla(db_session):
    """Un producto sin precio de lista configurado no se puede vender -- sin un precio
    de referencia no hay forma de detectar automaticamente si el precio que le pone el
    vendedor requiere autorizacion (descuento) o genera comision."""
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)  # sin crear_precio_producto
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="no tienen precio de venta configurado"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            pagos=pago_contado(db_session),
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
        )


def test_emitir_factura_sin_vendedor_falla(db_session):
    """El vendedor es obligatorio en toda factura desde
    migrations/0017_vendedor_obligatorio_factura.sql -- sin el, ComisionService no
    tendria a quien acreditarle la venta."""
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="vendedor es obligatorio"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=None,
            condicion_pago="contado",
            pagos=pago_contado(db_session),
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
        )


def test_anular_factura_sin_motivo(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session)
    crear_precio_producto(db_session, producto, "20.00")
    cliente = crear_cliente(db_session)
    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db_session),
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )

    with pytest.raises(ValueError, match="motivo"):
        VentaService.anular_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario, motivo="")


def test_anular_factura_ya_anulada(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session)
    crear_precio_producto(db_session, producto, "20.00")
    cliente = crear_cliente(db_session)
    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db_session),
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )
    VentaService.anular_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario, motivo="Motivo 1")

    with pytest.raises(ValueError, match="ya esta anulada"):
        VentaService.anular_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario, motivo="Motivo 2")


def test_listar_facturas_filtra_por_cliente(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "20.00")
    cliente_a = crear_cliente(db_session)
    cliente_b = crear_cliente(db_session)

    VentaService.emitir_factura(
        db_session,
        id_cliente=cliente_a.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db_session),
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )
    VentaService.emitir_factura(
        db_session,
        id_cliente=cliente_b.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db_session),
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )

    resultado = VentaService.listar_facturas(db_session, id_cliente=cliente_a.id_cliente, id_usuario=admin.id_usuario)

    assert resultado["total"] == 1
    assert resultado["items"][0].id_cliente_factura == cliente_a.id_cliente


def test_listar_facturas_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        VentaService.listar_facturas(db_session)


def test_listar_facturas_filtra_por_numero_parcial(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "20.00")
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db_session),
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )

    resultado = VentaService.listar_facturas(
        db_session, numero_factura=factura.numero_factura[-4:], id_usuario=admin.id_usuario
    )

    assert resultado["total"] == 1
    assert resultado["items"][0].numero_factura == factura.numero_factura


def test_listar_facturas_texto_busqueda_matchea_numero_cliente_o_vendedor(db_session):
    """texto_busqueda es la barra de busqueda unica de FacturacionPanel: un solo termino
    debe matchear numero de factura, nombre de cliente O nombre de vendedor -- antes eran
    dos cajas separadas (numero_factura/nombre_cliente) que se combinaban con AND."""
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session, nombre_vendedor="Roberto Distinguible")
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "20.00")
    cliente = crear_cliente(db_session, nombre_razon_social="Comercial Unico SA")

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db_session),
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )

    por_numero = VentaService.listar_facturas(
        db_session, texto_busqueda=factura.numero_factura[-4:], id_usuario=admin.id_usuario
    )
    por_cliente = VentaService.listar_facturas(db_session, texto_busqueda="Unico", id_usuario=admin.id_usuario)
    por_vendedor = VentaService.listar_facturas(db_session, texto_busqueda="Distinguible", id_usuario=admin.id_usuario)
    sin_match = VentaService.listar_facturas(db_session, texto_busqueda="NoExiste123", id_usuario=admin.id_usuario)

    for resultado in (por_numero, por_cliente, por_vendedor):
        assert resultado["total"] == 1
        assert resultado["items"][0].id_factura == factura.id_factura
    assert sin_match["total"] == 0


def test_listar_facturas_filtra_por_estado_vencida(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "20.00")
    cliente = crear_cliente(db_session, limite_credito=Decimal("1000.00"))

    factura_vencida = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
        fecha_vencimiento=date.today() - timedelta(days=5),
    )
    VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
        fecha_vencimiento=date.today() + timedelta(days=30),
    )

    resultado = VentaService.listar_facturas(db_session, estado="VENCIDA", id_usuario=admin.id_usuario)

    assert resultado["total"] == 1
    assert resultado["items"][0].id_factura == factura_vencida.id_factura
    assert resultado["items"][0].estado_visual == "VENCIDA"


def test_listar_facturas_filtra_por_estado_pagada(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "20.00")
    cliente = crear_cliente(db_session, limite_credito=Decimal("1000.00"))

    factura_pagada = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db_session),
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )
    VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )

    resultado = VentaService.listar_facturas(db_session, estado="PAGADA", id_usuario=admin.id_usuario)

    assert resultado["total"] == 1
    assert resultado["items"][0].id_factura == factura_pagada.id_factura


def test_obtener_factura_incluye_detalles(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "20.00")
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db_session),
        items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "20.00"}],
    )

    resultado = VentaService.obtener_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario)

    assert resultado["factura"].id_factura == factura.id_factura
    assert resultado["factura"].cliente.id_cliente == cliente.id_cliente
    assert len(resultado["detalles"]) == 1
    assert resultado["detalles"][0].producto.id_producto == producto.id_producto
    assert resultado["detalles"][0].cantidad_producto == Decimal("2.00")
    assert resultado["factura"].estado_visual == "PAGADA"


def test_obtener_factura_credito_recien_emitida_estado_visual_emitida(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "20.00")
    cliente = crear_cliente(db_session, limite_credito=Decimal("1000.00"))

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
        fecha_vencimiento=date.today() + timedelta(days=30),
    )

    resultado = VentaService.obtener_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario)

    assert resultado["factura"].estado_visual == "EMITIDA"


def test_obtener_factura_credito_pago_parcial_estado_visual_parcial(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "100.00")
    cliente = crear_cliente(db_session, limite_credito=Decimal("1000.00"))
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
        fecha_vencimiento=date.today() + timedelta(days=30),
    )
    cxc = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).one()
    PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto=Decimal("40.00"),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    resultado = VentaService.obtener_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario)

    assert resultado["factura"].estado_visual == "PARCIAL"


def test_obtener_factura_credito_vencida_estado_visual_vencida(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "20.00")
    cliente = crear_cliente(db_session, limite_credito=Decimal("1000.00"))

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
        fecha_vencimiento=date.today() - timedelta(days=5),
    )

    resultado = VentaService.obtener_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario)

    assert resultado["factura"].estado_visual == "VENCIDA"


def test_obtener_factura_anulada_estado_visual_anulada(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "20.00")
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db_session),
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )
    VentaService.anular_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario, motivo="Motivo")

    resultado = VentaService.obtener_factura(db_session, factura.id_factura, id_usuario=admin.id_usuario)

    assert resultado["factura"].estado_visual == "ANULADA"


def test_obtener_factura_inexistente_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Factura no encontrada"):
        VentaService.obtener_factura(db_session, 999999, id_usuario=admin.id_usuario)


def test_obtener_factura_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        VentaService.obtener_factura(db_session, 1)


# --- numero_control + IVA (facturacion fiscal, migrations/0018-0019) ------------------


def test_emitir_factura_numero_control_correlativo_unico(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "20.00")
    cliente = crear_cliente(db_session)

    primera = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db_session),
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )
    segunda = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db_session),
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )

    assert primera.numero_control.startswith("00-")
    assert primera.numero_control != segunda.numero_control
    assert primera.numero_control == f"00-{primera.id_factura:08d}"


def test_emitir_factura_sin_config_empresa_no_calcula_iva(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "20.00")
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db_session),
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "20.00"}],
    )

    assert factura.iva_aplicado is False
    assert factura.monto_iva == Decimal("0.00")


def test_emitir_factura_con_iva_activo_calcula_monto_y_snapshot(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "100.00")
    cliente = crear_cliente(db_session)
    EmpresaService.guardar_configuracion(
        db_session,
        rif=None,
        razon_social=None,
        direccion=None,
        telefono=None,
        iva_activo=True,
        iva_porcentaje="16.00",
        modificado_por=admin.id_usuario,
    )

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db_session),
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
    )

    assert factura.iva_aplicado is True
    assert factura.porcentaje_iva_aplicado == Decimal("16.00")
    assert factura.monto_iva == Decimal("16.00")
    assert factura.total_venta == Decimal("100.00")  # total_venta sigue siendo el subtotal


def test_emitir_factura_con_iva_desactivado_no_calcula_iva_aunque_haya_config(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "100.00")
    cliente = crear_cliente(db_session)
    EmpresaService.guardar_configuracion(
        db_session,
        rif=None,
        razon_social=None,
        direccion=None,
        telefono=None,
        iva_activo=False,
        iva_porcentaje="16.00",
        modificado_por=admin.id_usuario,
    )

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db_session),
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
    )

    assert factura.iva_aplicado is False
    assert factura.monto_iva == Decimal("0.00")


def test_emitir_factura_credito_con_iva_suma_iva_a_cuenta_por_cobrar(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "100.00")
    cliente = crear_cliente(db_session, limite_credito=1000)
    EmpresaService.guardar_configuracion(
        db_session,
        rif=None,
        razon_social=None,
        direccion=None,
        telefono=None,
        iva_activo=True,
        iva_porcentaje="16.00",
        modificado_por=admin.id_usuario,
    )

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
    )

    cxc = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).one()
    assert cxc.saldo_pendiente == Decimal("116.00")  # 100 + 16% IVA


def test_emitir_factura_credito_con_iva_valida_limite_credito_incluyendo_iva(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "100.00")
    # limite alcanza para el subtotal (100) pero no para subtotal+IVA (116)
    cliente = crear_cliente(db_session, limite_credito=Decimal("110.00"))
    EmpresaService.guardar_configuracion(
        db_session,
        rif=None,
        razon_social=None,
        direccion=None,
        telefono=None,
        iva_activo=True,
        iva_porcentaje="16.00",
        modificado_por=admin.id_usuario,
    )

    with pytest.raises(ValueError, match="limite de credito"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="credito",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
        )


# --- monto_descuento de factura (descuento manual, requiere autorizacion) -------------


def test_emitir_factura_monto_descuento_sin_autorizacion_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "100.00")
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="requiere un motivo"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            pagos=pago_contado(db_session),
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
            monto_descuento="10.00",
        )


def test_emitir_factura_monto_descuento_autorizado_resta_del_total(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "100.00")
    cliente = crear_cliente(db_session)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db_session),
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
        monto_descuento="10.00",
        motivo_descuento="Cliente frecuente",
        id_autorizador_descuento=admin.id_usuario,
    )

    assert factura.monto_descuento == Decimal("10.00")
    assert factura.autorizado_por_descuento == admin.id_usuario
    assert factura.total_venta == Decimal("100.00")  # subtotal crudo, sin tocar (triggers)


def test_emitir_factura_monto_descuento_mayor_al_subtotal_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "100.00")
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="no puede ser mayor al subtotal"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            pagos=pago_contado(db_session),
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
            monto_descuento="150.00",
            motivo_descuento="x",
            id_autorizador_descuento=admin.id_usuario,
        )


def test_emitir_factura_monto_descuento_negativo_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="no puede ser negativo"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            pagos=pago_contado(db_session),
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
            monto_descuento="-1.00",
        )


def test_emitir_factura_credito_con_descuento_y_iva_ajusta_cuenta_por_cobrar(db_session):
    """subtotal 100 - descuento 20 = 80; +16% IVA sobre 80 = 12.80; total a cobrar 92.80."""
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "100.00")
    cliente = crear_cliente(db_session, limite_credito=1000)
    EmpresaService.guardar_configuracion(
        db_session,
        rif=None,
        razon_social=None,
        direccion=None,
        telefono=None,
        iva_activo=True,
        iva_porcentaje="16.00",
        modificado_por=admin.id_usuario,
    )

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
        monto_descuento="20.00",
        motivo_descuento="Cliente frecuente",
        id_autorizador_descuento=admin.id_usuario,
    )

    assert factura.monto_iva == Decimal("12.80")
    cxc = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).one()
    assert cxc.saldo_pendiente == Decimal("92.80")


# --- dias_credito por cliente (bloqueo si no configurado + override autorizado) -------


def test_emitir_factura_credito_cliente_sin_dias_credito_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session, dias_credito=0)

    with pytest.raises(ValueError, match="no tiene dias de credito configurados"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="credito",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
        )

    assert db_session.query(FacturaVenta).count() == 0


def test_emitir_factura_credito_usa_dias_configurados_por_defecto(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "100.00")
    cliente = crear_cliente(db_session, limite_credito=1000, dias_credito=15)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
    )

    assert factura.dias_credito_aplicados == 15
    assert factura.fecha_vencimiento == date.today() + timedelta(days=15)
    assert factura.motivo_dias_credito is None
    assert factura.autorizado_por_dias_credito is None


def test_emitir_factura_credito_dias_personalizados_sin_autorizacion_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session, limite_credito=1000, dias_credito=15)

    with pytest.raises(ValueError, match="requiere un motivo"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="credito",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
            dias_credito_personalizados=45,
        )


def test_emitir_factura_credito_dias_personalizados_autorizado_ok(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "100.00")
    cliente = crear_cliente(db_session, limite_credito=1000, dias_credito=15)

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
        dias_credito_personalizados=45,
        motivo_dias_credito="Cliente VIP",
        id_autorizador_dias_credito=admin.id_usuario,
    )

    assert factura.dias_credito_aplicados == 45
    assert factura.fecha_vencimiento == date.today() + timedelta(days=45)
    assert factura.motivo_dias_credito == "Cliente VIP"
    assert factura.autorizado_por_dias_credito == admin.id_usuario


def test_emitir_factura_credito_dias_personalizados_sin_permiso_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session, limite_credito=1000, dias_credito=15)

    with pytest.raises(PermisoDenegadoError):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="credito",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
            dias_credito_personalizados=45,
            motivo_dias_credito="Cliente VIP",
            id_autorizador_dias_credito=999999,
        )


def test_emitir_factura_contado_no_admite_dias_credito_personalizados(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    cliente = crear_cliente(db_session)

    with pytest.raises(ValueError, match="solo aplica a condicion_pago='credito'"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            pagos=pago_contado(db_session),
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
            dias_credito_personalizados=30,
        )


# --- consultar_limite_disponible (bloqueo visual proactivo en factura_form_dialog) ----


def test_consultar_limite_disponible_sin_deuda(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session, limite_credito=Decimal("500.00"))

    resultado = VentaService.consultar_limite_disponible(db_session, cliente.id_cliente, id_usuario=admin.id_usuario)

    assert resultado["limite_credito"] == Decimal("500.00")
    assert resultado["deuda_actual"] == Decimal("0.00")
    assert resultado["disponible"] == Decimal("500.00")
    assert resultado["elegible_credito"] is True


def test_consultar_limite_disponible_descuenta_deuda_vigente(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "120.00")
    cliente = crear_cliente(db_session, limite_credito=Decimal("500.00"))

    VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "120.00"}],
    )

    resultado = VentaService.consultar_limite_disponible(db_session, cliente.id_cliente, id_usuario=admin.id_usuario)

    assert resultado["deuda_actual"] == Decimal("120.00")
    assert resultado["disponible"] == Decimal("380.00")


def test_consultar_limite_disponible_cliente_sin_dias_credito_no_es_elegible(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session, limite_credito=Decimal("500.00"), dias_credito=0)

    resultado = VentaService.consultar_limite_disponible(db_session, cliente.id_cliente, id_usuario=admin.id_usuario)

    # El limite y el disponible siguen calculandose tal cual (son datos reales del
    # cliente), pero elegible_credito=False deja claro que ese disponible no tiene
    # ningun efecto: el cliente no puede facturarse a credito por ningun monto.
    assert resultado["disponible"] == Decimal("500.00")
    assert resultado["elegible_credito"] is False


def test_consultar_limite_disponible_cliente_inexistente_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Cliente no encontrado"):
        VentaService.consultar_limite_disponible(db_session, 999999, id_usuario=admin.id_usuario)


def test_consultar_limite_disponible_sin_usuario_autorizado_falla(db_session):
    cliente = crear_cliente(db_session)
    with pytest.raises(PermisoDenegadoError):
        VentaService.consultar_limite_disponible(db_session, cliente.id_cliente)


# --- Vuelto (cambio) en facturas de contado -------------------------------------------


def test_emitir_factura_vuelto_bancario_sin_referencia_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "100.00")
    cliente = crear_cliente(db_session)
    cuenta = crear_cuenta_bancaria(db_session)
    cuenta_vuelto = crear_cuenta_bancaria(db_session)

    with pytest.raises(ValueError, match="referencia bancaria"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
            pagos=[
                {
                    "metodo_pago": "transferencia",
                    "moneda": "USD",
                    "monto_moneda_origen": Decimal("150.00"),
                    "id_cuenta_bancaria": cuenta.id_cuenta,
                }
            ],
            metodo_vuelto="transferencia",
            id_cuenta_bancaria_vuelto=cuenta_vuelto.id_cuenta,
            id_autorizador_vuelto=admin.id_usuario,
        )


def test_emitir_factura_vuelto_bancario_sin_autorizador_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "100.00")
    cliente = crear_cliente(db_session)
    cuenta = crear_cuenta_bancaria(db_session)
    cuenta_vuelto = crear_cuenta_bancaria(db_session)

    with pytest.raises(ValueError, match="autorizacion de un supervisor"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
            pagos=[
                {
                    "metodo_pago": "transferencia",
                    "moneda": "USD",
                    "monto_moneda_origen": Decimal("150.00"),
                    "id_cuenta_bancaria": cuenta.id_cuenta,
                }
            ],
            metodo_vuelto="pago_movil",
            id_cuenta_bancaria_vuelto=cuenta_vuelto.id_cuenta,
            referencia_vuelto="REF1234",
        )


def test_emitir_factura_vuelto_bancario_autorizador_sin_permiso_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "100.00")
    cliente = crear_cliente(db_session)
    cuenta = crear_cuenta_bancaria(db_session)
    cuenta_vuelto = crear_cuenta_bancaria(db_session)
    otro_rol = crear_rol(db_session)
    autorizador_sin_permiso = crear_usuario(db_session, id_rol=otro_rol.id_rol)

    with pytest.raises(PermisoDenegadoError):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
            pagos=[
                {
                    "metodo_pago": "transferencia",
                    "moneda": "USD",
                    "monto_moneda_origen": Decimal("150.00"),
                    "id_cuenta_bancaria": cuenta.id_cuenta,
                }
            ],
            metodo_vuelto="transferencia",
            id_cuenta_bancaria_vuelto=cuenta_vuelto.id_cuenta,
            referencia_vuelto="REF1234",
            id_autorizador_vuelto=autorizador_sin_permiso.id_usuario,
        )


def test_emitir_factura_vuelto_bancario_autorizado_ok(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "100.00")
    cliente = crear_cliente(db_session)
    cuenta = crear_cuenta_bancaria(db_session)
    cuenta_vuelto = crear_cuenta_bancaria(db_session, saldo_total_banco=Decimal("1000.00"))

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
        pagos=[
            {
                "metodo_pago": "transferencia",
                "moneda": "USD",
                "monto_moneda_origen": Decimal("150.00"),
                "id_cuenta_bancaria": cuenta.id_cuenta,
            }
        ],
        metodo_vuelto="transferencia",
        id_cuenta_bancaria_vuelto=cuenta_vuelto.id_cuenta,
        referencia_vuelto="REF1234",
        id_autorizador_vuelto=admin.id_usuario,
    )

    assert factura.monto_vuelto == Decimal("50.00")
    assert factura.metodo_vuelto == "transferencia"
    assert factura.referencia_vuelto == "REF1234"
    assert factura.autorizado_por_vuelto == admin.id_usuario
    assert factura.fecha_autorizacion_vuelto is not None

    movimiento = (
        db_session.query(BancoMovimiento)
        .filter(BancoMovimiento.id_cuenta == cuenta_vuelto.id_cuenta, BancoMovimiento.tipo_movimiento == "cargo")
        .first()
    )
    assert movimiento is not None
    assert movimiento.monto_movimiento == Decimal("50.00")
    assert movimiento.referencia_movimiento == "REF1234"


def test_emitir_factura_vuelto_efectivo_no_requiere_autorizacion(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "100.00")
    cliente = crear_cliente(db_session)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("500.00"))

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
        pagos=[
            {
                "metodo_pago": "efectivo",
                "moneda": "USD",
                "monto_moneda_origen": Decimal("150.00"),
                "id_caja": caja.id_caja,
            }
        ],
        metodo_vuelto="efectivo",
        id_caja_vuelto=caja.id_caja,
    )

    assert factura.monto_vuelto == Decimal("50.00")
    assert factura.metodo_vuelto == "efectivo"
    assert factura.referencia_vuelto is None
    assert factura.autorizado_por_vuelto is None

    salida = (
        db_session.query(CajaMovimiento)
        .filter(CajaMovimiento.id_caja == caja.id_caja, CajaMovimiento.tipo_movimiento == "salida")
        .first()
    )
    assert salida is not None
    assert salida.monto_movimiento == Decimal("50.00")

    # 500 apertura + 150 cobrado - 50 vuelto = 600
    assert CajaService.calcular_saldo_actual(db_session, caja.id_caja) == Decimal("600.00")


def test_emitir_factura_vuelto_efectivo_saldo_insuficiente_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "100.00")
    cliente = crear_cliente(db_session)
    caja = crear_caja(db_session)
    # La caja de vuelto abre en 0 y el pago que genera el vuelto entra por transferencia
    # (no aporta efectivo a esta caja) -- no hay de donde sacar el vuelto.
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("0.00"))
    cuenta = crear_cuenta_bancaria(db_session)

    with pytest.raises(ValueError, match="no tiene saldo suficiente"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="contado",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
            pagos=[
                {
                    "metodo_pago": "transferencia",
                    "moneda": "USD",
                    "monto_moneda_origen": Decimal("150.00"),
                    "id_cuenta_bancaria": cuenta.id_cuenta,
                }
            ],
            metodo_vuelto="efectivo",
            id_caja_vuelto=caja.id_caja,
        )


def test_emitir_factura_vuelto_efectivo_se_infiere_de_la_unica_caja_usada(db_session):
    """Sin metodo_vuelto explicito: si las formas de pago usaron una unica caja, el vuelto
    se infiere de esa misma caja (ver comentario en VentaService.emitir_factura) -- esto es
    lo que permite que pago_contado() (tests/factories.py) siga sin declarar nada de vuelto
    para tests de otros modulos (comisiones, notas de credito, etc.)."""
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "100.00")
    cliente = crear_cliente(db_session)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("500.00"))

    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
        pagos=[
            {
                "metodo_pago": "efectivo",
                "moneda": "USD",
                "monto_moneda_origen": Decimal("150.00"),
                "id_caja": caja.id_caja,
            }
        ],
    )

    assert factura.monto_vuelto == Decimal("50.00")
    assert factura.metodo_vuelto == "efectivo"
    assert factura.autorizado_por_vuelto is None
    salida = (
        db_session.query(CajaMovimiento)
        .filter(CajaMovimiento.id_caja == caja.id_caja, CajaMovimiento.tipo_movimiento == "salida")
        .first()
    )
    assert salida is not None
    assert salida.monto_movimiento == Decimal("50.00")

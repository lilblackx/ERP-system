"""Pruebas de NotaCreditoService en aislamiento. El flujo real (generarla automaticamente
al anular una factura/compra con pagos aplicados) se prueba en
test_ventas.py::test_anular_factura_con_pago_aplicado_genera_nota_de_credito y su
equivalente en test_compras.py.
"""

from decimal import Decimal

import pytest

from app.db.models import BancoMovimiento, CajaMovimiento, CuentaPorCobrar
from app.services.compras import CompraService
from app.services.notas_credito import NotaCreditoService
from app.services.permisos import PermisoDenegadoError
from app.services.tesoreria import CajaService
from app.services.ventas import VentaService
from tests.factories import (
    asignar_permiso,
    crear_caja,
    crear_cliente,
    crear_cuenta_bancaria,
    crear_permiso,
    crear_producto,
    crear_proveedor,
    crear_rol,
    crear_usuario,
    crear_usuario_admin,
    crear_vendedor,
    pago_contado,
)


def _crear_factura(session):
    admin = crear_usuario_admin(session)
    vendedor = crear_vendedor(session)
    producto = crear_producto(session, cantidad_unidad=10)
    cliente = crear_cliente(session)
    factura = VentaService.emitir_factura(
        session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "10.00"}],
        pagos=pago_contado(session),
    )
    return cliente, factura, admin


def _crear_compra(session):
    admin = crear_usuario_admin(session)
    producto = crear_producto(session, cantidad_unidad=10)
    proveedor = crear_proveedor(session)
    caja = crear_caja(session)
    CajaService.abrir_caja(session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("100.00"))
    compra = CompraService.registrar_compra(
        session,
        id_proveedor=proveedor.id_proveedor,
        id_usuario=admin.id_usuario,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "costo_unitario": "10.00"}],
        # Una compra de contado exige pago (validacion en compras.py, ver su docstring):
        # exactamente el total, sin vuelto -- por eso "10.00" a mano en vez de reusar
        # pago_contado() (pensado para VentaService.emitir_factura, que si tolera sobrante).
        pago={
            "metodo_pago": "efectivo",
            "moneda": "USD",
            "monto_moneda_origen": Decimal("10.00"),
            "id_caja": caja.id_caja,
            "id_cuenta_bancaria": None,
            "referencia": None,
        },
    )
    return proveedor, compra, admin


# --- crear_nota_credito_cliente --------------------------------------------------


def test_crear_nota_credito_cliente_ok(db_session):
    cliente, factura, _ = _crear_factura(db_session)

    nota = NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente.id_cliente,
        id_factura_origen=factura.id_factura,
        monto=Decimal("25.00"),
        motivo="Factura anulada con pago ya aplicado",
        id_usuario=None,
    )

    assert nota.id_nota_credito is not None
    assert nota.numero_nota_credito.startswith("NC-")
    assert nota.monto == Decimal("25.00")
    assert nota.saldo_disponible == Decimal("25.00")
    assert nota.estado == "disponible"


def test_crear_nota_credito_cliente_correlativo_es_unico_y_valido(db_session):
    # El generador usa MAX(id_nota_credito)+1 (igual que numero_factura/numero_compra),
    # que en tests puede no coincidir con lo que uno esperaria a simple vista porque el
    # IDENTITY real no se resetea entre tests aunque las filas se limpien -- por eso no
    # se afirma un valor exacto ni un incremento de +1 puntual, solo formato y unicidad.
    cliente, factura, _ = _crear_factura(db_session)

    primera = NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente.id_cliente,
        id_factura_origen=factura.id_factura,
        monto=Decimal("10.00"),
        motivo="x",
        id_usuario=None,
    )
    segunda = NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente.id_cliente,
        id_factura_origen=factura.id_factura,
        monto=Decimal("5.00"),
        motivo="y",
        id_usuario=None,
    )

    assert primera.numero_nota_credito != segunda.numero_nota_credito
    for numero in (primera.numero_nota_credito, segunda.numero_nota_credito):
        assert numero.startswith("NC-")
        assert numero.split("-")[1].isdigit()


def test_crear_nota_credito_cliente_monto_invalido(db_session):
    cliente, factura, _ = _crear_factura(db_session)

    with pytest.raises(ValueError, match="mayor a cero"):
        NotaCreditoService.crear_nota_credito_cliente(
            db_session,
            id_cliente=cliente.id_cliente,
            id_factura_origen=factura.id_factura,
            monto=Decimal("0.00"),
            motivo="x",
            id_usuario=None,
        )


def test_listar_notas_credito_cliente(db_session):
    cliente, factura, admin = _crear_factura(db_session)
    NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente.id_cliente,
        id_factura_origen=factura.id_factura,
        monto=Decimal("10.00"),
        motivo="x",
        id_usuario=None,
    )
    NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente.id_cliente,
        id_factura_origen=factura.id_factura,
        monto=Decimal("5.00"),
        motivo="y",
        id_usuario=None,
    )

    notas = NotaCreditoService.listar_notas_credito_cliente(db_session, cliente.id_cliente, id_usuario=admin.id_usuario)
    assert len(notas) == 2


def test_listar_notas_credito_cliente_sin_usuario_autorizado_falla(db_session):
    cliente, _, _ = _crear_factura(db_session)
    with pytest.raises(PermisoDenegadoError):
        NotaCreditoService.listar_notas_credito_cliente(db_session, cliente.id_cliente)


def test_listar_notas_credito_clientes_reporte_filtra_por_cliente_y_pagina(db_session):
    """El reporte con filtros (fecha, cliente, estado, paginacion) es el que se usaria
    para armar lo que pida el SENIAT -- distinto del listado simple por cliente."""
    cliente_a, factura_a, admin = _crear_factura(db_session)
    cliente_b, factura_b, _ = _crear_factura(db_session)
    NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente_a.id_cliente,
        id_factura_origen=factura_a.id_factura,
        monto=Decimal("10.00"),
        motivo="x",
        id_usuario=None,
    )
    NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente_b.id_cliente,
        id_factura_origen=factura_b.id_factura,
        monto=Decimal("20.00"),
        motivo="y",
        id_usuario=None,
    )

    reporte = NotaCreditoService.listar_notas_credito_clientes(
        db_session, id_cliente=cliente_a.id_cliente, id_usuario=admin.id_usuario
    )
    assert reporte["total"] == 1
    assert reporte["items"][0].id_cliente == cliente_a.id_cliente

    reporte_todas = NotaCreditoService.listar_notas_credito_clientes(
        db_session, pagina=1, por_pagina=1, id_usuario=admin.id_usuario
    )
    assert reporte_todas["total"] == 2
    assert len(reporte_todas["items"]) == 1


def test_listar_notas_credito_clientes_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        NotaCreditoService.listar_notas_credito_clientes(db_session)


# --- aplicar_nota_credito_cliente -------------------------------------------------


def _crear_factura_credito(session, cliente, monto="80.00"):
    admin = crear_usuario_admin(session)
    vendedor = crear_vendedor(session)
    producto = crear_producto(session, cantidad_unidad=10)
    return VentaService.emitir_factura(
        session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": monto}],
    )


def test_aplicar_nota_credito_cliente_ok(db_session):
    cliente, factura_origen, admin = _crear_factura(db_session)
    nota = NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente.id_cliente,
        id_factura_origen=factura_origen.id_factura,
        monto=Decimal("50.00"),
        motivo="x",
        id_usuario=None,
    )
    # limite_credito por defecto de crear_cliente() es 0 -- no califica para credito.
    cliente.limite_credito = Decimal("1000.00")
    db_session.commit()
    factura_destino = _crear_factura_credito(db_session, cliente, monto="80.00")

    nota_actualizada = NotaCreditoService.aplicar_nota_credito_cliente(
        db_session,
        id_nota_credito=nota.id_nota_credito,
        id_factura_destino=factura_destino.id_factura,
        monto=Decimal("50.00"),
        id_usuario=admin.id_usuario,
    )

    assert nota_actualizada.saldo_disponible == Decimal("0.00")
    assert nota_actualizada.estado == "aplicada"

    cxc = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura_destino.id_factura).one()
    assert cxc.saldo_pendiente == Decimal("30.00")
    assert cxc.estado == "parcial"


def test_aplicar_nota_credito_cliente_parcial_deja_saldo_disponible(db_session):
    cliente, factura_origen, admin = _crear_factura(db_session)
    nota = NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente.id_cliente,
        id_factura_origen=factura_origen.id_factura,
        monto=Decimal("50.00"),
        motivo="x",
        id_usuario=None,
    )
    cliente.limite_credito = Decimal("1000.00")
    db_session.commit()
    factura_destino = _crear_factura_credito(db_session, cliente, monto="80.00")

    nota_actualizada = NotaCreditoService.aplicar_nota_credito_cliente(
        db_session,
        id_nota_credito=nota.id_nota_credito,
        id_factura_destino=factura_destino.id_factura,
        monto=Decimal("20.00"),
        id_usuario=admin.id_usuario,
    )

    assert nota_actualizada.saldo_disponible == Decimal("30.00")
    assert nota_actualizada.estado == "disponible"


def test_aplicar_nota_credito_cliente_excede_saldo_disponible_falla(db_session):
    cliente, factura_origen, admin = _crear_factura(db_session)
    nota = NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente.id_cliente,
        id_factura_origen=factura_origen.id_factura,
        monto=Decimal("20.00"),
        motivo="x",
        id_usuario=None,
    )
    cliente.limite_credito = Decimal("1000.00")
    db_session.commit()
    factura_destino = _crear_factura_credito(db_session, cliente, monto="80.00")

    with pytest.raises(ValueError, match="excede el saldo disponible"):
        NotaCreditoService.aplicar_nota_credito_cliente(
            db_session,
            id_nota_credito=nota.id_nota_credito,
            id_factura_destino=factura_destino.id_factura,
            monto=Decimal("50.00"),
            id_usuario=admin.id_usuario,
        )


def test_aplicar_nota_credito_cliente_excede_saldo_pendiente_factura_falla(db_session):
    cliente, factura_origen, admin = _crear_factura(db_session)
    nota = NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente.id_cliente,
        id_factura_origen=factura_origen.id_factura,
        monto=Decimal("100.00"),
        motivo="x",
        id_usuario=None,
    )
    cliente.limite_credito = Decimal("1000.00")
    db_session.commit()
    factura_destino = _crear_factura_credito(db_session, cliente, monto="30.00")

    with pytest.raises(ValueError, match="excede el saldo pendiente"):
        NotaCreditoService.aplicar_nota_credito_cliente(
            db_session,
            id_nota_credito=nota.id_nota_credito,
            id_factura_destino=factura_destino.id_factura,
            monto=Decimal("50.00"),
            id_usuario=admin.id_usuario,
        )


def test_aplicar_nota_credito_cliente_de_otro_cliente_falla(db_session):
    cliente_a, factura_origen_a, admin = _crear_factura(db_session)
    nota = NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente_a.id_cliente,
        id_factura_origen=factura_origen_a.id_factura,
        monto=Decimal("50.00"),
        motivo="x",
        id_usuario=None,
    )
    cliente_b = crear_cliente(db_session, limite_credito=Decimal("1000.00"), dias_credito=30)
    factura_destino_b = _crear_factura_credito(db_session, cliente_b, monto="80.00")

    with pytest.raises(ValueError, match="otro cliente"):
        NotaCreditoService.aplicar_nota_credito_cliente(
            db_session,
            id_nota_credito=nota.id_nota_credito,
            id_factura_destino=factura_destino_b.id_factura,
            monto=Decimal("50.00"),
            id_usuario=admin.id_usuario,
        )


def test_aplicar_nota_credito_cliente_ya_aplicada_falla(db_session):
    cliente, factura_origen, admin = _crear_factura(db_session)
    nota = NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente.id_cliente,
        id_factura_origen=factura_origen.id_factura,
        monto=Decimal("50.00"),
        motivo="x",
        id_usuario=None,
    )
    cliente.limite_credito = Decimal("1000.00")
    db_session.commit()
    factura_destino_1 = _crear_factura_credito(db_session, cliente, monto="50.00")
    NotaCreditoService.aplicar_nota_credito_cliente(
        db_session,
        id_nota_credito=nota.id_nota_credito,
        id_factura_destino=factura_destino_1.id_factura,
        monto=Decimal("50.00"),
        id_usuario=admin.id_usuario,
    )
    factura_destino_2 = _crear_factura_credito(db_session, cliente, monto="10.00")

    with pytest.raises(ValueError, match="no esta disponible"):
        NotaCreditoService.aplicar_nota_credito_cliente(
            db_session,
            id_nota_credito=nota.id_nota_credito,
            id_factura_destino=factura_destino_2.id_factura,
            monto=Decimal("5.00"),
            id_usuario=admin.id_usuario,
        )


def test_aplicar_nota_credito_cliente_sin_usuario_autorizado_falla(db_session):
    cliente, factura_origen, _ = _crear_factura(db_session)
    nota = NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente.id_cliente,
        id_factura_origen=factura_origen.id_factura,
        monto=Decimal("50.00"),
        motivo="x",
        id_usuario=None,
    )
    cliente.limite_credito = Decimal("1000.00")
    db_session.commit()
    factura_destino = _crear_factura_credito(db_session, cliente, monto="80.00")

    with pytest.raises(PermisoDenegadoError):
        NotaCreditoService.aplicar_nota_credito_cliente(
            db_session,
            id_nota_credito=nota.id_nota_credito,
            id_factura_destino=factura_destino.id_factura,
            monto=Decimal("50.00"),
            id_usuario=None,
        )


# --- devolver_nota_credito_cliente ------------------------------------------------


def test_devolver_nota_credito_cliente_efectivo_ok(db_session):
    cliente, factura_origen, admin = _crear_factura(db_session)
    nota = NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente.id_cliente,
        id_factura_origen=factura_origen.id_factura,
        monto=Decimal("50.00"),
        motivo="x",
        id_usuario=None,
    )
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("500.00"))

    nota_actualizada = NotaCreditoService.devolver_nota_credito_cliente(
        db_session,
        id_nota_credito=nota.id_nota_credito,
        monto=Decimal("50.00"),
        metodo_devolucion="efectivo",
        id_caja=caja.id_caja,
        id_autorizador=admin.id_usuario,
        id_usuario=admin.id_usuario,
    )

    assert nota_actualizada.saldo_disponible == Decimal("0.00")
    assert nota_actualizada.estado == "devuelta"

    salida = (
        db_session.query(CajaMovimiento)
        .filter(CajaMovimiento.id_caja == caja.id_caja, CajaMovimiento.tipo_movimiento == "salida")
        .first()
    )
    assert salida is not None
    assert salida.monto_movimiento == Decimal("50.00")
    assert CajaService.calcular_saldo_actual(db_session, caja.id_caja) == Decimal("450.00")


def test_devolver_nota_credito_cliente_bancario_ok(db_session):
    cliente, factura_origen, admin = _crear_factura(db_session)
    nota = NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente.id_cliente,
        id_factura_origen=factura_origen.id_factura,
        monto=Decimal("50.00"),
        motivo="x",
        id_usuario=None,
    )
    cuenta = crear_cuenta_bancaria(db_session, saldo_total_banco=Decimal("1000.00"))

    nota_actualizada = NotaCreditoService.devolver_nota_credito_cliente(
        db_session,
        id_nota_credito=nota.id_nota_credito,
        monto=Decimal("30.00"),
        metodo_devolucion="transferencia",
        id_cuenta_bancaria=cuenta.id_cuenta,
        referencia="REF9999",
        id_autorizador=admin.id_usuario,
        id_usuario=admin.id_usuario,
    )

    assert nota_actualizada.saldo_disponible == Decimal("20.00")
    assert nota_actualizada.estado == "disponible"

    cargo = (
        db_session.query(BancoMovimiento)
        .filter(BancoMovimiento.id_cuenta == cuenta.id_cuenta, BancoMovimiento.tipo_movimiento == "cargo")
        .first()
    )
    assert cargo is not None
    assert cargo.monto_movimiento == Decimal("30.00")
    assert cargo.referencia_movimiento == "REF9999"


def test_devolver_nota_credito_cliente_sin_autorizador_falla(db_session):
    cliente, factura_origen, admin = _crear_factura(db_session)
    nota = NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente.id_cliente,
        id_factura_origen=factura_origen.id_factura,
        monto=Decimal("50.00"),
        motivo="x",
        id_usuario=None,
    )
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("500.00"))

    with pytest.raises(ValueError, match="autorizacion de un supervisor"):
        NotaCreditoService.devolver_nota_credito_cliente(
            db_session,
            id_nota_credito=nota.id_nota_credito,
            monto=Decimal("50.00"),
            metodo_devolucion="efectivo",
            id_caja=caja.id_caja,
            id_autorizador=None,
            id_usuario=admin.id_usuario,
        )


def test_devolver_nota_credito_cliente_autorizador_sin_permiso_editar_falla(db_session):
    """El autorizador necesita 'notas_credito'/'editar', no solo 'crear' (que ya tiene
    cualquiera que pueda iniciar la devolucion) -- ver docstring del metodo para el
    porque de esta separacion de permisos."""
    cliente, factura_origen, admin = _crear_factura(db_session)
    nota = NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente.id_cliente,
        id_factura_origen=factura_origen.id_factura,
        monto=Decimal("50.00"),
        motivo="x",
        id_usuario=None,
    )
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("500.00"))

    rol = crear_rol(db_session)
    permiso_crear = crear_permiso(db_session, recurso="notas_credito", accion="crear")
    asignar_permiso(db_session, rol, permiso_crear)
    autorizador_sin_editar = crear_usuario(db_session, id_rol=rol.id_rol)

    with pytest.raises(PermisoDenegadoError):
        NotaCreditoService.devolver_nota_credito_cliente(
            db_session,
            id_nota_credito=nota.id_nota_credito,
            monto=Decimal("50.00"),
            metodo_devolucion="efectivo",
            id_caja=caja.id_caja,
            id_autorizador=autorizador_sin_editar.id_usuario,
            id_usuario=admin.id_usuario,
        )


def test_devolver_nota_credito_cliente_efectivo_saldo_insuficiente_falla(db_session):
    cliente, factura_origen, admin = _crear_factura(db_session)
    nota = NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente.id_cliente,
        id_factura_origen=factura_origen.id_factura,
        monto=Decimal("50.00"),
        motivo="x",
        id_usuario=None,
    )
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("0.00"))

    with pytest.raises(ValueError, match="no tiene saldo suficiente"):
        NotaCreditoService.devolver_nota_credito_cliente(
            db_session,
            id_nota_credito=nota.id_nota_credito,
            monto=Decimal("50.00"),
            metodo_devolucion="efectivo",
            id_caja=caja.id_caja,
            id_autorizador=admin.id_usuario,
            id_usuario=admin.id_usuario,
        )


def test_devolver_nota_credito_cliente_bancario_sin_referencia_falla(db_session):
    cliente, factura_origen, admin = _crear_factura(db_session)
    nota = NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente.id_cliente,
        id_factura_origen=factura_origen.id_factura,
        monto=Decimal("50.00"),
        motivo="x",
        id_usuario=None,
    )
    cuenta = crear_cuenta_bancaria(db_session, saldo_total_banco=Decimal("1000.00"))

    with pytest.raises(ValueError, match="referencia bancaria"):
        NotaCreditoService.devolver_nota_credito_cliente(
            db_session,
            id_nota_credito=nota.id_nota_credito,
            monto=Decimal("30.00"),
            metodo_devolucion="transferencia",
            id_cuenta_bancaria=cuenta.id_cuenta,
            id_autorizador=admin.id_usuario,
            id_usuario=admin.id_usuario,
        )


def test_devolver_nota_credito_cliente_excede_saldo_disponible_falla(db_session):
    cliente, factura_origen, admin = _crear_factura(db_session)
    nota = NotaCreditoService.crear_nota_credito_cliente(
        db_session,
        id_cliente=cliente.id_cliente,
        id_factura_origen=factura_origen.id_factura,
        monto=Decimal("20.00"),
        motivo="x",
        id_usuario=None,
    )
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("500.00"))

    with pytest.raises(ValueError, match="excede el saldo disponible"):
        NotaCreditoService.devolver_nota_credito_cliente(
            db_session,
            id_nota_credito=nota.id_nota_credito,
            monto=Decimal("50.00"),
            metodo_devolucion="efectivo",
            id_caja=caja.id_caja,
            id_autorizador=admin.id_usuario,
            id_usuario=admin.id_usuario,
        )


# --- crear_nota_credito_proveedor -------------------------------------------------


def test_crear_nota_credito_proveedor_ok(db_session):
    proveedor, compra, _ = _crear_compra(db_session)

    nota = NotaCreditoService.crear_nota_credito_proveedor(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_compra_origen=compra.id_compra,
        monto=Decimal("15.00"),
        motivo="Compra anulada con pago ya aplicado",
        id_usuario=None,
    )

    assert nota.id_nota_credito is not None
    assert nota.saldo_disponible == Decimal("15.00")
    assert nota.estado == "disponible"


def test_crear_nota_credito_proveedor_monto_invalido(db_session):
    proveedor, compra, _ = _crear_compra(db_session)

    with pytest.raises(ValueError, match="mayor a cero"):
        NotaCreditoService.crear_nota_credito_proveedor(
            db_session,
            id_proveedor=proveedor.id_proveedor,
            id_compra_origen=compra.id_compra,
            monto=Decimal("-5.00"),
            motivo="x",
            id_usuario=None,
        )


def test_listar_notas_credito_proveedor(db_session):
    proveedor, compra, admin = _crear_compra(db_session)
    NotaCreditoService.crear_nota_credito_proveedor(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        id_compra_origen=compra.id_compra,
        monto=Decimal("15.00"),
        motivo="x",
        id_usuario=None,
    )

    notas = NotaCreditoService.listar_notas_credito_proveedor(
        db_session, proveedor.id_proveedor, id_usuario=admin.id_usuario
    )
    assert len(notas) == 1


def test_listar_notas_credito_proveedor_sin_usuario_autorizado_falla(db_session):
    proveedor, _, _ = _crear_compra(db_session)
    with pytest.raises(PermisoDenegadoError):
        NotaCreditoService.listar_notas_credito_proveedor(db_session, proveedor.id_proveedor)

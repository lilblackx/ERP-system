"""Hallazgos de la revision de seguridad / perdida de dinero (2026-10-22): escalada a ADMIN
via 'usuarios'/'editar', sobreabono que no entraba a caja, stock pisado al editar un
producto, limite de credito que ignoraba la deuda BCV, salidas manuales de caja sin saldo y
saldo bancario editable directo."""

from decimal import Decimal

import pytest

from app.db.models import CajaMovimiento, NotaCreditoCliente, Permiso, Rol
from app.services.cuentas_bancarias import CuentaBancariaService
from app.services.inventario import ProductoService
from app.services.pagos import PagoService
from app.services.permisos import PermisoDenegadoError
from app.services.tesoreria import CajaService
from app.services.usuarios import UsuarioService
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
)

CLAVE_VALIDA = "Clave#Segura123"


def _encargado_de_usuarios(db_session):
    """Usuario NO admin con 'usuarios'/'crear' y 'usuarios'/'editar'."""
    rol = crear_rol(db_session, nombre="ENCARGADO_USUARIOS")
    for accion in ("crear", "editar"):
        permiso = db_session.query(Permiso).filter_by(recurso="usuarios", accion=accion).first()
        asignar_permiso(db_session, rol, permiso or crear_permiso(db_session, recurso="usuarios", accion=accion))
    return crear_usuario(db_session, id_rol=rol.id_rol, estado="ACTIVO")


def _rol_admin(db_session):
    return db_session.query(Rol).filter_by(nombre="ADMIN").one()


# ── Usuarios: 'usuarios'/'editar' no debe equivaler a ser ADMIN ─────────────────


def test_encargado_de_usuarios_no_puede_darse_rol_admin(db_session):
    crear_usuario_admin(db_session)
    encargado = _encargado_de_usuarios(db_session)

    with pytest.raises(PermisoDenegadoError, match="administrador"):
        UsuarioService.editar_usuario(
            db_session,
            encargado.id_usuario,
            {"id_rol": _rol_admin(db_session).id_rol},
            realizado_por=encargado.id_usuario,
        )


def test_encargado_de_usuarios_no_puede_cambiar_clave_de_un_admin(db_session):
    admin = crear_usuario_admin(db_session)
    encargado = _encargado_de_usuarios(db_session)

    with pytest.raises(PermisoDenegadoError):
        UsuarioService.editar_usuario(
            db_session, admin.id_usuario, {}, nueva_clave=CLAVE_VALIDA, realizado_por=encargado.id_usuario
        )


def test_encargado_de_usuarios_no_puede_crear_admins(db_session):
    crear_usuario_admin(db_session)
    encargado = _encargado_de_usuarios(db_session)

    with pytest.raises(PermisoDenegadoError):
        UsuarioService.crear_usuario(
            db_session,
            nombre_usuario="nuevo_admin",
            nombre=None,
            apellido=None,
            email="nuevo.admin@example.com",
            clave=CLAVE_VALIDA,
            id_rol=_rol_admin(db_session).id_rol,
            realizado_por=encargado.id_usuario,
        )


def test_encargado_de_usuarios_si_gestiona_usuarios_comunes(db_session):
    encargado = _encargado_de_usuarios(db_session)
    rol_comun = crear_rol(db_session, nombre="CAJERO_TEST")

    usuario = UsuarioService.crear_usuario(
        db_session,
        nombre_usuario="cajero_nuevo",
        nombre=None,
        apellido=None,
        email="cajero.nuevo@example.com",
        clave=CLAVE_VALIDA,
        id_rol=rol_comun.id_rol,
        realizado_por=encargado.id_usuario,
    )

    assert usuario.id_rol == rol_comun.id_rol


def test_no_se_puede_quitar_el_rol_al_unico_admin(db_session):
    admin = crear_usuario_admin(db_session)
    otro_rol = crear_rol(db_session, nombre="OTRO_ROL")

    with pytest.raises(ValueError, match="unico administrador"):
        UsuarioService.editar_usuario(
            db_session, admin.id_usuario, {"id_rol": otro_rol.id_rol}, realizado_por=admin.id_usuario
        )


# ── Abono general: el sobreabono entra a la caja ────────────────────────────────


def test_sobreabono_entra_a_la_caja_y_queda_como_nota_de_credito(db_session):
    admin = crear_usuario_admin(db_session)
    cliente = crear_cliente(db_session, limite_credito=Decimal("500.00"))
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=100)
    crear_precio_producto(db_session, producto, "100.00")
    VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
    )
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)

    resultado = PagoService.aplicar_abono_general_cliente(
        db_session,
        id_cliente=cliente.id_cliente,
        monto_abono=Decimal("130.00"),
        tasa_cambio=Decimal("40.00"),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )

    # Entraron $130 fisicos: $100 a la factura + $30 de saldo a favor.
    assert CajaService.calcular_saldo_actual(db_session, caja.id_caja) == Decimal("130.00")
    nota = db_session.get(NotaCreditoCliente, resultado["nota_credito_id"])
    assert nota.saldo_disponible == Decimal("30.00")
    assert nota.numero_nota_credito.startswith("NC-")
    assert db_session.query(CajaMovimiento).filter_by(id_caja=caja.id_caja).count() == 2


# ── Inventario: guardar un producto no pisa el stock ajeno ──────────────────────


def test_ajuste_de_stock_con_valor_desactualizado_se_rechaza(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=10)

    # El usuario abrio el producto viendo 10, pero otra estacion vendio 2 mientras tanto.
    producto.cantidad_unidad = Decimal("8")
    db_session.commit()

    with pytest.raises(ValueError, match="cambio mientras lo editaba"):
        ProductoService.actualizar(
            db_session,
            producto.id_producto,
            id_usuario=admin.id_usuario,
            motivo="Conteo fisico",
            cantidad_unidad_anterior=Decimal("10"),
            cantidad_unidad=Decimal("15"),
        )


def test_ajuste_de_stock_sin_motivo_se_rechaza(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=10)

    with pytest.raises(ValueError, match="motivo"):
        ProductoService.actualizar(
            db_session,
            producto.id_producto,
            id_usuario=admin.id_usuario,
            cantidad_unidad_anterior=Decimal("10"),
            cantidad_unidad=Decimal("12"),
        )


def test_ajuste_de_stock_con_motivo_y_valor_vigente_funciona(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=10)

    actualizado = ProductoService.actualizar(
        db_session,
        producto.id_producto,
        id_usuario=admin.id_usuario,
        motivo="Conteo fisico",
        cantidad_unidad_anterior=Decimal("10"),
        cantidad_unidad=Decimal("12"),
    )

    assert actualizado.cantidad_unidad == Decimal("12")


# ── Limite de credito: cuenta la deuda BCV ──────────────────────────────────────


def test_factura_normal_a_credito_cuenta_la_deuda_bcv_del_cliente(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    cliente = crear_cliente(db_session, limite_credito=Decimal("150.00"))
    producto = crear_producto(db_session, cantidad_unidad=100)
    crear_precio_producto(db_session, producto, "100.00")
    VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
        porcentaje_bcv=Decimal("10"),
    )

    assert VentaService.consultar_limite_disponible(db_session, cliente.id_cliente, id_usuario=admin.id_usuario)[
        "deuda_actual"
    ] == Decimal("100.00")
    with pytest.raises(ValueError, match="limite de credito"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="credito",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
        )


# ── Caja: salidas manuales ──────────────────────────────────────────────────────


def test_salida_manual_mayor_al_saldo_de_caja_se_rechaza(db_session):
    admin = crear_usuario_admin(db_session)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("20.00"))

    with pytest.raises(ValueError, match="saldo suficiente"):
        CajaService.registrar_movimiento_manual(
            db_session,
            caja.id_caja,
            tipo="salida",
            monto=Decimal("50.00"),
            descripcion="Retiro",
            id_usuario=admin.id_usuario,
        )


def test_movimiento_manual_sin_motivo_se_rechaza(db_session):
    admin = crear_usuario_admin(db_session)
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=Decimal("20.00"))

    with pytest.raises(ValueError, match="motivo"):
        CajaService.registrar_movimiento_manual(
            db_session,
            caja.id_caja,
            tipo="salida",
            monto=Decimal("5.00"),
            descripcion="  ",
            id_usuario=admin.id_usuario,
        )


# ── Bancos: el saldo no se edita directo ────────────────────────────────────────


def test_editar_saldo_de_cuenta_bancaria_directo_se_rechaza(db_session):
    admin = crear_usuario_admin(db_session)
    cuenta = crear_cuenta_bancaria(db_session, saldo_total_banco=Decimal("100.00"))

    with pytest.raises(ValueError, match="no se edita"):
        CuentaBancariaService.actualizar(
            db_session, cuenta.id_cuenta, id_usuario=admin.id_usuario, saldo_total_banco=Decimal("999999.00")
        )

"""Pedidos de venta con reserva de stock (migrations/0100, app/services/pedidos.py + reservas_stock.py).

Contra SQL Server real: la reserva depende de la vista y de la hora del servidor, y la conversion a factura
pasa por los triggers de stock de factura_detalle.
"""

import threading
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.db.models import FacturaVenta, Pedido, Permiso
from app.services.pedidos import PedidoService
from app.services.permisos import PermisoDenegadoError
from app.services.reservas_stock import reservado_por_producto
from app.services.ventas import VentaService
from tests.factories import (
    asignar_permiso,
    crear_cliente,
    crear_permiso,
    crear_precio_producto,
    crear_producto,
    crear_rol,
    crear_usuario,
    crear_usuario_admin,
    crear_vendedor,
    pago_contado,
)


def _permiso_pedidos(db, accion):
    """El permiso ('pedidos', accion) es unico en el catalogo: se reutiliza si otro usuario del test ya lo creo."""
    existente = db.query(Permiso).filter_by(recurso="pedidos", accion=accion).first()
    return existente or crear_permiso(db, recurso="pedidos", accion=accion)


def _usuario_vendedor(db, vendedor, acciones=("ver", "crear")):
    rol = crear_rol(db)
    for accion in acciones:
        asignar_permiso(db, rol, _permiso_pedidos(db, accion))
    return crear_usuario(db, id_rol=rol.id_rol, id_vendedor_usuario=vendedor.id_vendedor)


def _escenario(db, stock=50, precio="20.00", **producto):
    admin = crear_usuario_admin(db)
    vendedor = crear_vendedor(db)
    usuario = _usuario_vendedor(db, vendedor)
    cliente = crear_cliente(db, vendedor_cliente=vendedor.id_vendedor)
    prod = crear_producto(db, cantidad_unidad=stock, **producto)
    crear_precio_producto(db, prod, precio)
    return SimpleNamespace(admin=admin, vendedor=vendedor, usuario=usuario, cliente=cliente, producto=prod)


def _items(esc, cantidad=5, precio="20.00", tipo_venta="unidad"):
    return [
        {
            "id_producto": esc.producto.id_producto,
            "cantidad": cantidad,
            "precio_unitario": precio,
            "tipo_venta": tipo_venta,
        }
    ]


def _crear(db, esc, cantidad=5, **kw):
    """Pedido hecho por el propio vendedor (el camino de la app movil)."""
    items = kw.pop("items", None)
    return PedidoService.crear_pedido(
        db,
        id_usuario=esc.usuario.id_usuario,
        id_cliente=kw.pop("id_cliente", esc.cliente.id_cliente),
        items=_items(esc, cantidad) if items is None else items,
        **kw,
    )


def _reservado(db, esc):
    return reservado_por_producto(db, [esc.producto.id_producto])[esc.producto.id_producto]


# -- Crear: la reserva -----------------------------------------------------------------------------------------


def test_un_pedido_aparta_stock_sin_tocar_el_inventario_real(db_session):
    esc = _escenario(db_session, stock=50)

    pedido = _crear(db_session, esc, cantidad=5)

    db_session.refresh(esc.producto)
    assert pedido.estado == "ENVIADO"
    assert pedido.numero_pedido.startswith("PED-")
    assert pedido.id_vendedor == esc.vendedor.id_vendedor
    assert esc.producto.cantidad_unidad == Decimal("50.00")  # el stock real no se mueve hasta facturar
    assert _reservado(db_session, esc) == Decimal("5.00")


def test_un_bulto_aparta_las_unidades_de_la_caja(db_session):
    esc = _escenario(db_session, stock=100, cantidad_caja=Decimal("12"))

    PedidoService.crear_pedido(
        db_session,
        id_usuario=esc.usuario.id_usuario,
        id_cliente=esc.cliente.id_cliente,
        items=_items(esc, cantidad=2, tipo_venta="bulto"),
    )

    assert _reservado(db_session, esc) == Decimal("24.00")


def test_el_disponible_descuenta_lo_apartado_por_otros_pedidos(db_session):
    esc = _escenario(db_session, stock=10)
    _crear(db_session, esc, cantidad=8)

    with pytest.raises(ValueError, match="apartadas por otros pedidos"):
        _crear(db_session, esc, cantidad=5)

    assert _reservado(db_session, esc) == Decimal("8.00")


def test_un_pedido_no_puede_dejar_el_stock_bajo_el_minimo(db_session):
    esc = _escenario(db_session, stock=10, cantidad_minima=Decimal("4"))

    with pytest.raises(ValueError, match="mínimo"):
        _crear(db_session, esc, cantidad=7)

    _crear(db_session, esc, cantidad=6)  # deja 4: justo el minimo


def test_reenviar_el_mismo_pedido_devuelve_el_existente_sin_apartar_dos_veces(db_session):
    esc = _escenario(db_session, stock=50)

    primero = _crear(db_session, esc, cantidad=5, id_cliente_local="movil-abc-1")
    segundo = _crear(db_session, esc, cantidad=5, id_cliente_local="movil-abc-1")

    assert segundo.id_pedido == primero.id_pedido
    assert db_session.query(Pedido).count() == 1
    assert _reservado(db_session, esc) == Decimal("5.00")


def test_un_credito_exige_que_el_cliente_tenga_dias_de_credito(db_session):
    esc = _escenario(db_session)
    sin_credito = crear_cliente(db_session, vendedor_cliente=esc.vendedor.id_vendedor, dias_credito=0)

    with pytest.raises(ValueError, match="no tiene credito"):
        _crear(db_session, esc, id_cliente=sin_credito.id_cliente, condicion_pago="credito")


def test_los_items_invalidos_se_rechazan(db_session):
    esc = _escenario(db_session)

    with pytest.raises(ValueError, match="al menos un item"):
        _crear(db_session, esc, items=[])
    with pytest.raises(ValueError, match="cantidad mayor a cero"):
        _crear(db_session, esc, cantidad=0)
    # El texto exacto: el CHECK de la base tambien menciona tipo_venta, y sin esto el test pasaria aunque la
    # validacion de Python no existiera (el mensaje del usuario seria el del trigger, no este).
    with pytest.raises(ValueError, match=r"tipo_venta debe ser 'bulto' o 'unidad'"):
        _crear(db_session, esc, items=_items(esc, tipo_venta="caja"))
    assert db_session.query(Pedido).count() == 0


@pytest.mark.parametrize("campo", ["cantidad", "precio_unitario"])
@pytest.mark.parametrize("valor", ["NaN", "Infinity", "-Infinity", "1e400", "no-es-un-numero", None])
def test_una_cantidad_o_un_precio_no_finito_o_enorme_se_rechaza_con_valueerror(db_session, campo, valor):
    """Un pedido llega de un celular: ni un 'NaN' (que antes escapaba como InvalidOperation) ni un 'Infinity' o
    un '1e400' (que antes pasaban la validacion) pueden llegar a la base."""
    esc = _escenario(db_session)
    item = {**_items(esc)[0], campo: valor}

    with pytest.raises(ValueError):
        _crear(db_session, esc, items=[item])

    assert db_session.query(Pedido).count() == 0
    assert _reservado(db_session, esc) == Decimal("0")


# -- Alcance y permisos ----------------------------------------------------------------------------------------


def test_un_vendedor_no_puede_pedir_para_un_cliente_de_otro(db_session):
    esc = _escenario(db_session)
    otro_vendedor = crear_vendedor(db_session)
    cliente_ajeno = crear_cliente(db_session, vendedor_cliente=otro_vendedor.id_vendedor)

    with pytest.raises(PermisoDenegadoError, match="no esta asignado"):
        _crear(db_session, esc, id_cliente=cliente_ajeno.id_cliente)


def test_un_vendedor_siempre_pide_a_su_nombre_aunque_mande_otro_vendedor(db_session):
    esc = _escenario(db_session)
    otro_vendedor = crear_vendedor(db_session)

    pedido = _crear(db_session, esc, id_vendedor=otro_vendedor.id_vendedor)

    assert pedido.id_vendedor == esc.vendedor.id_vendedor


def test_caja_o_admin_deben_indicar_el_vendedor(db_session):
    esc = _escenario(db_session)

    with pytest.raises(ValueError, match="vendedor es obligatorio"):
        PedidoService.crear_pedido(db_session, esc.admin.id_usuario, esc.cliente.id_cliente, _items(esc))

    pedido = PedidoService.crear_pedido(
        db_session, esc.admin.id_usuario, esc.cliente.id_cliente, _items(esc), id_vendedor=esc.vendedor.id_vendedor
    )
    assert pedido.id_vendedor == esc.vendedor.id_vendedor


def test_sin_permiso_no_se_crea_ni_se_ve_un_pedido(db_session):
    esc = _escenario(db_session)
    sin_permisos = crear_usuario(db_session, id_rol=crear_rol(db_session).id_rol)

    with pytest.raises(PermisoDenegadoError):
        PedidoService.crear_pedido(db_session, sin_permisos.id_usuario, esc.cliente.id_cliente, _items(esc))
    with pytest.raises(PermisoDenegadoError):
        PedidoService.listar_pedidos(db_session, sin_permisos.id_usuario)


def test_un_vendedor_solo_ve_sus_pedidos(db_session):
    esc = _escenario(db_session)
    otro_vendedor = crear_vendedor(db_session)
    otro_usuario = _usuario_vendedor(db_session, otro_vendedor)
    otro_cliente = crear_cliente(db_session, vendedor_cliente=otro_vendedor.id_vendedor)
    mio = _crear(db_session, esc, cantidad=2)
    ajeno = PedidoService.crear_pedido(
        db_session, otro_usuario.id_usuario, otro_cliente.id_cliente, _items(esc, cantidad=3)
    )

    visibles = PedidoService.listar_pedidos(db_session, esc.usuario.id_usuario, id_vendedor=otro_vendedor.id_vendedor)

    assert [p.id_pedido for p in visibles["items"]] == [mio.id_pedido]  # pidio el filtro de otro: se ignora
    with pytest.raises(PermisoDenegadoError, match="otro vendedor"):
        PedidoService.obtener_pedido(db_session, ajeno.id_pedido, esc.usuario.id_usuario)
    assert len(PedidoService.listar_pedidos(db_session, esc.admin.id_usuario)["items"]) == 2


def test_el_listado_filtra_por_estado(db_session):
    esc = _escenario(db_session)
    uno = _crear(db_session, esc, cantidad=1)
    dos = _crear(db_session, esc, cantidad=1)
    PedidoService.aprobar_pedido(db_session, dos.id_pedido, esc.admin.id_usuario)

    aprobados = PedidoService.listar_pedidos(db_session, esc.admin.id_usuario, estado="APROBADO")
    enviados = PedidoService.listar_pedidos(db_session, esc.admin.id_usuario, estado="ENVIADO")

    assert [p.id_pedido for p in aprobados["items"]] == [dos.id_pedido]
    assert [p.id_pedido for p in enviados["items"]] == [uno.id_pedido]
    with pytest.raises(ValueError, match="estado debe ser"):
        PedidoService.listar_pedidos(db_session, esc.admin.id_usuario, estado="NADA")


# -- Revision: aprobar, rechazar, anular -----------------------------------------------------------------------


def test_aprobar_exige_el_permiso_de_aprobar(db_session):
    esc = _escenario(db_session)
    pedido = _crear(db_session, esc)

    with pytest.raises(PermisoDenegadoError):
        PedidoService.aprobar_pedido(db_session, pedido.id_pedido, esc.usuario.id_usuario)


def test_aprobar_mantiene_la_reserva_y_ya_no_vence(db_session):
    esc = _escenario(db_session)
    pedido = _crear(db_session, esc, cantidad=5)
    assert pedido.fecha_vencimiento_reserva is not None

    aprobado = PedidoService.aprobar_pedido(db_session, pedido.id_pedido, esc.admin.id_usuario)

    assert aprobado.estado == "APROBADO"
    assert aprobado.fecha_vencimiento_reserva is None
    assert aprobado.id_usuario_revisor == esc.admin.id_usuario
    assert _reservado(db_session, esc) == Decimal("5.00")
    with pytest.raises(ValueError, match="no se puede aprobar"):
        PedidoService.aprobar_pedido(db_session, pedido.id_pedido, esc.admin.id_usuario)


def test_rechazar_libera_la_reserva_y_pide_motivo(db_session):
    esc = _escenario(db_session)
    pedido = _crear(db_session, esc, cantidad=5)

    with pytest.raises(ValueError, match="motivo"):
        PedidoService.rechazar_pedido(db_session, pedido.id_pedido, "  ", esc.admin.id_usuario)
    rechazado = PedidoService.rechazar_pedido(db_session, pedido.id_pedido, "Cliente con deuda", esc.admin.id_usuario)

    assert rechazado.estado == "RECHAZADO"
    assert rechazado.motivo == "Cliente con deuda"
    assert _reservado(db_session, esc) == Decimal("0")


def test_el_vendedor_anula_su_pedido_enviado_y_se_libera_el_stock(db_session):
    esc = _escenario(db_session)
    pedido = _crear(db_session, esc, cantidad=5)

    anulado = PedidoService.anular_pedido(db_session, pedido.id_pedido, esc.usuario.id_usuario, "Me equivoque")

    assert anulado.estado == "ANULADO"
    assert _reservado(db_session, esc) == Decimal("0")


def test_el_vendedor_no_anula_uno_aprobado_ni_el_de_otro(db_session):
    esc = _escenario(db_session)
    otro_vendedor = crear_vendedor(db_session)
    otro_usuario = _usuario_vendedor(db_session, otro_vendedor)
    pedido = _crear(db_session, esc, cantidad=5)

    with pytest.raises(PermisoDenegadoError, match="otro vendedor"):
        PedidoService.anular_pedido(db_session, pedido.id_pedido, otro_usuario.id_usuario)

    PedidoService.aprobar_pedido(db_session, pedido.id_pedido, esc.admin.id_usuario)
    with pytest.raises(PermisoDenegadoError, match="pide a caja"):
        PedidoService.anular_pedido(db_session, pedido.id_pedido, esc.usuario.id_usuario)

    anulado = PedidoService.anular_pedido(db_session, pedido.id_pedido, esc.admin.id_usuario, "Cliente cancelo")
    assert anulado.estado == "ANULADO"
    assert _reservado(db_session, esc) == Decimal("0")


def test_el_vendedor_puede_anular_su_pedido_vencido(db_session):
    esc = _escenario(db_session)
    pedido = _crear(db_session, esc, cantidad=5)
    db_session.execute(text("UPDATE dbo.pedidos SET estado = 'VENCIDO' WHERE id_pedido = :i"), {"i": pedido.id_pedido})
    db_session.commit()

    anulado = PedidoService.anular_pedido(db_session, pedido.id_pedido, esc.usuario.id_usuario, "Ya no lo quiere")

    assert anulado.estado == "ANULADO"
    assert anulado.motivo == "Ya no lo quiere"


# -- Vencimiento -----------------------------------------------------------------------------------------------


def _vencer_a_mano(db, pedido):
    db.execute(
        text("UPDATE dbo.pedidos SET fecha_vencimiento_reserva = DATEADD(HOUR, -1, GETDATE()) WHERE id_pedido = :i"),
        {"i": pedido.id_pedido},
    )
    db.commit()
    db.expire_all()


def test_un_pedido_vencido_suelta_el_stock_sin_esperar_a_ningun_job(db_session):
    esc = _escenario(db_session, stock=10)
    pedido = _crear(db_session, esc, cantidad=8)
    assert _reservado(db_session, esc) == Decimal("8.00")

    _vencer_a_mano(db_session, pedido)

    assert _reservado(db_session, esc) == Decimal("0")  # sigue ENVIADO en la tabla, pero ya no aparta
    _crear(db_session, esc, cantidad=9)  # otro pedido puede tomar ese stock


def test_vencer_pendientes_marca_el_estado_y_no_toca_los_vigentes(db_session):
    esc = _escenario(db_session)
    vencido = _crear(db_session, esc, cantidad=1)
    vigente = _crear(db_session, esc, cantidad=1)
    _vencer_a_mano(db_session, vencido)

    marcados = PedidoService.vencer_pendientes(db_session)

    assert marcados == 1
    assert db_session.get(Pedido, vencido.id_pedido).estado == "VENCIDO"
    assert db_session.get(Pedido, vigente.id_pedido).estado == "ENVIADO"


def test_aprobar_un_vencido_revisa_el_stock_que_otro_pudo_tomar(db_session):
    esc = _escenario(db_session, stock=10)
    viejo = _crear(db_session, esc, cantidad=8)
    _vencer_a_mano(db_session, viejo)
    PedidoService.vencer_pendientes(db_session)
    _crear(db_session, esc, cantidad=6)  # toma el stock que solto el vencido

    with pytest.raises(ValueError, match="Stock insuficiente"):
        PedidoService.aprobar_pedido(db_session, viejo.id_pedido, esc.admin.id_usuario)

    assert db_session.get(Pedido, viejo.id_pedido).estado == "VENCIDO"


def test_aprobar_un_vencido_con_stock_disponible_lo_rescata(db_session):
    esc = _escenario(db_session, stock=10)
    viejo = _crear(db_session, esc, cantidad=8)
    _vencer_a_mano(db_session, viejo)
    PedidoService.vencer_pendientes(db_session)

    rescatado = PedidoService.aprobar_pedido(db_session, viejo.id_pedido, esc.admin.id_usuario)

    assert rescatado.estado == "APROBADO"
    assert _reservado(db_session, esc) == Decimal("8.00")


# -- La factura respeta la reserva -----------------------------------------------------------------------------


def _factura_directa(db, esc, cantidad):
    return VentaService.emitir_factura(
        db,
        id_cliente=esc.cliente.id_cliente,
        id_usuario=esc.admin.id_usuario,
        id_vendedor=esc.vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db),
        items=_items(esc, cantidad),
    )


def test_una_factura_directa_no_puede_vender_lo_que_un_pedido_tiene_apartado(db_session):
    esc = _escenario(db_session, stock=10)
    _crear(db_session, esc, cantidad=8)

    with pytest.raises(ValueError, match="Stock insuficiente"):
        _factura_directa(db_session, esc, cantidad=5)

    _factura_directa(db_session, esc, cantidad=2)  # lo no apartado si se puede vender


def test_una_factura_directa_vende_el_stock_liberado_por_un_pedido_anulado(db_session):
    esc = _escenario(db_session, stock=10)
    pedido = _crear(db_session, esc, cantidad=8)
    PedidoService.anular_pedido(db_session, pedido.id_pedido, esc.admin.id_usuario)

    _factura_directa(db_session, esc, cantidad=9)


# -- Convertir en factura --------------------------------------------------------------------------------------


def test_convertir_un_pedido_aprobado_factura_descuenta_stock_y_cierra_el_pedido(db_session):
    esc = _escenario(db_session, stock=10)
    pedido = _crear(db_session, esc, cantidad=8)  # apartado 8 de 10: un pedido no se bloquea a si mismo
    PedidoService.aprobar_pedido(db_session, pedido.id_pedido, esc.admin.id_usuario)

    factura = PedidoService.convertir_a_factura(
        db_session, pedido.id_pedido, esc.admin.id_usuario, pagos=pago_contado(db_session)
    )

    db_session.refresh(esc.producto)
    db_session.refresh(pedido)
    assert factura.total_venta == Decimal("160.00")
    assert factura.id_vendedor == esc.vendedor.id_vendedor
    assert factura.id_cliente_factura == esc.cliente.id_cliente
    assert esc.producto.cantidad_unidad == Decimal("2.00")
    assert pedido.estado == "FACTURADO"
    assert pedido.id_factura == factura.id_factura
    assert _reservado(db_session, esc) == Decimal("0")  # facturado ya no aparta: el stock real ya bajo


def test_no_se_factura_dos_veces_el_mismo_pedido(db_session):
    esc = _escenario(db_session, stock=50)
    pedido = _crear(db_session, esc, cantidad=5)
    PedidoService.aprobar_pedido(db_session, pedido.id_pedido, esc.admin.id_usuario)
    PedidoService.convertir_a_factura(
        db_session, pedido.id_pedido, esc.admin.id_usuario, pagos=pago_contado(db_session)
    )

    with pytest.raises(ValueError, match="solo se factura uno APROBADO"):
        PedidoService.convertir_a_factura(
            db_session, pedido.id_pedido, esc.admin.id_usuario, pagos=pago_contado(db_session)
        )

    assert db_session.query(FacturaVenta).count() == 1


def test_solo_se_factura_un_pedido_aprobado(db_session):
    esc = _escenario(db_session)
    pedido = _crear(db_session, esc)

    with pytest.raises(ValueError, match="solo se factura uno APROBADO"):
        PedidoService.convertir_a_factura(db_session, pedido.id_pedido, esc.admin.id_usuario)


def test_convertir_exige_el_permiso_de_aprobar(db_session):
    esc = _escenario(db_session)
    pedido = _crear(db_session, esc)
    PedidoService.aprobar_pedido(db_session, pedido.id_pedido, esc.admin.id_usuario)

    with pytest.raises(PermisoDenegadoError):
        PedidoService.convertir_a_factura(db_session, pedido.id_pedido, esc.usuario.id_usuario)


def test_si_la_factura_falla_el_pedido_sigue_aprobado_y_apartando(db_session):
    esc = _escenario(db_session, stock=10, precio="20.00")
    pedido = _crear(db_session, esc, cantidad=5, items=_items(esc, cantidad=5, precio="10.00"))  # bajo la lista
    PedidoService.aprobar_pedido(db_session, pedido.id_pedido, esc.admin.id_usuario)

    with pytest.raises((ValueError, PermisoDenegadoError)):
        PedidoService.convertir_a_factura(
            db_session, pedido.id_pedido, esc.admin.id_usuario, pagos=pago_contado(db_session)
        )

    db_session.rollback()
    db_session.expire_all()
    assert db_session.get(Pedido, pedido.id_pedido).estado == "APROBADO"
    assert _reservado(db_session, esc) == Decimal("5.00")
    assert db_session.query(FacturaVenta).count() == 0


def _facturar_con_id_pedido(db, esc, id_pedido):
    return VentaService.emitir_factura(
        db,
        id_cliente=esc.cliente.id_cliente,
        id_usuario=esc.admin.id_usuario,
        id_vendedor=esc.vendedor.id_vendedor,
        condicion_pago="contado",
        pagos=pago_contado(db),
        items=_items(esc),
        id_pedido=id_pedido,
    )


@pytest.mark.parametrize("estado", ["ENVIADO", "RECHAZADO", "ANULADO", "FACTURADO"])
def test_emitir_factura_con_id_pedido_rechaza_un_pedido_que_no_esta_aprobado(db_session, estado):
    """`convertir_a_factura` ya lo comprueba, pero `emitir_factura(id_pedido=...)` es publico: la regla tiene que
    sostenerse tambien cuando se llama directo, sin pasar por el servicio de pedidos."""
    esc = _escenario(db_session, stock=50)
    admin = esc.admin.id_usuario
    pedido = _crear(db_session, esc, cantidad=5)
    if estado == "RECHAZADO":
        PedidoService.rechazar_pedido(db_session, pedido.id_pedido, "No", admin)
    elif estado == "ANULADO":
        PedidoService.anular_pedido(db_session, pedido.id_pedido, admin)
    elif estado == "FACTURADO":
        PedidoService.aprobar_pedido(db_session, pedido.id_pedido, admin)
        PedidoService.convertir_a_factura(db_session, pedido.id_pedido, admin, pagos=pago_contado(db_session))
    db_session.refresh(esc.producto)
    stock_antes = esc.producto.cantidad_unidad
    facturas_antes = db_session.query(FacturaVenta).count()

    with pytest.raises(ValueError, match="solo se factura uno APROBADO"):
        _facturar_con_id_pedido(db_session, esc, pedido.id_pedido)

    db_session.rollback()
    db_session.refresh(esc.producto)
    assert esc.producto.cantidad_unidad == stock_antes
    assert db_session.query(FacturaVenta).count() == facturas_antes


def test_emitir_factura_con_un_id_pedido_inexistente_se_rechaza(db_session):
    esc = _escenario(db_session)

    with pytest.raises(ValueError, match="Pedido no encontrado"):
        _facturar_con_id_pedido(db_session, esc, 999_999)

    db_session.rollback()
    assert db_session.query(FacturaVenta).count() == 0


def test_facturar_con_id_pedido_de_otro_cliente_se_rechaza(db_session):
    esc = _escenario(db_session)
    otro_cliente = crear_cliente(db_session, vendedor_cliente=esc.vendedor.id_vendedor)
    pedido = _crear(db_session, esc)
    PedidoService.aprobar_pedido(db_session, pedido.id_pedido, esc.admin.id_usuario)

    with pytest.raises(ValueError, match="otro cliente"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=otro_cliente.id_cliente,
            id_usuario=esc.admin.id_usuario,
            id_vendedor=esc.vendedor.id_vendedor,
            condicion_pago="contado",
            pagos=pago_contado(db_session),
            items=_items(esc),
            id_pedido=pedido.id_pedido,
        )


def test_facturar_un_pedido_a_nombre_de_otro_vendedor_se_rechaza(db_session):
    """La comision es del vendedor que tomo el pedido: una factura a nombre de otro se la llevaria."""
    esc = _escenario(db_session)
    otro_vendedor = crear_vendedor(db_session)
    pedido = _crear(db_session, esc)
    PedidoService.aprobar_pedido(db_session, pedido.id_pedido, esc.admin.id_usuario)

    with pytest.raises(ValueError, match="otro vendedor"):
        VentaService.emitir_factura(
            db_session,
            id_cliente=esc.cliente.id_cliente,
            id_usuario=esc.admin.id_usuario,
            id_vendedor=otro_vendedor.id_vendedor,
            condicion_pago="contado",
            pagos=pago_contado(db_session),
            items=_items(esc),
            id_pedido=pedido.id_pedido,
        )

    db_session.rollback()
    assert db_session.get(Pedido, pedido.id_pedido).estado == "APROBADO"
    assert db_session.query(FacturaVenta).count() == 0


# -- Reserva por estado y en lote ------------------------------------------------------------------------------


def test_solo_los_enviados_vigentes_y_los_aprobados_apartan_stock(db_session):
    esc = _escenario(db_session, stock=100)
    _crear(db_session, esc, cantidad=1)  # enviado y vigente: aparta
    aprobado = _crear(db_session, esc, cantidad=2)  # aprobado: aparta
    rechazado = _crear(db_session, esc, cantidad=4)
    vencido = _crear(db_session, esc, cantidad=8)
    anulado = _crear(db_session, esc, cantidad=16)
    facturado = _crear(db_session, esc, cantidad=32)
    admin = esc.admin.id_usuario
    PedidoService.aprobar_pedido(db_session, aprobado.id_pedido, admin)
    PedidoService.rechazar_pedido(db_session, rechazado.id_pedido, "No", admin)
    PedidoService.anular_pedido(db_session, anulado.id_pedido, admin)
    _vencer_a_mano(db_session, vencido)
    PedidoService.aprobar_pedido(db_session, facturado.id_pedido, admin)
    PedidoService.convertir_a_factura(db_session, facturado.id_pedido, admin, pagos=pago_contado(db_session))

    assert _reservado(db_session, esc) == Decimal("3.00")  # 1 + 2; los otros cuatro estados no apartan nada


def test_reservado_por_producto_suma_por_producto_y_excluye_el_pedido_indicado(db_session):
    esc = _escenario(db_session, stock=100)
    otro = crear_producto(db_session, cantidad_unidad=100)
    crear_precio_producto(db_session, otro, "20.00")
    sin_reservas = crear_producto(db_session, cantidad_unidad=100)
    mio = _crear(
        db_session,
        esc,
        items=_items(esc, cantidad=5) + [{**_items(esc)[0], "id_producto": otro.id_producto, "cantidad": 3}],
    )
    _crear(db_session, esc, cantidad=7)

    todos = reservado_por_producto(db_session, [esc.producto.id_producto, otro.id_producto, sin_reservas.id_producto])
    sin_el_mio = reservado_por_producto(
        db_session, [esc.producto.id_producto, otro.id_producto], excluir_pedido=mio.id_pedido
    )

    assert todos == {
        esc.producto.id_producto: Decimal("12"),
        otro.id_producto: Decimal("3"),
        sin_reservas.id_producto: Decimal("0"),
    }
    assert sin_el_mio == {esc.producto.id_producto: Decimal("7"), otro.id_producto: Decimal("0")}
    assert reservado_por_producto(db_session, []) == {}


def test_un_bulto_exige_que_el_producto_tenga_unidades_por_caja(db_session):
    """El trigger de factura_detalle descuenta `cantidad * cantidad_caja`: con 0 cajas descontaria 0 y el pedido
    apartaria unidades que la factura nunca bajaria."""
    esc = _escenario(db_session, stock=100)  # cantidad_caja queda en 0 (el default de la columna)

    with pytest.raises(ValueError, match="no tiene unidades por caja"):
        _crear(db_session, esc, items=_items(esc, cantidad=2, tipo_venta="bulto"))

    assert db_session.query(Pedido).count() == 0


# -- Concurrencia ----------------------------------------------------------------------------------------------


def _en_paralelo(db, *tareas):
    """Corre cada `tarea(session)` en su propio hilo y su propia Session, todas arrancando a la vez, y devuelve
    [("ok", valor) | ("error", excepcion)] en el orden de las tareas."""
    db.commit()  # que la sesion del test no retenga nada mientras los hilos compiten
    fabrica = sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False)
    salida = [None] * len(tareas)
    arranque = threading.Barrier(len(tareas))

    def correr(i, tarea):
        sesion = fabrica()
        try:
            arranque.wait(timeout=10)
            salida[i] = ("ok", tarea(sesion))
        except Exception as exc:
            salida[i] = ("error", exc)
        finally:
            sesion.close()

    hilos = [threading.Thread(target=correr, args=(i, t)) for i, t in enumerate(tareas)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=90)
    assert not any(h.is_alive() for h in hilos), "un hilo quedo esperando (lock o deadlock sin resolver)"
    return salida


def _pedir(esc, items, **kw):
    """Tarea para `_en_paralelo`: crea un pedido (caja/admin a nombre del vendedor) y devuelve su id."""
    # Los ids se sacan YA: los objetos de `esc` son de la sesion del test y otro hilo no puede tocarlos.
    id_usuario, id_cliente, id_vendedor = esc.admin.id_usuario, esc.cliente.id_cliente, esc.vendedor.id_vendedor
    return lambda s: (
        PedidoService.crear_pedido(s, id_usuario, id_cliente, items, id_vendedor=id_vendedor, **kw).id_pedido
    )


def test_dos_pedidos_simultaneos_no_pueden_apartar_el_mismo_stock(db_session):
    """Stock para uno solo: el UPDLOCK sobre el producto hace que el segundo espere al commit del primero y
    encuentre ya apartado lo que queria."""
    esc = _escenario(db_session, stock=10)

    resultados = _en_paralelo(db_session, _pedir(esc, _items(esc, cantidad=8)), _pedir(esc, _items(esc, cantidad=8)))

    assert sorted(r[0] for r in resultados) == ["error", "ok"]
    error = next(r[1] for r in resultados if r[0] == "error")
    assert isinstance(error, ValueError) and "Stock insuficiente" in str(error)
    assert db_session.query(Pedido).count() == 1
    assert _reservado(db_session, esc) == Decimal("8.00")


def test_pedidos_que_cargan_los_mismos_productos_en_distinto_orden_no_se_traban(db_session):
    """El bloqueo en orden de id evita el cruce de locks: [A, B] y [B, A] a la vez terminan los dos, sin
    deadlock ni espera eterna."""
    esc = _escenario(db_session, stock=100)
    otro = crear_producto(db_session, cantidad_unidad=100)
    crear_precio_producto(db_session, otro, "20.00")
    a, b = _items(esc, cantidad=2)[0], {**_items(esc, cantidad=2)[0], "id_producto": otro.id_producto}

    resultados = _en_paralelo(db_session, _pedir(esc, [a, b]), _pedir(esc, [b, a]))

    assert [r[0] for r in resultados] == ["ok", "ok"], resultados
    assert db_session.query(Pedido).count() == 2
    assert reservado_por_producto(db_session, [esc.producto.id_producto, otro.id_producto]) == {
        esc.producto.id_producto: Decimal("4"),
        otro.id_producto: Decimal("4"),
    }


def test_el_mismo_envio_simultaneo_se_convierte_en_un_solo_pedido(db_session):
    """La app reenvia el pedido porque se corto la senal: si los dos envios llegan juntos, el indice unico deja
    pasar uno y el otro recibe ese mismo pedido, no un error ni un duplicado."""
    esc = _escenario(db_session, stock=100)

    resultados = _en_paralelo(
        db_session,
        _pedir(esc, _items(esc, cantidad=5), id_cliente_local="movil-reintento-1"),
        _pedir(esc, _items(esc, cantidad=5), id_cliente_local="movil-reintento-1"),
    )

    assert [r[0] for r in resultados] == ["ok", "ok"], resultados
    assert resultados[0][1] == resultados[1][1]
    assert db_session.query(Pedido).count() == 1
    assert _reservado(db_session, esc) == Decimal("5.00")


# -- Datos para las pantallas ----------------------------------------------------------------------------------


def test_detalle_pedido_devuelve_datos_simples_con_las_lineas_y_el_total(db_session):
    esc = _escenario(db_session, stock=100, cantidad_caja=Decimal("12"))
    pedido = _crear(
        db_session,
        esc,
        items=_items(esc, cantidad=2, tipo_venta="bulto") + _items(esc, cantidad=3, precio="5.00"),
        observaciones="Entregar en la tarde",
    )

    datos = PedidoService.detalle_pedido(db_session, pedido.id_pedido, esc.usuario.id_usuario)

    assert datos["numero_pedido"] == pedido.numero_pedido
    assert datos["estado"] == "ENVIADO"
    assert datos["cliente"] == esc.cliente.nombre_razon_social
    assert datos["vendedor"] == esc.vendedor.nombre_vendedor
    assert datos["observaciones"] == "Entregar en la tarde"
    assert datos["fecha_vencimiento_reserva"] is not None
    bulto, unidad = datos["lineas"]
    assert (bulto["tipo_venta"], bulto["cantidad"], bulto["unidades"]) == ("bulto", Decimal("2"), Decimal("24"))
    assert bulto["codigo"] == esc.producto.cod_producto
    assert bulto["subtotal"] == Decimal("40.00")
    assert unidad["subtotal"] == Decimal("15.00")
    assert datos["total"] == Decimal("55.00")


def test_detalle_pedido_de_otro_vendedor_se_rechaza(db_session):
    esc = _escenario(db_session)
    otro_vendedor = crear_vendedor(db_session)
    otro_usuario = _usuario_vendedor(db_session, otro_vendedor)
    pedido = _crear(db_session, esc)

    with pytest.raises(PermisoDenegadoError, match="otro vendedor"):
        PedidoService.detalle_pedido(db_session, pedido.id_pedido, otro_usuario.id_usuario)


def test_datos_para_facturar_exige_un_pedido_aprobado(db_session):
    esc = _escenario(db_session)
    pedido = _crear(db_session, esc)
    admin = esc.admin.id_usuario

    with pytest.raises(ValueError, match="solo se factura uno APROBADO"):
        PedidoService.datos_para_facturar(db_session, pedido.id_pedido, admin)

    PedidoService.aprobar_pedido(db_session, pedido.id_pedido, admin)
    datos = PedidoService.datos_para_facturar(db_session, pedido.id_pedido, admin)
    assert datos["estado"] == "APROBADO"
    assert datos["id_cliente"] == esc.cliente.id_cliente
    assert datos["id_vendedor"] == esc.vendedor.id_vendedor


def test_datos_para_facturar_pide_el_permiso_de_revisar_no_basta_con_ver(db_session):
    esc = _escenario(db_session)
    pedido = _crear(db_session, esc)
    PedidoService.aprobar_pedido(db_session, pedido.id_pedido, esc.admin.id_usuario)

    with pytest.raises(PermisoDenegadoError):
        PedidoService.datos_para_facturar(db_session, pedido.id_pedido, esc.usuario.id_usuario)


def test_el_listado_trae_el_total_de_cada_pedido(db_session):
    esc = _escenario(db_session)
    _crear(db_session, esc, items=_items(esc, cantidad=2, precio="10.00") + _items(esc, cantidad=1, precio="5.00"))
    _crear(db_session, esc, items=_items(esc, cantidad=4, precio="3.00"))

    pedidos = PedidoService.listar_pedidos(db_session, esc.admin.id_usuario)["items"]

    assert sorted(p.total for p in pedidos) == [Decimal("12.00"), Decimal("25.00")]


def test_anotar_reservado_deja_lo_apartado_en_cada_producto(db_session):
    from app.services.reservas_stock import anotar_reservado

    esc = _escenario(db_session, stock=100)
    libre = crear_producto(db_session, cantidad_unidad=100)
    _crear(db_session, esc, cantidad=7)

    anotar_reservado(db_session, [esc.producto, libre])

    assert esc.producto.cantidad_reservada == Decimal("7")
    assert libre.cantidad_reservada == Decimal("0")

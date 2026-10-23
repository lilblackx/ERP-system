"""Flujo OC -> NR -> Compra: rechazado fuera del stock (migrations/0086), estado de las
recepciones segun lo facturado (0085), anulacion de una compra hecha desde una OC (0087) y
enmiendas de OC por linea (0088)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.db.models import Auditoria, CompraOCDetalle, NotaRecepcion
from app.services.compra_oc import CompraOCService
from app.services.compras import CompraService
from app.services.nota_recepcion import NotaRecepcionService
from tests.factories import crear_producto, crear_proveedor, crear_usuario_admin


def _oc_recibida(db_session, admin, proveedor, producto, solicitada, recibida, rechazada=0, precio="5.00"):
    oc = CompraOCService.crear_oc(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        items=[{"id_producto": producto.id_producto, "cantidad_solicitada": solicitada, "precio_unitario": precio}],
        id_usuario=admin.id_usuario,
    )
    NotaRecepcionService.crear_nota_recepcion(
        db_session,
        id_oc=oc.id_oc,
        items=[
            {
                "id_oc_detalle": oc.detalles[0].id_detalle,
                "cantidad_recibida": recibida,
                "cantidad_rechazada": rechazada,
            }
        ],
        id_usuario=admin.id_usuario,
    )
    return oc


def _facturar(db_session, admin, oc, cantidad):
    return CompraService.crear_compra_desde_oc(
        db_session,
        id_oc=oc.id_oc,
        id_usuario=admin.id_usuario,
        items=[{"id_oc_detalle": oc.detalles[0].id_detalle, "cantidad": cantidad}],
        condicion_pago="credito",
    )


def _estados_nr(db_session, oc):
    db_session.expire_all()
    return [nr.estado for nr in db_session.query(NotaRecepcion).filter_by(id_oc=oc.id_oc).order_by(NotaRecepcion.id_nr)]


# ===== Rechazado no entra al stock (migrations/0086) =====


def test_recepcion_solo_suma_al_stock_lo_aceptado(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=0)
    proveedor = crear_proveedor(db_session)

    _oc_recibida(db_session, admin, proveedor, producto, solicitada=10, recibida=10, rechazada=3)

    db_session.refresh(producto)
    assert producto.cantidad_unidad == Decimal("7")


def test_devolucion_de_lo_rechazado_no_resta_stock(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=0)
    proveedor = crear_proveedor(db_session)
    oc = _oc_recibida(db_session, admin, proveedor, producto, solicitada=10, recibida=10, rechazada=3)

    NotaRecepcionService.crear_nota_devolucion(
        db_session,
        id_nr=oc.recepciones[0].id_nr,
        items=[{"id_producto": producto.id_producto, "cantidad_devuelta": 3}],
        motivo="Producto defectuoso",
        id_usuario=admin.id_usuario,
    )

    db_session.refresh(producto)
    assert producto.cantidad_unidad == Decimal("7")


def test_recepcion_totalmente_rechazada_no_mueve_stock_ni_audita(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=0)
    proveedor = crear_proveedor(db_session)

    _oc_recibida(db_session, admin, proveedor, producto, solicitada=5, recibida=5, rechazada=5)

    db_session.refresh(producto)
    assert producto.cantidad_unidad == Decimal("0")
    assert db_session.query(Auditoria).filter(Auditoria.accion == "RECEPCION_MERCANCIA").count() == 0


# ===== Estado de las recepciones (migrations/0085) =====


def test_estado_de_recepcion_sigue_lo_facturado(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=0)
    proveedor = crear_proveedor(db_session, limite_credito=Decimal("1000.00"))
    oc = _oc_recibida(db_session, admin, proveedor, producto, solicitada=10, recibida=6)
    assert _estados_nr(db_session, oc) == ["RECIBIDA"]

    _facturar(db_session, admin, oc, 2)
    assert _estados_nr(db_session, oc) == ["PARCIAL"]

    _facturar(db_session, admin, oc, 4)
    assert _estados_nr(db_session, oc) == ["FACTURADA"]


def test_lo_facturado_se_reparte_entre_recepciones_en_orden_de_llegada(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=0)
    proveedor = crear_proveedor(db_session, limite_credito=Decimal("1000.00"))
    oc = _oc_recibida(db_session, admin, proveedor, producto, solicitada=10, recibida=4)
    NotaRecepcionService.crear_nota_recepcion(
        db_session,
        id_oc=oc.id_oc,
        items=[{"id_oc_detalle": oc.detalles[0].id_detalle, "cantidad_recibida": 6}],
        id_usuario=admin.id_usuario,
    )
    assert _estados_nr(db_session, oc) == ["RECIBIDA", "RECIBIDA"]

    _facturar(db_session, admin, oc, 5)  # cubre la 1ra NR (4) y 1 de la 2da
    assert _estados_nr(db_session, oc) == ["FACTURADA", "PARCIAL"]


def test_recepcion_nueva_de_oc_ya_facturada_queda_recibida(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=0)
    proveedor = crear_proveedor(db_session, limite_credito=Decimal("1000.00"))
    oc = _oc_recibida(db_session, admin, proveedor, producto, solicitada=10, recibida=4)
    _facturar(db_session, admin, oc, 4)

    NotaRecepcionService.crear_nota_recepcion(
        db_session,
        id_oc=oc.id_oc,
        items=[{"id_oc_detalle": oc.detalles[0].id_detalle, "cantidad_recibida": 6}],
        id_usuario=admin.id_usuario,
    )

    assert _estados_nr(db_session, oc) == ["FACTURADA", "RECIBIDA"]


def test_recepcion_totalmente_rechazada_queda_recibida(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=0)
    proveedor = crear_proveedor(db_session)
    oc = _oc_recibida(db_session, admin, proveedor, producto, solicitada=5, recibida=5, rechazada=5)

    assert _estados_nr(db_session, oc) == ["RECIBIDA"]


def test_listar_notas_recepcion_filtra_por_estado(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=0)
    proveedor = crear_proveedor(db_session, limite_credito=Decimal("1000.00"))
    oc = _oc_recibida(db_session, admin, proveedor, producto, solicitada=2, recibida=2)
    _facturar(db_session, admin, oc, 2)

    facturadas = NotaRecepcionService.listar_notas_recepcion(
        db_session, estado="FACTURADA", id_usuario=admin.id_usuario
    )
    recibidas = NotaRecepcionService.listar_notas_recepcion(db_session, estado="RECIBIDA", id_usuario=admin.id_usuario)

    assert [nr.id_oc for nr in facturadas["items"]] == [oc.id_oc]
    assert recibidas["total"] == 0


# ===== Anular una compra hecha desde una OC (migrations/0087) =====


def test_anular_compra_desde_oc_devuelve_lo_facturado_y_permite_refacturar(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=0)
    proveedor = crear_proveedor(db_session, limite_credito=Decimal("1000.00"))
    oc = _oc_recibida(db_session, admin, proveedor, producto, solicitada=10, recibida=10)
    compra = _facturar(db_session, admin, oc, 10)
    assert _estados_nr(db_session, oc) == ["FACTURADA"]

    CompraService.anular_compra(
        db_session, compra.id_compra, id_usuario=admin.id_usuario, motivo="Condicion mal cargada"
    )

    db_session.expire_all()
    assert oc.cantidad_facturada == Decimal("0")
    assert oc.detalles[0].cantidad_facturada == Decimal("0")
    assert _estados_nr(db_session, oc) == ["RECIBIDA"]
    # El stock no cambia: la mercancia sigue recibida en el deposito.
    db_session.refresh(producto)
    assert producto.cantidad_unidad == Decimal("10")

    nueva = _facturar(db_session, admin, oc, 10)
    assert nueva.total_compra == Decimal("50.00")


def test_anular_compra_desde_oc_solo_devuelve_lo_de_esa_compra(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=0)
    proveedor = crear_proveedor(db_session, limite_credito=Decimal("1000.00"))
    oc = _oc_recibida(db_session, admin, proveedor, producto, solicitada=10, recibida=10)
    primera = _facturar(db_session, admin, oc, 6)
    _facturar(db_session, admin, oc, 4)

    CompraService.anular_compra(db_session, primera.id_compra, id_usuario=admin.id_usuario, motivo="Error")

    db_session.expire_all()
    assert oc.detalles[0].cantidad_facturada == Decimal("4")
    assert oc.cantidad_facturada == Decimal("4")
    assert _estados_nr(db_session, oc) == ["PARCIAL"]


def test_anular_compra_desde_oc_con_producto_repetido_devuelve_a_la_linea_correcta(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=0)
    proveedor = crear_proveedor(db_session, limite_credito=Decimal("1000.00"))
    oc = CompraOCService.crear_oc(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        items=[
            {"id_producto": producto.id_producto, "cantidad_solicitada": 5, "precio_unitario": "5.00"},
            {"id_producto": producto.id_producto, "cantidad_solicitada": 5, "precio_unitario": "7.00"},
        ],
        id_usuario=admin.id_usuario,
    )
    linea_a, linea_b = sorted(oc.detalles, key=lambda d: d.id_detalle)
    NotaRecepcionService.crear_nota_recepcion(
        db_session,
        id_oc=oc.id_oc,
        items=[
            {"id_oc_detalle": linea_a.id_detalle, "cantidad_recibida": 5},
            {"id_oc_detalle": linea_b.id_detalle, "cantidad_recibida": 5},
        ],
        id_usuario=admin.id_usuario,
    )
    for linea in (linea_a, linea_b):
        compra = CompraService.crear_compra_desde_oc(
            db_session,
            id_oc=oc.id_oc,
            id_usuario=admin.id_usuario,
            items=[{"id_oc_detalle": linea.id_detalle, "cantidad": 5}],
            condicion_pago="credito",
        )

    CompraService.anular_compra(db_session, compra.id_compra, id_usuario=admin.id_usuario, motivo="Error")

    db_session.expire_all()
    a = db_session.get(CompraOCDetalle, linea_a.id_detalle)
    b = db_session.get(CompraOCDetalle, linea_b.id_detalle)
    assert (a.cantidad_facturada, b.cantidad_facturada) == (Decimal("5"), Decimal("0"))


# ===== Enmiendas de OC por linea (migrations/0088) =====


def _oc_dos_lineas(db_session, admin, proveedor):
    oc = CompraOCService.crear_oc(
        db_session,
        id_proveedor=proveedor.id_proveedor,
        items=[
            {
                "id_producto": crear_producto(db_session).id_producto,
                "cantidad_solicitada": 100,
                "precio_unitario": "2.00",
            },
            {
                "id_producto": crear_producto(db_session).id_producto,
                "cantidad_solicitada": 50,
                "precio_unitario": "4.00",
            },
        ],
        id_usuario=admin.id_usuario,
    )
    linea_a, linea_b = sorted(oc.detalles, key=lambda d: d.id_detalle)
    return oc, linea_a, linea_b


def _enmendar(db_session, admin, oc, linea, tipo, autorizar=True, **kwargs):
    enmienda = CompraOCService.crear_enmienda(
        db_session,
        id_oc=oc.id_oc,
        id_oc_detalle=linea.id_detalle,
        tipo_cambio=tipo,
        motivo="Acuerdo con el proveedor",
        id_usuario=admin.id_usuario,
        **kwargs,
    )
    if autorizar:
        CompraOCService.autorizar_enmienda(db_session, enmienda.id_enmienda, aprobar=True, id_usuario=admin.id_usuario)
    return enmienda


def test_enmienda_cantidad_ajusta_la_linea_y_recalcula_cabecera(db_session):
    admin = crear_usuario_admin(db_session)
    oc, linea_a, linea_b = _oc_dos_lineas(db_session, admin, crear_proveedor(db_session))

    enmienda = _enmendar(db_session, admin, oc, linea_a, "CANTIDAD", autorizar=False, cantidad_nueva=80)
    assert enmienda.cantidad_anterior == Decimal("100")
    db_session.refresh(linea_a)
    assert linea_a.cantidad_solicitada == Decimal("100")  # propuesta: todavia sin efecto

    CompraOCService.autorizar_enmienda(db_session, enmienda.id_enmienda, aprobar=True, id_usuario=admin.id_usuario)

    db_session.expire_all()
    assert linea_a.cantidad_solicitada == Decimal("80")
    assert linea_a.cantidad_pendiente == Decimal("80")
    assert linea_a.total_linea == Decimal("160.00")
    assert linea_b.cantidad_solicitada == Decimal("50")  # la otra linea no se toca
    assert oc.cantidad_solicitada == Decimal("130")
    assert oc.total_oc == Decimal("360.00")  # 80*2 + 50*4
    assert oc.estado == "PENDIENTE"  # no se recibio nada: ya no pasa a PARCIAL


def test_enmienda_cantidad_se_respeta_en_la_recepcion(db_session):
    admin = crear_usuario_admin(db_session)
    oc, linea_a, _ = _oc_dos_lineas(db_session, admin, crear_proveedor(db_session))
    _enmendar(db_session, admin, oc, linea_a, "CANTIDAD", cantidad_nueva=80)

    with pytest.raises(ValueError, match="solo quedan"):
        NotaRecepcionService.crear_nota_recepcion(
            db_session,
            id_oc=oc.id_oc,
            items=[{"id_oc_detalle": linea_a.id_detalle, "cantidad_recibida": 90}],
            id_usuario=admin.id_usuario,
        )


def test_enmienda_cantidad_a_lo_ya_recibido_completa_la_oc(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=0)
    oc = _oc_recibida(db_session, admin, crear_proveedor(db_session), producto, solicitada=10, recibida=6)
    assert oc.estado == "PARCIAL"

    _enmendar(db_session, admin, oc, oc.detalles[0], "CANTIDAD", cantidad_nueva=6)

    db_session.expire_all()
    assert oc.estado == "COMPLETA"
    assert oc.detalles[0].cantidad_pendiente == Decimal("0")


def test_enmienda_cantidad_por_debajo_de_lo_recibido_falla(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=0)
    oc = _oc_recibida(db_session, admin, crear_proveedor(db_session), producto, solicitada=10, recibida=6)

    with pytest.raises(ValueError, match="ya recibido"):
        _enmendar(db_session, admin, oc, oc.detalles[0], "CANTIDAD", cantidad_nueva=5)


def test_autorizar_enmienda_de_cantidad_ya_superada_por_recepciones_falla(db_session):
    admin = crear_usuario_admin(db_session)
    producto = crear_producto(db_session, cantidad_unidad=0)
    oc = _oc_recibida(db_session, admin, crear_proveedor(db_session), producto, solicitada=10, recibida=2)
    enmienda = _enmendar(db_session, admin, oc, oc.detalles[0], "CANTIDAD", autorizar=False, cantidad_nueva=4)
    NotaRecepcionService.crear_nota_recepcion(
        db_session,
        id_oc=oc.id_oc,
        items=[{"id_oc_detalle": oc.detalles[0].id_detalle, "cantidad_recibida": 5}],
        id_usuario=admin.id_usuario,
    )

    with pytest.raises(ValueError, match="ya se recibieron"):
        CompraOCService.autorizar_enmienda(db_session, enmienda.id_enmienda, aprobar=True, id_usuario=admin.id_usuario)


def test_enmienda_precio_cambia_la_linea_y_el_total_de_la_oc(db_session):
    admin = crear_usuario_admin(db_session)
    oc, linea_a, linea_b = _oc_dos_lineas(
        db_session, admin, crear_proveedor(db_session, limite_credito=Decimal("5000"))
    )

    enmienda = _enmendar(db_session, admin, oc, linea_b, "PRECIO", precio_nuevo="5.00")

    assert enmienda.precio_anterior == Decimal("4.0000")
    db_session.expire_all()
    assert linea_b.precio_unitario == Decimal("5.0000")
    assert linea_b.total_linea == Decimal("250.00")
    assert linea_a.precio_unitario == Decimal("2.0000")
    assert oc.total_oc == Decimal("450.00")  # 100*2 + 50*5

    # La factura toma el precio nuevo de la linea.
    NotaRecepcionService.crear_nota_recepcion(
        db_session,
        id_oc=oc.id_oc,
        items=[{"id_oc_detalle": linea_b.id_detalle, "cantidad_recibida": 10}],
        id_usuario=admin.id_usuario,
    )
    compra = CompraService.crear_compra_desde_oc(
        db_session,
        id_oc=oc.id_oc,
        id_usuario=admin.id_usuario,
        items=[{"id_oc_detalle": linea_b.id_detalle, "cantidad": 10}],
        condicion_pago="credito",
    )
    assert compra.total_compra == Decimal("50.00")


def test_enmienda_rechazada_no_cambia_nada(db_session):
    admin = crear_usuario_admin(db_session)
    oc, linea_a, _ = _oc_dos_lineas(db_session, admin, crear_proveedor(db_session))
    enmienda = _enmendar(db_session, admin, oc, linea_a, "CANTIDAD", autorizar=False, cantidad_nueva=10)

    CompraOCService.autorizar_enmienda(db_session, enmienda.id_enmienda, aprobar=False, id_usuario=admin.id_usuario)

    db_session.expire_all()
    assert linea_a.cantidad_solicitada == Decimal("100")
    assert oc.cantidad_solicitada == Decimal("150")


def test_enmienda_cantidad_y_precio_exigen_linea_de_la_misma_oc(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session)
    oc, _, _ = _oc_dos_lineas(db_session, admin, proveedor)
    _, linea_ajena, _ = _oc_dos_lineas(db_session, admin, proveedor)

    with pytest.raises(ValueError, match="id_oc_detalle es requerido"):
        CompraOCService.crear_enmienda(
            db_session,
            id_oc=oc.id_oc,
            tipo_cambio="CANTIDAD",
            cantidad_nueva=10,
            motivo="x",
            id_usuario=admin.id_usuario,
        )
    with pytest.raises(ValueError, match="no pertenece"):
        _enmendar(db_session, admin, oc, linea_ajena, "PRECIO", precio_nuevo="3.00")


def test_enmienda_de_fecha_sigue_siendo_de_cabecera(db_session):
    admin = crear_usuario_admin(db_session)
    oc, _, _ = _oc_dos_lineas(db_session, admin, crear_proveedor(db_session))
    nueva_fecha = date.today() + timedelta(days=15)
    enmienda = CompraOCService.crear_enmienda(
        db_session,
        id_oc=oc.id_oc,
        tipo_cambio="FECHA",
        fecha_entrega_nueva=nueva_fecha,
        motivo="Retraso del proveedor",
        id_usuario=admin.id_usuario,
    )

    CompraOCService.autorizar_enmienda(db_session, enmienda.id_enmienda, aprobar=True, id_usuario=admin.id_usuario)

    db_session.expire_all()
    assert oc.fecha_estimada_entrega == nueva_fecha
    assert oc.estado == "PENDIENTE"

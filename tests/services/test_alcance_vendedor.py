"""Un usuario VENDEDOR ve solo lo suyo (app/services/alcance_vendedor.py).

Dos criterios, los mismos de los filtros de vendedor de las pantallas:
  * por FACTURA (facturas, libro de ventas, ventas por periodo, productos vendidos): las facturas que emitio el
    vendedor;
  * por CLIENTE (clientes, cuentas por cobrar, cobros, morosos, aging): los clientes que tiene asignados.
Se aplica en el servicio: el vendedor que pida la pantalla se IGNORA, asi que no puede ver lo de otro cambiando un
combo. ADMIN y CAJERO (sin vendedor vinculado) siguen eligiendo el filtro libremente.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.db.models import CuentaPorCobrar, Permiso
from app.services.alcance_vendedor import es_usuario_vendedor, vendedor_efectivo, vendedor_propio
from app.services.busqueda_global import BusquedaGlobalService
from app.services.clientes import list_clientes
from app.services.dashboard import DashboardService
from app.services.pagos import PagoService
from app.services.pagos_bcv import PagoBCVService
from app.services.permisos import PermisoDenegadoError
from app.services.reportes import ReporteService
from app.services.tesoreria import CajaService
from app.services.ventas import VentaService
from tests.factories import (
    asignar_permiso,
    crear_caja,
    crear_cliente,
    crear_permiso,
    crear_precio_producto,
    crear_producto,
    crear_rol,
    crear_usuario,
    crear_usuario_admin,
    crear_vendedor,
)

RECURSOS = ("clientes", "ventas", "pagos", "reportes", "dashboard", "inventario")


def _rol_vendedor(db_session):
    rol = crear_rol(db_session)
    for recurso in RECURSOS:
        permiso = db_session.query(Permiso).filter_by(recurso=recurso, accion="ver").first()
        asignar_permiso(db_session, rol, permiso or crear_permiso(db_session, recurso=recurso, accion="ver"))
    return rol


@pytest.fixture()
def mundo(db_session):
    """Dos vendedores con su usuario; un cliente de cada uno; facturas a credito:
    f_a (vendedor A -> cliente de A), f_b (vendedor B -> cliente de B) y f_ab (vendedor A -> cliente de B)."""
    admin = crear_usuario_admin(db_session)
    vend_a = crear_vendedor(db_session, nombre_vendedor="Vendedor A")
    vend_b = crear_vendedor(db_session, nombre_vendedor="Vendedor B")
    rol = _rol_vendedor(db_session)
    user_a = crear_usuario(db_session, id_rol=rol.id_rol, id_vendedor_usuario=vend_a.id_vendedor)
    user_b = crear_usuario(db_session, id_rol=rol.id_rol, id_vendedor_usuario=vend_b.id_vendedor)
    cli_a = crear_cliente(
        db_session,
        limite_credito=Decimal("100000"),
        vendedor_cliente=vend_a.id_vendedor,
        nombre_razon_social="Cliente de A",
    )
    cli_b = crear_cliente(
        db_session,
        limite_credito=Decimal("100000"),
        vendedor_cliente=vend_b.id_vendedor,
        nombre_razon_social="Cliente de B",
    )
    producto = crear_producto(db_session, cantidad_unidad=1000)
    crear_precio_producto(db_session, producto, "10.00")

    def facturar(cliente, vendedor, cantidad):
        return VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=admin.id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="credito",
            items=[{"id_producto": producto.id_producto, "cantidad": cantidad, "precio_unitario": "10.00"}],
        )

    f_a = facturar(cli_a, vend_a, 1)  # $10
    f_b = facturar(cli_b, vend_b, 2)  # $20
    f_ab = facturar(cli_b, vend_a, 3)  # $30: la vendio A, pero el cliente es de B
    return {
        "admin": admin,
        "vend_a": vend_a,
        "vend_b": vend_b,
        "user_a": user_a,
        "user_b": user_b,
        "cli_a": cli_a,
        "cli_b": cli_b,
        "f_a": f_a,
        "f_b": f_b,
        "f_ab": f_ab,
    }


def _hoy():
    return date.today(), date.today()


# ── El alcance en si ──────────────────────────────────────────────────────────────────────────


def test_un_usuario_vendedor_tiene_su_vendedor_y_ignora_el_que_pida_la_pantalla(db_session, mundo):
    m = mundo

    assert vendedor_propio(db_session, m["user_a"].id_usuario) == m["vend_a"].id_vendedor
    assert es_usuario_vendedor(db_session, m["user_a"].id_usuario)
    # pide el vendedor B (o ninguno): sigue siendo el suyo
    assert vendedor_efectivo(db_session, m["user_a"].id_usuario, m["vend_b"].id_vendedor) == m["vend_a"].id_vendedor
    assert vendedor_efectivo(db_session, m["user_a"].id_usuario, None) == m["vend_a"].id_vendedor


def test_admin_y_usuario_inexistente_no_tienen_alcance_y_eligen_libremente(db_session, mundo):
    m = mundo

    assert vendedor_propio(db_session, m["admin"].id_usuario) is None
    assert not es_usuario_vendedor(db_session, m["admin"].id_usuario)
    assert vendedor_efectivo(db_session, m["admin"].id_usuario, 7) == 7
    assert vendedor_efectivo(db_session, m["admin"].id_usuario) is None
    assert vendedor_efectivo(db_session, None, 7) == 7
    assert vendedor_propio(db_session, 999999) is None


# ── Clientes y facturas ───────────────────────────────────────────────────────────────────────


def test_el_vendedor_solo_ve_los_clientes_que_tiene_asignados(db_session, mundo):
    m = mundo

    propios = list_clientes(db_session, id_usuario=m["user_a"].id_usuario)
    pidiendo_otro = list_clientes(db_session, id_usuario=m["user_a"].id_usuario, id_vendedor=m["vend_b"].id_vendedor)
    admin_todos = list_clientes(db_session, id_usuario=m["admin"].id_usuario)

    assert [c.id_cliente for c in propios["items"]] == [m["cli_a"].id_cliente]
    assert [c.id_cliente for c in pidiendo_otro["items"]] == [m["cli_a"].id_cliente]  # el combo no lo saca de lo suyo
    assert {m["cli_a"].id_cliente, m["cli_b"].id_cliente} <= {c.id_cliente for c in admin_todos["items"]}


def test_el_admin_puede_filtrar_los_clientes_por_vendedor(db_session, mundo):
    m = mundo

    resultado = list_clientes(db_session, id_usuario=m["admin"].id_usuario, id_vendedor=m["vend_b"].id_vendedor)

    assert [c.id_cliente for c in resultado["items"]] == [m["cli_b"].id_cliente]


def test_el_vendedor_solo_ve_las_facturas_que_emitio(db_session, mundo):
    m = mundo

    propias = VentaService.listar_facturas(db_session, id_usuario=m["user_a"].id_usuario)
    pidiendo_otro = VentaService.listar_facturas(
        db_session, id_usuario=m["user_a"].id_usuario, id_vendedor=m["vend_b"].id_vendedor
    )

    esperadas = {m["f_a"].id_factura, m["f_ab"].id_factura}  # la f_ab es de un cliente de B, pero la emitio A
    assert {f.id_factura for f in propias["items"]} == esperadas
    assert {f.id_factura for f in pidiendo_otro["items"]} == esperadas
    assert m["f_b"].id_factura not in {f.id_factura for f in propias["items"]}


def test_el_filtro_de_vendedor_del_listado_de_facturas_para_el_admin(db_session, mundo):
    m = mundo

    de_b = VentaService.listar_facturas(
        db_session, id_usuario=m["admin"].id_usuario, id_vendedor=m["vend_b"].id_vendedor
    )
    todas = VentaService.listar_facturas(db_session, id_usuario=m["admin"].id_usuario)

    assert [f.id_factura for f in de_b["items"]] == [m["f_b"].id_factura]
    assert {f.id_factura for f in todas["items"]} == {m["f_a"].id_factura, m["f_b"].id_factura, m["f_ab"].id_factura}


def test_el_vendedor_no_puede_abrir_la_factura_de_otro(db_session, mundo):
    m = mundo

    assert VentaService.obtener_factura(db_session, m["f_a"].id_factura, id_usuario=m["user_a"].id_usuario)
    with pytest.raises(PermisoDenegadoError):
        VentaService.obtener_factura(db_session, m["f_b"].id_factura, id_usuario=m["user_a"].id_usuario)
    assert VentaService.obtener_factura(db_session, m["f_b"].id_factura, id_usuario=m["admin"].id_usuario)


# ── Cuentas por cobrar (por cliente) ──────────────────────────────────────────────────────────


def test_el_vendedor_solo_ve_la_cartera_de_sus_clientes(db_session, mundo):
    m = mundo

    propia = PagoService.listar_cuentas_por_cobrar_por_cliente(db_session, id_usuario=m["user_a"].id_usuario)
    pidiendo_otro = PagoService.listar_cuentas_por_cobrar_por_cliente(
        db_session, id_usuario=m["user_a"].id_usuario, id_vendedor=m["vend_b"].id_vendedor
    )

    clientes = {i["cliente"].id_cliente for i in propia["items"]}
    assert clientes == {m["cli_a"].id_cliente}  # la f_ab (la emitio A) es de un cliente de B: no es su cartera
    assert {i["cliente"].id_cliente for i in pidiendo_otro["items"]} == clientes


def test_el_vendedor_solo_ve_la_cartera_bcv_de_sus_clientes(db_session, mundo):
    m = mundo
    producto = crear_producto(db_session, cantidad_unidad=100)
    crear_precio_producto(db_session, producto, "100.00")
    for cliente, vendedor in ((m["cli_a"], m["vend_a"]), (m["cli_b"], m["vend_b"])):
        VentaService.emitir_factura(
            db_session,
            id_cliente=cliente.id_cliente,
            id_usuario=m["admin"].id_usuario,
            id_vendedor=vendedor.id_vendedor,
            condicion_pago="credito",
            items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "100.00"}],
            porcentaje_bcv=Decimal("10"),
        )

    propia = PagoBCVService.listar_cuentas_por_cobrar_bcv_agrupadas(db_session, id_usuario=m["user_a"].id_usuario)
    admin_b = PagoBCVService.listar_cuentas_por_cobrar_bcv_agrupadas(
        db_session, id_usuario=m["admin"].id_usuario, id_vendedor=m["vend_b"].id_vendedor
    )

    assert [i.id_cliente for i in propia["items"]] == [m["cli_a"].id_cliente]
    assert [i.id_cliente for i in admin_b["items"]] == [m["cli_b"].id_cliente]


# ── Reportes ──────────────────────────────────────────────────────────────────────────────────


def test_libro_de_ventas_del_vendedor_solo_tiene_sus_facturas_y_sus_totales(db_session, mundo):
    m = mundo

    propio = ReporteService.libro_ventas(db_session, m["user_a"].id_usuario, *_hoy())
    pidiendo_otro = ReporteService.libro_ventas(
        db_session, m["user_a"].id_usuario, *_hoy(), id_vendedor=m["vend_b"].id_vendedor
    )
    admin_de_b = ReporteService.libro_ventas(
        db_session, m["admin"].id_usuario, *_hoy(), id_vendedor=m["vend_b"].id_vendedor
    )
    admin_todo = ReporteService.libro_ventas(db_session, m["admin"].id_usuario, *_hoy())

    assert {f["numero_factura"] for f in propio["filas"]} == {m["f_a"].numero_factura, m["f_ab"].numero_factura}
    assert propio["cantidad_facturas"] == 2
    assert pidiendo_otro["cantidad_facturas"] == 2  # el vendedor que pide la pantalla se ignora
    assert [f["numero_factura"] for f in admin_de_b["filas"]] == [m["f_b"].numero_factura]
    assert admin_todo["cantidad_facturas"] == 3
    # el paginado y el completo coinciden en los totales
    pagina = ReporteService.libro_ventas(db_session, m["user_a"].id_usuario, *_hoy(), pagina=1, por_pagina=1)
    assert pagina["cantidad_facturas"] == 2 and pagina["paginacion"]["total"] == 2


def test_ventas_por_periodo_y_productos_vendidos_del_vendedor(db_session, mundo):
    m = mundo

    por_periodo = ReporteService.ventas_por_periodo(db_session, m["user_a"].id_usuario, *_hoy())
    por_periodo_admin_b = ReporteService.ventas_por_periodo(
        db_session, m["admin"].id_usuario, *_hoy(), id_vendedor=m["vend_b"].id_vendedor
    )
    productos = ReporteService.productos_mas_vendidos(db_session, m["user_a"].id_usuario, *_hoy())
    productos_admin = ReporteService.productos_mas_vendidos(db_session, m["admin"].id_usuario, *_hoy())

    assert por_periodo["total_facturas"] == 2 and por_periodo["total_general"] == Decimal("40.00")  # f_a + f_ab
    assert por_periodo_admin_b["total_facturas"] == 1 and por_periodo_admin_b["total_general"] == Decimal("20.00")
    assert productos["total_general"] == Decimal("40.00")  # lo que vendio A: 1 + 3 unidades a $10
    assert productos_admin["total_general"] == Decimal("60.00")


def test_clientes_morosos_y_aging_del_vendedor_son_los_de_sus_clientes(db_session, mundo):
    m = mundo
    ayer = date.today() - timedelta(days=1)
    for cuenta in db_session.query(CuentaPorCobrar).all():
        cuenta.fecha_vencimiento = ayer
    db_session.commit()

    morosos = ReporteService.clientes_morosos(db_session, m["user_a"].id_usuario)
    morosos_admin_b = ReporteService.clientes_morosos(
        db_session, m["admin"].id_usuario, id_vendedor=m["vend_b"].id_vendedor
    )
    morosos_admin = ReporteService.clientes_morosos(db_session, m["admin"].id_usuario)
    aging = ReporteService.aging_cuentas_por_cobrar(db_session, m["user_a"].id_usuario)

    assert [f["id_cliente"] for f in morosos["filas"]] == [m["cli_a"].id_cliente]
    assert [f["id_cliente"] for f in morosos_admin_b["filas"]] == [m["cli_b"].id_cliente]
    assert {f["id_cliente"] for f in morosos_admin["filas"]} == {m["cli_a"].id_cliente, m["cli_b"].id_cliente}
    assert {f["cliente"] for f in aging["filas"]} == {m["cli_a"].nombre_razon_social}


def test_cobros_del_periodo_del_vendedor_son_los_de_sus_clientes(db_session, mundo):
    m = mundo
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=m["admin"].id_usuario, saldo_apertura=0)
    for factura, monto in ((m["f_a"], "4.00"), (m["f_b"], "7.00")):
        cuenta = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).one()
        PagoService.registrar_pago_cobro(
            db_session,
            id_cuenta_por_cobrar=cuenta.id_cuenta_por_cobrar,
            monto=monto,
            metodo_pago="efectivo",
            id_caja=caja.id_caja,
            id_usuario=m["admin"].id_usuario,
        )

    propios = ReporteService.cobros_del_periodo(db_session, m["user_a"].id_usuario, *_hoy())
    admin_b = ReporteService.cobros_del_periodo(
        db_session, m["admin"].id_usuario, *_hoy(), id_vendedor=m["vend_b"].id_vendedor
    )
    paginado = ReporteService.cobros_del_periodo(db_session, m["user_a"].id_usuario, *_hoy(), pagina=1, por_pagina=10)

    assert [f["monto"] for f in propios["filas"]] == [Decimal("4.00")] and propios["total_general"] == Decimal("4.00")
    assert [f["monto"] for f in admin_b["filas"]] == [Decimal("7.00")]
    assert paginado["paginacion"]["total"] == 1 and paginado["total_general"] == Decimal("4.00")


# ── Panel de inicio y busqueda ────────────────────────────────────────────────────────────────


def test_el_dashboard_del_vendedor_solo_cuenta_lo_suyo(db_session, mundo):
    m = mundo

    propio = DashboardService.get_panel_general_data(db_session, id_usuario=m["user_a"].id_usuario)
    admin = DashboardService.get_panel_general_data(db_session, id_usuario=m["admin"].id_usuario)

    assert propio["ventas_hoy"]["total"] == Decimal("40.00") and admin["ventas_hoy"]["total"] == Decimal("60.00")
    assert propio["por_cobrar"]["saldo_total"] == Decimal("10.00")  # la cartera de su unico cliente
    assert admin["por_cobrar"]["saldo_total"] == Decimal("60.00")
    assert propio["por_pagar"] == {"saldo_total": Decimal("0.00"), "compras_vencidas": 0}  # no es de un vendedor
    assert propio["cajas_activas"] == []
    assert {f["numero_factura"] for f in propio["facturas_recientes"]} == {
        m["f_a"].numero_factura,
        m["f_ab"].numero_factura,
    }
    assert sum(d["monto"] for d in propio["grafico_semanal"]) == Decimal("40.00")


def test_la_busqueda_global_del_vendedor_solo_encuentra_lo_suyo(db_session, mundo):
    m = mundo

    clientes = [
        r for r in BusquedaGlobalService.buscar(db_session, m["user_a"].id_usuario, "Cliente de") if r.tipo == "Cliente"
    ]
    facturas = [
        r for r in BusquedaGlobalService.buscar(db_session, m["user_a"].id_usuario, "FV-") if r.tipo == "Factura"
    ]
    cobrar = [
        r
        for r in BusquedaGlobalService.buscar(db_session, m["user_a"].id_usuario, "Cliente de")
        if r.tipo == "Cuenta por cobrar"
    ]
    admin_clientes = [
        r for r in BusquedaGlobalService.buscar(db_session, m["admin"].id_usuario, "Cliente de") if r.tipo == "Cliente"
    ]

    assert [r.titulo for r in clientes] == ["Cliente de A"]
    assert {r.titulo for r in facturas} == {m["f_a"].numero_factura, m["f_ab"].numero_factura}
    assert {r.detalle.split(" — ")[0] for r in cobrar} == {"Cliente de A"}
    assert {r.titulo for r in admin_clientes} == {"Cliente de A", "Cliente de B"}

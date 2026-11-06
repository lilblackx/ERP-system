"""Exportacion del historial del cliente (Excel/PDF) con abonos: los montos negativos de los pagos
tienen que llegar a Excel como NUMEROS negativos, no como texto alterado ("'-40.00").

Contra la base de pruebas real: el historial arma facturas + abonos con triggers de por medio."""

from decimal import Decimal

from openpyxl import load_workbook

from app.services.exportacion import exportar_excel, exportar_pdf
from app.services.pagos import PagoService
from app.services.tesoreria import CajaService
from app.services.ventas import VentaService
from app.ui.historial_cliente_window import COLS_HISTORIAL, _filas_historial_para_exportar
from tests.factories import (
    crear_caja,
    crear_cliente,
    crear_precio_producto,
    crear_producto,
    crear_usuario_admin,
    crear_vendedor,
)


def _cliente_con_factura_y_abono(db_session, total="100.00", abono="40.00"):
    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=100)
    crear_precio_producto(db_session, producto, total)
    cliente = crear_cliente(db_session, limite_credito=Decimal(total) * 2)
    factura = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": total}],
    )
    from app.db.models import CuentaPorCobrar

    cxc = db_session.query(CuentaPorCobrar).filter_by(id_factura=factura.id_factura).one()
    caja = crear_caja(db_session)
    CajaService.abrir_caja(db_session, caja.id_caja, id_usuario=admin.id_usuario, saldo_apertura=0)
    PagoService.registrar_pago_cobro(
        db_session,
        id_cuenta_por_cobrar=cxc.id_cuenta_por_cobrar,
        monto=Decimal(abono),
        metodo_pago="efectivo",
        id_caja=caja.id_caja,
        id_usuario=admin.id_usuario,
    )
    return cliente


def test_los_abonos_del_historial_se_exportan_a_excel_como_numeros_negativos(db_session, tmp_path):
    cliente = _cliente_con_factura_y_abono(db_session)
    filas = _filas_historial_para_exportar(db_session, cliente.id_cliente)
    ruta = tmp_path / "historial.xlsx"

    exportar_excel(ruta, COLS_HISTORIAL, filas)

    hoja = load_workbook(ruta).active
    col_monto = COLS_HISTORIAL.index("Monto")
    por_tipo = {}
    for fila in list(hoja.iter_rows(min_row=2)):
        celda = fila[col_monto]
        por_tipo.setdefault("abono" if celda.value is not None and celda.value < 0 else "factura", celda)
    abono, factura = por_tipo["abono"], por_tipo["factura"]

    assert (abono.value, abono.data_type) == (-40, "n")  # numero negativo, no el texto "'-40.00"
    assert (factura.value, factura.data_type) == (100, "n")
    assert not any(
        isinstance(c.value, str) and c.value.startswith("'") for fila in hoja.iter_rows() for c in fila
    )  # ningun dato quedo con apostrofe pegado


def test_los_montos_del_historial_son_decimales_no_texto(db_session):
    cliente = _cliente_con_factura_y_abono(db_session)

    filas = _filas_historial_para_exportar(db_session, cliente.id_cliente)

    col_monto = COLS_HISTORIAL.index("Monto")
    col_saldo = COLS_HISTORIAL.index("Saldo Corrido")
    assert all(isinstance(f[col_monto], Decimal) for f in filas)
    # El saldo corrido es numerico en facturas y vacio en los abonos (no aplica a un abono suelto).
    for f in filas:
        assert (f[col_saldo] is None) if f[0] == "Abono" else isinstance(f[col_saldo], Decimal)
    assert Decimal("-40.00") in [f[col_monto] for f in filas]


def test_el_historial_con_abonos_se_exporta_a_pdf(db_session, tmp_path):
    cliente = _cliente_con_factura_y_abono(db_session)
    filas = _filas_historial_para_exportar(db_session, cliente.id_cliente)
    ruta = tmp_path / "historial.pdf"

    exportar_pdf(ruta, "Historial del Cliente", COLS_HISTORIAL, filas, cliente_nombre=cliente.nombre_razon_social)

    assert ruta.read_bytes().startswith(b"%PDF")

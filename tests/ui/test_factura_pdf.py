"""Textos de la nota de entrega (app/ui/factura_pdf.py): encabezado de datos del cliente y
marca "(und)" en los items facturados por unidad."""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest

import app.ui.factura_pdf as fp
from app.ui.factura_pdf import _armar_html


def _datos(tipo_venta):
    factura = NS(
        numero_factura="FV-000001",
        fecha_emision=datetime(2026, 10, 9, 10, 0),
        condicion_pago="contado",
        fecha_vencimiento=None,
        monto_vuelto=0,
        metodo_vuelto=None,
        total_venta=Decimal("10.00"),
        monto_descuento=0,
        monto_iva=0,
        iva_aplicado=False,
        porcentaje_iva_aplicado=0,
        estado_factura="EMITIDA",
        observaciones_factura=None,
        cliente=NS(
            nombre_razon_social="Cliente Prueba",
            id_legal="J",
            identificacion_cliente="1",
            telefono=None,
            email=None,
            direccion="Maracaibo",
            vendedor=None,
        ),
        vendedor=NS(nombre_vendedor="Vendedor"),
        tasa=None,
    )
    detalle = NS(
        producto=NS(cod_producto="P1", nombre_producto="Aceite 1L"),
        cantidad_producto=Decimal("1"),
        precio_unitario=Decimal("10"),
        observaciones_item=None,
        tipo_venta=tipo_venta,
    )
    return {"factura": factura, "detalles": [detalle], "metodo_pago": "efectivo"}


def test_encabezado_de_cliente_usa_datos_razon_social_y_direccion_fiscal():
    html = _armar_html(_datos("bulto"), None)
    assert "Datos" in html
    assert "DATOS" not in html
    assert "CLIENTE" not in html
    assert "<b>Razón social:</b> Cliente Prueba" in html
    assert "<b>Dirección fiscal:</b> Maracaibo" in html


def test_item_vendido_por_unidad_lleva_und_junto_a_la_descripcion():
    assert "Aceite 1L (und)" in _armar_html(_datos("unidad"), None)


def test_item_vendido_por_bulto_no_lleva_und():
    html = _armar_html(_datos("bulto"), None)
    assert "Aceite 1L" in html
    assert "(und)" not in html


def test_rif_de_la_empresa_y_del_cliente_salen_formateados():
    datos = _datos("bulto")
    datos["factura"].cliente.id_legal = "J"
    datos["factura"].cliente.identificacion_cliente = "070007508"
    config = NS(
        razon_social_empresa="Distribuidora DJ C.A",
        rif_empresa="070007508",
        direccion_empresa=None,
        telefono_empresa=None,
        pie_pagina_empresa=None,
        logotipo_empresa=None,
    )

    html = _armar_html(datos, config)

    assert html.count("J-07000750-8") == 2  # RIF de la empresa y RIF / C.I. del cliente
    assert "070007508" not in html


# -- Telefono del encabezado: vendedor del cliente, con la empresa como respaldo -----------


def _config(telefono_empresa="0261-1111111"):
    return NS(
        razon_social_empresa="Distribuidora DJ C.A",
        rif_empresa="070007508",
        direccion_empresa=None,
        telefono_empresa=telefono_empresa,
        pie_pagina_empresa=None,
        logotipo_empresa=None,
    )


def test_encabezado_usa_el_telefono_del_vendedor_del_cliente():
    datos = _datos("bulto")
    datos["factura"].cliente.vendedor = NS(telefono_vendedor="0414-2223344")

    html = _armar_html(datos, _config())

    assert "0414-2223344" in html
    assert "0261-1111111" not in html


def test_encabezado_cae_al_telefono_de_la_empresa_si_el_vendedor_no_tiene():
    datos = _datos("bulto")
    datos["factura"].cliente.vendedor = NS(telefono_vendedor=None)

    assert "0261-1111111" in _armar_html(datos, _config())


def test_encabezado_cae_al_telefono_de_la_empresa_si_el_cliente_no_tiene_vendedor():
    datos = _datos("bulto")  # cliente.vendedor = None

    assert "0261-1111111" in _armar_html(datos, _config())


def test_encabezado_sin_ningun_telefono_no_revienta():
    datos = _datos("bulto")

    html = _armar_html(datos, _config(telefono_empresa=None))

    assert "FV-000001" in html
    assert _armar_html(datos, None)


# -- "Copia del cliente" ----------------------------------------------------------------


def test_el_original_no_lleva_la_leyenda_de_copia():
    assert "COPIA DEL CLIENTE" not in _armar_html(_datos("bulto"), None)


def test_la_copia_lleva_la_leyenda_de_copia_del_cliente():
    html = _armar_html(_datos("bulto"), None, es_copia=True)

    assert "*** COPIA DEL CLIENTE ***" in html
    assert "Aceite 1L" in html  # el resto del documento es identico al original


def test_titulo_de_la_seccion_de_datos_es_datos_del_cliente():
    assert "Datos del Cliente" in _armar_html(_datos("bulto"), None)


# -- imprimir_factura: dos impresiones en impresora fisica, una sola en PDF -----------------


class _InfoImpresora:
    def __init__(self, nula=False):
        self._nula = nula

    def isNull(self):
        return self._nula


def _preparar_impresion(monkeypatch, nombre_nulo=False):
    impresiones = []

    class _Documento:
        def __init__(self, es_copia):
            self.es_copia = es_copia

        def print_(self, impresora):
            impresiones.append((self.es_copia, impresora))

    monkeypatch.setattr(fp.QPrinterInfo, "printerInfo", staticmethod(lambda nombre: _InfoImpresora(nombre_nulo)))

    class _Impresora:
        PrinterMode = fp.QPrinter.PrinterMode

        def __init__(self, info, modo):
            self.info = info

    monkeypatch.setattr(fp, "QPrinter", _Impresora)
    monkeypatch.setattr(fp, "_configurar_pagina", lambda impresora: None)
    monkeypatch.setattr(fp, "_documento", lambda datos, config, es_copia=False: _Documento(es_copia))
    return impresiones


def test_impresora_fisica_imprime_original_y_despues_la_copia_del_cliente(monkeypatch):
    impresiones = _preparar_impresion(monkeypatch)

    resultado = fp.imprimir_factura(_datos("bulto"), None, "HP LaserJet")

    assert resultado is None
    assert [es_copia for es_copia, _ in impresiones] == [False, True]
    assert impresiones[0][1] is not impresiones[1][1]  # cada copia con su propio QPrinter


def test_impresora_pdf_genera_un_solo_archivo_sin_segunda_copia(monkeypatch):
    impresiones = _preparar_impresion(monkeypatch)
    generados = []
    monkeypatch.setattr(fp, "generar_pdf_factura", lambda datos, config, ruta: generados.append(ruta))

    ruta = fp.imprimir_factura(_datos("bulto"), None, "Microsoft Print to PDF")

    assert impresiones == []
    assert generados == [ruta]
    assert ruta.endswith("Nota_Entrega_FV-000001.pdf")


def test_impresora_que_ya_no_existe_lanza_value_error_sin_imprimir_nada(monkeypatch):
    impresiones = _preparar_impresion(monkeypatch, nombre_nulo=True)

    with pytest.raises(ValueError, match="ya no está disponible"):
        fp.imprimir_factura(_datos("bulto"), None, "Impresora fantasma")

    assert impresiones == []

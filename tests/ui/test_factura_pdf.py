"""Textos de la nota de entrega (app/ui/factura_pdf.py): encabezado de datos del cliente y
marca "(und)" en los items facturados por unidad."""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace as NS

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

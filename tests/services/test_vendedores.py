from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.services.permisos import PermisoDenegadoError
from app.services.rutas import RutaService
from app.services.vendedores import VendedorService
from app.services.ventas import VentaService
from tests.factories import (
    crear_cliente,
    crear_precio_producto,
    crear_producto,
    crear_ruta,
    crear_usuario_admin,
    pago_contado,
)


def _datos_vendedor(db_session: Session, **overrides) -> dict:
    datos = {
        "codigo_vendedor": "VEN-001",
        "identificacion_vendedor": "V-11111111",
        "nombre_vendedor": "Vendedor de Prueba",
    }
    datos.update(overrides)
    if not datos.get("id_ruta"):
        datos["id_ruta"] = crear_ruta(db_session).id_ruta
    return datos


def test_crear_vendedor(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(db_session, creado_por=admin.id_usuario))
    assert vendedor.id_vendedor is not None
    assert vendedor.nombre_vendedor == "Vendedor de Prueba"


def test_crear_vendedor_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        VendedorService.crear(
            db_session,
            **_datos_vendedor(
                db_session,
            ),
        )


def test_crear_vendedor_requiere_nombre(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="nombre_vendedor"):
        VendedorService.crear(
            db_session, **_datos_vendedor(db_session, nombre_vendedor="", creado_por=admin.id_usuario)
        )


def test_crear_vendedor_codigo_duplicado(db_session):
    admin = crear_usuario_admin(db_session)
    VendedorService.crear(db_session, **_datos_vendedor(db_session, creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="codigo_vendedor"):
        VendedorService.crear(
            db_session,
            **_datos_vendedor(db_session, identificacion_vendedor="V-99999999", creado_por=admin.id_usuario),
        )


def test_crear_vendedor_identificacion_duplicada(db_session):
    admin = crear_usuario_admin(db_session)
    VendedorService.crear(db_session, **_datos_vendedor(db_session, creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="identificacion_vendedor"):
        VendedorService.crear(
            db_session,
            **_datos_vendedor(db_session, codigo_vendedor="VEN-002", creado_por=admin.id_usuario),
        )


def test_crear_vendedor_requiere_codigo(db_session):
    """codigo_vendedor paso a ser obligatorio (decision del usuario, 2026-09-01) --
    mismo criterio que Cliente/Proveedor, ya no es legitimamente opcional."""
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="codigo_vendedor"):
        VendedorService.crear(
            db_session, **_datos_vendedor(db_session, codigo_vendedor=None, creado_por=admin.id_usuario)
        )


def test_crear_vendedor_requiere_identificacion(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="identificacion_vendedor"):
        VendedorService.crear(
            db_session, **_datos_vendedor(db_session, identificacion_vendedor=None, creado_por=admin.id_usuario)
        )


def test_crear_vendedor_requiere_ruta(db_session):
    """id_ruta paso a ser obligatorio (decision del usuario, 2026-09-01), mismo criterio
    que codigo_vendedor/identificacion_vendedor -- sin test dedicado hasta esta auditoria
    (2026-09-02)."""
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="id_ruta"):
        VendedorService.crear(
            db_session,
            codigo_vendedor="VEN-001",
            identificacion_vendedor="V-11111111",
            nombre_vendedor="Vendedor de Prueba",
            id_ruta=None,
            creado_por=admin.id_usuario,
        )


def test_crear_vendedor_ruta_inexistente_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="no corresponde a una ruta existente"):
        VendedorService.crear(db_session, **_datos_vendedor(db_session, id_ruta=999999, creado_por=admin.id_usuario))


def test_crear_vendedor_ruta_inactiva_falla(db_session):
    admin = crear_usuario_admin(db_session)
    ruta = crear_ruta(db_session)
    RutaService.cambiar_estado(db_session, ruta.id_ruta, "INACTIVO", id_usuario=admin.id_usuario)

    with pytest.raises(ValueError, match="INACTIVA"):
        VendedorService.crear(
            db_session, **_datos_vendedor(db_session, id_ruta=ruta.id_ruta, creado_por=admin.id_usuario)
        )


def test_crear_vendedor_meta_activacion_opcional(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(db_session, creado_por=admin.id_usuario))
    assert vendedor.meta_activacion is None


def test_crear_vendedor_con_meta_activacion(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(
        db_session, **_datos_vendedor(db_session, meta_activacion=4, creado_por=admin.id_usuario)
    )
    assert vendedor.meta_activacion == 4


def test_crear_vendedor_meta_activacion_cero_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="meta_activacion"):
        VendedorService.crear(db_session, **_datos_vendedor(db_session, meta_activacion=0, creado_por=admin.id_usuario))


def test_crear_vendedor_meta_activacion_negativa_falla(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="meta_activacion"):
        VendedorService.crear(
            db_session, **_datos_vendedor(db_session, meta_activacion=-1, creado_por=admin.id_usuario)
        )


def test_actualizar_vendedor_meta_activacion(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(db_session, creado_por=admin.id_usuario))

    VendedorService.actualizar(db_session, vendedor.id_vendedor, id_usuario=admin.id_usuario, meta_activacion=8)

    db_session.refresh(vendedor)
    assert vendedor.meta_activacion == 8


def test_actualizar_vendedor_meta_activacion_invalida_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(db_session, creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="meta_activacion"):
        VendedorService.actualizar(db_session, vendedor.id_vendedor, id_usuario=admin.id_usuario, meta_activacion=0)


def test_actualizar_vendedor_no_permite_vaciar_ruta(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(db_session, creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="id_ruta"):
        VendedorService.actualizar(db_session, vendedor.id_vendedor, id_usuario=admin.id_usuario, id_ruta=None)


def test_actualizar_vendedor_ruta_inactiva_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(db_session, creado_por=admin.id_usuario))
    otra_ruta = crear_ruta(db_session)
    RutaService.cambiar_estado(db_session, otra_ruta.id_ruta, "INACTIVO", id_usuario=admin.id_usuario)

    with pytest.raises(ValueError, match="INACTIVA"):
        VendedorService.actualizar(
            db_session, vendedor.id_vendedor, id_usuario=admin.id_usuario, id_ruta=otra_ruta.id_ruta
        )


def test_obtener_vendedor(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(db_session, creado_por=admin.id_usuario))
    encontrado = VendedorService.obtener(db_session, vendedor.id_vendedor, id_usuario=admin.id_usuario)
    assert encontrado is not None
    assert encontrado.id_vendedor == vendedor.id_vendedor


def test_obtener_vendedor_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    assert VendedorService.obtener(db_session, 999999, id_usuario=admin.id_usuario) is None


def test_obtener_vendedor_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        VendedorService.obtener(db_session, 999999)


def test_listar_vendedores_filtra_por_texto(db_session):
    admin = crear_usuario_admin(db_session)
    VendedorService.crear(db_session, **_datos_vendedor(db_session, creado_por=admin.id_usuario))
    VendedorService.crear(
        db_session,
        **_datos_vendedor(
            db_session,
            codigo_vendedor="VEN-002",
            identificacion_vendedor="V-22222222",
            nombre_vendedor="Otro",
            creado_por=admin.id_usuario,
        ),
    )

    resultado = VendedorService.listar(db_session, texto_busqueda="Prueba", id_usuario=admin.id_usuario)

    assert resultado["total"] == 1
    assert resultado["items"][0].nombre_vendedor == "Vendedor de Prueba"


def test_listar_vendedores_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        VendedorService.listar(db_session)


def test_listar_vendedores_pagina_resultados(db_session):
    """D-01, mismo patron que ClienteService.list_clientes()."""
    admin = crear_usuario_admin(db_session)
    for i in range(5):
        VendedorService.crear(
            db_session,
            **_datos_vendedor(
                db_session,
                codigo_vendedor=f"VEN-PAG-{i}",
                identificacion_vendedor=f"V-{i:08d}",
                nombre_vendedor=f"Vendedor Pagina {i}",
                creado_por=admin.id_usuario,
            ),
        )

    pagina_1 = VendedorService.listar(db_session, pagina=1, por_pagina=2, id_usuario=admin.id_usuario)
    pagina_2 = VendedorService.listar(db_session, pagina=2, por_pagina=2, id_usuario=admin.id_usuario)

    assert pagina_1["total"] == 5
    assert len(pagina_1["items"]) == 2
    assert len(pagina_2["items"]) == 2
    assert {v.id_vendedor for v in pagina_1["items"]}.isdisjoint({v.id_vendedor for v in pagina_2["items"]})


def test_listar_vendedores_filtra_por_estado(db_session):
    admin = crear_usuario_admin(db_session)
    activo = VendedorService.crear(db_session, **_datos_vendedor(db_session, creado_por=admin.id_usuario))
    inactivo = VendedorService.crear(
        db_session,
        **_datos_vendedor(
            db_session, codigo_vendedor="VEN-002", identificacion_vendedor="V-22222222", nombre_vendedor="Otro"
        ),
        creado_por=admin.id_usuario,
    )
    VendedorService.cambiar_estado(db_session, inactivo.id_vendedor, "INACTIVO", id_usuario=admin.id_usuario)

    resultado = VendedorService.listar(db_session, estado_vendedor="ACTIVO", id_usuario=admin.id_usuario)

    assert resultado["total"] == 1
    assert resultado["items"][0].id_vendedor == activo.id_vendedor


def test_actualizar_vendedor(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(db_session, creado_por=admin.id_usuario))

    actualizado = VendedorService.actualizar(
        db_session, vendedor.id_vendedor, id_usuario=admin.id_usuario, nombre_vendedor="Nombre Nuevo"
    )

    assert actualizado.nombre_vendedor == "Nombre Nuevo"


def test_actualizar_vendedor_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(db_session, creado_por=admin.id_usuario))

    with pytest.raises(PermisoDenegadoError):
        VendedorService.actualizar(db_session, vendedor.id_vendedor, nombre_vendedor="X")


def test_actualizar_vendedor_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Vendedor no encontrado"):
        VendedorService.actualizar(db_session, 999999, id_usuario=admin.id_usuario, nombre_vendedor="X")


def test_actualizar_vendedor_no_permite_vaciar_nombre(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(db_session, creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="nombre_vendedor"):
        VendedorService.actualizar(db_session, vendedor.id_vendedor, id_usuario=admin.id_usuario, nombre_vendedor="")


def test_actualizar_vendedor_no_permite_vaciar_codigo(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(db_session, creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="codigo_vendedor"):
        VendedorService.actualizar(db_session, vendedor.id_vendedor, id_usuario=admin.id_usuario, codigo_vendedor="")


def test_actualizar_vendedor_no_permite_vaciar_identificacion(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(db_session, creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="identificacion_vendedor"):
        VendedorService.actualizar(
            db_session, vendedor.id_vendedor, id_usuario=admin.id_usuario, identificacion_vendedor=""
        )


def test_actualizar_vendedor_codigo_duplicado(db_session):
    admin = crear_usuario_admin(db_session)
    VendedorService.crear(db_session, **_datos_vendedor(db_session, creado_por=admin.id_usuario))
    otro = VendedorService.crear(
        db_session,
        **_datos_vendedor(
            db_session, codigo_vendedor="VEN-002", identificacion_vendedor="V-22222222", creado_por=admin.id_usuario
        ),
    )

    with pytest.raises(ValueError, match="codigo_vendedor"):
        VendedorService.actualizar(db_session, otro.id_vendedor, id_usuario=admin.id_usuario, codigo_vendedor="VEN-001")


def test_actualizar_vendedor_identificacion_duplicada(db_session):
    admin = crear_usuario_admin(db_session)
    VendedorService.crear(db_session, **_datos_vendedor(db_session, creado_por=admin.id_usuario))
    otro = VendedorService.crear(
        db_session,
        **_datos_vendedor(
            db_session, codigo_vendedor="VEN-002", identificacion_vendedor="V-22222222", creado_por=admin.id_usuario
        ),
    )

    with pytest.raises(ValueError, match="identificacion_vendedor"):
        VendedorService.actualizar(
            db_session, otro.id_vendedor, id_usuario=admin.id_usuario, identificacion_vendedor="V-11111111"
        )


def test_actualizar_vendedor_permite_conservar_su_propio_codigo(db_session):
    """Guardar sin cambiar codigo_vendedor/identificacion_vendedor no debe chocar contra
    si mismo -- misma logica que ClienteService.update_cliente."""
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(db_session, creado_por=admin.id_usuario))

    actualizado = VendedorService.actualizar(
        db_session,
        vendedor.id_vendedor,
        id_usuario=admin.id_usuario,
        codigo_vendedor="VEN-001",
        telefono_vendedor="0414-0000000",
    )

    assert actualizado.telefono_vendedor == "0414-0000000"


def test_eliminar_vendedor_siempre_falla_para_proteger_integridad(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(db_session, creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="No se puede eliminar"):
        VendedorService.eliminar(db_session, vendedor.id_vendedor, id_usuario=admin.id_usuario)

    assert VendedorService.listar(db_session, id_usuario=admin.id_usuario)["total"] == 1


def test_eliminar_vendedor_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(db_session, creado_por=admin.id_usuario))

    with pytest.raises(PermisoDenegadoError):
        VendedorService.eliminar(db_session, vendedor.id_vendedor)


def test_cambiar_estado_vendedor_desactiva(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(db_session, creado_por=admin.id_usuario))

    actualizado = VendedorService.cambiar_estado(
        db_session, vendedor.id_vendedor, "INACTIVO", id_usuario=admin.id_usuario
    )

    assert actualizado.estado_vendedor == "INACTIVO"


def test_cambiar_estado_vendedor_estado_invalido(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(db_session, creado_por=admin.id_usuario))

    with pytest.raises(ValueError, match="nuevo_estado"):
        VendedorService.cambiar_estado(db_session, vendedor.id_vendedor, "BLOQUEADO", id_usuario=admin.id_usuario)


def test_cambiar_estado_vendedor_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Vendedor no encontrado"):
        VendedorService.cambiar_estado(db_session, 999999, "INACTIVO", id_usuario=admin.id_usuario)


def test_cambiar_estado_vendedor_sin_usuario_autorizado_falla(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(db_session, creado_por=admin.id_usuario))

    with pytest.raises(PermisoDenegadoError):
        VendedorService.cambiar_estado(db_session, vendedor.id_vendedor, "INACTIVO")


# --- obtener_desempeno_mes -----------------------------------------------------


def test_desempeno_mes_vendedor_inexistente(db_session):
    admin = crear_usuario_admin(db_session)
    with pytest.raises(ValueError, match="Vendedor no encontrado"):
        VendedorService.obtener_desempeno_mes(db_session, 999999, anio=2026, mes=8, id_usuario=admin.id_usuario)


def test_desempeno_mes_sin_usuario_autorizado_falla(db_session):
    with pytest.raises(PermisoDenegadoError):
        VendedorService.obtener_desempeno_mes(db_session, 999999, anio=2026, mes=8)


def test_desempeno_mes_suma_ventas_y_excluye_anuladas(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(db_session, creado_por=admin.id_usuario))
    producto = crear_producto(db_session, cantidad_unidad=50)
    crear_precio_producto(db_session, producto, "10.00")
    cliente = crear_cliente(db_session, vendedor_cliente=vendedor.id_vendedor)

    VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 2, "precio_unitario": "10.00"}],
        pagos=pago_contado(db_session),
    )
    # precio_unitario == precio de lista (10.00): a proposito, para no generar comision
    # -- si el vendedor vendiera por encima de precio de lista, la comision de una venta
    # de contado nace 'liberada' de inmediato (C14/migrations/0045) y anular_factura()
    # bloquea la anulacion mientras esa comision siga sin pagar (ver ventas.py:774-788).
    # Este test solo verifica que las facturas anuladas no cuenten en el desempeno del
    # vendedor, no el flujo de comisiones.
    factura_anulada = VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="contado",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "10.00"}],
        pagos=pago_contado(db_session),
    )
    VentaService.anular_factura(
        db_session, factura_anulada.id_factura, id_usuario=admin.id_usuario, motivo="Error de carga"
    )

    hoy = date.today()
    resultado = VendedorService.obtener_desempeno_mes(
        db_session, vendedor.id_vendedor, anio=hoy.year, mes=hoy.month, id_usuario=admin.id_usuario
    )

    assert resultado["total_vendido"] == Decimal("20.00")
    assert resultado["cantidad_facturas"] == 1
    assert resultado["total_clientes_asignados"] == 1


def test_desempeno_mes_sin_ventas_en_el_periodo(db_session):
    admin = crear_usuario_admin(db_session)
    vendedor = VendedorService.crear(db_session, **_datos_vendedor(db_session, creado_por=admin.id_usuario))

    resultado = VendedorService.obtener_desempeno_mes(
        db_session, vendedor.id_vendedor, anio=2020, mes=1, id_usuario=admin.id_usuario
    )

    assert resultado["total_vendido"] == 0
    assert resultado["cantidad_facturas"] == 0
    assert resultado["total_clientes_asignados"] == 0

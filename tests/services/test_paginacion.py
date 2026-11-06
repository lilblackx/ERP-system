"""Paginacion central (app/services/paginacion.py): limites, ultima pagina, desempate y listas en memoria."""

import pytest

from app.services.paginacion import (
    normalizar_paginacion,
    paginar,
    paginar_lista,
    total_paginas,
)
from tests.factories import crear_banco


@pytest.mark.parametrize(
    ("pagina", "por_pagina", "esperado"),
    [
        (1, 20, (1, 20)),
        (0, 20, (1, 20)),
        (-5, 20, (1, 20)),
        (3, 0, (3, 1)),
        (3, -7, (3, 1)),
        (None, None, (1, 20)),
        ("2", "10", (2, 10)),
        ("abc", "xyz", (1, 20)),
    ],
)
def test_normalizar_paginacion(pagina, por_pagina, esperado):
    assert normalizar_paginacion(pagina, por_pagina) == esperado


@pytest.mark.parametrize(
    ("total", "por_pagina", "esperado"),
    [(0, 20, 1), (1, 20, 1), (20, 20, 1), (21, 20, 2), (40, 20, 2), (41, 20, 3), (5, 0, 5)],
)
def test_total_paginas_nunca_baja_de_uno(total, por_pagina, esperado):
    assert total_paginas(total, por_pagina) == esperado


def test_paginar_lista_corta_la_pagina_y_lleva_una_pagina_excedida_a_la_ultima():
    datos = list(range(1, 46))  # 45 elementos -> 3 paginas de 20

    p1 = paginar_lista(datos, 1, 20)
    p3 = paginar_lista(datos, 3, 20)
    p9 = paginar_lista(datos, 9, 20)  # excede: se lleva a la ultima
    p0 = paginar_lista(datos, 0, 20)  # invalida: primera

    assert p1["items"] == datos[:20] and p1["total"] == 45 and p1["total_paginas"] == 3
    assert p3["items"] == datos[40:] and p3["pagina"] == 3
    assert p9["items"] == p3["items"] and p9["pagina"] == 3
    assert p0["pagina"] == 1 and p0["items"] == datos[:20]


def test_paginar_lista_vacia_es_la_pagina_1_de_1():
    r = paginar_lista([], 5, 20)

    assert (r["items"], r["total"], r["pagina"], r["total_paginas"]) == ([], 0, 1, 1)


def test_paginar_exige_un_orden():
    with pytest.raises(ValueError):
        paginar(object(), 1, 20)


# -- con base de datos real -------------------------------------------------------------------------------


def _bancos(db_session, nombres):
    from app.db.models import Banco

    for i, nombre in enumerate(nombres):
        crear_banco(db_session, nombre_banco=nombre, codigo_banco=f"{i:04d}", identificacion_banco=f"J-{i:08d}-0")
    return db_session.query(Banco)


def test_paginar_con_valores_repetidos_no_repite_ni_pierde_filas(db_session):
    """El caso que rompia con ORDER BY sin desempate: muchas filas con el MISMO nombre. Se recorren todas las
    paginas y cada fila debe salir exactamente una vez."""
    from app.db.models import Banco

    query = _bancos(db_session, ["Banco Igual"] * 23 + ["Otro Banco"] * 4)

    vistos = []
    for pagina in range(1, 7):  # 27 filas / 5 por pagina = 6 paginas
        r = paginar(query, pagina, 5, Banco.nombre_banco, Banco.id_banco)
        vistos.extend(b.id_banco for b in r["items"])

    ids = sorted(b.id_banco for b in query.all())
    assert sorted(vistos) == ids  # ni repetidas ni faltantes
    assert len(vistos) == len(set(vistos)) == 27


def test_paginar_ultima_pagina_y_pagina_excedida(db_session):
    from app.db.models import Banco

    query = _bancos(db_session, [f"Banco {i:02d}" for i in range(12)])

    ultima = paginar(query, 3, 5, Banco.nombre_banco, Banco.id_banco)
    excedida = paginar(query, 99, 5, Banco.nombre_banco, Banco.id_banco)
    invalida = paginar(query, 0, 5, Banco.nombre_banco, Banco.id_banco)

    assert (ultima["pagina"], len(ultima["items"]), ultima["total"], ultima["total_paginas"]) == (3, 2, 12, 3)
    assert [b.id_banco for b in excedida["items"]] == [b.id_banco for b in ultima["items"]]
    assert excedida["pagina"] == 3  # la pagina que realmente se cargo
    assert invalida["pagina"] == 1 and len(invalida["items"]) == 5  # antes: OFFSET negativo -> error de SQL


def test_paginar_sin_resultados(db_session):
    from app.db.models import Banco

    vacia = paginar(db_session.query(Banco), 4, 20, Banco.nombre_banco, Banco.id_banco)

    assert (vacia["items"], vacia["total"], vacia["pagina"], vacia["total_paginas"]) == ([], 0, 1, 1)


# -- servicios reales ------------------------------------------------------------------------------------


def test_list_clientes_con_nombres_repetidos_no_repite_ni_pierde_clientes(db_session):
    from app.services.clientes import list_clientes
    from tests.factories import crear_cliente, crear_usuario_admin

    admin = crear_usuario_admin(db_session)
    for _ in range(23):
        crear_cliente(db_session, nombre_razon_social="Cliente Repetido")

    ids = []
    for pagina in range(1, 6):  # 23 clientes / 5 por pagina = 5 paginas
        r = list_clientes(db_session, id_usuario=admin.id_usuario, pagina=pagina, por_pagina=5)
        ids.extend(c.id_cliente for c in r["items"])

    assert len(ids) == len(set(ids)) == 23


def test_list_clientes_pagina_invalida_o_excedida_no_falla(db_session):
    from app.services.clientes import list_clientes
    from tests.factories import crear_cliente, crear_usuario_admin

    admin = crear_usuario_admin(db_session)
    for _ in range(7):
        crear_cliente(db_session)

    cero = list_clientes(db_session, id_usuario=admin.id_usuario, pagina=0, por_pagina=5)
    excedida = list_clientes(db_session, id_usuario=admin.id_usuario, pagina=50, por_pagina=5)

    assert cero["pagina"] == 1 and len(cero["items"]) == 5  # antes: OFFSET negativo -> error de SQL
    assert excedida["pagina"] == 2 == excedida["total_paginas"] and len(excedida["items"]) == 2


def _cliente_con_deuda(db_session, admin, vendedor, nombre, monto):
    from decimal import Decimal

    from app.services.ventas import VentaService
    from tests.factories import crear_cliente, crear_precio_producto, crear_producto

    producto = crear_producto(db_session, cantidad_unidad=100)
    crear_precio_producto(db_session, producto, monto)
    cliente = crear_cliente(db_session, nombre_razon_social=nombre, limite_credito=Decimal(monto) * 3)
    VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": monto}],
    )
    return cliente


def test_cuentas_por_cobrar_por_cliente_busca_por_nombre_antes_de_paginar(db_session):
    from app.services.pagos import PagoService
    from tests.factories import crear_usuario_admin, crear_vendedor

    admin = crear_usuario_admin(db_session)
    vendedor = crear_vendedor(db_session)
    for nombre, monto in (("Alfa C.A.", "10.00"), ("Beta C.A.", "20.00"), ("Alfabeto S.A.", "30.00")):
        _cliente_con_deuda(db_session, admin, vendedor, nombre, monto)

    todos = PagoService.listar_cuentas_por_cobrar_por_cliente(db_session, id_usuario=admin.id_usuario, por_pagina=2)
    busqueda = PagoService.listar_cuentas_por_cobrar_por_cliente(
        db_session, id_usuario=admin.id_usuario, texto_busqueda="alfa", por_pagina=1
    )

    assert todos["total"] == 3 and todos["total_paginas"] == 2 and len(todos["items"]) == 2
    # Mayor saldo primero (30, 20, 10)
    assert [d["cliente"].nombre_razon_social for d in todos["items"]] == ["Alfabeto S.A.", "Beta C.A."]
    # "alfa" coincide con 2 clientes: el total y las paginas salen de la busqueda, no de los 3 clientes
    assert busqueda["total"] == 2 and busqueda["total_paginas"] == 2 and len(busqueda["items"]) == 1

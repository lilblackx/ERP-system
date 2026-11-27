"""Los numeros de documento salen del correlativo (migrations/0104 y 0107), no del IDENTITY.

El apagado forzoso de SQL Server hace saltar el IDENTITY ~10.000 posiciones. Aqui el salto se provoca con DBCC
CHECKIDENT y se comprueba que la numeracion de cada documento sigue consecutiva.
"""

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.services.compra_oc import CompraOCService
from app.services.compras import CompraService
from app.services.correlativos import MENSAJE_CORRELATIVO_OCUPADO, siguiente_numero
from app.services.nota_recepcion import NotaRecepcionService
from app.services.notas_credito import NotaCreditoService
from tests.factories import crear_cliente, crear_producto, crear_proveedor, crear_usuario_admin

TABLAS_CON_NUMERO = [
    "notas_credito_clientes",
    "compras",
    "compra_oc",
    "compra_oc_enmienda",
    "nota_recepcion",
    "nota_devolucion",
]


def _saltar_identity(session) -> None:
    for tabla in TABLAS_CON_NUMERO:
        actual = session.execute(text(f"SELECT CAST(IDENT_CURRENT('dbo.{tabla}') AS BIGINT)")).scalar()
        session.execute(text(f"DBCC CHECKIDENT ('dbo.{tabla}', RESEED, {actual + 10000}) WITH NO_INFOMSGS"))
    session.commit()


def _valor(numero: str) -> int:
    return int(numero.split("-")[1])


def _emitir_uno_de_cada(session, admin, proveedor, producto, cliente) -> dict[str, str]:
    """Un documento de cada tipo, con el flujo real: OC, enmienda, recepcion con rechazo, devolucion, compra desde
    la OC y nota de credito de cliente."""
    oc = CompraOCService.crear_oc(
        session,
        id_proveedor=proveedor.id_proveedor,
        items=[{"id_producto": producto.id_producto, "cantidad_solicitada": 10, "precio_unitario": "5.00"}],
        id_usuario=admin.id_usuario,
    )
    enmienda = CompraOCService.crear_enmienda(
        session,
        id_oc=oc.id_oc,
        tipo_cambio="CANTIDAD",
        motivo="Ajuste del proveedor",
        cantidad_nueva=12,
        id_oc_detalle=oc.detalles[0].id_detalle,
        id_usuario=admin.id_usuario,
    )
    recepcion = NotaRecepcionService.crear_nota_recepcion(
        session,
        id_oc=oc.id_oc,
        items=[{"id_oc_detalle": oc.detalles[0].id_detalle, "cantidad_recibida": 10, "cantidad_rechazada": 3}],
        id_usuario=admin.id_usuario,
    )
    devolucion = NotaRecepcionService.crear_nota_devolucion(
        session,
        id_nr=recepcion.id_nr,
        items=[{"id_producto": producto.id_producto, "cantidad_devuelta": 3}],
        motivo="Producto defectuoso",
        id_usuario=admin.id_usuario,
    )
    compra = CompraService.crear_compra_desde_oc(
        session,
        id_oc=oc.id_oc,
        id_usuario=admin.id_usuario,
        items=[{"id_oc_detalle": oc.detalles[0].id_detalle, "cantidad": 7}],
        condicion_pago="credito",
    )
    nota = NotaCreditoService.crear_nota_credito_cliente(
        session,
        id_cliente=cliente.id_cliente,
        id_factura_origen=None,
        monto=Decimal("5.00"),
        motivo="Ajuste",
        id_usuario=admin.id_usuario,
    )
    return {
        "ODC": oc.numero_oc,
        "ENM": enmienda.numero_enmienda,
        "NR": recepcion.numero_nr,
        "ND": devolucion.numero_nota_devolucion,
        "OC": compra.numero_compra,
        "NC": nota.numero_nota_credito,
    }


def test_todos_los_documentos_siguen_consecutivos_aunque_el_identity_salte_de_bloque(db_session):
    admin = crear_usuario_admin(db_session)
    proveedor = crear_proveedor(db_session, limite_credito=Decimal("100000.00"))
    producto = crear_producto(db_session, cantidad_unidad=0)
    cliente = crear_cliente(db_session)

    antes = _emitir_uno_de_cada(db_session, admin, proveedor, producto, cliente)
    _saltar_identity(db_session)
    despues = _emitir_uno_de_cada(db_session, admin, proveedor, producto, cliente)

    for prefijo, numero in despues.items():
        assert numero == f"{prefijo}-{_valor(antes[prefijo]) + 1:06d}"


def test_si_otra_estacion_retiene_el_correlativo_el_mensaje_es_claro_y_no_se_pierde_el_numero(db_session, test_engine):
    fabrica = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    ocupada, en_espera = fabrica(), fabrica()
    try:
        reservado = siguiente_numero(ocupada, "compra")  # sin commit: la fila queda tomada
        en_espera.execute(text("SET LOCK_TIMEOUT 200"))

        with pytest.raises(ValueError) as error:
            siguiente_numero(en_espera, "compra")

        assert str(error.value) == MENSAJE_CORRELATIVO_OCUPADO
        ocupada.rollback()
        assert siguiente_numero(en_espera, "compra") == reservado
    finally:
        for session in (ocupada, en_espera):
            session.rollback()
            session.execute(text("SET LOCK_TIMEOUT -1"))  # la conexion vuelve al pool
            session.close()


def test_un_correlativo_que_no_existe_avisa_de_la_migracion(db_session):
    with pytest.raises(ValueError, match="migracion"):
        siguiente_numero(db_session, "no_existe")

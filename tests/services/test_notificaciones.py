from datetime import date, datetime, timedelta
from decimal import Decimal

from app.db.models import ControlDeTasa
from app.services.licencia import ESTADO_VENCIDA, EstadoLicencia
from app.services.notificaciones import (
    SEVERIDAD_ALTA,
    SEVERIDAD_INFO,
    SEVERIDAD_MEDIA,
    NotificacionesService,
)
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
)


def _claves(notificaciones):
    return {n.clave for n in notificaciones}


def _sin_licencia(monkeypatch):
    """Por defecto el licenciamiento esta apagado en tests, pero mejor no depender de eso."""
    monkeypatch.setattr(
        "app.services.notificaciones.LicenciaService.estado_actual",
        lambda *a, **k: EstadoLicencia("ACTIVA", "ok"),
    )


def _registrar_tasa_de_hoy(session):
    session.add(ControlDeTasa(fecha_tasa=datetime.now(), tasa_dolar_bcv=Decimal("40.00")))
    session.commit()


def test_sin_nada_que_avisar_no_hay_notificaciones(db_session, monkeypatch):
    _sin_licencia(monkeypatch)
    admin = crear_usuario_admin(db_session)
    _registrar_tasa_de_hoy(db_session)

    assert NotificacionesService.obtener(db_session, admin.id_usuario) == []


def test_cuenta_por_cobrar_vencida_alerta_con_cantidad_y_saldo(db_session, monkeypatch):
    _sin_licencia(monkeypatch)
    admin = crear_usuario_admin(db_session)
    _registrar_tasa_de_hoy(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=100)
    crear_precio_producto(db_session, producto, "80.00")
    cliente = crear_cliente(db_session, limite_credito=Decimal("1000.00"))
    VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "80.00"}],
        fecha_vencimiento=date.today() - timedelta(days=5),
    )

    notificaciones = NotificacionesService.obtener(db_session, admin.id_usuario)

    assert _claves(notificaciones) == {"cxc_vencidas"}
    n = notificaciones[0]
    assert n.severidad == SEVERIDAD_ALTA
    assert n.modulo == "cuentas_por_cobrar"
    assert "1 factura vencida" in n.detalle
    assert "$80.00" in n.detalle


def test_cuenta_por_cobrar_por_vencer_no_alerta(db_session, monkeypatch):
    _sin_licencia(monkeypatch)
    admin = crear_usuario_admin(db_session)
    _registrar_tasa_de_hoy(db_session)
    vendedor = crear_vendedor(db_session)
    producto = crear_producto(db_session, cantidad_unidad=100)
    crear_precio_producto(db_session, producto, "80.00")
    cliente = crear_cliente(db_session, limite_credito=Decimal("1000.00"))
    VentaService.emitir_factura(
        db_session,
        id_cliente=cliente.id_cliente,
        id_usuario=admin.id_usuario,
        id_vendedor=vendedor.id_vendedor,
        condicion_pago="credito",
        items=[{"id_producto": producto.id_producto, "cantidad": 1, "precio_unitario": "80.00"}],
        fecha_vencimiento=date.today() + timedelta(days=10),
    )

    assert "cxc_vencidas" not in _claves(NotificacionesService.obtener(db_session, admin.id_usuario))


def test_stock_bajo_alerta_solo_con_minimo_configurado(db_session, monkeypatch):
    _sin_licencia(monkeypatch)
    admin = crear_usuario_admin(db_session)
    _registrar_tasa_de_hoy(db_session)
    crear_producto(db_session, cantidad_unidad=3, cantidad_minima=Decimal("10.00"))  # bajo
    crear_producto(db_session, cantidad_unidad=500, cantidad_minima=Decimal("10.00"))  # sobrado
    crear_producto(db_session, cantidad_unidad=1)  # sin minimo configurado: nunca alerta

    notificaciones = NotificacionesService.obtener(db_session, admin.id_usuario)

    assert _claves(notificaciones) == {"stock_bajo"}
    assert "1 producto por debajo" in notificaciones[0].detalle
    assert notificaciones[0].modulo == "inventario"
    assert notificaciones[0].severidad == SEVERIDAD_MEDIA


def test_producto_por_vencer_alerta(db_session, monkeypatch):
    _sin_licencia(monkeypatch)
    admin = crear_usuario_admin(db_session)
    _registrar_tasa_de_hoy(db_session)
    crear_producto(db_session, cantidad_unidad=50, fecha_vencimiento=date.today() + timedelta(days=10))
    crear_producto(db_session, cantidad_unidad=50, fecha_vencimiento=date.today() + timedelta(days=400))

    notificaciones = NotificacionesService.obtener(db_session, admin.id_usuario)

    assert _claves(notificaciones) == {"productos_por_vencer"}


def test_producto_inactivo_no_alerta(db_session, monkeypatch):
    _sin_licencia(monkeypatch)
    admin = crear_usuario_admin(db_session)
    _registrar_tasa_de_hoy(db_session)
    crear_producto(db_session, cantidad_unidad=1, cantidad_minima=Decimal("10.00"), estado_producto="INACTIVO")

    assert NotificacionesService.obtener(db_session, admin.id_usuario) == []


def test_tasa_de_hoy_sin_registrar_avisa_como_info(db_session, monkeypatch):
    _sin_licencia(monkeypatch)
    admin = crear_usuario_admin(db_session)
    db_session.add(ControlDeTasa(fecha_tasa=datetime.now() - timedelta(days=3), tasa_dolar_bcv=Decimal("38.00")))
    db_session.commit()

    notificaciones = NotificacionesService.obtener(db_session, admin.id_usuario)

    assert _claves(notificaciones) == {"tasa_sin_registrar"}
    assert notificaciones[0].severidad == SEVERIDAD_INFO
    assert notificaciones[0].modulo == "control_tasas"


def test_licencia_no_activa_alerta_como_alta(db_session, monkeypatch):
    admin = crear_usuario_admin(db_session)
    _registrar_tasa_de_hoy(db_session)
    monkeypatch.setattr(
        "app.services.notificaciones.LicenciaService.estado_actual",
        lambda *a, **k: EstadoLicencia(ESTADO_VENCIDA, "La licencia venció."),
    )

    notificaciones = NotificacionesService.obtener(db_session, admin.id_usuario)

    assert _claves(notificaciones) == {"licencia"}
    assert notificaciones[0].severidad == SEVERIDAD_ALTA
    assert notificaciones[0].modulo == "config_empresa"


def test_licencia_proxima_a_vencer_avisa(db_session, monkeypatch):
    admin = crear_usuario_admin(db_session)
    _registrar_tasa_de_hoy(db_session)
    monkeypatch.setattr(
        "app.services.notificaciones.LicenciaService.estado_actual",
        lambda *a, **k: EstadoLicencia("ACTIVA", "ok", expira=datetime.now() + timedelta(days=5)),
    )

    notificaciones = NotificacionesService.obtener(db_session, admin.id_usuario)

    assert _claves(notificaciones) == {"licencia"}
    assert notificaciones[0].severidad == SEVERIDAD_MEDIA
    assert "vence el" in notificaciones[0].detalle


def test_las_mas_urgentes_van_primero(db_session, monkeypatch):
    _sin_licencia(monkeypatch)
    admin = crear_usuario_admin(db_session)  # sin tasa registrada -> "info"
    crear_producto(db_session, cantidad_unidad=1, cantidad_minima=Decimal("10.00"))  # "media"
    monkeypatch.setattr(
        "app.services.notificaciones.LicenciaService.estado_actual",
        lambda *a, **k: EstadoLicencia(ESTADO_VENCIDA, "vencida"),  # "alta"
    )

    severidades = [n.severidad for n in NotificacionesService.obtener(db_session, admin.id_usuario)]

    assert severidades == [SEVERIDAD_ALTA, SEVERIDAD_MEDIA, SEVERIDAD_INFO]


def test_usuario_sin_permisos_no_ve_ninguna_alerta(db_session, monkeypatch):
    _sin_licencia(monkeypatch)
    rol = crear_rol(db_session)
    usuario = crear_usuario(db_session, id_rol=rol.id_rol)
    crear_producto(db_session, cantidad_unidad=1, cantidad_minima=Decimal("10.00"))

    assert NotificacionesService.obtener(db_session, usuario.id_usuario) == []


def test_solo_ve_las_alertas_de_los_modulos_que_puede_ver(db_session, monkeypatch):
    _sin_licencia(monkeypatch)
    rol = crear_rol(db_session)
    asignar_permiso(db_session, rol, crear_permiso(db_session, recurso="inventario", accion="ver"))
    usuario = crear_usuario(db_session, id_rol=rol.id_rol)
    crear_producto(db_session, cantidad_unidad=1, cantidad_minima=Decimal("10.00"))
    # Sin tasa registrada, pero este rol no tiene 'tasas'/'ver': esa alerta no le corresponde.

    assert _claves(NotificacionesService.obtener(db_session, usuario.id_usuario)) == {"stock_bajo"}


def test_una_fuente_que_falla_no_tumba_las_demas(db_session, monkeypatch):
    _sin_licencia(monkeypatch)
    admin = crear_usuario_admin(db_session)
    _registrar_tasa_de_hoy(db_session)
    crear_producto(db_session, cantidad_unidad=1, cantidad_minima=Decimal("10.00"))

    def _revienta(session, id_usuario, hoy):
        raise RuntimeError("tabla inexistente")

    monkeypatch.setattr(NotificacionesService, "_cuentas_por_cobrar_vencidas", staticmethod(_revienta))

    assert _claves(NotificacionesService.obtener(db_session, admin.id_usuario)) == {"stock_bajo"}

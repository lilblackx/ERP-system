"""Botones de escritura de cada panel segun el rol del usuario.

Bug real (rol CAJERO, Inventario): el boton "Nuevo Producto" se mostraba sin tener inventario:crear y
abria el formulario antes de avisar que no habia permiso. Ningun panel validaba permisos en sus
botones. Aca se arma cada panel con usuarios y permisos REALES (db_session) para los roles ADMIN,
CAJERO y VENDEDOR (con la matriz que dejan las migraciones) y dos roles personalizados, y se
comprueba que cada boton aparece solo si el rol tiene el permiso que exige el servicio.

La barrera de seguridad sigue siendo el servicio (require_permiso); esto cubre la usabilidad: que el
usuario no vea acciones que va a fallar."""

import pytest
from PySide6.QtWidgets import QPushButton
from sqlalchemy.orm import sessionmaker

from app.db.models import Permiso
from app.ui.bancos_panel import BancosPanel
from app.ui.cajas_panel import CajasPanel
from app.ui.clientes_panel import ClientesPanel
from app.ui.compras import ComprasView
from app.ui.config_empresa_panel import ConfigEmpresaPanel
from app.ui.cuentas_bancarias_panel import CuentasBancariasPanel
from app.ui.cuentas_por_pagar_panel import CuentasPorPagarPanel
from app.ui.facturacion_panel import FacturacionPanel
from app.ui.inventario_panel import InventarioPanel
from app.ui.message_box import MessageBox
from app.ui.proveedores_panel import ProveedoresPanel
from app.ui.roles_permisos_panel import RolesPermisosPanel
from app.ui.rutas_panel import RutasPanel
from app.ui.tasas_panel import TasasPanel
from app.ui.usuarios_panel import UsuariosPanel
from app.ui.vendedores_panel import VendedoresPanel
from tests.factories import (
    asignar_permiso,
    crear_permiso,
    crear_rol,
    crear_usuario,
    crear_usuario_admin,
    crear_vendedor,
)

ADMIN = "ADMIN"  # operaciones que el servicio restringe al rol ADMIN literal

# Matriz de los roles sembrados por las migraciones (0004/0030/0041/0047 y el seed base).
PERMISOS_CAJERO = {
    ("dashboard", "ver"),
    ("clientes", "ver"),
    ("clientes", "crear"),
    ("inventario", "ver"),
    ("ventas", "ver"),
    ("ventas", "crear"),
    ("pagos", "ver"),
    ("pagos", "crear"),
    ("notas_credito", "ver"),
    ("notas_credito", "crear"),
    ("cajas", "ver"),
    ("cajas", "crear"),
    ("vendedores", "ver"),
    ("rutas", "ver"),
    ("tasas", "ver"),
}
PERMISOS_VENDEDOR = {("inventario", "ver"), ("reportes_comisiones", "ver"), ("reportes_ventas", "ver")}

RECURSOS = (
    "inventario",
    "clientes",
    "vendedores",
    "rutas",
    "proveedores",
    "bancos",
    "tasas",
    "ventas",
    "cajas",
    "pagos",
    "usuarios",
    "permisos",
    "empresa",
    "compras",
)
ACCIONES_COMPRAS = ("crear_oc", "crear_enmienda_oc", "recibir_mercancia", "crear_nota_devolucion")

# Un rol personalizado con todo menos eliminar, y uno de solo lectura.
PERMISOS_SUPERVISOR = (
    {(r, a) for r in RECURSOS for a in ("ver", "crear", "editar")}
    | {("compras", a) for a in ACCIONES_COMPRAS}
    | {("notas_credito", "ver"), ("notas_credito", "crear")}
)
PERMISOS_SOLO_LECTURA = {(r, "ver") for r in RECURSOS}

# panel -> [(etiqueta del boton o "attr:nombre", (recurso, accion) | ADMIN)]
PANELES = {
    "inventario": (
        InventarioPanel,
        [
            ("Nuevo Producto", ("inventario", "crear")),
            ("Editar seleccionado", ("inventario", "editar")),
            ("Cambiar estado", ("inventario", "eliminar")),
        ],
    ),
    "clientes": (
        ClientesPanel,
        [
            ("Nuevo Cliente", ("clientes", "crear")),
            ("Editar seleccionado", ("clientes", "editar")),
            ("Cambiar estado", ("clientes", "eliminar")),
        ],
    ),
    "vendedores": (
        VendedoresPanel,
        [
            ("Nuevo Vendedor", ("vendedores", "crear")),
            ("Editar seleccionado", ("vendedores", "editar")),
            ("Cambiar estado", ("vendedores", "eliminar")),
        ],
    ),
    "rutas": (
        RutasPanel,
        [
            ("Nueva Ruta", ("rutas", "crear")),
            ("Editar seleccionada", ("rutas", "editar")),
            ("Cambiar estado", ("rutas", "eliminar")),
        ],
    ),
    "proveedores": (
        ProveedoresPanel,
        [
            ("Nuevo Proveedor", ("proveedores", "crear")),
            ("Editar seleccionado", ("proveedores", "editar")),
            ("Cambiar estado", ("proveedores", "eliminar")),
        ],
    ),
    "bancos": (
        BancosPanel,
        [
            ("Nuevo Banco", ("bancos", "crear")),
            ("Editar seleccionado", ("bancos", "editar")),
            ("Cambiar estado", ("bancos", "eliminar")),
        ],
    ),
    "cuentas_bancarias": (
        CuentasBancariasPanel,
        [
            ("Nueva cuenta", ("bancos", "crear")),
            ("Conciliación de bancos", ("bancos", "crear")),
            ("Editar seleccionado", ("bancos", "editar")),
            ("Cambiar estado", ("bancos", "eliminar")),
        ],
    ),
    "tasas": (TasasPanel, [("Registrar tasa del día", ("tasas", "crear"))]),
    "facturacion": (
        FacturacionPanel,
        [("Nueva Factura", ("ventas", "crear")), ("Anular factura", ("ventas", "eliminar"))],
    ),
    "cajas": (
        CajasPanel,
        [
            ("Nueva Caja", ADMIN),
            ("Movimiento Manual", ("cajas", "crear")),
            ("Cerrar Turno", ADMIN),
        ],
    ),
    "cuentas_por_pagar": (CuentasPorPagarPanel, [("Pagar", ("pagos", "crear"))]),
    "usuarios": (
        UsuariosPanel,
        [
            ("Nuevo Usuario", ("usuarios", "crear")),
            ("Editar seleccionado", ("usuarios", "editar")),
            ("Cambiar estado", ("usuarios", "editar")),
            ("Desbloquear", ("usuarios", "editar")),
        ],
    ),
    "roles": (
        RolesPermisosPanel,
        [
            ("attr:btn_nuevo_rol", ("permisos", "crear")),
            ("attr:btn_editar_rol", ("permisos", "editar")),
            ("attr:btn_eliminar_rol", ("permisos", "eliminar")),
            ("Guardar permisos", ("permisos", "editar")),
        ],
    ),
    "config_empresa": (ConfigEmpresaPanel, [("Guardar Cambios", ("empresa", "editar"))]),
    "compras": (
        ComprasView,
        [
            ("Nueva ODC", ("compras", "crear_oc")),
            ("Enmendar", ("compras", "crear_enmienda_oc")),
            ("Rechazar (Devolución)", ("compras", "crear_nota_devolucion")),
            ("Nueva Factura", ("compras", "crear")),
            ("Anular factura", ("compras", "eliminar")),
        ],
    ),
}


@pytest.fixture(autouse=True)
def _sin_avisos_modales(monkeypatch):
    """Armar un panel para un rol sin su permiso 'ver' (que el sidebar nunca mostraria) hace que su carga
    inicial avise "sin permiso": un aviso modal bloquearia el test. Aca solo importan los botones."""
    for nombre in ("warning", "critical", "information"):
        monkeypatch.setattr(MessageBox, nombre, staticmethod(lambda *args, **kwargs: None))


def _usuario_con_permisos(db_session, permisos, vendedor=False):
    rol = crear_rol(db_session)
    for recurso, accion in sorted(permisos):
        permiso = db_session.query(Permiso).filter_by(recurso=recurso, accion=accion).first()
        asignar_permiso(db_session, rol, permiso or crear_permiso(db_session, recurso=recurso, accion=accion))
    extra = {"id_vendedor_usuario": crear_vendedor(db_session).id_vendedor} if vendedor else {}
    return crear_usuario(db_session, id_rol=rol.id_rol, **extra)


def _crear_usuario(db_session, rol):
    if rol == "ADMIN":
        return crear_usuario_admin(db_session), None
    if rol == "CAJERO":
        return _usuario_con_permisos(db_session, PERMISOS_CAJERO), PERMISOS_CAJERO
    if rol == "VENDEDOR":
        return _usuario_con_permisos(db_session, PERMISOS_VENDEDOR, vendedor=True), PERMISOS_VENDEDOR
    if rol == "SUPERVISOR":
        return _usuario_con_permisos(db_session, PERMISOS_SUPERVISOR), PERMISOS_SUPERVISOR
    return _usuario_con_permisos(db_session, PERMISOS_SOLO_LECTURA), PERMISOS_SOLO_LECTURA


def _construir(qtbot, db_session, clase, usuario):
    fabrica = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False)
    panel = clase(fabrica, usuario)
    qtbot.addWidget(panel)
    return panel


def _boton_mostrado(panel, etiqueta) -> bool:
    """El boton se arma siempre pero solo se agrega al layout (queda con padre) si el usuario puede."""
    if etiqueta.startswith("attr:"):
        return getattr(panel, etiqueta[5:]).parent() is not None
    return any(b.text() == etiqueta for b in panel.findChildren(QPushButton))


@pytest.mark.parametrize("rol", ["ADMIN", "CAJERO", "VENDEDOR", "SUPERVISOR", "SOLO_LECTURA"])
@pytest.mark.parametrize("nombre_panel", sorted(PANELES))
def test_cada_boton_de_escritura_aparece_solo_si_el_rol_tiene_el_permiso(qtbot, db_session, nombre_panel, rol):
    clase, botones = PANELES[nombre_panel]
    usuario, permisos = _crear_usuario(db_session, rol)
    panel = _construir(qtbot, db_session, clase, usuario)

    for etiqueta, requisito in botones:
        if rol == "ADMIN":
            esperado = True
        elif requisito == ADMIN:
            esperado = False
        else:
            esperado = requisito in permisos
        # Inventario oculta ademas todo a los usuarios vendedor, tengan o no el permiso.
        if nombre_panel == "inventario" and usuario.id_vendedor_usuario is not None:
            esperado = False
        assert _boton_mostrado(panel, etiqueta) is esperado, (
            f"{nombre_panel} / {etiqueta!r} con rol {rol}: esperado {'visible' if esperado else 'oculto'} "
            f"(requiere {requisito})"
        )


def test_el_cajero_no_ve_ningun_boton_de_escritura_de_modulos_back_office(qtbot, db_session):
    """Resumen legible del caso que motivo esto: el CAJERO solo conserva lo de caja y facturacion."""
    usuario, _ = _crear_usuario(db_session, "CAJERO")

    visibles = {}
    for nombre, (clase, botones) in PANELES.items():
        panel = _construir(qtbot, db_session, clase, usuario)
        visibles[nombre] = {e for e, _ in botones if _boton_mostrado(panel, e)}

    assert visibles["inventario"] == set()
    assert visibles["vendedores"] == set()
    assert visibles["rutas"] == set()
    assert visibles["proveedores"] == set()
    assert visibles["bancos"] == set()
    assert visibles["usuarios"] == set()
    assert visibles["roles"] == set()
    assert visibles["config_empresa"] == set()
    assert visibles["compras"] == set()
    assert visibles["clientes"] == {"Nuevo Cliente"}  # tiene clientes:crear, no editar ni eliminar
    assert visibles["facturacion"] == {"Nueva Factura"}  # no puede anular
    assert visibles["cajas"] == {"Movimiento Manual"}  # crear caja y cerrar turno son solo ADMIN
    assert visibles["cuentas_por_pagar"] == {"Pagar"}  # ver nota: pagos es un permiso unico

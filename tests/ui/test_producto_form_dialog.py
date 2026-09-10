"""Tests de ProductoFormDialog tras migrar costo_input/precio_venta_input (AMOUNT) y
cantidad_unidad_input/cantidad_minima_input (QUANTITY) de QDoubleSpinBox a
NumericLineEdit -- ver app/ui/producto_form_dialog.py.

A diferencia de ClienteFormDialog/ProveedorFormDialog, _build_ui() de este dialogo SI
hace consultas reales contra la Session al construirse (CategoriaService.listar() via
_cargar_categorias(), que a su vez pasa por require_permiso()) -- por eso el mock de
sesion aca resuelve un usuario ADMIN real en session.get(Usuario/Rol, ...) en vez de
dejar que require_permiso() explote con PermisoDenegadoError (que dispararia
MessageBox.warning(), un QDialog modal con .exec() que colgaria el test)."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.ui.producto_form_dialog import ProductoFormDialog

_USUARIO_ADMIN = SimpleNamespace(estado="ACTIVO", bloqueado_desde=None, id_rol=1, nombre_usuario="admin")
_ROL_ADMIN = SimpleNamespace(nombre="ADMIN")


def _mock_session(precio_existente: Decimal | None = None) -> MagicMock:
    session = MagicMock()

    def get_side_effect(modelo, _id):
        nombre = getattr(modelo, "__name__", "")
        if nombre == "Usuario":
            return _USUARIO_ADMIN
        if nombre == "Rol":
            return _ROL_ADMIN
        return None

    session.get.side_effect = get_side_effect

    def query_side_effect(modelo):
        nombre = getattr(modelo, "__name__", "")
        query_mock = MagicMock()
        if nombre == "Categoria":
            query_mock.order_by.return_value.all.return_value = []
        elif nombre == "ProductoPrecio":
            precio_mock = None
            if precio_existente is not None:
                precio_mock = SimpleNamespace(precio_venta=precio_existente)
            query_mock.filter.return_value.first.return_value = precio_mock
        return query_mock

    session.query.side_effect = query_side_effect
    return session


def _dar_foco(qtbot, campo):
    # Mismo gotcha que tests/ui/test_proveedor_form_dialog.py: un campo anidado en un
    # QDialog no shown() nunca resuelve el foco logico de Qt bajo
    # QT_QPA_PLATFORM=offscreen sin exponer tambien la ventana top-level.
    campo.window().show()
    qtbot.waitExposed(campo.window())
    campo.setFocus()
    qtbot.waitUntil(campo.hasFocus)


def _escribir_y_perder_foco(qtbot, campo, texto):
    _dar_foco(qtbot, campo)
    qtbot.keyClicks(campo, texto)
    campo.clearFocus()


def test_campos_monetarios_arrancan_en_cero_formateado(qtbot):
    dialogo = ProductoFormDialog(_mock_session(), id_usuario=1)
    qtbot.addWidget(dialogo)
    assert dialogo.costo_input.text() == "$ 0,00"
    assert dialogo.costo_input.get_value() == Decimal("0")
    assert dialogo.precio_venta_input.text() == "$ 0,00"
    assert dialogo.precio_venta_input.get_value() == Decimal("0")


def test_campos_cantidad_arrancan_en_cero_formateado(qtbot):
    dialogo = ProductoFormDialog(_mock_session(), id_usuario=1)
    qtbot.addWidget(dialogo)
    assert dialogo.cantidad_unidad_input.text() == "0,00"
    assert dialogo.cantidad_unidad_input.get_value() == Decimal("0")
    assert dialogo.cantidad_minima_input.text() == "0,00"
    assert dialogo.cantidad_minima_input.get_value() == Decimal("0")


def test_costo_formatea_miles_al_perder_foco(qtbot):
    dialogo = ProductoFormDialog(_mock_session(), id_usuario=1)
    qtbot.addWidget(dialogo)
    _escribir_y_perder_foco(qtbot, dialogo.costo_input, "12345,5")
    assert dialogo.costo_input.get_value() == Decimal("12345.50")
    assert dialogo.costo_input.text() == "$ 12.345,50"


def test_actualizar_margen_se_recalcula_al_perder_foco(qtbot):
    dialogo = ProductoFormDialog(_mock_session(), id_usuario=1)
    qtbot.addWidget(dialogo)
    _escribir_y_perder_foco(qtbot, dialogo.costo_input, "100")
    _escribir_y_perder_foco(qtbot, dialogo.precio_venta_input, "150")
    assert dialogo.lbl_margen.text() == "Margen: 50.00%"


def test_actualizar_margen_con_costo_cero_no_divide_por_cero(qtbot):
    dialogo = ProductoFormDialog(_mock_session(), id_usuario=1)
    qtbot.addWidget(dialogo)
    _escribir_y_perder_foco(qtbot, dialogo.precio_venta_input, "50")
    assert dialogo.lbl_margen.text() == "Margen: 0.00%"


def test_precargar_setea_valores_desde_producto(qtbot):
    dialogo = ProductoFormDialog(_mock_session(precio_existente=Decimal("19.99")), id_usuario=1)
    qtbot.addWidget(dialogo)
    producto = SimpleNamespace(
        id_producto=7,
        cod_producto="PROD-001",
        nombre_producto="Refresco Cola 2L",
        descripcion_producto=None,
        costo_producto=Decimal("8.50"),
        cantidad_unidad=Decimal("120.00"),
        cantidad_minima=Decimal("10.00"),
        id_categoria=None,
        fecha_vencimiento=None,
    )
    dialogo._precargar(producto)
    assert dialogo.costo_input.get_value() == Decimal("8.50")
    assert dialogo.cantidad_unidad_input.get_value() == Decimal("120.00")
    assert dialogo.cantidad_minima_input.get_value() == Decimal("10.00")
    assert dialogo.precio_venta_input.get_value() == Decimal("19.99")


def test_get_data_devuelve_decimal(qtbot):
    dialogo = ProductoFormDialog(_mock_session(), id_usuario=1)
    qtbot.addWidget(dialogo)
    dialogo.codigo_input.setText("PROD-002")
    dialogo.nombre_input.setText("Otro Producto")
    _escribir_y_perder_foco(qtbot, dialogo.costo_input, "5,25")
    _escribir_y_perder_foco(qtbot, dialogo.cantidad_unidad_input, "42,5")
    _escribir_y_perder_foco(qtbot, dialogo.cantidad_minima_input, "3")

    datos = dialogo.get_data()

    assert datos["costo_producto"] == Decimal("5.25")
    assert datos["cantidad_unidad"] == Decimal("42.50")
    assert datos["cantidad_minima"] == Decimal("3.00")


def test_get_precio_venta_devuelve_decimal(qtbot):
    dialogo = ProductoFormDialog(_mock_session(), id_usuario=1)
    qtbot.addWidget(dialogo)
    _escribir_y_perder_foco(qtbot, dialogo.precio_venta_input, "99,90")
    assert dialogo.get_precio_venta() == Decimal("99.90")

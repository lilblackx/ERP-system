"""Control de paginacion central (app/ui/paginacion.py): numeracion desde 1, botones y senales."""

from app.ui.paginacion import ControlPaginacion, MixinPaginacion


def _control(qtbot):
    control = ControlPaginacion()
    qtbot.addWidget(control)
    return control


def test_arranca_en_la_pagina_1_de_1_con_los_dos_botones_deshabilitados(qtbot):
    c = _control(qtbot)

    assert (c.pagina, c.total_paginas) == (1, 1)
    assert c.lbl_pagina.text() == "Página 1 de 1"
    assert not c.btn_anterior.isEnabled() and not c.btn_siguiente.isEnabled()


def test_actualizar_refleja_lo_que_devolvio_el_servicio(qtbot):
    c = _control(qtbot)

    c.actualizar(2, 5)

    assert c.lbl_pagina.text() == "Página 2 de 5"
    assert c.btn_anterior.isEnabled() and c.btn_siguiente.isEnabled()


def test_en_la_primera_pagina_no_se_puede_retroceder_y_en_la_ultima_no_se_puede_avanzar(qtbot):
    c = _control(qtbot)

    c.actualizar(1, 3)
    assert not c.btn_anterior.isEnabled() and c.btn_siguiente.isEnabled()
    c.actualizar(3, 3)
    assert c.btn_anterior.isEnabled() and not c.btn_siguiente.isEnabled()


def test_siguiente_y_anterior_emiten_la_pagina_nueva_desde_1(qtbot):
    c = _control(qtbot)
    c.actualizar(1, 3)

    with qtbot.waitSignal(c.pagina_cambiada) as s:
        c.btn_siguiente.click()
    assert s.args == [2] and c.pagina == 2

    with qtbot.waitSignal(c.pagina_cambiada) as s:
        c.btn_anterior.click()
    assert s.args == [1] and c.pagina == 1


def test_no_se_pasa_de_los_limites_ni_emite_si_no_cambia(qtbot):
    c = _control(qtbot)
    c.actualizar(3, 3)
    emitidas = []
    c.pagina_cambiada.connect(emitidas.append)

    c.siguiente()  # ya es la ultima
    c.ir_a(99)  # se lleva a la ultima (no cambia)
    c.ir_a(0)  # se lleva a la 1

    assert emitidas == [1]
    assert c.pagina == 1


def test_actualizar_y_reiniciar_no_emiten_para_no_disparar_otra_carga(qtbot):
    c = _control(qtbot)
    emitidas = []
    c.pagina_cambiada.connect(emitidas.append)

    c.actualizar(4, 9)
    c.reiniciar()

    assert emitidas == []
    assert c.pagina == 1 and c.total_paginas == 9


def test_actualizar_corrige_una_pagina_fuera_de_rango(qtbot):
    c = _control(qtbot)

    c.actualizar(9, 3)  # el servicio ya la lleva a la ultima; el control tambien se protege
    assert c.pagina == 3
    c.actualizar(0, 0)
    assert (c.pagina, c.total_paginas) == (1, 1)


def test_el_mixin_expone_pagina_actual_y_total_paginas_sin_duplicar_estado(qtbot):
    class Panel(MixinPaginacion):
        pass

    panel = Panel()
    panel.paginacion = _control(qtbot)
    panel.paginacion.actualizar(1, 4)

    panel.pagina_actual = 3  # como hacen los filtros / la carga
    assert panel.paginacion.pagina == 3
    assert (panel.pagina_actual, panel.total_paginas) == (3, 4)
    panel.pagina_actual = 1
    assert panel.paginacion.pagina == 1


def test_actualizar_desde_usa_el_resultado_del_servicio(qtbot):
    c = _control(qtbot)

    c.actualizar_desde({"pagina": 2, "total_paginas": 4, "total": 70, "por_pagina": 20})

    assert (c.pagina, c.total_paginas) == (2, 4)
    assert c.lbl_pagina.text() == "Página 2 de 4"  # sin el total por defecto


def test_actualizar_desde_puede_mostrar_el_total_de_registros(qtbot):
    c = _control(qtbot)

    c.actualizar_desde({"pagina": 1, "total_paginas": 3, "total": 45}, mostrar_total=True)

    assert c.lbl_pagina.text() == "Página 1 de 3 (45)"


def test_actualizar_desde_calcula_las_paginas_si_el_resultado_no_las_trae(qtbot):
    c = _control(qtbot)

    c.actualizar_desde({"items": [], "total": 45, "pagina": 3, "por_pagina": 20})  # resultado armado a mano

    assert (c.pagina, c.total_paginas) == (3, 3)
    c.actualizar_desde({"total": 0, "pagina": 1, "por_pagina": 20})
    assert c.total_paginas == 1


def test_paginas_por_clave_lee_y_escribe_en_el_control_de_cada_pestana(qtbot):
    from app.ui.paginacion import PaginasPorClave

    controles = {"oc": _control(qtbot), "nr": _control(qtbot)}
    paginas, totales = PaginasPorClave(controles), PaginasPorClave(controles, total=True)
    controles["oc"].actualizar(1, 5)

    paginas["oc"] = 3
    assert controles["oc"].pagina == 3 and paginas["oc"] == 3 and totales["oc"] == 5
    assert paginas["nr"] == 1  # cada pestaña lleva su propia pagina
    with pytest.raises(TypeError):
        totales["oc"] = 9


import pytest  # noqa: E402

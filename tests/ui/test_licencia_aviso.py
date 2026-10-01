"""AvisoLicencia: muestra un dialogo claro al bloquearse una escritura, pero no uno por cada
sentencia bloqueada (un guardado dispara varias seguidas)."""

from app.services.licencia import ESTADO_REVOCADA, EstadoLicencia
from app.ui import licencia_aviso
from app.ui.licencia_aviso import AvisoLicencia


def test_avisa_una_sola_vez_por_intervalo(qtbot, monkeypatch):
    mostrados = []
    monkeypatch.setattr(licencia_aviso.MessageBox, "warning", lambda parent, titulo, texto: mostrados.append(texto))
    aviso = AvisoLicencia()
    estado = EstadoLicencia(ESTADO_REVOCADA, "Esta licencia fue revocada.")

    aviso.notificar(estado)
    aviso.notificar(estado)
    aviso.notificar(estado)

    assert len(mostrados) == 1
    assert "revocada" in mostrados[0]
    assert "solo lectura" in mostrados[0]


def test_vuelve_a_avisar_pasado_el_intervalo(qtbot, monkeypatch):
    mostrados = []
    monkeypatch.setattr(licencia_aviso.MessageBox, "warning", lambda parent, titulo, texto: mostrados.append(texto))
    aviso = AvisoLicencia()
    estado = EstadoLicencia(ESTADO_REVOCADA, "x")

    aviso.notificar(estado)
    aviso._ultimo_aviso -= licencia_aviso.INTERVALO_ENTRE_AVISOS_SEG + 1
    aviso.notificar(estado)

    assert len(mostrados) == 2

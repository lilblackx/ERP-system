"""El instalador (packaging/instalador.iss) y el servicio (app/servicio_licencia.py) deben
llamarse igual: el servicio lo registra el instalador con sc.exe, pero el codigo Python lo
consulta y lo controla por su nombre. Tambien cubre que el cliente vea solo "Nexo ERP"."""

import re
from pathlib import Path

from app import servicio_licencia

RAIZ = Path(__file__).resolve().parent.parent
INSTALADOR = (RAIZ / "packaging" / "instalador.iss").read_text(encoding="utf-8-sig")


def _define(nombre: str) -> str:
    coincidencia = re.search(rf'^#define {nombre} "([^"]*)"', INSTALADOR, re.MULTILINE)
    assert coincidencia, f"#define {nombre} no esta en instalador.iss"
    return coincidencia.group(1)


def test_el_nombre_interno_del_servicio_coincide_entre_instalador_y_python():
    assert _define("Servicio") == servicio_licencia.NOMBRE_SERVICIO == "NexoERPLicencia"


def test_el_instalador_registra_el_servicio_con_el_mismo_nombre_visible_y_descripcion_que_python():
    assert f'DisplayName= "{servicio_licencia.NOMBRE_VISIBLE}"' in INSTALADOR
    descripcion_instalador = re.search(r"'description ' \+ NOMBRE_SERVICIO \+ ' \"([^\"]*)\"'", INSTALADOR)
    assert descripcion_instalador
    assert descripcion_instalador.group(1) in servicio_licencia.DESCRIPCION


def test_el_cliente_ve_nexo_erp_en_servicio_firewall_y_ejecutables():
    assert servicio_licencia.NOMBRE_VISIBLE.startswith("Nexo ERP")
    assert "Distribuidora DJ" not in servicio_licencia.DESCRIPCION
    assert _define("ReglaFirewall").startswith("Nexo ERP")
    assert "NexoERP.exe" in INSTALADOR
    for viejo in ("DistribuidoraDJ.exe", "DJ-Servicio.exe", "DJ-Herramientas.exe"):
        # Solo aparecen en [InstallDelete], para borrar los de una version anterior.
        lineas = [linea for linea in INSTALADOR.splitlines() if viejo in linea]
        assert lineas and all(linea.startswith("Type: files; Name:") for linea in lineas), viejo


def test_el_instalador_migra_el_servicio_y_la_regla_de_firewall_anteriores():
    assert _define("ServicioAnterior") == "DistribuidoraDJLicencia"
    assert _define("ReglaFirewallAnterior") == "Distribuidora DJ - SQL Server"
    assert "'delete ' + NOMBRE_SERVICIO_ANTERIOR" in INSTALADOR
    assert "new name=" in INSTALADOR

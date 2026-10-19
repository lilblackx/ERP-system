"""
Abre (o crea y abre) una caja real contra la base configurada, usando el primer usuario
ADMIN activo que encuentre -- util para probar el flujo de facturacion/pagos de contado
mientras no existe todavia un panel de UI para administrar cajas (crear/listar cajas).

No es un bypass de codigo: usa CajaService.abrir_caja() tal cual lo hace la app, asi que
respeta las mismas reglas (solo ADMIN, no permite abrir una caja ya abierta, etc.). La
caja queda abierta al terminar -- correlo de nuevo mas adelante para abrir otra caja, o
usa la UI (CajaAperturaDialog) para cerrarla cuando termines de probar.
"""

import sys
from decimal import Decimal
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.db.models import Caja, Rol, Usuario
from app.db.session import SessionLocal
from app.services.tesoreria import CajaService

NOMBRE_CAJA_DEFAULT = "Caja Principal"
SALDO_APERTURA_DEFAULT = Decimal("100.00")


def main():
    session = SessionLocal()
    try:
        admin = session.query(Usuario).join(Rol).filter(Rol.nombre == "ADMIN", Usuario.estado == "ACTIVO").first()
        if admin is None:
            print("No hay ningun usuario ADMIN activo. Cree uno con scripts/create_admin_user.py.")
            return

        nombre_caja = input(f"Nombre de la caja [{NOMBRE_CAJA_DEFAULT}]: ").strip() or NOMBRE_CAJA_DEFAULT
        caja = session.query(Caja).filter(Caja.nombre_caja == nombre_caja).first()
        if caja is None:
            caja = Caja(nombre_caja=nombre_caja, estado_caja="CERRADA")
            session.add(caja)
            session.commit()
            print(f"Caja '{nombre_caja}' creada (id={caja.id_caja}).")

        if caja.fecha_apertura is not None and caja.fecha_cierre is None:
            print(f"La caja '{nombre_caja}' (id={caja.id_caja}) ya esta abierta desde {caja.fecha_apertura}.")
            return

        saldo_input = input(f"Saldo de apertura [{SALDO_APERTURA_DEFAULT}]: ").strip()
        saldo_apertura = Decimal(saldo_input) if saldo_input else SALDO_APERTURA_DEFAULT

        CajaService.abrir_caja(session, caja.id_caja, admin.id_usuario, saldo_apertura)
        print(
            f"Caja '{nombre_caja}' (id={caja.id_caja}) abierta con saldo {saldo_apertura} "
            f"por '{admin.nombre_usuario}'. Queda abierta para pruebas manuales."
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()

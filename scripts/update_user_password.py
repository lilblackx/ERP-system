import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.db.models import Usuario
from app.db.session import SessionLocal
from app.services.auth import hash_password


def main():
    if len(sys.argv) >= 3:
        nombre_usuario = sys.argv[1].strip()
        clave = sys.argv[2].strip()
    else:
        nombre_usuario = input("Nombre de usuario: ").strip()
        clave = input("Nueva clave: ").strip()

    session = SessionLocal()
    try:
        usuario = session.query(Usuario).filter(Usuario.nombre_usuario == nombre_usuario).first()
        if usuario is None:
            print(f"Usuario '{nombre_usuario}' no encontrado.")
            return

        usuario.clave = hash_password(clave)
        usuario.estado = "ACTIVO"
        usuario.intentos_fallidos = 0
        usuario.bloqueado_desde = None
        session.commit()
        print(f"Usuario '{nombre_usuario}' actualizado correctamente.")
    finally:
        session.close()


if __name__ == "__main__":
    main()

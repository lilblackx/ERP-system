import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.db.models import Rol, Usuario
from app.db.session import SessionLocal
from app.services.auth import hash_password, validar_password_policy


def main():
    nombre_usuario = input("Nombre de usuario: ").strip()
    clave = input("Clave: ").strip()
    nombre = input("Nombre completo: ").strip()

    try:
        validar_password_policy(clave)
    except ValueError as exc:
        print(exc)
        return

    session = SessionLocal()
    try:
        rol_admin = session.query(Rol).filter(Rol.nombre == "ADMIN").first()
        if rol_admin is None:
            print("No existe el rol ADMIN. Corre primero el seed de roles del schema.")
            return

        usuario = Usuario(
            nombre_usuario=nombre_usuario,
            nombre=nombre,
            clave=hash_password(clave),
            id_rol=rol_admin.id_rol,
        )
        session.add(usuario)
        session.commit()
        print(f"Usuario '{nombre_usuario}' creado con rol ADMIN.")
    finally:
        session.close()


if __name__ == "__main__":
    main()

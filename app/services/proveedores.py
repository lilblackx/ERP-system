from sqlalchemy.orm import Session

from app.db.models import Proveedor
from app.services.auditoria import AuditoriaService
from app.services.permisos import require_permiso

ESTADOS_VALIDOS = {"ACTIVO", "INACTIVO"}


class ProveedorService:
    @staticmethod
    def _validar_unico(session: Session, campo: str, valor: str | None, excluir_id: int | None = None) -> None:
        if not valor:
            return
        query = session.query(Proveedor).filter(getattr(Proveedor, campo) == valor)
        if excluir_id is not None:
            query = query.filter(Proveedor.id_proveedor != excluir_id)
        if query.first() is not None:
            raise ValueError(f"Ya existe un proveedor con {campo}='{valor}'")

    @staticmethod
    def obtener(session: Session, id_proveedor: int, id_usuario: int | None = None) -> Proveedor | None:
        require_permiso(session, id_usuario, "proveedores", "ver")
        return session.get(Proveedor, id_proveedor)

    @staticmethod
    def listar(
        session: Session, texto_busqueda: str | None = None, id_usuario: int | None = None
    ) -> list[Proveedor]:
        require_permiso(session, id_usuario, "proveedores", "ver")
        query = session.query(Proveedor)
        if texto_busqueda:
            like = f"%{texto_busqueda}%"
            query = query.filter(
                Proveedor.nombre_razon_social.ilike(like)
                | Proveedor.identificacion_proveedor.ilike(like)
                | Proveedor.codigo_proveedor.ilike(like)
            )
        return query.order_by(Proveedor.nombre_razon_social).all()

    @staticmethod
    def _validar_requeridos(datos: dict) -> None:
        if not datos.get("codigo_proveedor"):
            raise ValueError("codigo_proveedor es requerido")
        if not datos.get("identificacion_proveedor"):
            raise ValueError("identificacion_proveedor es requerido")

    @staticmethod
    def crear(session: Session, **datos) -> Proveedor:
        require_permiso(session, datos.get("creado_por"), "proveedores", "crear")
        ProveedorService._validar_requeridos(datos)
        ProveedorService._validar_unico(session, "codigo_proveedor", datos.get("codigo_proveedor"))
        ProveedorService._validar_unico(session, "identificacion_proveedor", datos.get("identificacion_proveedor"))
        proveedor = Proveedor(**datos)
        session.add(proveedor)
        session.commit()
        session.refresh(proveedor)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=proveedor.creado_por,
            accion="CREAR_PROVEEDOR",
            modulo="PROVEEDORES",
            detalle={"id_proveedor": proveedor.id_proveedor, "nombre_razon_social": proveedor.nombre_razon_social},
        )
        return proveedor

    @staticmethod
    def actualizar(session: Session, id_proveedor: int, id_usuario: int | None = None, **datos) -> Proveedor:
        require_permiso(session, id_usuario, "proveedores", "editar")
        proveedor = session.get(Proveedor, id_proveedor)
        if proveedor is None:
            raise ValueError("Proveedor no encontrado")

        if "codigo_proveedor" in datos and not datos["codigo_proveedor"]:
            raise ValueError("codigo_proveedor es requerido")
        if "identificacion_proveedor" in datos and not datos["identificacion_proveedor"]:
            raise ValueError("identificacion_proveedor es requerido")

        nuevo_codigo = datos.get("codigo_proveedor")
        if nuevo_codigo and nuevo_codigo != proveedor.codigo_proveedor:
            ProveedorService._validar_unico(session, "codigo_proveedor", nuevo_codigo, excluir_id=id_proveedor)

        nueva_identificacion = datos.get("identificacion_proveedor")
        if nueva_identificacion and nueva_identificacion != proveedor.identificacion_proveedor:
            ProveedorService._validar_unico(
                session, "identificacion_proveedor", nueva_identificacion, excluir_id=id_proveedor
            )

        for campo, valor in datos.items():
            setattr(proveedor, campo, valor)
        session.commit()
        session.refresh(proveedor)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="ACTUALIZAR_PROVEEDOR",
            modulo="PROVEEDORES",
            detalle={"id_proveedor": proveedor.id_proveedor, "campos": list(datos.keys())},
        )
        return proveedor

    @staticmethod
    def actualizar_credito(
        session: Session,
        id_proveedor: int,
        limite_credito=None,
        dias_credito: int | None = None,
        id_usuario: int | None = None,
    ) -> Proveedor:
        require_permiso(session, id_usuario, "proveedores", "editar")
        proveedor = session.get(Proveedor, id_proveedor)
        if proveedor is None:
            raise ValueError("Proveedor no encontrado")
        if limite_credito is not None:
            proveedor.limite_credito = limite_credito
        if dias_credito is not None:
            proveedor.dias_credito = dias_credito
        session.commit()
        session.refresh(proveedor)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="AJUSTE_CREDITO_PROVEEDOR",
            modulo="PROVEEDORES",
            detalle={
                "id_proveedor": proveedor.id_proveedor,
                "limite_credito": str(proveedor.limite_credito),
                "dias_credito": proveedor.dias_credito,
            },
        )
        return proveedor

    # Un proveedor nunca se borra fisicamente: FK_compras_id_proveedor es ON DELETE NO
    # ACTION, asi que borrar uno con compras registradas revienta con un IntegrityError
    # crudo de pyodbc -- y aunque no tenga ninguna todavia, podria tenerlas despues, asi
    # que la politica es no permitir el DELETE nunca. Usar cambiar_estado(...,
    # "INACTIVO") para retirarlo de circulacion preservando el historial. Decision de
    # producto 2026-08-22 (hallazgo de auditoria del mismo dia).
    @staticmethod
    def eliminar(session: Session, id_proveedor: int, id_usuario: int | None = None) -> None:
        require_permiso(session, id_usuario, "proveedores", "eliminar")
        raise ValueError(
            "No se puede eliminar un proveedor para proteger la integridad de los datos. "
            "Use ProveedorService.cambiar_estado() para desactivarlo."
        )

    @staticmethod
    def cambiar_estado(
        session: Session, id_proveedor: int, nuevo_estado: str, id_usuario: int | None = None
    ) -> Proveedor:
        require_permiso(session, id_usuario, "proveedores", "eliminar")
        if nuevo_estado not in ESTADOS_VALIDOS:
            raise ValueError(f"nuevo_estado debe ser uno de {ESTADOS_VALIDOS}")
        proveedor = session.get(Proveedor, id_proveedor)
        if proveedor is None:
            raise ValueError("Proveedor no encontrado")

        proveedor.estado_proveedor = nuevo_estado
        session.commit()
        session.refresh(proveedor)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="CAMBIAR_ESTADO_PROVEEDOR",
            modulo="PROVEEDORES",
            detalle={"id_proveedor": proveedor.id_proveedor, "nuevo_estado": nuevo_estado},
        )
        return proveedor

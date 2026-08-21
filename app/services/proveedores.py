from sqlalchemy.orm import Session

from app.db.models import Proveedor
from app.services.auditoria import AuditoriaService


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
    def obtener(session: Session, id_proveedor: int) -> Proveedor | None:
        return session.get(Proveedor, id_proveedor)

    @staticmethod
    def listar(session: Session, texto_busqueda: str | None = None) -> list[Proveedor]:
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

    @staticmethod
    def eliminar(session: Session, id_proveedor: int, id_usuario: int | None = None) -> None:
        proveedor = session.get(Proveedor, id_proveedor)
        if proveedor is None:
            return
        detalle = {"id_proveedor": proveedor.id_proveedor, "nombre_razon_social": proveedor.nombre_razon_social}
        session.delete(proveedor)
        session.commit()

        AuditoriaService.registrar_evento(
            session, id_usuario=id_usuario, accion="ELIMINAR_PROVEEDOR", modulo="PROVEEDORES", detalle=detalle
        )

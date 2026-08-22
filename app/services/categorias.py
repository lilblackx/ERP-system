from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Categoria, Inventario
from app.services.auditoria import AuditoriaService
from app.services.permisos import require_permiso


class CategoriaService:
    @staticmethod
    def listar(session: Session, id_usuario: int | None = None) -> list[Categoria]:
        require_permiso(session, id_usuario, "categorias", "ver")
        return session.query(Categoria).order_by(Categoria.nombre).all()

    @staticmethod
    def listar_con_conteo(session: Session, id_usuario: int | None = None) -> list[dict]:
        require_permiso(session, id_usuario, "categorias", "ver")
        filas = (
            session.query(Categoria, func.count(Inventario.id_producto).label("total_productos"))
            .outerjoin(Inventario, Inventario.id_categoria == Categoria.id_categoria)
            .group_by(Categoria.id_categoria, Categoria.nombre, Categoria.creado_por, Categoria.fecha_creacion)
            .order_by(Categoria.nombre)
            .all()
        )
        return [{"categoria": categoria, "total_productos": total} for categoria, total in filas]

    @staticmethod
    def obtener(session: Session, id_categoria: int, id_usuario: int | None = None) -> Categoria | None:
        require_permiso(session, id_usuario, "categorias", "ver")
        return session.get(Categoria, id_categoria)

    @staticmethod
    def contar_productos(session: Session, id_categoria: int) -> int:
        return session.query(Inventario).filter(Inventario.id_categoria == id_categoria).count()

    @staticmethod
    def crear(session: Session, **datos) -> Categoria:
        require_permiso(session, datos.get("creado_por"), "categorias", "crear")
        categoria = Categoria(**datos)
        session.add(categoria)
        session.commit()
        session.refresh(categoria)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=categoria.creado_por,
            accion="CREAR_CATEGORIA",
            modulo="INVENTARIO",
            detalle={"id_categoria": categoria.id_categoria, "nombre": categoria.nombre},
        )
        return categoria

    @staticmethod
    def actualizar(session: Session, id_categoria: int, id_usuario: int | None = None, **datos) -> Categoria:
        require_permiso(session, id_usuario, "categorias", "editar")
        categoria = session.get(Categoria, id_categoria)
        if categoria is None:
            raise ValueError("Categoria no encontrada")
        for campo, valor in datos.items():
            setattr(categoria, campo, valor)
        session.commit()
        session.refresh(categoria)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="ACTUALIZAR_CATEGORIA",
            modulo="INVENTARIO",
            detalle={"id_categoria": categoria.id_categoria, "campos": list(datos.keys())},
        )
        return categoria

    @staticmethod
    def eliminar(session: Session, id_categoria: int, id_usuario: int | None = None) -> None:
        require_permiso(session, id_usuario, "categorias", "eliminar")
        categoria = session.get(Categoria, id_categoria)
        if categoria is None:
            return
        if CategoriaService.contar_productos(session, id_categoria) > 0:
            raise ValueError("No se puede eliminar: existen productos asociados a la categoria")
        detalle = {"id_categoria": categoria.id_categoria, "nombre": categoria.nombre}
        session.delete(categoria)
        session.commit()

        AuditoriaService.registrar_evento(
            session, id_usuario=id_usuario, accion="ELIMINAR_CATEGORIA", modulo="INVENTARIO", detalle=detalle
        )

import datetime

from sqlalchemy.orm import Session

from app.db.models import Banco
from app.services.auditoria import AuditoriaService
from app.services.permisos import require_permiso

ESTADOS_VALIDOS = {"ACTIVO", "INACTIVO"}
TIPOS_VALIDOS = {"AHORRO", "CORRIENTE"}


class BancoService:
    @staticmethod
    def _validar_unico(session: Session, campo: str, valor: str | None, excluir_id: int | None = None) -> None:
        if not valor:
            return
        query = session.query(Banco).filter(getattr(Banco, campo) == valor)
        if excluir_id is not None:
            query = query.filter(Banco.id_banco != excluir_id)
        if query.first() is not None:
            raise ValueError(f"Ya existe un banco con {campo}='{valor}'")

    @staticmethod
    def obtener(session: Session, id_banco: int, id_usuario: int | None = None) -> Banco | None:
        require_permiso(session, id_usuario, "bancos", "ver")
        return session.get(Banco, id_banco)

    @staticmethod
    def listar(
        session: Session,
        texto_busqueda: str | None = None,
        estado_banco: str | None = None,
        id_usuario: int | None = None,
        pagina: int = 1,
        por_pagina: int = 20,
    ) -> dict:
        require_permiso(session, id_usuario, "bancos", "ver")
        query = session.query(Banco)
        if texto_busqueda:
            like = f"%{texto_busqueda}%"
            query = query.filter(
                Banco.nombre_banco.ilike(like) | Banco.identificacion_banco.ilike(like) | Banco.codigo_banco.ilike(like)
            )
        if estado_banco:
            query = query.filter(Banco.estado_banco == estado_banco)

        query = query.order_by(Banco.nombre_banco)
        total = query.count()
        bancos = query.offset((pagina - 1) * por_pagina).limit(por_pagina).all()
        return {"items": bancos, "total": total, "pagina": pagina, "por_pagina": por_pagina}

    @staticmethod
    def _validar_requeridos(datos: dict) -> None:
        if not datos.get("codigo_banco"):
            raise ValueError("codigo_banco es requerido")
        if not datos.get("nombre_banco"):
            raise ValueError("nombre_banco es requerido")
        if not datos.get("identificacion_banco"):
            raise ValueError("identificacion_banco es requerido")
        if not datos.get("tipo_banco"):
            raise ValueError("tipo_banco es requerido")
        if datos.get("tipo_banco") not in TIPOS_VALIDOS:
            raise ValueError(f"tipo_banco debe ser uno de {TIPOS_VALIDOS}")

    @staticmethod
    def crear(session: Session, **datos) -> Banco:
        require_permiso(session, datos.get("creado_por"), "bancos", "crear")
        BancoService._validar_requeridos(datos)
        BancoService._validar_unico(session, "codigo_banco", datos.get("codigo_banco"))
        BancoService._validar_unico(session, "identificacion_banco", datos.get("identificacion_banco"))
        # Establecer fecha de creación explícitamente
        if "fecha_creacion" not in datos:
            datos["fecha_creacion"] = datetime.datetime.now()
        banco = Banco(**datos)
        session.add(banco)
        session.commit()
        session.refresh(banco)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=banco.creado_por,
            accion="CREAR_BANCO",
            modulo="BANCOS",
            detalle={"id_banco": banco.id_banco, "nombre_banco": banco.nombre_banco},
        )
        return banco

    @staticmethod
    def actualizar(session: Session, id_banco: int, id_usuario: int | None = None, **datos) -> Banco:
        require_permiso(session, id_usuario, "bancos", "editar")
        banco = session.get(Banco, id_banco)
        if banco is None:
            raise ValueError("Banco no encontrado")

        if "codigo_banco" in datos and not datos["codigo_banco"]:
            raise ValueError("codigo_banco es requerido")
        if "nombre_banco" in datos and not datos["nombre_banco"]:
            raise ValueError("nombre_banco es requerido")
        if "identificacion_banco" in datos and not datos["identificacion_banco"]:
            raise ValueError("identificacion_banco es requerido")
        if "tipo_banco" in datos:
            if not datos["tipo_banco"]:
                raise ValueError("tipo_banco es requerido")
            if datos["tipo_banco"] not in TIPOS_VALIDOS:
                raise ValueError(f"tipo_banco debe ser uno de {TIPOS_VALIDOS}")

        nuevo_codigo = datos.get("codigo_banco")
        if nuevo_codigo and nuevo_codigo != banco.codigo_banco:
            BancoService._validar_unico(session, "codigo_banco", nuevo_codigo, excluir_id=id_banco)

        nueva_identificacion = datos.get("identificacion_banco")
        if nueva_identificacion and nueva_identificacion != banco.identificacion_banco:
            BancoService._validar_unico(session, "identificacion_banco", nueva_identificacion, excluir_id=id_banco)

        # Establecer modificado_por al actualizar
        banco.modificado_por = id_usuario

        for campo, valor in datos.items():
            setattr(banco, campo, valor)
        session.commit()
        session.refresh(banco)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="ACTUALIZAR_BANCO",
            modulo="BANCOS",
            detalle={"id_banco": banco.id_banco, "campos": list(datos.keys())},
        )
        return banco

    @staticmethod
    def cambiar_estado(session: Session, id_banco: int, nuevo_estado: str, id_usuario: int | None = None) -> Banco:
        require_permiso(session, id_usuario, "bancos", "eliminar")
        if nuevo_estado not in ESTADOS_VALIDOS:
            raise ValueError(f"nuevo_estado debe ser uno de {ESTADOS_VALIDOS}")
        banco = session.get(Banco, id_banco)
        if banco is None:
            raise ValueError("Banco no encontrado")

        banco.estado_banco = nuevo_estado
        session.commit()
        session.refresh(banco)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="CAMBIAR_ESTADO_BANCO",
            modulo="BANCOS",
            detalle={"id_banco": banco.id_banco, "nuevo_estado": nuevo_estado},
        )
        return banco

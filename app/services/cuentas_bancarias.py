import datetime

from sqlalchemy.orm import Session

from app.db.models import CuentaBancaria
from app.services.auditoria import AuditoriaService
from app.services.permisos import require_permiso

ESTADOS_VALIDOS = {"ACTIVO", "INACTIVO"}
TIPOS_CUENTA_VALIDOS = {"AHORRO", "CORRIENTE"}


class CuentaBancariaService:
    @staticmethod
    def _validar_unico(session: Session, campo: str, valor: str | None, excluir_id: int | None = None) -> None:
        if not valor:
            return
        query = session.query(CuentaBancaria).filter(getattr(CuentaBancaria, campo) == valor)
        if excluir_id is not None:
            query = query.filter(CuentaBancaria.id_cuenta != excluir_id)
        if query.first() is not None:
            raise ValueError(f"Ya existe una cuenta bancaria con {campo}='{valor}'")

    @staticmethod
    def obtener(session: Session, id_cuenta: int, id_usuario: int | None = None) -> CuentaBancaria | None:
        require_permiso(session, id_usuario, "bancos", "ver")
        return session.get(CuentaBancaria, id_cuenta)

    @staticmethod
    def listar(
        session: Session,
        texto_busqueda: str | None = None,
        estado_cuenta: str | None = None,
        id_banco: int | None = None,
        id_usuario: int | None = None,
        pagina: int = 1,
        por_pagina: int = 20,
    ) -> dict:
        require_permiso(session, id_usuario, "bancos", "ver")
        query = session.query(CuentaBancaria)
        if texto_busqueda:
            like = f"%{texto_busqueda}%"
            query = query.filter(
                CuentaBancaria.numero_cuenta.ilike(like)
                | CuentaBancaria.nombre_titular.ilike(like)
                | CuentaBancaria.identificacion_titular.ilike(like)
            )
        if estado_cuenta:
            query = query.filter(CuentaBancaria.estado_cuenta == estado_cuenta)
        if id_banco:
            query = query.filter(CuentaBancaria.id_banco == id_banco)

        query = query.order_by(CuentaBancaria.numero_cuenta)
        total = query.count()
        cuentas = query.offset((pagina - 1) * por_pagina).limit(por_pagina).all()
        return {"items": cuentas, "total": total, "pagina": pagina, "por_pagina": por_pagina}

    @staticmethod
    def _validar_requeridos(datos: dict) -> None:
        if not datos.get("id_banco"):
            raise ValueError("id_banco es requerido")
        if not datos.get("numero_cuenta"):
            raise ValueError("numero_cuenta es requerido")
        if not datos.get("nombre_titular"):
            raise ValueError("nombre_titular es requerido")
        if not datos.get("identificacion_titular"):
            raise ValueError("identificacion_titular es requerido")
        if datos.get("tipo_cuenta_banco") and datos.get("tipo_cuenta_banco") not in TIPOS_CUENTA_VALIDOS:
            raise ValueError(f"tipo_cuenta_banco debe ser uno de {TIPOS_CUENTA_VALIDOS}")

    @staticmethod
    def crear(session: Session, **datos) -> CuentaBancaria:
        require_permiso(session, datos.get("creado_por"), "bancos", "crear")
        CuentaBancariaService._validar_requeridos(datos)
        CuentaBancariaService._validar_unico(session, "numero_cuenta", datos.get("numero_cuenta"))
        # Establecer fecha de creación explícitamente
        if "fecha_creacion" not in datos:
            datos["fecha_creacion"] = datetime.datetime.now()
        cuenta = CuentaBancaria(**datos)
        session.add(cuenta)
        session.commit()
        session.refresh(cuenta)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=cuenta.creado_por,
            accion="CREAR_CUENTA_BANCARIA",
            modulo="CUENTAS_BANCARIAS",
            detalle={"id_cuenta": cuenta.id_cuenta, "numero_cuenta": cuenta.numero_cuenta},
        )
        return cuenta

    @staticmethod
    def actualizar(session: Session, id_cuenta: int, id_usuario: int | None = None, **datos) -> CuentaBancaria:
        require_permiso(session, id_usuario, "bancos", "editar")
        cuenta = session.get(CuentaBancaria, id_cuenta)
        if cuenta is None:
            raise ValueError("Cuenta bancaria no encontrada")

        if "numero_cuenta" in datos and not datos["numero_cuenta"]:
            raise ValueError("numero_cuenta es requerido")
        if "nombre_titular" in datos and not datos["nombre_titular"]:
            raise ValueError("nombre_titular es requerido")
        if "identificacion_titular" in datos and not datos["identificacion_titular"]:
            raise ValueError("identificacion_titular es requerido")
        if "tipo_cuenta_banco" in datos:
            if datos["tipo_cuenta_banco"] and datos["tipo_cuenta_banco"] not in TIPOS_CUENTA_VALIDOS:
                raise ValueError(f"tipo_cuenta_banco debe ser uno de {TIPOS_CUENTA_VALIDOS}")

        nuevo_numero = datos.get("numero_cuenta")
        if nuevo_numero and nuevo_numero != cuenta.numero_cuenta:
            CuentaBancariaService._validar_unico(session, "numero_cuenta", nuevo_numero, excluir_id=id_cuenta)

        for campo, valor in datos.items():
            setattr(cuenta, campo, valor)
        session.commit()
        session.refresh(cuenta)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="ACTUALIZAR_CUENTA_BANCARIA",
            modulo="CUENTAS_BANCARIAS",
            detalle={"id_cuenta": cuenta.id_cuenta, "campos": list(datos.keys())},
        )
        return cuenta

    @staticmethod
    def cambiar_estado(
        session: Session, id_cuenta: int, nuevo_estado: str, id_usuario: int | None = None
    ) -> CuentaBancaria:
        require_permiso(session, id_usuario, "bancos", "eliminar")
        if nuevo_estado not in ESTADOS_VALIDOS:
            raise ValueError(f"nuevo_estado debe ser uno de {ESTADOS_VALIDOS}")
        cuenta = session.get(CuentaBancaria, id_cuenta)
        if cuenta is None:
            raise ValueError("Cuenta bancaria no encontrada")

        cuenta.estado_cuenta = nuevo_estado
        session.commit()
        session.refresh(cuenta)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="CAMBIAR_ESTADO_CUENTA_BANCARIA",
            modulo="CUENTAS_BANCARIAS",
            detalle={"id_cuenta": cuenta.id_cuenta, "nuevo_estado": nuevo_estado},
        )
        return cuenta

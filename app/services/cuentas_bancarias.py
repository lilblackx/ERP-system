import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.db.models import BancoMovimiento, CuentaBancaria, PagoCobro, PagoCobroBCV, PagoComision, PagoProveedor
from app.services.auditoria import AuditoriaService
from app.services.busqueda_sql import contiene, patron_contiene
from app.services.moneda_cuentas import MONEDAS_CUENTA
from app.services.paginacion import paginar
from app.services.permisos import require_permiso
from app.services.tesoreria import _enmascarar_numero_cuenta, _require_admin

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
        moneda: str | None = None,
    ) -> dict:
        require_permiso(session, id_usuario, "bancos", "ver")
        query = session.query(CuentaBancaria).options(joinedload(CuentaBancaria.banco))
        if texto_busqueda:
            like = patron_contiene(texto_busqueda)
            query = query.filter(
                contiene(session, CuentaBancaria.numero_cuenta, like)
                | contiene(session, CuentaBancaria.nombre_titular, like)
                | contiene(session, CuentaBancaria.identificacion_titular, like)
            )
        if estado_cuenta:
            query = query.filter(CuentaBancaria.estado_cuenta == estado_cuenta)
        if id_banco:
            query = query.filter(CuentaBancaria.id_banco == id_banco)
        if moneda:
            query = query.filter(CuentaBancaria.moneda == moneda)

        return paginar(query, pagina, por_pagina, CuentaBancaria.numero_cuenta, CuentaBancaria.id_cuenta)

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
        if datos.get("moneda") and datos["moneda"] not in MONEDAS_CUENTA:
            raise ValueError(f"moneda debe ser una de {MONEDAS_CUENTA}")

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
            detalle={
                "id_cuenta": cuenta.id_cuenta,
                "numero_cuenta": _enmascarar_numero_cuenta(cuenta.numero_cuenta),
            },
        )
        return cuenta

    @staticmethod
    def _reclasificar_saldo_local(cuenta: CuentaBancaria, moneda_anterior: str | None) -> None:
        """El monto "local" de los movimientos va a `saldo_total_banco_bs` (cuentas VES/USD) o a
        `saldo_total_banco_cop` (cuentas COP). Si la cuenta pasa de VES a COP (o al reves) su saldo local pasa
        de una columna a la otra, para que los pesos no queden contados como bolivares ni al reves."""
        nueva = cuenta.moneda
        if moneda_anterior == nueva:
            return
        bs = cuenta.saldo_total_banco_bs or 0
        cop = cuenta.saldo_total_banco_cop or 0
        if moneda_anterior != "COP" and nueva == "COP":
            cuenta.saldo_total_banco_cop = cop + bs
            cuenta.saldo_total_banco_bs = 0
        elif moneda_anterior == "COP" and nueva != "COP":
            cuenta.saldo_total_banco_bs = bs + cop
            cuenta.saldo_total_banco_cop = 0

    @staticmethod
    def resumen_uso(session: Session, id_cuenta: int, id_usuario: int | None = None) -> dict:
        """Cuanto se ha usado una cuenta: total de movimientos y pagos por metodo ({"zelle": 3, ...}). Lo muestra el
        aviso de confirmacion antes de cambiarle la moneda a una cuenta con historial."""
        require_permiso(session, id_usuario, "bancos", "ver")
        movimientos = (
            session.query(func.count(BancoMovimiento.id_movimiento))
            .filter(BancoMovimiento.id_cuenta == id_cuenta)
            .scalar()
        )
        por_metodo: dict[str, int] = {}
        for modelo in (PagoCobro, PagoCobroBCV, PagoProveedor, PagoComision):
            filas = (
                session.query(modelo.metodo_pago, func.count())
                .filter(modelo.id_cuenta_bancaria == id_cuenta)
                .group_by(modelo.metodo_pago)
                .all()
            )
            for metodo, cantidad in filas:
                por_metodo[metodo] = por_metodo.get(metodo, 0) + int(cantidad)
        return {"movimientos": int(movimientos or 0), "por_metodo": dict(sorted(por_metodo.items()))}

    @staticmethod
    def actualizar(
        session: Session,
        id_cuenta: int,
        id_usuario: int | None = None,
        confirmar_cambio_moneda: bool = False,
        **datos,
    ) -> CuentaBancaria:
        """`confirmar_cambio_moneda`: cambiarle la moneda a una cuenta que ya tiene movimientos solo lo hace un ADMIN
        y solo con esta confirmacion explicita (la pantalla la pide tras mostrar el resumen de uso); el cambio no
        toca el historial, solo decide que pagos futuros acepta la cuenta, y queda en la auditoria."""
        require_permiso(session, id_usuario, "bancos", "editar")
        cuenta = session.get(CuentaBancaria, id_cuenta)
        if cuenta is None:
            raise ValueError("Cuenta bancaria no encontrada")
        campos_saldo = {"saldo_total_banco", "saldo_total_banco_bs", "saldo_total_banco_cop"} & datos.keys()
        if campos_saldo:
            # El saldo solo se mueve con movimientos bancarios (BancoMovimientoService.crear,
            # pagos, cobros): editarlo directo no deja ningun movimiento que explique la
            # diferencia. Antes esto solo lo impedia la UI (campo deshabilitado).
            raise ValueError("El saldo de una cuenta bancaria no se edita: registre un movimiento bancario")

        if "numero_cuenta" in datos and not datos["numero_cuenta"]:
            raise ValueError("numero_cuenta es requerido")
        if "nombre_titular" in datos and not datos["nombre_titular"]:
            raise ValueError("nombre_titular es requerido")
        if "identificacion_titular" in datos and not datos["identificacion_titular"]:
            raise ValueError("identificacion_titular es requerido")
        if "tipo_cuenta_banco" in datos:
            if datos["tipo_cuenta_banco"] and datos["tipo_cuenta_banco"] not in TIPOS_CUENTA_VALIDOS:
                raise ValueError(f"tipo_cuenta_banco debe ser uno de {TIPOS_CUENTA_VALIDOS}")

        cambio_moneda_con_historial: dict | None = None
        if "moneda" in datos:
            if datos["moneda"] not in MONEDAS_CUENTA:
                raise ValueError(f"moneda debe ser una de {MONEDAS_CUENTA}")
            if datos["moneda"] != cuenta.moneda:
                tiene_movimientos = (
                    session.query(BancoMovimiento.id_movimiento).filter(BancoMovimiento.id_cuenta == id_cuenta).first()
                )
                if tiene_movimientos is not None:
                    _require_admin(session, id_usuario, "cambiar la moneda de una cuenta bancaria con movimientos")
                    if not confirmar_cambio_moneda:
                        raise ValueError(
                            "Cambiar la moneda de una cuenta con movimientos requiere confirmación explícita"
                        )
                    cambio_moneda_con_historial = {
                        "moneda_anterior": cuenta.moneda,
                        "moneda_nueva": datos["moneda"],
                        **CuentaBancariaService.resumen_uso(session, id_cuenta, id_usuario),
                    }

        nuevo_numero = datos.get("numero_cuenta")
        if nuevo_numero and nuevo_numero != cuenta.numero_cuenta:
            CuentaBancariaService._validar_unico(session, "numero_cuenta", nuevo_numero, excluir_id=id_cuenta)

        moneda_anterior = cuenta.moneda
        for campo, valor in datos.items():
            setattr(cuenta, campo, valor)
        CuentaBancariaService._reclasificar_saldo_local(cuenta, moneda_anterior)
        session.commit()
        session.refresh(cuenta)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="ACTUALIZAR_CUENTA_BANCARIA",
            modulo="CUENTAS_BANCARIAS",
            detalle={"id_cuenta": cuenta.id_cuenta, "campos": list(datos.keys())},
        )
        if cambio_moneda_con_historial is not None:
            AuditoriaService.registrar_evento(
                session,
                id_usuario=id_usuario,
                accion="CAMBIAR_MONEDA_CUENTA_BANCARIA",
                modulo="CUENTAS_BANCARIAS",
                detalle={"id_cuenta": cuenta.id_cuenta, **cambio_moneda_con_historial},
            )
        return cuenta

    @staticmethod
    def cambiar_estado(
        session: Session,
        id_cuenta: int,
        nuevo_estado: str,
        id_usuario: int | None = None,
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

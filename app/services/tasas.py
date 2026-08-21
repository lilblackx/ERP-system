from datetime import datetime, time
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import ControlDeTasa
from app.services.auditoria import AuditoriaService


def _calcular_porcentaje(valor_actual, valor_anterior) -> float | None:
    if not valor_anterior:
        return None
    return round(float((valor_actual - valor_anterior) / valor_anterior * 100), 2)


def _calcular_brecha(tasa_paralelo, tasa_bcv) -> float | None:
    if not tasa_bcv or tasa_paralelo is None:
        return None
    return round(float((tasa_paralelo - tasa_bcv) / tasa_bcv * 100), 2)


class TasaService:
    @staticmethod
    def registrar_tasa(
        session: Session,
        tasa_bcv,
        tasa_paralelo=None,
        tasa_cop=None,
        creado_por: int | None = None,
    ) -> ControlDeTasa:
        if Decimal(str(tasa_bcv)) <= 0:
            raise ValueError("tasa_bcv debe ser mayor a cero")

        tasa = ControlDeTasa(
            fecha_tasa=datetime.now(),
            tasa_dolar_bcv=tasa_bcv,
            tasa_dolar_paralelo=tasa_paralelo,
            tasa_cop=tasa_cop,
            creado_por=creado_por,
        )
        session.add(tasa)
        session.commit()
        session.refresh(tasa)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=creado_por,
            accion="CAMBIO_TASA",
            modulo="TASAS",
            detalle={
                "id_tasa": tasa.id_tasa,
                "tasa_bcv": str(tasa.tasa_dolar_bcv),
                "tasa_paralelo": str(tasa.tasa_dolar_paralelo) if tasa.tasa_dolar_paralelo is not None else None,
                "tasa_cop": str(tasa.tasa_cop) if tasa.tasa_cop is not None else None,
            },
        )
        return tasa

    @staticmethod
    def obtener_tasa_actual(session: Session) -> dict | None:
        actual = session.query(ControlDeTasa).order_by(
            ControlDeTasa.fecha_tasa.desc(), ControlDeTasa.id_tasa.desc()
        ).first()
        if actual is None:
            return None

        inicio_dia_actual = datetime.combine(actual.fecha_tasa.date(), time.min)
        anterior = (
            session.query(ControlDeTasa)
            .filter(ControlDeTasa.fecha_tasa < inicio_dia_actual)
            .order_by(ControlDeTasa.fecha_tasa.desc(), ControlDeTasa.id_tasa.desc())
            .first()
        )

        return {
            "id_tasa": actual.id_tasa,
            "fecha_tasa": actual.fecha_tasa,
            "tasa_bcv": actual.tasa_dolar_bcv,
            "tasa_paralelo": actual.tasa_dolar_paralelo,
            "tasa_cop": actual.tasa_cop,
            "porcentaje_vs_ayer_bcv": _calcular_porcentaje(
                actual.tasa_dolar_bcv, anterior.tasa_dolar_bcv if anterior else None
            ),
            "porcentaje_vs_ayer_paralelo": _calcular_porcentaje(
                actual.tasa_dolar_paralelo, anterior.tasa_dolar_paralelo if anterior else None
            ),
        }

    @staticmethod
    def obtener_historico_tasas(session: Session, limite: int = 30) -> list[dict]:
        tasas = (
            session.query(ControlDeTasa)
            .order_by(ControlDeTasa.fecha_tasa.desc(), ControlDeTasa.id_tasa.desc())
            .limit(limite)
            .all()
        )
        tasas.reverse()  # cronologico ascendente (mas antiguo -> mas reciente)

        return [
            {
                "id_tasa": tasa.id_tasa,
                "fecha": tasa.fecha_tasa,
                "tasa_bcv": tasa.tasa_dolar_bcv,
                "tasa_paralelo": tasa.tasa_dolar_paralelo,
                "brecha_porcentual": _calcular_brecha(tasa.tasa_dolar_paralelo, tasa.tasa_dolar_bcv),
            }
            for tasa in tasas
        ]

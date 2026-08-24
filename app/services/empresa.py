from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import ConfiguracionEmpresa
from app.services.auditoria import AuditoriaService
from app.services.permisos import require_permiso

_SENTINEL = object()


class EmpresaService:
    @staticmethod
    def obtener_configuracion(session: Session, id_usuario: int | None = None) -> ConfiguracionEmpresa | None:
        require_permiso(session, id_usuario, "empresa", "ver")
        return session.query(ConfiguracionEmpresa).order_by(ConfiguracionEmpresa.id_config).first()

    @staticmethod
    def guardar_configuracion(
        session: Session,
        rif: str | None,
        razon_social: str | None,
        direccion: str | None,
        telefono: str | None,
        logo_bytes: bytes | None = _SENTINEL,
        pie_pagina: str | None = None,
        iva_activo: bool = False,
        iva_porcentaje: Decimal | int | str = Decimal("16.00"),
        impresora_predeterminada: str | None = None,
        modificado_por: int | None = None,
    ) -> ConfiguracionEmpresa:
        """Actualiza el registro singleton, o lo crea si no existe ninguno.

        logo_bytes usa un sentinel: si se omite, el logotipo actual no se toca; para
        borrarlo explicitamente hay que pasar logo_bytes=None o b"".

        iva_porcentaje se valida en [0, 100] independientemente de iva_activo -- guardar
        un porcentaje invalido mientras el IVA esta desactivado igual dejaria un valor
        corrupto listo para aplicarse mal el dia que se reactive.
        """
        require_permiso(session, modificado_por, "empresa", "editar")
        iva_porcentaje = Decimal(str(iva_porcentaje))
        if iva_porcentaje < 0 or iva_porcentaje > 100:
            raise ValueError("iva_porcentaje debe estar entre 0 y 100")

        config = session.query(ConfiguracionEmpresa).order_by(ConfiguracionEmpresa.id_config).first()

        if config is None:
            config = ConfiguracionEmpresa()
            session.add(config)

        config.rif_empresa = rif
        config.razon_social_empresa = razon_social
        config.direccion_empresa = direccion
        config.telefono_empresa = telefono
        config.pie_pagina_empresa = pie_pagina
        config.iva_activo = iva_activo
        config.iva_porcentaje = iva_porcentaje
        config.impresora_predeterminada = impresora_predeterminada
        config.modificado_por = modificado_por
        if logo_bytes is not _SENTINEL:
            config.logotipo_empresa = logo_bytes

        session.commit()
        session.refresh(config)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=modificado_por,
            accion="ACTUALIZAR_CONFIGURACION_EMPRESA",
            modulo="EMPRESA",
            detalle={
                "rif": config.rif_empresa,
                "razon_social": config.razon_social_empresa,
                "iva_activo": config.iva_activo,
                "iva_porcentaje": str(config.iva_porcentaje),
            },
        )
        return config

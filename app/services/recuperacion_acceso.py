import hashlib
import hmac
import html
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CodigoVerificacion, ConfiguracionEmpresa, Usuario
from app.services.auditoria import AuditoriaService
from app.services.auth import hash_password, validar_password_policy
from app.services.email_service import enviar_correo

VALIDEZ_CODIGO = timedelta(minutes=15)
MAX_INTENTOS_VERIFICACION = 5
COOLDOWN_SOLICITUD = timedelta(seconds=60)

TIPO_DESBLOQUEO = "DESBLOQUEO"
TIPO_RECUPERAR_CLAVE = "RECUPERAR_CLAVE"

MENSAJE_SOLICITUD_GENERICO = "Si el usuario existe y tiene un correo registrado, se envio un codigo."


def _nombre_empresa(session: Session) -> str:
    config_empresa = session.query(ConfiguracionEmpresa).order_by(ConfiguracionEmpresa.id_config).first()
    if config_empresa and config_empresa.razon_social_empresa:
        return config_empresa.razon_social_empresa
    return "Mi Empresa"  # mismo fallback que MainWindow._obtener_nombre_empresa


def _construir_html_codigo(nombre_empresa: str, titulo: str, codigo: str, minutos_validez: int) -> str:
    """Version HTML del correo de codigo (desbloqueo/recuperar clave) -- antes solo se
    mandaba texto plano (`msg.set_content`), pedido del usuario de que se vea corporativo
    y formal en vez de un mail crudo (2026-08-28). Layout con tablas + estilos inline (no
    un <style> en el <head>) porque es lo unico que Outlook/Gmail/etc. renderizan de forma
    consistente en HTML de correo -- CSS moderno (flex/grid, hojas de estilo externas) se
    ignora o se recorta segun el cliente.

    Colores calcados de app/ui/styles.py (COLOR_PRIMARY/COLOR_TEXT_DARK/COLOR_TEXT_MUTED/
    etc.) para que el correo se vea "de la misma familia" que el resto de la app -- se
    copian los valores hex en vez de importar ese modulo: importarlo arrastraria PySide6
    (dependencia de UI) dentro de la capa de servicios, que hoy no depende de Qt para nada."""
    nombre_empresa_html = html.escape(nombre_empresa)
    titulo_html = html.escape(titulo)
    return f"""\
<!DOCTYPE html>
<html lang="es">
  <body style="margin:0; padding:0; background-color:#F1F5F9;
      font-family:'Segoe UI', Arial, sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
        style="background-color:#F1F5F9; padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="480" cellpadding="0" cellspacing="0"
              style="background-color:#FFFFFF; border-radius:10px; overflow:hidden;
              box-shadow:0 1px 3px rgba(0,0,0,0.08); max-width:480px;">
            <tr>
              <td style="background-color:#0D47A1; padding:22px 32px;">
                <span style="color:#FFFFFF; font-size:17px; font-weight:bold;
                    letter-spacing:0.3px;">{nombre_empresa_html}</span>
              </td>
            </tr>
            <tr>
              <td style="padding:32px;">
                <p style="margin:0 0 4px 0; color:#1E293B; font-size:16px;
                    font-weight:bold;">{titulo_html}</p>
                <p style="margin:0 0 24px 0; color:#64748B; font-size:13px; line-height:1.5;">
                  Usa el siguiente código para continuar. Es válido por {minutos_validez} minutos.
                </p>
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                  <tr>
                    <td align="center" style="background-color:#EFF6FF; border:1px solid #BFDBFE;
                        border-radius:8px; padding:18px;">
                      <span style="font-family:'Consolas','Courier New',monospace; font-size:32px;
                          font-weight:bold; letter-spacing:8px; color:#0D47A1;">{codigo}</span>
                    </td>
                  </tr>
                </table>
                <p style="margin:24px 0 0 0; color:#64748B; font-size:12px; line-height:1.5;">
                  Si no solicitaste este código, ignora este correo -- tu cuenta sigue segura
                  y nadie puede usarlo sin acceso a esta bandeja de entrada.
                </p>
              </td>
            </tr>
            <tr>
              <td style="background-color:#F8FAFC; border-top:1px solid #E2E8F0; padding:16px 32px;">
                <p style="margin:0; color:#94A3B8; font-size:11px; line-height:1.5;">
                  Correo generado automáticamente por {nombre_empresa_html}. Por favor no respondas a este mensaje.
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


def _generar_codigo() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _hash_codigo(codigo: str) -> str:
    return hashlib.sha256(codigo.encode("utf-8")).hexdigest()


def _buscar_usuario(session: Session, nombre_usuario: str) -> Usuario | None:
    return session.query(Usuario).filter(Usuario.nombre_usuario == nombre_usuario).first()


def _dentro_del_cooldown(session: Session, usuario: Usuario, tipo: str) -> bool:
    """C19: sin esto, el endpoint (pre-autenticacion, solo requiere el nombre de usuario)
    permite mail-bombear el correo real de un usuario y agotar la cuota de envio de la
    cuenta Gmail compartida por toda la app. `fecha_creacion` se compara contra
    datetime.now() (reloj de la app) porque _crear_y_enviar_codigo() ahora la fija
    explicito en vez de dejar el GETDATE() del server_default -- mismo criterio que C12
    (un solo reloj para todo este tipo de comparaciones, no mezclar Python con SQL Server)."""
    ultimo = (
        session.execute(
            select(CodigoVerificacion.fecha_creacion)
            .where(CodigoVerificacion.id_usuario == usuario.id_usuario, CodigoVerificacion.tipo == tipo)
            .order_by(CodigoVerificacion.fecha_creacion.desc())
        )
        .scalars()
        .first()
    )
    return ultimo is not None and datetime.now() - ultimo < COOLDOWN_SOLICITUD


def _crear_y_enviar_codigo(session: Session, usuario: Usuario, tipo: str) -> None:
    codigo = _generar_codigo()
    registro = CodigoVerificacion(
        id_usuario=usuario.id_usuario,
        tipo=tipo,
        codigo_hash=_hash_codigo(codigo),
        fecha_creacion=datetime.now(),
        fecha_expiracion=datetime.now() + VALIDEZ_CODIGO,
    )
    session.add(registro)
    session.commit()

    asunto = "Codigo de desbloqueo de cuenta" if tipo == TIPO_DESBLOQUEO else "Codigo para recuperar tu clave"
    minutos_validez = int(VALIDEZ_CODIGO.total_seconds() // 60)
    # cuerpo (texto plano) se mantiene igual que antes -- es el fallback para clientes de
    # correo sin HTML y lo unico que la suite de tests inspecciona (_extraer_codigo en
    # test_recuperacion_acceso.py). cuerpo_html es la version "corporativa" nueva.
    cuerpo = (
        f"Tu codigo es: {codigo}\n\nVence en {minutos_validez} minutos. Si no solicitaste esto, ignora este correo."
    )
    cuerpo_html = _construir_html_codigo(_nombre_empresa(session), asunto, codigo, minutos_validez)
    enviar_correo(usuario.email, asunto, cuerpo, cuerpo_html=cuerpo_html)

    AuditoriaService.registrar_evento(
        session,
        id_usuario=usuario.id_usuario,
        accion=f"SOLICITUD_{tipo}",
        modulo="AUTH",
        detalle=f"Codigo enviado a '{usuario.nombre_usuario}'",
    )


def _solicitar_codigo(session: Session, nombre_usuario: str, tipo: str) -> None:
    """No revela si el usuario existe o tiene correo -- siempre responde generico
    (MENSAJE_SOLICITUD_GENERICO), igual que authenticate() no distingue usuario
    inexistente de clave incorrecta. Por la misma razon, si esta en cooldown (C19) no se
    reenvia el codigo pero tampoco se avisa nada distinto -- una respuesta diferente
    revelaria que el usuario existe y tiene correo, aunque no se le mande nada nuevo."""
    usuario = _buscar_usuario(session, nombre_usuario)
    if usuario is not None and usuario.email and not _dentro_del_cooldown(session, usuario, tipo):
        _crear_y_enviar_codigo(session, usuario, tipo)


def _consumir_codigo(session: Session, usuario: Usuario, tipo: str, codigo_ingresado: str) -> None:
    """Verifica el codigo vigente mas reciente de ese tipo para el usuario. Lanza
    ValueError con un mensaje apto para mostrar tal cual al usuario (mismo criterio que
    C3: nunca un str(exc) tecnico)."""
    registro = (
        session.execute(
            select(CodigoVerificacion)
            .where(
                CodigoVerificacion.id_usuario == usuario.id_usuario,
                CodigoVerificacion.tipo == tipo,
                CodigoVerificacion.usado == False,  # noqa: E712 -- BIT en mssql, "IS 0" no es sintaxis valida
            )
            .order_by(CodigoVerificacion.fecha_creacion.desc())
        )
        .scalars()
        .first()
    )
    if registro is None:
        raise ValueError("No hay un codigo pendiente para este usuario. Solicite uno nuevo.")

    if registro.fecha_expiracion < datetime.now():
        registro.usado = True
        session.commit()
        raise ValueError("El codigo vencio. Solicite uno nuevo.")

    if registro.intentos_verificacion >= MAX_INTENTOS_VERIFICACION:
        registro.usado = True
        session.commit()
        raise ValueError("Se agotaron los intentos para este codigo. Solicite uno nuevo.")

    if not hmac.compare_digest(_hash_codigo(codigo_ingresado), registro.codigo_hash):
        registro.intentos_verificacion += 1
        if registro.intentos_verificacion >= MAX_INTENTOS_VERIFICACION:
            registro.usado = True
        session.commit()
        raise ValueError("Codigo incorrecto.")

    registro.usado = True
    session.commit()


class RecuperacionAccesoService:
    @staticmethod
    def solicitar_codigo_desbloqueo(session: Session, nombre_usuario: str) -> str:
        _solicitar_codigo(session, nombre_usuario, TIPO_DESBLOQUEO)
        return MENSAJE_SOLICITUD_GENERICO

    @staticmethod
    def verificar_codigo_desbloqueo(session: Session, nombre_usuario: str, codigo: str) -> None:
        usuario = _buscar_usuario(session, nombre_usuario)
        if usuario is None:
            raise ValueError("Codigo incorrecto.")

        _consumir_codigo(session, usuario, TIPO_DESBLOQUEO, codigo)

        usuario.bloqueado_desde = None
        usuario.intentos_fallidos = 0
        session.commit()

        AuditoriaService.registrar_evento(
            session,
            id_usuario=usuario.id_usuario,
            accion="DESBLOQUEO_EXITOSO",
            modulo="AUTH",
            detalle=f"Cuenta '{usuario.nombre_usuario}' desbloqueada por codigo",
        )

    @staticmethod
    def solicitar_codigo_recuperacion(session: Session, nombre_usuario: str) -> str:
        _solicitar_codigo(session, nombre_usuario, TIPO_RECUPERAR_CLAVE)
        return MENSAJE_SOLICITUD_GENERICO

    @staticmethod
    def verificar_codigo_y_cambiar_clave(session: Session, nombre_usuario: str, codigo: str, nueva_clave: str) -> None:
        usuario = _buscar_usuario(session, nombre_usuario)
        if usuario is None:
            raise ValueError("Codigo incorrecto.")

        # Se valida la politica ANTES de consumir el codigo: si la clave elegida no
        # cumple, no tiene sentido quemar el codigo (ni sus intentos) por un problema
        # que no tiene nada que ver con el codigo en si -- el usuario deberia poder
        # reintentar con otra clave sin pedir un codigo nuevo.
        validar_password_policy(nueva_clave)
        _consumir_codigo(session, usuario, TIPO_RECUPERAR_CLAVE, codigo)

        usuario.clave = hash_password(nueva_clave)
        usuario.bloqueado_desde = None
        usuario.intentos_fallidos = 0
        session.commit()

        AuditoriaService.registrar_evento(
            session,
            id_usuario=usuario.id_usuario,
            accion="CLAVE_RESTABLECIDA",
            modulo="AUTH",
            detalle=f"Clave restablecida por codigo para '{usuario.nombre_usuario}'",
        )

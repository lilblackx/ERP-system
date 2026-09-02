import json
import math

from sqlalchemy.orm import Session

from app.db.models import Ruta
from app.services.auditoria import AuditoriaService
from app.services.permisos import require_permiso

ESTADOS_VALIDOS = {"ACTIVO", "INACTIVO"}

_RADIO_TIERRA_KM = 6371.0


def _validar_unico(session: Session, nombre_ruta: str, excluir_id: int | None = None) -> None:
    query = session.query(Ruta).filter(Ruta.nombre_ruta == nombre_ruta)
    if excluir_id is not None:
        query = query.filter(Ruta.id_ruta != excluir_id)
    if query.first() is not None:
        raise ValueError(f"Ya existe una ruta con nombre_ruta='{nombre_ruta}'")


def _validar_rango_coordenadas(latitud, longitud, etiqueta: str = "") -> None:
    """Solo el rango -- la obligatoriedad se valida aparte en cada callsite (mismo
    criterio 'no permite vaciar' que nombre_ruta). `etiqueta` distingue origen/destino en
    el mensaje de error sin duplicar la funcion."""
    prefijo = f"{etiqueta} " if etiqueta else ""
    if latitud is not None and not (-90 <= float(latitud) <= 90):
        raise ValueError(f"{prefijo}latitud debe estar entre -90 y 90")
    if longitud is not None and not (-180 <= float(longitud) <= 180):
        raise ValueError(f"{prefijo}longitud debe estar entre -180 y 180")


def _distancia_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Haversine -- distancia en linea recta entre dos puntos, sin considerar calles."""
    rad_lat1, rad_lat2 = math.radians(lat1), math.radians(lat2)
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = math.sin(d_lat / 2) ** 2 + math.cos(rad_lat1) * math.cos(rad_lat2) * math.sin(d_lng / 2) ** 2
    return 2 * _RADIO_TIERRA_KM * math.asin(math.sqrt(a))


class RutaService:
    @staticmethod
    def obtener(session: Session, id_ruta: int, id_usuario: int | None = None) -> Ruta | None:
        require_permiso(session, id_usuario, "rutas", "ver")
        return session.get(Ruta, id_ruta)

    @staticmethod
    def listar(
        session: Session,
        texto_busqueda: str | None = None,
        id_usuario: int | None = None,
        estado_ruta: str | None = None,
        pagina: int = 1,
        por_pagina: int = 20,
    ) -> dict:
        require_permiso(session, id_usuario, "rutas", "ver")
        query = session.query(Ruta)
        if texto_busqueda:
            like = f"%{texto_busqueda}%"
            query = query.filter(Ruta.nombre_ruta.ilike(like) | Ruta.descripcion_ruta.ilike(like))
        if estado_ruta:
            query = query.filter(Ruta.estado_ruta == estado_ruta)
        query = query.order_by(Ruta.nombre_ruta)

        total = query.count()
        rutas = query.offset((pagina - 1) * por_pagina).limit(por_pagina).all()
        return {"items": rutas, "total": total, "pagina": pagina, "por_pagina": por_pagina}

    @staticmethod
    def crear(session: Session, **datos) -> Ruta:
        require_permiso(session, datos.get("creado_por"), "rutas", "crear")
        if not datos.get("nombre_ruta"):
            raise ValueError("nombre_ruta es requerido")
        # is None (no falsy) a proposito: latitud/longitud=0.0 son coordenadas legitimas
        # (ecuador / meridiano de Greenwich).
        if datos.get("latitud") is None:
            raise ValueError("latitud (origen) es requerida")
        if datos.get("longitud") is None:
            raise ValueError("longitud (origen) es requerida")
        if datos.get("destino_latitud") is None:
            raise ValueError("destino_latitud es requerida")
        if datos.get("destino_longitud") is None:
            raise ValueError("destino_longitud es requerida")
        _validar_unico(session, datos["nombre_ruta"])
        _validar_rango_coordenadas(datos.get("latitud"), datos.get("longitud"), etiqueta="origen:")
        _validar_rango_coordenadas(datos.get("destino_latitud"), datos.get("destino_longitud"), etiqueta="destino:")

        ruta = Ruta(**datos)
        session.add(ruta)
        session.commit()
        session.refresh(ruta)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=ruta.creado_por,
            accion="CREAR_RUTA",
            modulo="RUTAS",
            detalle={"id_ruta": ruta.id_ruta, "nombre_ruta": ruta.nombre_ruta},
        )
        return ruta

    @staticmethod
    def actualizar(session: Session, id_ruta: int, id_usuario: int | None = None, **datos) -> Ruta:
        require_permiso(session, id_usuario, "rutas", "editar")
        ruta = session.get(Ruta, id_ruta)
        if ruta is None:
            raise ValueError("Ruta no encontrada")

        if "nombre_ruta" in datos and not datos["nombre_ruta"]:
            raise ValueError("nombre_ruta es requerido")
        if "latitud" in datos and datos["latitud"] is None:
            raise ValueError("latitud (origen) es requerida")
        if "longitud" in datos and datos["longitud"] is None:
            raise ValueError("longitud (origen) es requerida")
        if "destino_latitud" in datos and datos["destino_latitud"] is None:
            raise ValueError("destino_latitud es requerida")
        if "destino_longitud" in datos and datos["destino_longitud"] is None:
            raise ValueError("destino_longitud es requerida")

        nuevo_nombre = datos.get("nombre_ruta")
        if nuevo_nombre and nuevo_nombre != ruta.nombre_ruta:
            _validar_unico(session, nuevo_nombre, excluir_id=id_ruta)

        nueva_latitud = datos["latitud"] if "latitud" in datos else ruta.latitud
        nueva_longitud = datos["longitud"] if "longitud" in datos else ruta.longitud
        _validar_rango_coordenadas(nueva_latitud, nueva_longitud, etiqueta="origen:")

        nuevo_destino_lat = datos["destino_latitud"] if "destino_latitud" in datos else ruta.destino_latitud
        nuevo_destino_lng = datos["destino_longitud"] if "destino_longitud" in datos else ruta.destino_longitud
        _validar_rango_coordenadas(nuevo_destino_lat, nuevo_destino_lng, etiqueta="destino:")

        for campo, valor in datos.items():
            setattr(ruta, campo, valor)
        session.commit()
        session.refresh(ruta)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="ACTUALIZAR_RUTA",
            modulo="RUTAS",
            detalle={"id_ruta": ruta.id_ruta, "campos": list(datos.keys())},
        )
        return ruta

    # Igual que VendedorService.eliminar(): FK_vendedores_id_ruta (ON DELETE NO ACTION)
    # hace que borrar una ruta con vendedores asignados reviente con un IntegrityError
    # crudo de pyodbc. Politica del modulo es no permitir el DELETE nunca -- usar
    # cambiar_estado(..., "INACTIVO") para retirarla de circulacion preservando el
    # historial de los vendedores que ya la tuvieron asignada.
    @staticmethod
    def eliminar(session: Session, id_ruta: int, id_usuario: int | None = None) -> None:
        require_permiso(session, id_usuario, "rutas", "eliminar")
        raise ValueError(
            "No se puede eliminar una ruta para proteger la integridad de los datos. "
            "Use RutaService.cambiar_estado() para desactivarla."
        )

    @staticmethod
    def cambiar_estado(session: Session, id_ruta: int, nuevo_estado: str, id_usuario: int | None = None) -> Ruta:
        require_permiso(session, id_usuario, "rutas", "eliminar")
        if nuevo_estado not in ESTADOS_VALIDOS:
            raise ValueError(f"nuevo_estado debe ser uno de {ESTADOS_VALIDOS}")
        ruta = session.get(Ruta, id_ruta)
        if ruta is None:
            raise ValueError("Ruta no encontrada")

        ruta.estado_ruta = nuevo_estado
        session.commit()
        session.refresh(ruta)

        AuditoriaService.registrar_evento(
            session,
            id_usuario=id_usuario,
            accion="CAMBIAR_ESTADO_RUTA",
            modulo="RUTAS",
            detalle={"id_ruta": ruta.id_ruta, "nuevo_estado": nuevo_estado},
        )
        return ruta

    @staticmethod
    def distancia_a_trazado(ruta: Ruta, lat: float, lng: float) -> float | None:
        """Distancia en km (Haversine) de (lat, lng) al vertice mas cercano del trazado de
        la ruta -- no es una proyeccion punto-segmento exacta, pero el trazado de OSRM trae
        vertices muy juntos siguiendo la calle, asi que la aproximacion es suficiente para
        una alerta orientativa (ver ClienteFormDialog._validar_y_aceptar) sin necesitar
        geometria de segmentos. `None` si la ruta no tiene trazado calculado -- no hay nada
        contra que comparar. No necesita Session: opera sobre el objeto Ruta ya cargado
        (ej. via Vendedor.ruta)."""
        if not ruta.trazado_geojson:
            return None
        puntos = json.loads(ruta.trazado_geojson)
        if not puntos:
            return None
        return min(_distancia_km(lat, lng, p_lat, p_lng) for p_lat, p_lng in puntos)

import json

from sqlalchemy.orm import Session

from app.db.models import Ruta
from app.services.auditoria import AuditoriaService
from app.services.permisos import require_permiso

ESTADOS_VALIDOS = {"ACTIVO", "INACTIVO"}


def _validar_unico(session: Session, nombre_ruta: str, excluir_id: int | None = None) -> None:
    query = session.query(Ruta).filter(Ruta.nombre_ruta == nombre_ruta)
    if excluir_id is not None:
        query = query.filter(Ruta.id_ruta != excluir_id)
    if query.first() is not None:
        raise ValueError(f"Ya existe una ruta con nombre_ruta='{nombre_ruta}'")


def _validar_zona(zona_geojson: str) -> list[list[float]]:
    """Parsea y valida la zona de cobertura: JSON de al menos 3 vertices [lat,lng] (menos
    de 3 no forma un poligono real, ver decision de negocio 2026-09-03 en
    migrations/0043). Devuelve la lista ya parseada para que el caller no tenga que
    volver a json.loads()."""
    try:
        vertices = json.loads(zona_geojson)
    except (TypeError, ValueError) as exc:
        raise ValueError("zona_geojson debe ser un JSON valido") from exc
    if not isinstance(vertices, list) or len(vertices) < 3:
        raise ValueError("La zona de cobertura debe tener al menos 3 vertices")
    for vertice in vertices:
        if not (isinstance(vertice, list | tuple) and len(vertice) == 2):
            raise ValueError("Cada vertice de la zona debe ser un par [latitud, longitud]")
        lat, lng = vertice
        if not (-90 <= float(lat) <= 90):
            raise ValueError("La latitud de un vertice de la zona debe estar entre -90 y 90")
        if not (-180 <= float(lng) <= 180):
            raise ValueError("La longitud de un vertice de la zona debe estar entre -180 y 180")
    return vertices


def _punto_en_poligono(lat: float, lng: float, vertices: list[tuple[float, float]]) -> bool:
    """Ray casting -- True si (lat,lng) cae dentro del poligono `vertices` (se asume
    cerrado implicitamente uniendo el ultimo vertice con el primero, igual que lo dibuja
    Leaflet). Aproximacion planar (trata lat/lng como coordenadas cartesianas): valida
    para el tamaño de una zona de reparto local, no pensada para poligonos que crucen el
    antimeridiano o un polo."""
    dentro = False
    n = len(vertices)
    j = n - 1
    for i in range(n):
        lat_i, lng_i = vertices[i]
        lat_j, lng_j = vertices[j]
        if (lng_i > lng) != (lng_j > lng) and lat < (lat_j - lat_i) * (lng - lng_i) / (lng_j - lng_i) + lat_i:
            dentro = not dentro
        j = i
    return dentro


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
        if not datos.get("zona_geojson"):
            raise ValueError("zona_geojson (zona de cobertura) es requerida")
        _validar_unico(session, datos["nombre_ruta"])
        _validar_zona(datos["zona_geojson"])

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
        if "zona_geojson" in datos and not datos["zona_geojson"]:
            raise ValueError("zona_geojson (zona de cobertura) es requerida")

        nuevo_nombre = datos.get("nombre_ruta")
        if nuevo_nombre and nuevo_nombre != ruta.nombre_ruta:
            _validar_unico(session, nuevo_nombre, excluir_id=id_ruta)

        nueva_zona = datos["zona_geojson"] if "zona_geojson" in datos else ruta.zona_geojson
        _validar_zona(nueva_zona)

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
    def contiene_punto(ruta: Ruta, lat: float, lng: float) -> bool:
        """True si (lat,lng) cae dentro de la zona de cobertura de la ruta. False si la
        ruta no tiene zona cargada (o con menos de 3 vertices) -- no hay poligono contra
        el cual comparar. No necesita Session: opera sobre el objeto Ruta ya cargado."""
        if not ruta.zona_geojson:
            return False
        vertices = json.loads(ruta.zona_geojson)
        if len(vertices) < 3:
            return False
        return _punto_en_poligono(lat, lng, [tuple(v) for v in vertices])

    @staticmethod
    def sugerir_ruta_por_ubicacion(
        session: Session, lat: float, lng: float, id_usuario: int | None = None
    ) -> Ruta | None:
        """Primera ruta ACTIVA cuya zona de cobertura contiene (lat,lng), o None si
        ninguna la contiene -- usado para SUGERIR (nunca forzar) el vendedor de un
        cliente nuevo segun donde se geolocaliza (ClienteFormDialog, decision de negocio
        2026-09-03: la asignacion puede ser automatica por geografia pero siempre editable
        a mano). Si dos zonas se superponen devuelve la primera por nombre_ruta -- caso de
        borde que el negocio deberia evitar dibujando zonas sin solape, no algo que este
        metodo intente resolver."""
        require_permiso(session, id_usuario, "rutas", "ver")
        rutas = (
            session.query(Ruta)
            .filter(Ruta.estado_ruta == "ACTIVO", Ruta.zona_geojson.isnot(None))
            .order_by(Ruta.nombre_ruta)
            .all()
        )
        for ruta in rutas:
            if RutaService.contiene_punto(ruta, lat, lng):
                return ruta
        return None

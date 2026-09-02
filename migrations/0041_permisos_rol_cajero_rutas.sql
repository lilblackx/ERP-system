-- CAJERO ya tenia ('vendedores', 'ver') desde migrations/0030 (puede abrir el modulo
-- Vendedores), pero migrations/0038 agrego dos pestañas nuevas a esa misma pantalla
-- ("Rutas" y "Mapa", app/ui/rutas_panel.py / app/ui/mapa_rutas_panel.py) sin otorgarle el
-- permiso 'rutas'/'ver' que ambas requieren -- CAJERO veia "Sin permiso" al abrir esas
-- pestañas dentro de un modulo al que ya tenia acceso (hallazgo de auditoria, 2026-09-02).
-- Solo 'ver': mismo criterio que 0030 con 'vendedores' (CAJERO consulta, no administra
-- el catalogo de rutas).

INSERT INTO dbo.rol_permisos ([id_rol], [id_permiso])
SELECT r.[id_rol], p.[id_permiso]
FROM dbo.roles r
JOIN dbo.permisos p ON (p.[recurso] = 'rutas' AND p.[accion] = 'ver')
WHERE r.[nombre] = 'CAJERO';
GO

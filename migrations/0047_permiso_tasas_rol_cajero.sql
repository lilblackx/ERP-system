-- CxC/CxP (app/ui/cuentas_por_cobrar_panel.py, app/ui/cuentas_por_pagar_panel.py) ahora
-- muestran el equivalente en Bs del saldo pendiente/monto a pagar, usando la tasa BCV
-- vigente (TasaService.obtener_tasa_actual, mismo patron informativo que
-- factura_form_dialog.py). Esa consulta exige el permiso 'tasas'/'ver', que CAJERO no
-- tenia -- migrations/0030 lo excluyo a proposito como "back-office, fuera del dia a dia
-- de caja", pero CAJERO es justamente el usuario principal de CxC/CxP en el dia a dia
-- (tiene 'pagos'/'ver'+'crear' desde esa misma migracion). Sin este permiso, CAJERO
-- nunca veria el equivalente en Bs (la UI lo oculta en silencio ante
-- PermisoDenegadoError, no rompe, pero queda invisible para el usuario que mas lo usa).
-- Solo 'ver': mismo criterio que 0030/0041 con 'vendedores'/'rutas' -- CAJERO consulta la
-- tasa vigente, no la registra (eso sigue siendo 'tasas'/'crear', no otorgado aca).

INSERT INTO dbo.rol_permisos ([id_rol], [id_permiso])
SELECT r.[id_rol], p.[id_permiso]
FROM dbo.roles r
JOIN dbo.permisos p ON (p.[recurso] = 'tasas' AND p.[accion] = 'ver')
WHERE r.[nombre] = 'CAJERO';
GO

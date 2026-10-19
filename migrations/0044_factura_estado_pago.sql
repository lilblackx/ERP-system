-- Agregar columna estado_pago a la tabla factura_venta
-- Esta columna indica el estado de pago de la factura (pendiente, pagada, parcial, etc.)

IF NOT EXISTS (
    SELECT * FROM sys.columns 
    WHERE object_id = OBJECT_ID(N'[dbo].[factura_venta]') 
    AND name = 'estado_pago'
)
BEGIN
    ALTER TABLE [dbo].[factura_venta] 
    ADD [estado_pago] VARCHAR(20) NULL;
END
GO

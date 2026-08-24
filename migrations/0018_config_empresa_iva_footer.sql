-- Datos de facturacion fiscal configurables por empresa: pie de pagina libre para la
-- factura digital (app/services/facturas_pdf.py) y el IVA, que no todas las empresas
-- cobran (regimenes/rubros exentos) y cuyo porcentaje cambia con el tiempo -- se
-- snapshotea por factura al emitirla (ver migrations/0019_factura_numero_control_iva.sql)
-- para que un cambio futuro aca no altere retroactivamente facturas ya emitidas.

ALTER TABLE dbo.configuracion_empresa ADD [pie_pagina_empresa] VARCHAR(500) NULL;
GO

ALTER TABLE dbo.configuracion_empresa ADD [iva_activo] BIT NOT NULL CONSTRAINT DF_configuracion_empresa_iva_activo DEFAULT (0);
GO

ALTER TABLE dbo.configuracion_empresa ADD [iva_porcentaje] DECIMAL(5,2) NOT NULL CONSTRAINT DF_configuracion_empresa_iva_porcentaje DEFAULT (16.00);
GO

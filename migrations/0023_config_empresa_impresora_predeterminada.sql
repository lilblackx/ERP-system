-- Impresora del sistema a la que se envia automaticamente la factura digital al
-- emitirla (boton "Facturar", ver FacturacionPanel.nueva_factura /
-- app/ui/factura_pdf.py::imprimir_factura). Se guarda por nombre (tal como lo
-- reporta QPrinterInfo) porque no hay un identificador estable mas alla de eso;
-- si la impresora se desconecta o se reinstala con otro nombre, imprimir_factura
-- lanza un error legible en vez de fallar silenciosamente.

ALTER TABLE dbo.configuracion_empresa ADD [impresora_predeterminada] VARCHAR(255) NULL;
GO

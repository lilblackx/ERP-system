-- Marcas de tiempo contra la manipulacion del reloj (app/services/licencia.py). Son una tercera copia,
-- junto a reloj.dat y el registro de Windows: para saltarse la proteccion hay que borrar las tres.
--   ultimo_visto    hora mas alta vista por el servidor (epoch, segundos)
--   ancla_servidor  hora del servidor de licencias en la ultima validacion en linea (epoch)
--   ancla_tick      contador de arranque de Windows del servidor en ese instante (ms)

IF COL_LENGTH('dbo.licencia_sistema', 'ultimo_visto') IS NULL
	ALTER TABLE dbo.licencia_sistema ADD [ultimo_visto] BIGINT NULL;
GO

IF COL_LENGTH('dbo.licencia_sistema', 'ancla_servidor') IS NULL
	ALTER TABLE dbo.licencia_sistema ADD [ancla_servidor] BIGINT NULL;
GO

IF COL_LENGTH('dbo.licencia_sistema', 'ancla_tick') IS NULL
	ALTER TABLE dbo.licencia_sistema ADD [ancla_tick] BIGINT NULL;
GO

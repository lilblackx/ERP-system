-- Nombre del equipo (hostname de la PC) que abrio el turno de cada caja.
--
-- Las cajas se comparten entre varias estaciones: dos cajeros en PCs distintas pueden abrir
-- turnos de cajas diferentes o, si la caja quedo mal cerrada, ver quien la abrio. El panel de
-- Cajas lo muestra en la columna "NOMBRE DEL EQUIPO". NULL en cajas que nunca se abrieron y en
-- los turnos abiertos antes de esta migracion (no hay forma de saber desde donde se abrieron).
-- Se actualiza en cada apertura: el equipo que figura es el que abrio el turno vigente.

IF COL_LENGTH('dbo.cajas', 'equipo') IS NULL
BEGIN
	ALTER TABLE dbo.cajas ADD [equipo] VARCHAR(128) NULL;
END
GO

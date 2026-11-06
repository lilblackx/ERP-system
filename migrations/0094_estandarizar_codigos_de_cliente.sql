-- Estandariza codigo_cliente: todos los clientes pasan al formato  CLI-000123  (prefijo "CLI-"
-- + numero con relleno de ceros a 6 digitos; con mas de 6 digitos simplemente crece).
--
-- Hasta la 0093 el codigo podia ser cualquier texto ("CLI-001", "ABC", vacio), un numero ("57") o
-- NULL. Esta migracion lleva los clientes existentes a un unico formato y deja la columna
-- generando el mismo formato para los nuevos (DEFAULT sobre la SEQUENCE creada en la 0093).
--
-- Regla para los clientes existentes:
--   * Si el codigo ya contiene un numero (con o sin "CLI-": "CLI-001", "CLI-45", "57", "000012"),
--     CONSERVA ESE NUMERO: "CLI-001" -> "CLI-000001", "57" -> "CLI-000057". Asi el personal sigue
--     reconociendo a sus clientes. Si dos clientes caen en el mismo numero ("CLI-5" y "5"), se queda
--     con el el que ya estaba en formato estandar o, si no, el mas antiguo (id_cliente); el otro se
--     trata como "sin numero".
--   * El resto (texto sin numero, vacio, NULL, cero, de mas de 12 digitos, o el repetido) recibe
--     el siguiente numero libre, en orden de creacion (id_cliente), a partir del mayor numero.
--   * El codigo anterior de cada cliente cuyo codigo cambia se guarda en dbo.clientes_codigo_anterior,
--     para poder buscarlo por su codigo viejo. La migracion no tiene vuelta atras automatica: el
--     unico "deshacer" es ese historial o un restore del respaldo.
--   * La secuencia se reposiciona por encima del mayor numero y el DEFAULT de la columna pasa al
--     nuevo formato.
--
-- El codigo no se copia en ninguna otra tabla (las facturas guardan id_cliente), asi que no hay
-- nada mas que actualizar.
--
-- SEGURIDAD (modifica datos de produccion). Todo corre en UNA transaccion; si cualquier verificacion
-- falla se hace THROW y se revierte TODO, sin dejar nada a medias:
--   - Bloquea dbo.clientes (TABLOCKX) mientras corre, para que ninguna estacion con la version
--     anterior inserte un cliente a mitad y descuadre los numeros.
--   - Antes de tocar nada exige la secuencia y el DEFAULT de la 0093.
--   - Despues verifica: misma cantidad de clientes; filas en el historial = filas actualizadas;
--     todos los codigos en formato estandar y sin repetidos; NINGUN cliente que ya estaba bien fue
--     modificado; secuencia y DEFAULT bien puestos.

IF OBJECT_ID(N'dbo.clientes_codigo_anterior', N'U') IS NULL
	CREATE TABLE dbo.clientes_codigo_anterior (
		[id_cliente] BIGINT NOT NULL PRIMARY KEY,
		[codigo_anterior] VARCHAR(20) NULL,
		[codigo_nuevo] VARCHAR(20) NOT NULL,
		[fecha_cambio] DATETIME2 NOT NULL CONSTRAINT DF_clientes_codigo_anterior_fecha DEFAULT SYSDATETIME()
	);
GO

BEGIN TRY
	DECLARE @propia BIT = CASE WHEN @@TRANCOUNT = 0 THEN 1 ELSE 0 END;
	IF @propia = 1 BEGIN TRANSACTION;

	DECLARE @msg NVARCHAR(2048);
	DECLARE @filas INT;

	IF OBJECT_ID(N'dbo.seq_codigo_cliente', N'SO') IS NULL
		OR OBJECT_ID(N'DF_clientes_codigo_cliente', N'D') IS NULL
	BEGIN
		SET @msg = N'Falta la secuencia o el DEFAULT de codigo_cliente: aplique primero la migracion 0093. '
			+ N'No se modifico ningun dato.';
		THROW 50001, @msg, 1;
	END

	-- Bloqueo exclusivo de la tabla hasta el final de la transaccion.
	DECLARE @total_antes INT = (SELECT COUNT(*) FROM dbo.clientes WITH (TABLOCKX, HOLDLOCK));

	IF OBJECT_ID(N'tempdb..#antes') IS NOT NULL DROP TABLE #antes;
	IF OBJECT_ID(N'tempdb..#cand') IS NOT NULL DROP TABLE #cand;
	IF OBJECT_ID(N'tempdb..#num') IS NOT NULL DROP TABLE #num;
	IF OBJECT_ID(N'tempdb..#plan') IS NOT NULL DROP TABLE #plan;
	IF OBJECT_ID(N'tempdb..#renumerar') IS NOT NULL DROP TABLE #renumerar;

	-- Foto de como estaba todo, para comprobar al final que lo que ya estaba bien no se toco.
	SELECT [id_cliente], [codigo_cliente] INTO #antes FROM dbo.clientes;

	-- 1) Numero que contiene cada codigo: lo que sigue a "CLI-" (si lo tiene) debe ser solo digitos (1 a 12).
	SELECT
		c.[id_cliente],
		c.[codigo_cliente] AS anterior,
		TRY_CAST(d.digitos AS BIGINT) AS v
	INTO #cand
	FROM dbo.clientes c
	CROSS APPLY (
		SELECT CASE WHEN LEN(x.t) BETWEEN 1 AND 12 AND x.t NOT LIKE '%[^0-9]%' THEN x.t END AS digitos
		FROM (
			SELECT CASE WHEN c.[codigo_cliente] LIKE 'CLI-%' THEN SUBSTRING(c.[codigo_cliente], 5, 20)
				ELSE c.[codigo_cliente] END AS t
		) x
	) d;

	-- 2) Un solo cliente por numero: gana el que ya esta en formato estandar y, si no, el mas antiguo.
	SELECT
		[id_cliente],
		v,
		ROW_NUMBER() OVER (
			PARTITION BY v
			ORDER BY
				CASE WHEN anterior COLLATE Latin1_General_BIN = N'CLI-' + FORMAT(v, N'000000') THEN 0 ELSE 1 END,
				[id_cliente]
		) AS pos
	INTO #num
	FROM #cand
	WHERE v IS NOT NULL AND v > 0;

	DECLARE @base BIGINT = ISNULL((SELECT MAX(v) FROM #num WHERE pos = 1), 0);

	-- 3) Plan: los que conservan numero lo mantienen; el resto sigue a partir de @base, por id_cliente.
	SELECT
		c.[id_cliente],
		c.[codigo_cliente] AS anterior,
		k.v AS v_conservado,
		ROW_NUMBER() OVER (
			PARTITION BY CASE WHEN k.v IS NULL THEN 0 ELSE 1 END
			ORDER BY c.[id_cliente]
		) AS rn
	INTO #plan
	FROM dbo.clientes c
	LEFT JOIN (SELECT [id_cliente], v FROM #num WHERE pos = 1) k ON k.[id_cliente] = c.[id_cliente];

	DECLARE @sin_numero INT = (SELECT COUNT(*) FROM #plan WHERE v_conservado IS NULL);

	IF @base + @sin_numero >= 999999999999
	BEGIN
		SET @msg = N'Los codigos nuevos excederian los 12 digitos. No se modifico ningun dato.';
		THROW 50002, @msg, 1;
	END

	-- 4) Solo se tocan los que realmente cambian (los que ya estan exactamente en formato estandar no).
	SELECT
		[id_cliente],
		anterior,
		CAST(N'CLI-' + FORMAT(numero, N'000000') AS VARCHAR(20)) AS nuevo
	INTO #renumerar
	FROM (
		SELECT [id_cliente], anterior,
			CASE WHEN v_conservado IS NOT NULL THEN v_conservado ELSE @base + rn END AS numero
		FROM #plan
	) p
	WHERE anterior IS NULL
		OR anterior COLLATE Latin1_General_BIN <> CAST(N'CLI-' + FORMAT(numero, N'000000') AS VARCHAR(20));

	DECLARE @n INT = (SELECT COUNT(*) FROM #renumerar);

	INSERT INTO dbo.clientes_codigo_anterior ([id_cliente], [codigo_anterior], [codigo_nuevo])
	SELECT [id_cliente], anterior, nuevo FROM #renumerar;
	SET @filas = @@ROWCOUNT;
	IF @filas <> @n
	BEGIN
		SET @msg = N'El historial de codigos anteriores no quedo completo (' + CAST(@filas AS NVARCHAR(20))
			+ N' de ' + CAST(@n AS NVARCHAR(20)) + N'). Se revierte todo.';
		THROW 50003, @msg, 1;
	END

	UPDATE c
	SET c.[codigo_cliente] = r.nuevo
	FROM dbo.clientes c
	JOIN #renumerar r ON r.[id_cliente] = c.[id_cliente];
	SET @filas = @@ROWCOUNT;
	IF @filas <> @n
	BEGIN
		SET @msg = N'Se actualizaron ' + CAST(@filas AS NVARCHAR(20)) + N' clientes y se esperaban '
			+ CAST(@n AS NVARCHAR(20)) + N'. Se revierte todo.';
		THROW 50004, @msg, 1;
	END

	-- Verificaciones finales ------------------------------------------------------------
	IF (SELECT COUNT(*) FROM dbo.clientes) <> @total_antes
	BEGIN
		SET @msg = N'La cantidad de clientes cambio durante la migracion. Se revierte todo.';
		THROW 50005, @msg, 1;
	END

	-- Formato estandar: "CLI-" (mayusculas) + solo digitos, al menos 6.
	IF EXISTS (
		SELECT 1 FROM dbo.clientes
		WHERE [codigo_cliente] IS NULL
			OR NOT (
				[codigo_cliente] COLLATE Latin1_General_BIN LIKE 'CLI-%'
				AND LEN(SUBSTRING([codigo_cliente], 5, 20)) >= 6
				AND SUBSTRING([codigo_cliente], 5, 20) NOT LIKE '%[^0-9]%'
			)
	)
	BEGIN
		SET @msg = N'Quedaron clientes con un codigo que no tiene el formato CLI-000000. Se revierte todo.';
		THROW 50006, @msg, 1;
	END

	IF (SELECT COUNT(*) - COUNT(DISTINCT [codigo_cliente]) FROM dbo.clientes) <> 0
	BEGIN
		SET @msg = N'Quedaron codigos de cliente repetidos. Se revierte todo.';
		THROW 50007, @msg, 1;
	END

	IF EXISTS (
		SELECT 1
		FROM dbo.clientes c
		JOIN #antes a ON a.[id_cliente] = c.[id_cliente]
		WHERE c.[id_cliente] NOT IN (SELECT [id_cliente] FROM #renumerar)
			AND ISNULL(c.[codigo_cliente], N'') COLLATE Latin1_General_BIN
				<> ISNULL(a.[codigo_cliente], N'') COLLATE Latin1_General_BIN
	)
	BEGIN
		SET @msg = N'Se modifico el codigo de un cliente que ya estaba en formato estandar. Se revierte todo.';
		THROW 50008, @msg, 1;
	END

	-- Reposicionar la secuencia por encima del mayor numero (RESTART WITH no acepta variables).
	DECLARE @siguiente BIGINT = ISNULL(
		(SELECT MAX(CAST(SUBSTRING([codigo_cliente], 5, 20) AS BIGINT)) FROM dbo.clientes), 0
	) + 1;
	DECLARE @sql NVARCHAR(200) = N'ALTER SEQUENCE dbo.seq_codigo_cliente RESTART WITH '
		+ CAST(@siguiente AS NVARCHAR(20)) + N';';
	EXEC sp_executesql @sql;

	IF (SELECT CAST(current_value AS BIGINT) FROM sys.sequences WHERE object_id = OBJECT_ID(N'dbo.seq_codigo_cliente'))
		<> @siguiente
	BEGIN
		SET @msg = N'La secuencia de codigos no quedo en el valor esperado. Se revierte todo.';
		THROW 50009, @msg, 1;
	END

	-- El DEFAULT de la columna pasa al nuevo formato (la secuencia es la misma de la 0093).
	ALTER TABLE dbo.clientes DROP CONSTRAINT DF_clientes_codigo_cliente;
	ALTER TABLE dbo.clientes
		ADD CONSTRAINT DF_clientes_codigo_cliente
		DEFAULT (CAST(N'CLI-' + FORMAT(NEXT VALUE FOR dbo.seq_codigo_cliente, N'000000') AS VARCHAR(20)))
		FOR [codigo_cliente];

	IF NOT EXISTS (
		SELECT 1 FROM sys.default_constraints
		WHERE name = N'DF_clientes_codigo_cliente' AND definition LIKE N'%CLI-%'
	)
	BEGIN
		SET @msg = N'El DEFAULT de codigo_cliente no quedo con el nuevo formato. Se revierte todo.';
		THROW 50010, @msg, 1;
	END

	DROP TABLE #antes;
	DROP TABLE #cand;
	DROP TABLE #num;
	DROP TABLE #plan;
	DROP TABLE #renumerar;

	IF @propia = 1 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
	IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
	THROW;
END CATCH
GO

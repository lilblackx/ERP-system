# Distribuidora DJ

Sistema de gestion (clientes, inventario, ventas, compras, tesoreria) con backend en
SQLAlchemy/SQL Server y UI de escritorio en PySide6. Ver [docs/ESTADO_DEL_PROYECTO.md](docs/ESTADO_DEL_PROYECTO.md)
para el detalle de arquitectura y modulos.

## Requisitos

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (para SQL Server).
- Python 3.11+.
- [ODBC Driver 18 for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server)
  instalado en el sistema (lo usa `pyodbc` para conectarse; no viene con `pip install`).

La app (`app/main.py`) es una aplicacion de escritorio PySide6, no corre dentro de
Docker: solo la base de datos SQL Server se levanta en contenedor. La app corre nativa
contra ese contenedor por `localhost,1433`.

## 1. Base de datos (Docker)

```bash
cp .env.example .env
# Editar .env si se quiere otra contrasena (debe coincidir con la que usa el contenedor).

docker compose up -d
```

Esperar a que el contenedor este healthy:

```bash
docker compose ps
```

## 2. Crear la base de datos y el schema

El contenedor solo trae el motor SQL Server; hay que crear la base y correr el script
de schema manualmente:

```bash
docker exec -it distribuidora_dj_sqlserver /opt/mssql-tools18/bin/sqlcmd \
  -S localhost -U sa -P "<tu DB_PASSWORD>" -C \
  -Q "CREATE DATABASE distribuidora_dj"

docker exec -i distribuidora_dj_sqlserver /opt/mssql-tools18/bin/sqlcmd \
  -S localhost -U sa -P "<tu DB_PASSWORD>" -C -d distribuidora_dj \
  < schema_sqlserver.sql
```

(Opcional) correr las pruebas de triggers para validar que todo quedo bien:

```bash
docker exec -i distribuidora_dj_sqlserver /opt/mssql-tools18/bin/sqlcmd \
  -S localhost -U sa -P "<tu DB_PASSWORD>" -C -d distribuidora_dj \
  < test_triggers_sqlserver.sql
```

## 3. Entorno Python y app

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate   # Linux/Mac

pip install -r requirements.txt

python scripts/create_admin_user.py   # crea el primer usuario ADMIN

python app/main.py
```

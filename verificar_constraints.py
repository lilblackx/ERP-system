"""Script para verificar los constraints e índices de cuentas_por_cobrar_bcv."""

from sqlalchemy import text
from app.db.session import engine

def verificar_constraints():
    """Verifica los constraints e índices de la tabla."""
    # Verificar constraints
    query_constraints = """
    SELECT
        OBJECT_NAME(parent_object_id) AS table_name,
        name AS constraint_name,
        type_desc AS constraint_type
    FROM sys.objects
    WHERE parent_object_id = OBJECT_ID('dbo.cuentas_por_cobrar_bcv')
    ORDER BY type_desc, name
    """

    # Verificar índices
    query_indices = """
    SELECT
        OBJECT_NAME(object_id) AS table_name,
        name AS index_name,
        type_desc AS index_type,
        is_primary_key,
        is_unique
    FROM sys.indexes
    WHERE object_id = OBJECT_ID('dbo.cuentas_por_cobrar_bcv')
    ORDER BY name
    """

    with engine.connect() as connection:
        print("Constraints de cuentas_por_cobrar_bcv:")
        results = connection.execute(text(query_constraints))
        for row in results:
            print(f"  {row[1]} ({row[2]})")

        print("\nÍndices de cuentas_por_cobrar_bcv:")
        results = connection.execute(text(query_indices))
        for row in results:
            print(f"  {row[1]} ({row[2]}, PK: {row[3]}, Unique: {row[4]})")

if __name__ == "__main__":
    verificar_constraints()

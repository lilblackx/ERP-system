from app.db.session import engine
from sqlalchemy import text

conn = engine.connect()

# Verificar si existe el trigger de auditoría
trigger_audit = conn.execute(
    text("SELECT OBJECT_ID('dbo.trg_auditoria_recepcion_mercancia')")
)
print(f"Trigger trg_auditoria_recepcion_mercancia existe: {trigger_audit.scalar() is not None}")

# Verificar los últimos registros de auditoría de recepción
auditoria = conn.execute(
    text("""
    SELECT TOP 5 id_auditoria, accion, modulo, detalle, fecha_evento
    FROM dbo.auditoria
    WHERE accion = 'RECEPCION_MERCANCIA'
    ORDER BY fecha_evento DESC
    """)
)
print("\nÚltimos registros de RECEPCION_MERCANCIA:")
for row in auditoria:
    print(f"  ID: {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]}")

conn.close()

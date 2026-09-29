from sqlalchemy import text

from app.db.session import engine

session = engine.connect()
try:
    result = session.execute(
        text("SELECT COUNT(*) as total FROM cuentas_por_cobrar_bcv")
    )
    print(f"Total cuentas BCV: {result.scalar()}")

    query = (
        "SELECT TOP 5 c.id_cuenta_por_cobrar, c.id_factura, c.saldo_pendiente, "
        "c.porcentaje, c.estado, f.numero_factura "
        "FROM cuentas_por_cobrar_bcv c "
        "LEFT JOIN factura_venta f ON c.id_factura = f.id_factura"
    )
    result = session.execute(text(query))
    print("Cuentas BCV recientes:")
    for row in result:
        print(row)
finally:
    session.close()

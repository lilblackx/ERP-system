"""Script para diagnosticar el saldo en BS de cuentas bancarias."""
import sys
from decimal import Decimal

# Agregar el directorio del proyecto al path
sys.path.insert(0, r"C:\Users\JD\Desktop\ERP-system-main\ERP-system")

from app.db.session import engine
from sqlalchemy import text


def diagnosticar_saldo_bs():
    """Diagnostica el saldo en BS de todas las cuentas bancarias."""
    with engine.connect() as conn:
        # Obtener información de cuentas bancarias
        query_cuentas = text("""
            SELECT 
                cb.id_cuenta,
                b.nombre_banco,
                cb.numero_cuenta,
                cb.saldo_total_banco,
                cb.saldo_total_banco_bs
            FROM dbo.cuentas_bancarias cb
            LEFT JOIN dbo.bancos b ON cb.id_banco = b.id_banco
            ORDER BY cb.id_cuenta
        """)
        
        cuentas = conn.execute(query_cuentas).fetchall()
        
        print("=== DIAGNÓSTICO DE SALDO EN BS ===\n")
        
        for cuenta in cuentas:
            id_cuenta = cuenta[0]
            nombre_banco = cuenta[1]
            numero_cuenta = cuenta[2]
            saldo_usd = cuenta[3]
            saldo_bs_actual = cuenta[4]
            
            print(f"Cuenta: {nombre_banco} - {numero_cuenta} (ID: {id_cuenta})")
            print(f"Saldo USD: ${saldo_usd or 0:,.2f}")
            print(f"Saldo BS actual: {saldo_bs_actual or 0:,.2f}")
            
            # Calcular saldo BS esperado basado en movimientos
            query_movimientos = text("""
                SELECT 
                    tipo_movimiento,
                    monto_movimiento,
                    monto_bolivares,
                    tasa_cambio,
                    fecha_movimiento,
                    descripcion_movimiento
                FROM dbo.banco_movimientos
                WHERE id_cuenta = :id_cuenta
                AND monto_bolivares IS NOT NULL
                ORDER BY fecha_movimiento DESC
            """)
            
            movimientos = conn.execute(query_movimientos, {"id_cuenta": id_cuenta}).fetchall()
            
            saldo_bs_calculado = Decimal("0.00")
            
            if movimientos:
                print(f"\nMovimientos en BS ({len(movimientos)} registros):")
                print(f"{'Fecha':<20} {'Tipo':<10} {'Monto USD':<15} {'Monto BS':<20} {'Tasa':<10} {'Descripción'}")
                print("-" * 100)
                
                for mov in movimientos:
                    tipo = mov[0]
                    monto_usd = mov[1]
                    monto_bs = mov[2]
                    tasa = mov[3]
                    fecha = mov[4]
                    descripcion = mov[5]
                    
                    # Calcular delta
                    if tipo in ('abono', 'deposito'):
                        delta = monto_bs
                    else:
                        delta = -monto_bs
                    
                    saldo_bs_calculado += delta
                    
                    print(f"{str(fecha)[:19]:<20} {tipo:<10} ${monto_usd or 0:>10,.2f} {monto_bs:>18,.2f} {tasa or 0:>8,.2f} {descripcion or 'N/A'}")
                
                print(f"\nSaldo BS calculado: {saldo_bs_calculado:,.2f}")
                print(f"Diferencia: {saldo_bs_calculado - (saldo_bs_actual or 0):,.2f}")
                
                if abs(saldo_bs_calculado - (saldo_bs_actual or 0)) > 0.01:
                    print("⚠️  HAY DIFERENCIA - El saldo BS en la base de datos no coincide con los movimientos")
                else:
                    print("✓ Saldo BS correcto")
            else:
                print("No hay movimientos en BS")
            
            print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    diagnosticar_saldo_bs()

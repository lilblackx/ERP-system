"""Version de la aplicacion: UNA sola fuente.

Al publicar una version nueva:
  1. Subir VERSION aqui (el instalador la lee de este archivo: packaging/construir.ps1).
  2. Agregar su entrada en app/assets/novedades.json (lo que ve el usuario al abrir la app despues de actualizar). Una
     prueba (tests/test_novedades.py) falla si VERSION no tiene entrada de novedades.

Criterio para escribir las novedades (DISCRETAS, y las pruebas lo hacen cumplir):
  * Solo lo util y visible para el usuario: algo nuevo o que ahora se usa distinto. Maximo 6 lineas de <= 140
    caracteres, de una frase cada una, sin detalles tecnicos.
  * Resaltar lo mas util con "destacado": true.
  * Los arreglos de algo que no debio fallar NO se anuncian (no existe el tipo "corregido"): quedan cubiertos por la
    unica linea {"tipo": "general", "texto": "Mejoras de estabilidad y funcionamiento."}.
  * Las novedades NO se acumulan: cada version trae solo las suyas; quien se salta versiones ve unicamente las de la
    instalada.
  * Cada cambio puede declarar "modulos" (claves del sidebar) para que solo lo vean los roles que usan ese modulo.
"""

VERSION = "1.1.0"

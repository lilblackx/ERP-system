"""
Administracion de licencias contra el Worker de Cloudflare (licencias/worker/).

    python scripts/licencias_admin.py generar-claves
    python scripts/licencias_admin.py emitir --cliente "Distribuidora X" --plan pro --dias 365
    python scripts/licencias_admin.py listar
    python scripts/licencias_admin.py renovar  --clave XXXXX-... --dias 365
    python scripts/licencias_admin.py revocar  --clave XXXXX-...
    python scripts/licencias_admin.py restaurar --clave XXXXX-...
    python scripts/licencias_admin.py liberar  --clave XXXXX-...   (cambio de PC / reinstalacion)

Variables de entorno (o .env): LICENCIAS_URL, LICENCIAS_ADMIN_TOKEN. Si solo tienes el
hash (lo que muestra `listar`), usa --hash en vez de --clave.
"""

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()


def _generar_claves() -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

    privada = Ed25519PrivateKey.generate()
    privada_b64 = base64.b64encode(privada.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())).decode()
    publica_b64 = base64.b64encode(privada.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    print("CLAVE PRIVADA (secreta: guardala en un gestor de contrasenas, NUNCA en el repo ni en la app):")
    print(f"  {privada_b64}")
    print("  -> cargala en Cloudflare con:  wrangler secret put PRIVATE_KEY_B64\n")
    print("CLAVE PUBLICA (va embebida en la app, no es secreta):")
    print(f"  {publica_b64}")
    print("  -> .env de desarrollo: LICENCIA_PUBLIC_KEY=<esta clave>")
    print("\nSi pierdes la privada no podras emitir licencias que la app existente acepte.")


def _llamar(metodo: str, ruta: str, cuerpo: dict | None = None) -> dict:
    url = os.getenv("LICENCIAS_URL", "").rstrip("/")
    token = os.getenv("LICENCIAS_ADMIN_TOKEN", "")
    if not url or not token:
        sys.exit("Faltan LICENCIAS_URL y/o LICENCIAS_ADMIN_TOKEN en el entorno o en .env")
    peticion = urllib.request.Request(
        f"{url}{ruta}",
        data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "DistribuidoraDJ-admin/1.0",
        },
        method=metodo,
    )
    try:
        with urllib.request.urlopen(peticion, timeout=20) as respuesta:
            return json.loads(respuesta.read())
    except urllib.error.HTTPError as exc:
        detalle = exc.read().decode(errors="replace")
        sys.exit(f"Error {exc.code}: {detalle}")


def _fecha(epoch: int | None) -> str:
    return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d") if epoch else "perpetua"


def _vigencia(args) -> dict:
    if args.perpetua:
        return {"perpetua": True}
    if args.expira:
        return {"expira": args.expira}
    if args.dias:
        return {"dias": args.dias}
    sys.exit("Indique --dias, --expira AAAA-MM-DD o --perpetua")


def _referencia(args) -> dict:
    if args.hash:
        return {"hash": args.hash}
    if args.clave:
        return {"clave": args.clave}
    sys.exit("Indique --clave o --hash")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="comando", required=True)

    sub.add_parser("generar-claves")
    sub.add_parser("listar")

    emitir = sub.add_parser("emitir")
    emitir.add_argument("--cliente", required=True)
    emitir.add_argument("--plan", default="estandar")
    emitir.add_argument("--estaciones", type=int, default=1, help="PCs permitidas (servidor + estaciones)")

    for nombre in ("renovar", "revocar", "restaurar", "liberar"):
        p = sub.add_parser(nombre)
        p.add_argument("--clave")
        p.add_argument("--hash")

    for nombre in ("emitir", "renovar"):
        p = sub.choices[nombre]
        p.add_argument("--dias", type=int)
        p.add_argument("--expira", help="AAAA-MM-DD (inclusive)")
        p.add_argument("--perpetua", action="store_true")

    args = parser.parse_args()

    if args.comando == "generar-claves":
        _generar_claves()
    elif args.comando == "emitir":
        r = _llamar(
            "POST",
            "/admin/emitir",
            {"cliente": args.cliente, "plan": args.plan, "max_estaciones": args.estaciones, **_vigencia(args)},
        )
        print(f"Clave (se muestra UNA sola vez, guardala): {r['clave']}")
        lic = r["licencia"]
        print(f"Cliente: {lic['cliente']}  Plan: {lic['plan']}  Vence: {_fecha(lic['expira'])}")
    elif args.comando == "listar":
        for lic in _llamar("GET", "/admin/listar")["licencias"]:
            estado = "REVOCADA" if lic.get("revocada") else ("activada" if lic.get("hw_id") else "sin activar")
            print(
                f"{lic['hash'][:12]}  ...{lic.get('sufijo', '????')}  {lic.get('cliente', ''):<30} "
                f"{lic.get('plan', ''):<10} vence {_fecha(lic.get('expira'))}  {estado}"
            )
    elif args.comando == "renovar":
        r = _llamar("POST", "/admin/renovar", {**_referencia(args), **_vigencia(args)})
        print(f"Renovada. Vence: {_fecha(r['licencia']['expira'])}")
    else:
        r = _llamar("POST", f"/admin/{args.comando}", _referencia(args))
        print(f"{args.comando}: ok ({r['hash'][:12]})")


if __name__ == "__main__":
    main()

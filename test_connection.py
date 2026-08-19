import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tuya_reader import TuyaReader, TuyaReaderError

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def main():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    api_key = os.environ.get("TUYA_API_KEY") or cfg.get("apiKey", "")
    api_secret = os.environ.get("TUYA_API_SECRET") or cfg.get("apiSecret", "")

    if not api_key or not api_secret:
        print("ERROR: falta apiKey/apiSecret")
        print("  Opcion A: edita config.json")
        print("  Opcion B: set TUYA_API_KEY=... y TUYA_API_SECRET=...")
        return 1

    names = cfg.get("deviceNames", {})
    filtro = [d.strip() for d in cfg.get("deviceFilter", []) if d.strip()]

    print("Creando cliente cloud (region=%s)..." % cfg.get("region", "us"))
    reader = TuyaReader(api_key, api_secret, cfg.get("region", "us"))

    print("\nDispositivos:")
    devices = reader.list_devices(force=True, device_filter=filtro)
    if not devices:
        print("  (ninguno - revisa deviceFilter y el vinculo de la app)")
        return 1
    for d in devices:
        n = names.get(d.get("id"), "") or d.get("name", "")
        print("  %-10s %-22s cat=%s mac=%s ip=%s" % (
            n, d.get("id"), d.get("category"), d.get("mac"), d.get("ip") or "-"))

    print("\nEstado (cloud primero, luego LAN):")
    for d in devices:
        n = names.get(d.get("id"), "") or d.get("name", "") or d.get("id")
        try:
            source, items = reader.read(d, local_first=bool(cfg.get("localRead", True)))
            vals = ", ".join(
                "%s=%s" % (i.get("code"), i.get("value"))
                for i in items if i.get("value") is not None
            )
            print("  %-10s [%s] %s" % (n, source, vals or "(sin datos)"))
        except TuyaReaderError as e:
            print("  %-10s ERROR: %s" % (n, e))
        except Exception as e:
            print("  %-10s ERROR: %s: %s" % (n, type(e).__name__, e))

    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
import json
import os
import threading
import time

from flask import Flask, jsonify, render_template, request

import db
from tuya_reader import TuyaReader, TuyaReaderError

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

app = Flask(__name__)


@app.after_request
def _no_cache(resp):
    resp.headers["Cache-Control"] = "no-store"
    return resp

# ----------------------------------------------------------------------
# Estado / cache
# ----------------------------------------------------------------------
_lock = threading.Lock()
_reader = None
_reader_error = None
_status_cache = {}          # device_id -> {"source","items","at"[,"error"]}
_devices_cache = None
_devices_fetched_at = 0
_force_all = False
_wake = threading.Event()


db.init()


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("region", "us")
    cfg.setdefault("apiKey", "")
    cfg.setdefault("apiSecret", "")
    cfg.setdefault("refreshSeconds", 15)
    cfg.setdefault("deviceFilter", [])
    cfg.setdefault("localRead", True)
    cfg.setdefault("deviceNames", {})
    cfg["apiKey"] = os.environ.get("TUYA_API_KEY") or cfg.get("apiKey", "")
    cfg["apiSecret"] = os.environ.get("TUYA_API_SECRET") or cfg.get("apiSecret", "")
    return cfg


CONFIG = load_config()


def get_reader():
    global _reader, _reader_error
    with _lock:
        if _reader is not None:
            return _reader
        if not CONFIG.get("apiKey") or not CONFIG.get("apiSecret"):
            _reader_error = "Configura apiKey/apiSecret en config.json"
            return None
        try:
            _reader = TuyaReader(
                CONFIG["apiKey"], CONFIG["apiSecret"], CONFIG.get("region", "us")
            )
            _reader_error = None
            return _reader
        except TuyaReaderError as e:
            _reader_error = str(e)
            return None


def reset_reader():
    global _reader, _reader_error, _devices_cache
    with _lock:
        _reader = None
        _reader_error = None
        _devices_cache = None


# ----------------------------------------------------------------------
# Traduccion de codigos DP
# ----------------------------------------------------------------------
DP_LABELS = {
    "cur_current": "Corriente (A)",
    "cur_power": "Potencia (W)",
    "cur_voltage": "Voltaje (V)",
    "add_ele": "Energia acum. (kWh)",
    "power": "Potencia (W)",
    "voltage": "Voltaje (V)",
    "current": "Corriente (A)",
    "kwh": "Energia (kWh)",
    "ele": "Energia (kWh)",
    "today_ele": "Energia hoy (kWh)",
    "month_ele": "Energia del mes (kWh)",
    "relay_status": "Estado rele",
    "onoff": "Estado",
    "switch_1": "Interruptor 1",
    "switch_2": "Interruptor 2",
    "switch_3": "Interruptor 3",
    "temp_current": "Temperatura (°C)",
    "hum_current": "Humedad (%)",
    "temp_unit": "Unidad temp.",
    "battery_state": "Bateria",
    "battery_percentage": "Bateria (%)",
    "co2": "CO2 (ppm)",
    "pm25": "PM2.5 (ug/m3)",
    "child_lock": "Bloqueo",
    "bright_value": "Brillo",
    "va_power": "Pot. aparente (VA)",
    "frequence": "Frecuencia (Hz)",
    "factor": "Factor de potencia",
    "forward_energy_total": "Energia total (0.01 kWh)",
    "phase_a": "Fase A",
    "fault": "Falla",
    "switch_prepayment": "Modo prepago",
    "balance_energy": "Saldo (0.01 kWh)",
    "clear_energy": "Borrar energia",
    "charge_energy": "Energia cargada",
    "alarm_set_2": "Umbrales de alarma",
    "event_clear": "Borrar eventos",
}

ENERGY_CODES = {"cur_current", "cur_power", "cur_voltage", "add_ele", "power",
                "voltage", "current", "kwh", "ele", "today_ele", "month_ele",
                "va_power", "frequence", "factor",
                "forward_energy_total", "phase_a", "balance_energy",
                "charge_energy", "switch", "switch_prepayment"}
TEMP_CODES = {"temp_current", "hum_current", "co2", "pm25"}

CATEGORY_LABELS = {
    "dd": "Medidor de energia",
    "kg": "Toma / medidor",
    "wk": "Sensor temp/humedad",
    "ws": "Sensor temperatura",
    "ms": "Sensor movimiento",
    "cz": "Enchufe inteligente",
    "pc": "Enchufe inteligente",
    "tgq": "Toma inteligente",
    "zndb": "Medidor de energia (WiFi)",
}


def classify(status_codes):
    codes = set(status_codes)
    if codes & ENERGY_CODES:
        return "energy"
    if codes & TEMP_CODES:
        return "climate"
    return "other"


def friendly_label(code):
    return DP_LABELS.get(code, code)


def format_value(value):
    if isinstance(value, bool):
        return "ON" if value else "OFF"
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


PHASE_A_SUB = [
    ("voltage", "Voltaje fase A (V)"),
    ("electricCurrent", "Corriente fase A (A)"),
    ("power", "Potencia fase A (kW)"),
    ("forwardEnergy", "Energia fase A (kWh)"),
]


def flatten_items(items):
    out = []
    for dp in items:
        if not isinstance(dp, dict):
            continue
        code = dp.get("code")
        value = dp.get("value")
        t = dp.get("t")
        if code == "phase_a":
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except (ValueError, TypeError):
                    pass
            if isinstance(value, dict):
                for key, label in PHASE_A_SUB:
                    if key in value:
                        out.append({
                            "code": "phase_a.%s" % key,
                            "label": label,
                            "value": value[key],
                            "raw": value[key],
                            "t": t,
                        })
                continue
        if code == "forward_energy_total" and isinstance(value, (int, float)):
            out.append({
                "code": code,
                "label": "Energia total (kWh)",
                "value": round(value / 100.0, 2),
                "raw": value,
                "t": t,
            })
            continue
        if code in ("balance_energy", "charge_energy") and isinstance(value, (int, float)):
            out.append({
                "code": code,
                "label": "Saldo (kWh)" if code == "balance_energy" else "Energia cargada (kWh)",
                "value": round(value / 100.0, 2),
                "raw": value,
                "t": t,
            })
            continue
        out.append({"code": code, "label": friendly_label(code), "value": value, "raw": value, "t": t})
    return out


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def fetch_devices(force=False):
    global _devices_cache, _devices_fetched_at
    if force or _devices_cache is None or time.time() - _devices_fetched_at > 60:
        reader = get_reader()
        if reader is None:
            raise TuyaReaderError(_reader_error or "sin credenciales")
        filtro = [d.strip() for d in CONFIG.get("deviceFilter", []) if d.strip()]
        devices = reader.list_devices(force=force, device_filter=filtro)
        _devices_cache = devices
        _devices_fetched_at = time.time()
    return _devices_cache


def fetch_status(device):
    global _status_cache
    device_id = device.get("id", "")
    with _lock:
        cached = _status_cache.get(device_id)
        if cached and not cached.get("error") and time.time() - cached["at"] < CONFIG.get("refreshSeconds", 15):
            return cached["source"], cached["items"]
    reader = get_reader()
    if reader is None:
        raise TuyaReaderError(_reader_error or "sin credenciales")
    source, items = reader.read(
        device, local_first=bool(CONFIG.get("localRead", True))
    )
    db.record(device_id, source, flatten_items(items))
    with _lock:
        _status_cache[device_id] = {
            "source": source, "items": items, "at": time.time(),
        }
    return source, items


def cached_status(device_id):
    """Ultima lectura en cache, sin ir a la red."""
    with _lock:
        c = _status_cache.get(device_id)
    if not c:
        return None, [], None
    return c.get("source"), c.get("items") or [], c.get("error")


def _store_error(device_id, msg):
    with _lock:
        prev = _status_cache.get(device_id) or {}
        _status_cache[device_id] = {**prev, "error": msg, "at": time.time()}


def _poll_loop():
    """Hilo de fondo: mantiene la cache de lecturas fresca para que
    /api/devices siempre responda al instante, sin importar cuantos
    medidores haya configurados."""
    while True:
        interval = max(int(CONFIG.get("refreshSeconds", 15)), 10)
        try:
            devices = fetch_devices()
        except Exception:
            _wake.wait(5)
            _wake.clear()
            continue
        with _lock:
            force = _force_all
            globals()["_force_all"] = False
        started = time.time()
        for d in devices:
            did = d.get("id", "")
            with _lock:
                c = _status_cache.get(did)
                stale = c is None or force or (time.time() - c["at"] >= interval)
            if not stale:
                continue
            try:
                fetch_status(d)
            except TuyaReaderError as e:
                _store_error(did, str(e))
            except Exception as e:
                _store_error(did, "%s: %s" % (type(e).__name__, e))
            time.sleep(0.3)
        elapsed = time.time() - started
        _wake.wait(max(2.0, interval - elapsed))
        _wake.clear()


def start_poller():
    threading.Thread(target=_poll_loop, daemon=True, name="tuya-poller").start()


def _normalize_mac(mac):
    if not mac:
        return None
    return mac.replace(":", "").replace("-", "").lower()


def build_device_view(device):
    device_id = device.get("id", "")
    name = (CONFIG.get("deviceNames") or {}).get(device_id) or device.get("name") or device_id
    source = None
    items = []
    error = None

    ip = device.get("ip")
    mac = device.get("mac")
    lan_map = CONFIG.get("lanIpMap") or {}
    mac_key = _normalize_mac(mac)
    if not ip and mac_key and mac_key in lan_map:
        ip = lan_map[mac_key]
        device["ip"] = ip

    try:
        source, items, cached_err = cached_status(device_id)
        error = cached_err if (items or cached_err) else "esperando primera lectura..."
    except Exception as e:
        source, items, error = None, [], "%s: %s" % (type(e).__name__, e)

    readings = []
    for dp in flatten_items(items):
        if not isinstance(dp, dict):
            continue
        code = dp.get("code")
        value = dp.get("value")
        if code is None:
            continue
        readings.append({
            "code": code,
            "label": dp.get("label") or friendly_label(code),
            "value": format_value(value),
            "raw": dp.get("raw", value),
            "t": dp.get("t"),
        })

    kind = classify(r["code"] for r in readings)
    return {
        "id": device_id,
        "name": name,
        "category": device.get("category"),
        "categoryLabel": CATEGORY_LABELS.get(device.get("category"), device.get("category") or "desconocido"),
        "product": device.get("product_name"),
        "ip": ip,
        "mac": mac,
        "online": bool(device.get("online", True)),
        "kind": kind,
        "source": source,
        "readings": readings,
        "error": error,
        "fetchedAt": time.time() if items else None,
    }


# ----------------------------------------------------------------------
# Rutas
# ----------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html", refresh=CONFIG.get("refreshSeconds", 15))


@app.route("/api/config")
def api_config():
    configured = bool(CONFIG.get("apiKey") and CONFIG.get("apiSecret"))
    return jsonify({
        "configured": configured,
        "region": CONFIG.get("region"),
        "refreshSeconds": CONFIG.get("refreshSeconds", 15),
        "localRead": bool(CONFIG.get("localRead", True)),
        "error": _reader_error,
        "apiKeyShort": CONFIG.get("apiKey")[:6] + "..." if CONFIG.get("apiKey") else "",
    })


@app.route("/api/devices")
def api_devices():
    try:
        devices = fetch_devices()
    except TuyaReaderError as e:
        return jsonify({"ok": False, "error": str(e)}), 502
    views = [build_device_view(d) for d in devices]
    return jsonify({"ok": True, "devices": views})


@app.route("/api/history")
def api_history():
    try:
        days = int(request.args.get("days", 7))
    except ValueError:
        days = 7
    days = min(max(days, 1), 90)
    try:
        devices = fetch_devices()
    except TuyaReaderError as e:
        return jsonify({"ok": False, "error": str(e)}), 502
    ids = [d.get("id") for d in devices]
    data = db.daily(device_ids=ids, days=days)
    names = {}
    for d in devices:
        names[d.get("id")] = (CONFIG.get("deviceNames") or {}).get(
            d.get("id")
        ) or d.get("name") or d.get("id")
    named = {names[k]: v for k, v in data.items()}
    return jsonify({
        "ok": True,
        "days": days,
        "totalRows": db.row_count(),
        "history": named,
    })


@app.route("/api/readings")
def api_readings():
    device_id = request.args.get("device_id", "")
    code = request.args.get("code", "forward_energy_total")
    try:
        minutes = int(request.args.get("minutes", 60))
    except ValueError:
        minutes = 60
    minutes = min(max(minutes, 5), 10080)
    try:
        limit = int(request.args.get("limit", 2000))
    except ValueError:
        limit = 2000
    limit = min(max(limit, 10), 5000)
    points = db.readings(device_id, code, minutes=minutes, limit=limit)
    return jsonify({
        "ok": True,
        "device_id": device_id,
        "code": code,
        "minutes": minutes,
        "points": points,
    })


@app.route("/api/refresh")
def api_refresh():
    global _force_all
    try:
        devices = fetch_devices(force=True)
    except TuyaReaderError as e:
        return jsonify({"ok": False, "error": str(e)}), 502
    with _lock:
        _force_all = True
    _wake.set()
    views = [build_device_view(d) for d in devices]
    return jsonify({"ok": True, "devices": views})


@app.route("/api/reload-config")
def api_reload_config():
    global CONFIG, _status_cache, _force_all
    CONFIG = load_config()
    reset_reader()
    with _lock:
        _status_cache = {}
        _force_all = True
    _wake.set()
    return jsonify({"ok": True, "config": {
        "configured": bool(CONFIG.get("apiKey") and CONFIG.get("apiSecret")),
        "region": CONFIG.get("region"),
        "localRead": bool(CONFIG.get("localRead", True)),
    }})


start_poller()


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    print(f"Tuya Meter Dashboard -> http://{host}:{port}")
    print("En produccion usar: docker compose up -d --build")
    app.run(host=host, port=port, threaded=True)

import json
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

TZ = ZoneInfo("America/Bogota")
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://tuya:tuya@localhost:5435/tuyameters"
)


def _conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def now_bogota():
    return datetime.now(TZ)


def init(retries=30, delay=2):
    """Crea las tablas. Reintenta mientras Postgres no este listo."""
    last = None
    for i in range(retries):
        try:
            with _conn() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS readings (
                        id        BIGSERIAL PRIMARY KEY,
                        device_id TEXT NOT NULL,
                        ts        TIMESTAMPTZ NOT NULL,
                        code      TEXT NOT NULL,
                        value     JSONB,
                        source    TEXT
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_readings_dev_ts ON readings (device_id, ts)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_readings_code_ts ON readings (code, ts)"
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS daily_consumption (
                        device_id  TEXT NOT NULL,
                        date       DATE NOT NULL,
                        base_total DOUBLE PRECISION,
                        last_total DOUBLE PRECISION,
                        kwh        DOUBLE PRECISION NOT NULL DEFAULT 0,
                        updated_at TIMESTAMPTZ,
                        PRIMARY KEY (device_id, date)
                    )
                    """
                )
                conn.commit()
            return True
        except psycopg.OperationalError as e:
            last = e
            time.sleep(delay)
    raise RuntimeError("No se pudo conectar a Postgres: %s" % last)


# ----------------------------------------------------------------------
# Registro de datos
# ----------------------------------------------------------------------
def _update_daily(conn, device_id, now, total):
    """Variable 'Consumo del dia': por dia (UTC-5) se compara el totalizador
    con la ultima lectura del dia anterior, de modo que a las 00:00 se
    reinicia (nueva fila) y acumula el consumo del dia en curso."""
    day = now.date()
    row = conn.execute(
        "SELECT * FROM daily_consumption WHERE device_id=%s AND date=%s",
        (device_id, day),
    ).fetchone()
    if row is None:
        prev = conn.execute(
            "SELECT last_total FROM daily_consumption WHERE device_id=%s AND date=%s",
            (device_id, day - timedelta(days=1)),
        ).fetchone()
        base = float(prev["last_total"]) if prev and prev["last_total"] is not None else float(total)
        conn.execute(
            "INSERT INTO daily_consumption (device_id, date, base_total, last_total, kwh, updated_at)"
            " VALUES (%s,%s,%s,%s,%s,%s)",
            (device_id, day, base, float(total), _kwh(total, base), now),
        )
    else:
        conn.execute(
            "UPDATE daily_consumption SET last_total=%s, kwh=%s, updated_at=%s"
            " WHERE device_id=%s AND date=%s",
            (float(total), _kwh(total, row["base_total"]), now, device_id, day),
        )


def _kwh(total, base):
    """Diferencia de totalizador en unidades 0.01 kWh -> kWh."""
    return max(0.0, (float(total) - float(base)) / 100.0)


def record(device_id, source, items):
    """Registra todos los DPs recibidos y actualiza el consumo del dia."""
    now = now_bogota()
    energy_total = None
    with _conn() as conn:
        with conn.cursor() as cur:
            for it in items:
                if not isinstance(it, dict):
                    continue
                code = it.get("code")
                value = it.get("value")
                if code is None:
                    continue
                cur.execute(
                    "INSERT INTO readings (device_id, ts, code, value, source)"
                    " VALUES (%s,%s,%s,%s,%s)",
                    (device_id, now, code, json.dumps(value, ensure_ascii=False), source),
                )
                if code == "forward_energy_total" and isinstance(value, (int, float)):
                    energy_total = float(value)
        if energy_total is not None:
            _update_daily(conn, device_id, now, energy_total)
        conn.commit()


# ----------------------------------------------------------------------
# Consultas
# ----------------------------------------------------------------------
def daily(device_ids=None, days=7):
    since = now_bogota().date() - timedelta(days=days - 1)
    q = "SELECT device_id, date, kwh, last_total FROM daily_consumption WHERE date >= %s"
    args = [since]
    if device_ids:
        placeholders = ",".join(["%s"] * len(device_ids))
        q += " AND device_id IN (%s)" % placeholders
        args += list(device_ids)
    q += " ORDER BY date"
    with _conn() as conn:
        rows = conn.execute(q, args).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["device_id"], []).append({
            "date": r["date"].isoformat(),
            "kwh": round(r["kwh"] or 0, 3),
            "total": round((r["last_total"] or 0) / 100.0, 2),
        })
    return out


def readings(device_id, code, minutes=60, limit=2000):
    since = now_bogota() - timedelta(minutes=minutes)
    with _conn() as conn:
        rows = conn.execute(
            "SELECT ts, value FROM readings WHERE device_id=%s AND code=%s AND ts>=%s"
            " ORDER BY ts LIMIT %s",
            (device_id, code, since, limit),
        ).fetchall()
    return [
        {
            "ts": r["ts"].astimezone(TZ).isoformat(timespec="seconds"),
            "value": r["value"],
        }
        for r in rows
    ]


def row_count():
    with _conn() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM readings").fetchone()["n"]
# Grafana — Tuya Meter Dashboard

Grafana lee directo de Postgres (`tuyameters`).

## Local (docker compose)

```bash
docker compose up -d   # levanta db + app + grafana
```

Abre http://localhost:3000 (admin/admin) -> Dashboards -> **Tuya — Medidores**.

Datasource provisionado: `tuya-postgres` -> `db:5432`, DB `tuyameters`, user `tuya`.

## Coolify

No uses el `grafana` del compose. Crea un servicio Grafana aparte en Coolify:

1. New Resource -> Grafana (o Application con `grafana/grafana:11.5.2`)
2. Datasource manual: Type `PostgreSQL`, Host `clxm6oxr80j2o0rspm1vzu77:5432`, Database `postgres`, User `postgres`, Password `...`, SSL `disable`.
3. Importa `grafana/dashboards/tuya-dashboard.json` (Import -> Upload JSON).

## Tablas

- `readings(device_id, ts timestamptz, code text, value jsonb, source text)` — todos los DPs. `value` es JSONB: para numéricos usar `(value::text)::double precision`. Para `forward_energy_total` dividir /100.
- `daily_consumption(device_id, date, kwh double precision)` — consumo diario ya en kWh.

## Queries de ejemplo (Grafana -> Explore)

Serie temporal voltaje:
```sql
SELECT
  ts AT TIME ZONE 'America/Bogota' AS time,
  (value::text)::double precision AS voltage
FROM readings
WHERE code = 'phase_a.voltage' AND device_id = '$device_id'
  AND ts >= $__timeFrom() AND ts <= $__timeTo()
ORDER BY ts
```

Energía total (kWh):
```sql
SELECT
  ts AT TIME ZONE 'America/Bogota' AS time,
  (value::text)::double precision / 100.0 AS kwh
FROM readings
WHERE code = 'forward_energy_total' AND device_id = '$device_id'
ORDER BY ts
```

Consumo diario por medidor:
```sql
SELECT date AS time, kwh FROM daily_consumption WHERE device_id = '$device_id' ORDER BY date
```

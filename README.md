# Tuya Meter Dashboard

Dashboard web para monitorear medidores de energía Tuya (categoría `zndb`). Lee los 5 medidores por la nube Tuya (con respaldo LAN), registra **todos** los DP en PostgreSQL y muestra lecturas, histórico diario y gráficas en tiempo real, todo en zona horaria Colombia (UTC-5).

## Requisitos

- Python 3.12+ (modo local) o Docker + Docker Compose (recomendado)
- Cuenta en [iot.tuya.com](https://iot.tuya.com) con una Cloud Project y los medidores vinculados
- PostgreSQL (se levanta automáticamente con Docker)

## Configuración

1. Copia `config.example.json` a `config.json` y pon tus claves:

   ```json
   {
       "region": "us",
       "apiKey": "TU_API_KEY",
       "apiSecret": "TU_API_SECRET",
       "deviceFilter": ["id_del_medidor"],
       "deviceNames": { "id_del_medidor": "nombre" },
       "localRead": true,
       "lanIpMap": {}
   }
   ```

   > `config.json` está en `.gitignore` y **no se debe subir** (contiene tus credenciales). La app también acepta `TUYA_API_KEY` y `TUYA_API_SECRET` como variables de entorno.

2. Los IDs de los dispositivos se obtienen en iot.tuya.com → Cloud Project → Devices. La categoría de estos medidores es `zndb` ("medidor de energía WiFi").

## Ejecución con Docker (recomendado)

```bash
docker compose up -d --build
```

- Dashboard: http://localhost:5000
- PostgreSQL: `localhost:5435` (usuario `tuya`, password `tuya`, db `tuyameters`). El puerto 5435 se usa porque 5432/5433/5434 suelen estar ocupados; se puede cambiar en `docker-compose.yml`.

Para ver logs: `docker compose logs -f app`

## Ejecución local (desarrollo)

```bash
docker compose up -d db        # levanta solo Postgres
python -m pip install -r requirements.txt
python app.py                  # http://127.0.0.1:5000
```

## Cómo funciona

- `tuya_reader.py`: cliente tinyTuya. Lee por LAN (`localRead: true`) y cae a la nube si el medidor no está en la red local.
- `db.py`: store en PostgreSQL. Tabla `readings` guarda **todos** los data points (`code`, `value` jsonb, `source`, `ts`) y `daily_consumption` calcula la variable **"Consumo del día"** por medidor, que se reinicia sola a las 00:00 hora Colombia (`kwh = totalizador − base del día anterior`).
- `app.py`: API Flask + dashboard.

## API

| Endpoint | Descripción |
|---|---|
| `GET /api/devices` | Estado de los medidores y sus lecturas |
| `GET /api/readings?device_id=&code=&minutes=` | Serie temporal de un DP (ej. `phase_a.voltage`) |
| `GET /api/history?days=N` | Consumo diario (kWh) por medidor |
| `GET /api/config` | Configuración (sin secretos) |
| `GET /api/refresh` | Forzar refresco de lecturas |
| `GET /api/reload-config` | Recargar `config.json` sin reiniciar |

## Unidades

Los totalizadores de Tuya (`forward_energy_total`, `balance_energy`, `charge_energy`) vienen en **0.01 kWh**; la app los convierte a kWh (÷100) para mostrar.

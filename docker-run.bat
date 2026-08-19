@echo off
echo Construyendo y levantando el sistema (Postgres + dashboard)...
docker compose up -d --build
echo.
echo Dashboard:   http://localhost:5000
echo PostgreSQL:  localhost:5435 (tuya/tuya, db tuyameters)  -- 5432/5433/5434 ya estan ocupados
echo Logs:        docker compose logs -f app
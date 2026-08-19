@echo off
cd /d "%~dp0"
echo Instalando dependencias (solo la primera vez)...
python -m pip install -r requirements.txt
echo Nota: requiere Postgres arriba. Si no esta, ejecuta:  docker compose up -d db
echo Iniciando Tuya Meter Dashboard...
python app.py
pause

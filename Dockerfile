FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    TZ=America/Bogota \
    PGTZ=America/Bogota

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py db.py tuya_reader.py test_connection.py ./
COPY templates templates
COPY static static

# config.json (contiene las API keys) se monta como volumen desde el host
EXPOSE 5000

CMD ["gunicorn", "-w", "1", "--threads", "4", "-b", "0.0.0.0:5000", "app:app"]
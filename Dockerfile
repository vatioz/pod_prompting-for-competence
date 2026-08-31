FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POD_RUNTIME_DIR=/data \
    POD_HOST=0.0.0.0 \
    POD_PORT=6001

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
COPY scripts /app/scripts
COPY config /app/config
COPY data /app/data
COPY README.md /app/README.md

RUN mkdir -p /data

EXPOSE 6001

CMD ["python", "scripts/run_app.py"]

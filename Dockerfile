FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py blockchain.py ./
COPY templates/ templates/

ENV PORT=5000 \
    DATA_DIR=/data \
    DEBUG=false \
    DISCOVERY_PORT=5999

VOLUME ["/data"]

EXPOSE $PORT
EXPOSE 5999/udp

CMD ["python", "app.py"]

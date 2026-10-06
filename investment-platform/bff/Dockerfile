FROM python:3.12-slim

WORKDIR /app

# Same corporate TLS-inspection CA handling as backend/Dockerfile.
COPY combined-ca-bundle.pem ./
ENV PIP_CERT=/app/combined-ca-bundle.pem
ENV SSL_CERT_FILE=/app/combined-ca-bundle.pem
ENV REQUESTS_CA_BUNDLE=/app/combined-ca-bundle.pem

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Never bake keys into the image: secrets/ is mounted at runtime (see infra/docker-compose.yml).
RUN useradd --create-home bff && chown -R bff /app
USER bff

EXPOSE 8080

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8080"]

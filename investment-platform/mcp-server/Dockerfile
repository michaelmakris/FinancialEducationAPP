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

# Keys are mounted at runtime (infra/docker-compose.yml), never baked into the image.
RUN useradd --create-home mcp && chown -R mcp /app
USER mcp

EXPOSE 8090

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]

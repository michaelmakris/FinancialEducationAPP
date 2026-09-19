FROM python:3.12-slim

WORKDIR /app

# Corporate network TLS-inspection proxy re-signs HTTPS with its own root CA
# (intermittently -- some connections pass through untouched, others don't),
# so pip/requests need a bundle that trusts BOTH the normal public CAs and
# the corporate one, or installs / live API calls fail unpredictably.
# Harmless outside that network -- these certs simply go unused.
COPY combined-ca-bundle.pem ./
ENV PIP_CERT=/app/combined-ca-bundle.pem
ENV SSL_CERT_FILE=/app/combined-ca-bundle.pem
ENV REQUESTS_CA_BUNDLE=/app/combined-ca-bundle.pem

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

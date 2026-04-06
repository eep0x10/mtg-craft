FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cria usuário não-root
RUN useradd -r -u 1000 -s /sbin/nologin appuser \
    && mkdir -p /app/cache /app/uploads \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:5001/')" || exit 1

CMD ["python3", "app.py"]

# Imagem da interface web do assistente de suporte.
# A chave da API NUNCA entra na imagem: é passada como variável de ambiente pela plataforma (ou --env-file).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY main.py ./
COPY src ./src
COPY prompts ./prompts
COPY schemas ./schemas
COPY data ./data
COPY samples ./samples

# Usuário sem privilégios; o histórico fica em /app/outputs (efêmero, a não ser que se monte um volume).
RUN useradd --create-home --uid 10001 app && mkdir -p /app/outputs && chown -R app:app /app/outputs
USER app

# Padrões para rodar exposto: escuta em todas as interfaces, atrás de proxy, com limites e histórico de demonstração.
ENV HOST=0.0.0.0 \
    PORT=8000 \
    WEB_TRUST_PROXY=true \
    WEB_RATE_LIMIT=10 \
    WEB_RATE_WINDOW_SECONDS=3600 \
    WEB_DAILY_MODEL_CALLS=200 \
    WEB_SEED_SAMPLES=true \
    LOG_LEVEL=INFO

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/api/health', timeout=4)"

CMD ["python", "main.py", "web"]

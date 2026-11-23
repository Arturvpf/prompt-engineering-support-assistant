"""Ponto de entrada da interface web na Vercel (funções Python).

A Vercel procura, em ``api/*.py``, uma classe ``handler`` derivada de
``BaseHTTPRequestHandler``. É exatamente o que ``web.make_handler`` devolve, então
a mesma aplicação roda localmente (``python main.py web``), em container e aqui.

Diferenças da plataforma, tratadas por variáveis de ambiente com padrões seguros:

- só ``/tmp`` aceita escrita, e cada instância começa do zero: o histórico fica em
  ``/tmp/outputs`` e é semeado com as execuções de ``samples/`` (demonstração);
- a instalação é pública: limite por pessoa (IP do ``X-Forwarded-For``) e teto
  diário de chamadas ao modelo, os dois valendo por instância;
- a chave da API vem das variáveis do projeto na Vercel, nunca do repositório.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Padrões de instalação pública; qualquer um pode ser trocado nas variáveis do projeto.
for name, value in {
    "OUTPUT_DIR": "/tmp/outputs",
    "WEB_TRUST_PROXY": "true",
    "WEB_RATE_LIMIT": "10",
    "WEB_RATE_WINDOW_SECONDS": "3600",
    "WEB_DAILY_MODEL_CALLS": "200",
    "WEB_SEED_SAMPLES": "true",
    "LOG_LEVEL": "INFO",
}.items():
    os.environ.setdefault(name, value)

from support_assistant.config import load_settings, load_web_settings  # noqa: E402
from support_assistant.observability import configure_logging  # noqa: E402
from support_assistant.service import AssistantService  # noqa: E402
from support_assistant.web import App, make_handler  # noqa: E402

_settings = load_settings(require_api_key=False)
configure_logging(_settings.output_dir / "logs", _settings.log_level)  # eventos vão para os logs da Vercel
app = App(AssistantService(_settings), web=load_web_settings())

handler = make_handler(app)

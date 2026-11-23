"""Ponto de entrada da interface web na Vercel (funções Python).

A Vercel carrega ``api.index:app`` e espera uma aplicação WSGI ou ASGI. ``app`` é o
adaptador WSGI de ``web.make_wsgi_app``, que usa o mesmo roteador (``web.dispatch``)
do servidor local: a aplicação é a mesma em ``python main.py web``, no container e aqui.

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
from support_assistant.web import App, make_wsgi_app  # noqa: E402

_settings = load_settings(require_api_key=False)
configure_logging(_settings.output_dir / "logs", _settings.log_level)  # eventos vão para os logs da Vercel
assistant = App(AssistantService(_settings), web=load_web_settings())

app = make_wsgi_app(assistant)

# Assistente de Suporte com Engenharia de Prompt

Assistente de atendimento ao cliente que recebe um **perfil de cliente** e um **ticket** e gera, com prompts distintos e versionados:

1. Diagnóstico (hipóteses, evidências, dados faltantes, conclusão provável)
2. Passo a passo de resolução adaptado ao perfil
3. Perguntas de esclarecimento priorizadas
4. Resumo visual do fluxo (fluxograma ASCII)

Stack: Python 3.10+ e Google Gemini.

> Documentação completa (setup, uso, arquitetura e exemplos) em construção.

## Setup rápido

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # depois preencha GEMINI_API_KEY
```

# Assistente de Suporte com Engenharia de Prompt

Este assistente de atendimento recebe um **perfil de cliente** e um **ticket** e gera quatro tipos de conteúdo. Cada tipo tem um prompt próprio e versionado:

| Tipo | id | O que entrega |
|---|---|---|
| Diagnóstico | `diagnosis` | hipóteses, evidências do relato, informações faltantes e conclusão provável |
| Passo a passo | `resolution_steps` | ações em ordem, com resultado esperado, adaptadas ao nível técnico, estilo e canal |
| Perguntas de esclarecimento | `clarifying_questions` | até 3 perguntas priorizadas, só o que muda o próximo passo |
| Resumo visual do fluxo | `flow_summary` | fluxograma ASCII, decisões sim/não e quando escalar |

Cada execução é salva em JSON com data/hora, versão do prompt, modelo e configurações. Uma execução equivalente é reaproveitada do cache. As versões de prompt podem ser comparadas com uma rubrica fixa: clareza, adequação ao cliente e acionabilidade, com notas de 1 a 5.

As decisões de prompt, a comparação v1 × v2 e as limitações estão em [PROMPT_ENGINEERING_NOTES.md](PROMPT_ENGINEERING_NOTES.md).

---

## Requisitos

- Python 3.10 ou superior (testado com 3.12).
- Uma chave de API gratuita, de um destes provedores:
  - **OpenRouter** (padrão): crie a chave em <https://openrouter.ai/keys>. Os modelos terminados em `:free` não têm custo.
  - **Google Gemini**: crie a chave em <https://aistudio.google.com/apikey>. Em algumas contas o nível gratuito não está disponível (erro 403).

## Setup

**Windows (PowerShell)**

```powershell
git clone https://github.com/Arturvpf/prompt-engineering-support-assistant.git
cd prompt-engineering-support-assistant
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

**Linux / macOS**

```bash
git clone https://github.com/Arturvpf/prompt-engineering-support-assistant.git
cd prompt-engineering-support-assistant
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

No `.env`, preencha `OPENROUTER_API_KEY`. Para usar o Gemini, troque `LLM_PROVIDER=gemini` e preencha `GEMINI_API_KEY`. O `.env` está no `.gitignore` e nunca é versionado.

Para conferir a instalação sem gastar chamadas, rode:

```bash
python main.py list
```

### Variáveis do `.env`

| Variável | Padrão | Para que serve |
|---|---|---|
| `LLM_PROVIDER` | `openrouter` | `openrouter` ou `gemini` |
| `OPENROUTER_API_KEY` / `GEMINI_API_KEY` | (vazio) | chave do provedor escolhido |
| `OPENROUTER_MODEL` | `nvidia/nemotron-3.5-super-vl:free` | se der 429, troque por outro modelo `:free` |
| `GEMINI_MODEL` | `gemini-2.5-flash` | modelo do Gemini |
| `LLM_TEMPERATURE` | `0.2` | baixa, para respostas mais estáveis |
| `LLM_MAX_OUTPUT_TOKENS` | `2048` | limite de tokens da resposta |
| `LLM_SEED` | `42` | reduz a variação entre execuções (`none` desativa) |
| `LLM_THINKING_BUDGET` | `0` | desativa o raciocínio interno do modelo (`none` usa o padrão) |
| `LLM_TIMEOUT_SECONDS` | `60` | tempo limite por chamada |
| `LLM_MAX_RETRIES` | `3` | novas tentativas em 408, 429, 5xx e falhas de rede |
| `OUTPUT_DIR` | `outputs` | pasta do `history.json` (histórico e cache) |

---

## Como usar

### Modo interativo (menus)

```bash
python main.py
```

Os menus pedem, em ordem:

1. O perfil do cliente.
2. O ticket: um dos exemplos ou um texto novo.
3. O tipo de conteúdo, ou os 4 de uma vez.
4. A versão do prompt, ou "Comparar todas as versões".

A saída aparece formatada no terminal, junto com o caminho do JSON salvo e o `run_id`.

### Linha de comando

```bash
# perfis, tickets, tipos de conteúdo e versões disponíveis
python main.py list

# os 4 tipos para um cliente e um ticket de exemplo, com o prompt v2 (padrão)
python main.py generate -c marta-leigo-telefone -t T001

# um tipo, com um ticket novo digitado na hora
python main.py generate -c rafael-avancado-chat --text "A API retorna 500 ao criar pedido desde ontem" --type diagnosis

# o mesmo cenário com duas versões de prompt (para comparar)
python main.py generate -c joao-leigo-chat -t T004 --type all -v v1 v2

# ignorar o cache / imprimir o registro completo em JSON
python main.py generate -c joao-leigo-chat -t T004 --type diagnosis --no-cache
python main.py generate -c joao-leigo-chat -t T004 --type diagnosis --json
```

### Histórico, avaliação e comparação

```bash
# execuções salvas, com run_id, origem (modelo ou cache) e nota
python main.py history -c joao-leigo-chat -t T004

# avaliar uma execução com a rubrica: sem argumentos, pergunta nota e justificativa de cada critério
python main.py evaluate a2cf94288d19

# ou passar as notas na linha de comando
python main.py evaluate a2cf94288d19 --clarity 4 "Organizado..." --customer-fit 3 "..." --actionability 3 "..."

# ou passar as notas por arquivo JSON: {"clarity": {"score": 4, "justification": "..."}, ...}
python main.py evaluate a2cf94288d19 --file notas.json

# comparar execuções avaliadas do mesmo cenário (pode juntar vários tipos)
python main.py compare a2cf94288d19 524bbca9b910 --verdict "Por que a v2 é melhor..."
```

O `compare` recusa execuções que diferem em algo além da versão do prompt (cliente, ticket, provedor, modelo ou configurações). Também recusa execuções sem avaliação e registros vindos do cache. Por padrão, salva o resultado em `outputs/comparisons/`; use `--out` para escolher outro caminho.

### Exemplo de saída (trecho)

```
========================================================================================
Perguntas de esclarecimento  |  prompt v2  |  openrouter/nvidia/nemotron-3.5-super-vl:free
Cliente: João Pereira (joao-leigo-chat)  |  Ticket: T004
========================================================================================
1. Você está usando o mesmo login (e-mail ou usuário) do celular antigo?
   Motivo: Confirma se o acesso está sendo feito com a conta correta.
   Onde encontrar: No campo de login do aplicativo, onde você digita para entrar.
...
----------------------------------------------------------------------------------------
[cache] Resultado reaproveitado da execução 62960c793a80 (nenhuma chamada à API).
Salvo em: ...\outputs\history.json  (run_id 887b2b27ea9b)
```

Exemplos completos em JSON estão em [`samples/`](samples/README.md).

### Códigos de saída

| Código | Quando |
|---|---|
| `0` | sucesso |
| `1` | erro esperado (configuração, API, histórico, avaliação) ou algum tipo de conteúdo falhou |
| `2` | entrada inválida (perfil, ticket, versão ou nota inexistente) |
| `130` | cancelado com Ctrl+C |

---

## Arquitetura

```
main.py                      ponto de entrada (python main.py ...)
data/
  customers.json             5 perfis: nível técnico, estilo, canal e contexto
  tickets.json               4 tickets de exemplo (missing_on_purpose é gabarito, nunca vai ao prompt)
prompts/
  v1/  v2/                   uma pasta por versão; manifest.json descreve a versão e a hipótese
    persona.md               mensagem de sistema (papel, responsabilidades, limites, formato)
    context.md               perfil + ticket (template com $variaveis)
    <tipo>.md                tarefa e formato JSON de cada tipo de conteúdo
    style_rules.json         (v2) regras de escrita por nível, estilo e canal
src/support_assistant/
  data_loader.py             carrega e valida perfis e tickets
  content_types.py           os 4 tipos e os campos obrigatórios de cada um
  prompt_engine.py           monta system + user a partir da versão, do perfil e do ticket
  config.py                  lê o .env (provedor, modelo, parâmetros fixos)
  llm_client.py              cliente Gemini, retry com backoff e classificação de erros
  openrouter_client.py       cliente OpenRouter (API compatível com OpenAI, via httpx)
  generators.py              uma função por tipo; valida o JSON e tenta 1 correção se vier inválido
  output_validation.py       extrai o JSON da resposta e confere campos e tipos
  history.py                 histórico em JSON com gravação atômica
  service.py                 cache + geração + gravação (a camada que a CLI usa)
  evaluation.py              rubrica, avaliação e comparação justa entre versões
  formatting.py              saída legível no terminal
  cli.py                     comandos interactive, list, generate, history, evaluate, compare
samples/                     exemplos de saída e a comparação v1 x v2 completa
```

### Fluxo de uma geração

```
perfil + ticket + tipo + versão
        |
        v
PromptEngine.build()  ->  system (persona.md) + user (context.md + <tipo>.md)
        |
        v
chave de cache = sha256(prompt renderizado + tipo + versão + provedor/modelo/parâmetros)
        |
        +-- já existe no history.json? --sim--> registra cache_hit (sem chamar a API)
        |
       não
        v
chamada ao LLM (JSON mode, temperatura 0.2, seed 42, retry em erro temporário)
        |
        v
valida o JSON  --inválido--> reenvia com o erro anexado (1 vez)
        |
        v
grava o registro em outputs/history.json e mostra no terminal
```

### O que vai em cada registro do histórico

`run_id`, `timestamp`, `customer_id` e `customer`, `ticket_id` e `ticket`, `content_type`, `prompt_version`, `prompt_fingerprint`, `provider`, `model`, `generation_params`, `cache_key`, `cache_hit`, `source_run_id`, `output`, `warnings`, `metrics` (tentativas, latência, tokens, finish_reason) e `evaluation` (notas e justificativas da rubrica).

### Como criar uma versão nova de prompt

1. Copie `prompts/v2` para `prompts/v3`.
2. Edite os arquivos e descreva no `manifest.json` o que mudou e qual a hipótese.
3. Rode `python main.py generate -c <perfil> -t <ticket> -v v2 v3`.

A versão aparece sozinha no `list` e nos menus. O cache não mistura versões, porque a versão e o prompt renderizado fazem parte da chave.

---

## Segurança

- As chaves ficam só no `.env`, que está no `.gitignore`. O `.env.example` não tem valores reais. A configuração nunca imprime a chave.
- O relato do cliente vai entre `<ticket>` e `</ticket>`, e a persona manda tratá-lo como dado. É uma proteção básica contra prompt injection, não uma garantia.
- O prompt v2 proíbe pedir senhas, códigos de verificação, dados de cartão ou documentos.
- O gabarito `missing_on_purpose` dos tickets não entra no prompt nem no histórico.

## Limitações conhecidas

- A avaliação da rubrica é manual: a nota é uma opinião justificada, não uma métrica automática.
- Os modelos gratuitos têm limite diário e podem responder 429. Nesse caso, troque `OPENROUTER_MODEL` por outro modelo `:free`.
- Mesmo com seed e temperatura baixa, o provedor pode variar a resposta. O cache garante a reprodução exata só de uma execução já feita.
- Outras limitações das respostas estão em [PROMPT_ENGINEERING_NOTES.md](PROMPT_ENGINEERING_NOTES.md#7-limitações).

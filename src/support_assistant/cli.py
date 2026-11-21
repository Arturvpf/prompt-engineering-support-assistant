"""Interface de linha de comando.

Uso rápido::

    python main.py                       # modo interativo (menus)
    python main.py list                  # perfis, tickets, versões e tipos disponíveis
    python main.py generate -c marta-leigo-telefone -t T001 --type all --version v2
    python main.py generate -c rafael-avancado-chat --text "API retorna 500 ao criar pedido" --type diagnosis
    python main.py generate -c joao-leigo-chat -t T004 --type resolution_steps --version v1 v2
"""

from __future__ import annotations

import argparse
import json
import sys

from .config import ConfigError, load_settings
from .content_types import CONTENT_TYPES
from .data_loader import DataValidationError, load_customers, load_tickets, make_adhoc_ticket
from .formatting import render_record
from .history import HistoryError
from .llm_client import LLMError
from .prompt_engine import PromptEngine, PromptError
from .service import AssistantService

EXPECTED_ERRORS = (ConfigError, DataValidationError, PromptError, LLMError, HistoryError)


class UserInputError(ValueError):
    """Entrada inválida informada pelo usuário."""


def main(argv: list[str] | None = None) -> int:
    _utf8_console()
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            return cmd_list()
        if args.command == "generate":
            return cmd_generate(args)
        return cmd_interactive()
    except UserInputError as exc:
        print(f"Entrada inválida: {exc}", file=sys.stderr)
        return 2
    except EXPECTED_ERRORS as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelado.", file=sys.stderr)
        return 130


# ------------------------------------------------------------------ comandos

def cmd_list() -> int:
    engine = PromptEngine()
    print("PERFIS DE CLIENTE")
    for c in load_customers().values():
        print(f"  {c.id:<28} {c.technical_level:<14} {c.communication_style:<10} {c.channel}")
    print("\nTICKETS")
    for t in load_tickets().values():
        print(f"  {t.id:<6} {t.title}")
    print("\nTIPOS DE CONTEÚDO")
    for ct in CONTENT_TYPES.values():
        print(f"  {ct.id:<22} {ct.label}")
    print("\nVERSÕES DE PROMPT")
    for v in engine.available_versions():
        print(f"  {v:<4} {engine.manifest(v).get('description', '')}")
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    customers, tickets, engine = load_customers(), load_tickets(), PromptEngine()

    customer = _pick(customers, args.customer, "perfil")
    if args.text:
        ticket = make_adhoc_ticket(args.text)
    elif args.ticket:
        ticket = _pick(tickets, args.ticket, "ticket")
    else:
        raise UserInputError("informe --ticket ID ou --text \"descrição do problema\".")

    content_types = list(CONTENT_TYPES) if args.type == "all" else [args.type]
    versions = _validate_versions(args.version, engine)
    return _run(customer, ticket, content_types, versions, use_cache=not args.no_cache, as_json=args.json)


def cmd_interactive() -> int:
    customers, tickets, engine = load_customers(), load_tickets(), PromptEngine()
    print("Assistente de suporte: modo interativo (Ctrl+C para sair)\n")

    customer = customers[_menu(
        "Escolha o perfil do cliente:",
        [(c.id, f"{c.name}: {c.technical_level}, {c.communication_style}, {c.channel}") for c in customers.values()],
    )]

    options = [(t.id, f"{t.id}: {t.title}") for t in tickets.values()] + [("NOVO", "Digitar um ticket novo")]
    ticket_id = _menu("Escolha o ticket:", options)
    ticket = tickets[ticket_id] if ticket_id != "NOVO" else make_adhoc_ticket(_read_multiline())

    type_options = [(ct.id, ct.label) for ct in CONTENT_TYPES.values()] + [("all", "Todos os 4")]
    chosen_type = _menu("Escolha o tipo de conteúdo:", type_options)
    content_types = list(CONTENT_TYPES) if chosen_type == "all" else [chosen_type]

    versions = engine.available_versions()
    version_options = [(v, f"{v}: {engine.manifest(v).get('description', '')[:70]}") for v in versions]
    version_options.append(("compare", "Comparar todas as versões (" + " e ".join(versions) + ")"))
    chosen_version = _menu("Escolha a versão do prompt:", version_options)
    selected_versions = versions if chosen_version == "compare" else [chosen_version]

    return _run(customer, ticket, content_types, selected_versions, use_cache=True, as_json=False)


# ------------------------------------------------------------------ execução

def _run(customer, ticket, content_types, versions, use_cache: bool, as_json: bool) -> int:
    # A chave só é exigida se houver chamada real; resultados em cache funcionam sem ela.
    service = AssistantService(load_settings(require_api_key=False))
    failures = 0
    for version in versions:
        for content_type in content_types:
            label = CONTENT_TYPES[content_type].label
            print(f"\n> Gerando {label} com o prompt {version}...", file=sys.stderr)
            try:
                record = service.generate(customer, ticket, content_type, version, use_cache=use_cache)
            except LLMError as exc:
                # Falha em um tipo não impede os outros (ex.: modelo devolveu JSON inválido duas vezes).
                failures += 1
                print(f"Erro ao gerar {label} ({version}): {exc}", file=sys.stderr)
                continue
            if as_json:
                print(json.dumps(record, ensure_ascii=False, indent=2))
            else:
                print(render_record(record, service.store.path))
    return 1 if failures else 0


# ------------------------------------------------------------------ helpers

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="Assistente de suporte com respostas personalizadas por engenharia de prompt.",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("interactive", help="modo interativo com menus (padrão)")
    sub.add_parser("list", help="lista perfis, tickets, tipos de conteúdo e versões de prompt")

    gen = sub.add_parser("generate", help="gera conteúdo sem menus")
    gen.add_argument("-c", "--customer", required=True, help="id do perfil (veja 'list')")
    source = gen.add_mutually_exclusive_group()
    source.add_argument("-t", "--ticket", help="id de um ticket de exemplo (veja 'list')")
    source.add_argument("--text", help="descrição de um ticket novo")
    gen.add_argument("--type", default="all", choices=[*CONTENT_TYPES, "all"], help="tipo de conteúdo (padrão: all)")
    gen.add_argument("-v", "--version", nargs="+", default=["v2"], help="uma ou mais versões de prompt (padrão: v2)")
    gen.add_argument("--no-cache", action="store_true", help="ignora o cache e chama o modelo de novo")
    gen.add_argument("--json", action="store_true", help="imprime o registro completo em JSON")
    return parser


def _pick(items: dict, key: str, label: str):
    if key not in items:
        raise UserInputError(f"{label} {key!r} não existe. Opções: {', '.join(items)}")
    return items[key]


def _validate_versions(versions: list[str], engine: PromptEngine) -> list[str]:
    available = engine.available_versions()
    unknown = [v for v in versions if v not in available]
    if unknown:
        raise UserInputError(f"versão {', '.join(unknown)} não existe. Opções: {', '.join(available)}")
    return list(dict.fromkeys(versions))  # remove repetidas mantendo a ordem


def _menu(title: str, options: list[tuple[str, str]]) -> str:
    print(title)
    for i, (_, text) in enumerate(options, start=1):
        print(f"  {i}. {text}")
    while True:
        raw = _input("> ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            print()
            return options[int(raw) - 1][0]
        print(f"  Digite um número de 1 a {len(options)}.")


def _read_multiline() -> str:
    print("Descreva o problema (linha vazia para terminar):")
    lines = []
    while True:
        line = _input("")
        if not line.strip():
            if lines:
                break
            print("  A descrição não pode ficar vazia.")
            continue
        lines.append(line)
    return "\n".join(lines)


def _input(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        raise KeyboardInterrupt from None


def _utf8_console() -> None:
    # O console do Windows usa cp1252 por padrão e quebraria os acentos.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

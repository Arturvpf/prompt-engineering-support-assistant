"""Interface de linha de comando.

Uso rápido::

    python main.py                       # modo interativo (menus)
    python main.py list                  # perfis, tickets, versões e tipos disponíveis
    python main.py generate -c marta-leigo-telefone -t T001 --type all --version v3
    python main.py generate -c rafael-avancado-chat --text "API retorna 500 ao criar pedido" --type diagnosis
    python main.py generate -c joao-leigo-chat -t T004 --type resolution_steps --version v2 v3
    python main.py history -c joao-leigo-chat -t T004            # execuções salvas (run_id)
    python main.py evaluate RUN_ID                              # dá as notas da rubrica (pergunta cada uma)
    python main.py evaluate RUN_ID --clarity 4 "..." --customer-fit 3 "..." --actionability 5 "..."
    python main.py compare RUN_V2 RUN_V3 --verdict "por que a v3 é melhor..."
    python main.py stats                                        # cache, tokens, latência
    python main.py web                                          # interface web em http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import ConfigError, load_settings
from .content_types import CONTENT_TYPES
from .data_loader import DataValidationError, load_customers, load_tickets, make_adhoc_ticket
from .evaluation import (
    CRITERIA,
    SCALE,
    EvaluationError,
    build_comparison,
    default_comparison_path,
    evaluate_run,
    load_scores_file,
    save_comparison,
)
from .formatting import render_comparison, render_evaluation, render_record
from .history import HistoryError, HistoryStore
from .llm_client import LLMError
from .observability import configure_logging, history_stats
from .prompt_engine import DEFAULT_VERSION, PromptEngine, PromptError
from .service import HISTORY_FILENAME, AssistantService

EXPECTED_ERRORS = (ConfigError, DataValidationError, PromptError, LLMError, HistoryError, EvaluationError)


class UserInputError(ValueError):
    """Entrada inválida informada pelo usuário."""


def main(argv: list[str] | None = None) -> int:
    _utf8_console()
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        settings = load_settings(require_api_key=False)
        configure_logging(settings.output_dir / "logs", settings.log_level)
        if args.command == "list":
            return cmd_list()
        if args.command == "generate":
            return cmd_generate(args)
        if args.command == "history":
            return cmd_history(args)
        if args.command == "evaluate":
            return cmd_evaluate(args)
        if args.command == "compare":
            return cmd_compare(args)
        if args.command == "stats":
            return cmd_stats(args)
        if args.command == "web":
            from .web import serve

            return serve(args.host, args.port)
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


def cmd_history(args: argparse.Namespace) -> int:
    store = _store()
    records = [
        r for r in store.load()
        if (not args.customer or r.get("customer_id") == args.customer)
        and (not args.ticket or r.get("ticket_id") == args.ticket)
        and (not args.type or r.get("content_type") == args.type)
    ]
    if not records:
        print(f"Nenhuma execução encontrada em {store.path}.")
        return 0
    print(f"{'run_id':<13} {'data':<20} {'cliente':<26} {'ticket':<6} {'tipo':<21} {'versão':<6} {'origem':<20} nota")
    for r in records[-args.limit:]:
        origin = f"cache de {r['source_run_id']}" if r.get("cache_hit") else "modelo"
        ev = r.get("evaluation")
        score = f"{ev['total']}/15" if ev else "-"
        print(f"{r['run_id']:<13} {r['timestamp'][:19]:<20} {r['customer_id']:<26} {r['ticket_id']:<6} "
              f"{r['content_type']:<21} {r['prompt_version']:<6} {origin:<20} {score}")
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    store = _store()
    record = store.get(args.run_id)

    if args.file:
        scores = load_scores_file(args.file)
    else:
        given = {cid: getattr(args, cid) for cid in CRITERIA if getattr(args, cid)}
        if given and len(given) != len(CRITERIA):
            raise UserInputError("informe os três critérios (--clarity, --customer-fit, --actionability) ou nenhum.")
        scores = {cid: (_parse_score(v[0]), v[1]) for cid, v in given.items()}
        if not scores:
            print(render_record(record, store.path))
            scores = _ask_scores()

    updated = evaluate_run(store, args.run_id, scores, evaluator=args.evaluator)
    print(render_evaluation(updated["evaluation"]))
    print(f"\nAvaliação salva no histórico: {store.path} (run_id {args.run_id})")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    store = _store()
    verdict = args.verdict or ""
    if args.verdict_file:
        verdict = args.verdict_file.read_text(encoding="utf-8")
    comparison = build_comparison(store, args.run_ids, verdict=verdict)
    print(render_comparison(comparison))
    path = save_comparison(comparison, args.out or default_comparison_path(store.path.parent, comparison))
    print(f"\nComparação salva em: {path}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    store = _store()
    s = history_stats(store.load())
    if args.json:
        print(json.dumps(s, ensure_ascii=False, indent=2))
        return 0
    print(f"Histórico: {store.path}")
    print(f"  execuções: {s['total_runs']}  |  chamadas ao modelo: {s['model_calls']}  |  "
          f"cache hits: {s['cache_hits']} ({s['cache_hit_rate']:.0%})")
    print(f"  tokens gastos: {s['tokens_total']}  |  tokens economizados pelo cache: {s['tokens_saved_by_cache']}")
    print(f"  com correção de JSON: {s['runs_with_repair']}  |  com avisos: {s['runs_with_warnings']}  |  "
          f"avaliadas: {s['evaluated_runs']}")
    if s["by_version_and_type"]:
        print(f"\n  {'versão':<7}{'tipo':<22}{'execuções':>10}{'latência média':>16}{'tokens médios':>15}")
        for g in s["by_version_and_type"]:
            print(f"  {g['prompt_version']:<7}{g['content_type']:<22}{g['runs']:>10}"
                  f"{g['avg_latency_ms'] / 1000:>15.1f}s{g['avg_tokens']:>15}")
    return 0


# ------------------------------------------------------------------ execução

def _run(customer, ticket, content_types, versions, use_cache: bool, as_json: bool) -> int:
    # A chave só é exigida se houver chamada real; resultados em cache funcionam sem ela.
    service = AssistantService(load_settings(require_api_key=False))
    failures = 0
    for version in versions:
        produced: dict[str, dict] = {}  # v3+: o diagnóstico desta rodada alimenta os outros tipos
        for content_type in content_types:
            label = CONTENT_TYPES[content_type].label
            print(f"\n> Gerando {label} com o prompt {version}...", file=sys.stderr)
            try:
                record = service.generate(customer, ticket, content_type, version, use_cache=use_cache,
                                          upstream_records=produced)
                produced[content_type] = record
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
    gen.add_argument("-v", "--version", nargs="+", default=[DEFAULT_VERSION],
                     help=f"uma ou mais versões de prompt (padrão: {DEFAULT_VERSION})")
    gen.add_argument("--no-cache", action="store_true", help="ignora o cache e chama o modelo de novo")
    gen.add_argument("--json", action="store_true", help="imprime o registro completo em JSON")

    hist = sub.add_parser("history", help="lista as execuções salvas no histórico")
    hist.add_argument("-c", "--customer", help="filtra por perfil")
    hist.add_argument("-t", "--ticket", help="filtra por ticket")
    hist.add_argument("--type", choices=list(CONTENT_TYPES), help="filtra por tipo de conteúdo")
    hist.add_argument("-n", "--limit", type=int, default=30, help="quantas execuções mostrar (padrão: 30)")

    ev = sub.add_parser("evaluate", help="dá as notas da rubrica (1 a 5) a uma execução")
    ev.add_argument("run_id", help="id da execução (veja 'history')")
    for cid, crit in CRITERIA.items():
        ev.add_argument(
            f"--{cid.replace('_', '-')}", dest=cid, nargs=2, metavar=("NOTA", "JUSTIFICATIVA"),
            help=f"{crit.label}: {crit.description}",
        )
    ev.add_argument("--file", type=Path, help="JSON com as notas: {\"clarity\": {\"score\": 4, \"justification\": \"...\"}, ...}")
    ev.add_argument("--evaluator", default="manual", help="quem avaliou (padrão: manual)")

    cmp_ = sub.add_parser("compare", help="compara execuções avaliadas do mesmo cenário (só o prompt muda)")
    cmp_.add_argument("run_ids", nargs="+", help="ids das execuções (duas versões por tipo de conteúdo)")
    verdict = cmp_.add_mutually_exclusive_group()
    verdict.add_argument("--verdict", help="por que uma versão é melhor que a outra")
    verdict.add_argument("--verdict-file", type=Path, help="arquivo de texto com o veredito")
    cmp_.add_argument("--out", type=Path, help="onde salvar o JSON da comparação (padrão: outputs/comparisons/)")

    st = sub.add_parser("stats", help="métricas do histórico: cache, tokens, latência, correções")
    st.add_argument("--json", action="store_true", help="imprime em JSON")

    web = sub.add_parser("web", help="abre a interface web local")
    web.add_argument("--host", default="127.0.0.1", help="endereço (padrão: 127.0.0.1, só esta máquina)")
    web.add_argument("--port", type=int, default=8000, help="porta (padrão: 8000)")
    return parser


def _store() -> HistoryStore:
    return HistoryStore(load_settings(require_api_key=False).output_dir / HISTORY_FILENAME)


def _parse_score(raw: str) -> int:
    if not raw.strip().isdigit() or int(raw) not in SCALE:
        raise UserInputError(f"nota {raw!r} inválida: use um inteiro de 1 a 5.")
    return int(raw)


def _ask_scores() -> dict[str, tuple[int, str]]:
    print("\nEscala: " + ", ".join(f"{k} {v}" for k, v in SCALE.items()))
    scores = {}
    for cid, crit in CRITERIA.items():
        print(f"\n{crit.label}: {crit.description}")
        while True:
            raw = _input("  Nota (1-5): ").strip()
            if raw.isdigit() and int(raw) in SCALE:
                break
            print("  Digite um inteiro de 1 a 5.")
        while True:
            why = _input("  Justificativa: ").strip()
            if why:
                break
            print("  A justificativa não pode ficar vazia.")
        scores[cid] = (int(raw), why)
    return scores


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

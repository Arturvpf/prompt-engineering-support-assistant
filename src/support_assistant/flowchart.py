"""Fluxograma a partir de um grafo de decisão.

Na v2 o modelo desenhava o fluxograma ASCII direto, e errava o alinhamento das
caixas e desenhava as decisões como uma linha reta. A partir da v3 o modelo
devolve só a estrutura (nós e ligações) em ``flow.nodes``; este módulo valida o
grafo e desenha o ASCII de forma determinística. Os ``decision_points`` também
são derivados do grafo, então o desenho e a lista de decisões nunca divergem.

Formato do grafo::

    {"nodes": [
        {"id": "N1", "type": "start",    "text": "...", "next": "N2"},
        {"id": "N2", "type": "decision", "text": "...?", "yes": "N3", "no": "N4"},
        {"id": "N3", "type": "action",   "text": "...", "next": "N5"},
        {"id": "N5", "type": "end",      "text": "RESOLVIDO"}
    ]}
"""

from __future__ import annotations

import textwrap

from .output_validation import OutputValidationError

MAX_NODES = 12
MAX_DECISIONS = 6
BOX_TEXT_WIDTH = 56
REF_WIDTH = 44
INDENT = "    "

NODE_TYPES = ("start", "action", "decision", "end")


class FlowGraphError(OutputValidationError):
    """O grafo não forma um fluxo válido (nó solto, ligação quebrada, decisão sem ramo).

    É um erro de saída: o gerador reenvia o prompt com a mensagem, como nos outros erros de formato.
    """


# ------------------------------------------------------------- validação

def validate_graph(flow) -> list[dict]:
    """Confere a estrutura do grafo e devolve a lista de nós. Lança FlowGraphError com todos os problemas."""
    if not isinstance(flow, dict) or not isinstance(flow.get("nodes"), list):
        raise FlowGraphError("'flow.nodes' deve ser uma lista de nós")
    nodes = flow["nodes"]
    problems: list[str] = []

    if len(nodes) < 2:
        problems.append("o fluxo precisa de pelo menos 2 nós (início e fim)")
    if len(nodes) > MAX_NODES:
        problems.append(f"o fluxo tem nós demais ({len(nodes)}; máximo {MAX_NODES})")

    by_id: dict[str, dict] = {}
    for i, node in enumerate(nodes, start=1):
        if not isinstance(node, dict):
            problems.append(f"nó {i} deve ser um objeto")
            continue
        node_id, kind, text = node.get("id"), node.get("type"), node.get("text")
        if not isinstance(node_id, str) or not node_id.strip():
            problems.append(f"nó {i} sem 'id'")
            continue
        if node_id in by_id:
            problems.append(f"id repetido: {node_id}")
        by_id[node_id] = node
        if kind not in NODE_TYPES:
            problems.append(f"nó {node_id}: 'type' = {kind!r} não é permitido (use: {', '.join(NODE_TYPES)})")
        if not isinstance(text, str) or not text.strip():
            problems.append(f"nó {node_id} sem 'text'")
    if problems:
        raise FlowGraphError("; ".join(problems))

    starts = [n["id"] for n in nodes if n["type"] == "start"]
    if len(starts) != 1:
        problems.append(f"o fluxo precisa de exatamente 1 nó 'start' (tem {len(starts)})")
    elif nodes[0]["type"] != "start":
        problems.append("o nó 'start' deve ser o primeiro da lista")
    if not any(n["type"] == "end" for n in nodes):
        problems.append("o fluxo precisa de pelo menos 1 nó 'end'")
    decisions = sum(n["type"] == "decision" for n in nodes)
    if decisions > MAX_DECISIONS:
        problems.append(f"decisões demais ({decisions}; máximo {MAX_DECISIONS})")

    for node in nodes:
        for key in _exits(node):
            target = node.get(key)
            if not isinstance(target, str) or target not in by_id:
                problems.append(f"nó {node['id']}: '{key}' aponta para {target!r}, que não existe")
            elif target == node["id"]:
                problems.append(f"nó {node['id']}: '{key}' aponta para ele mesmo")
        if node["type"] == "decision" and node.get("yes") == node.get("no") and node.get("yes"):
            problems.append(f"decisão {node['id']}: 'yes' e 'no' levam ao mesmo nó")
    if problems:
        raise FlowGraphError("; ".join(problems))

    for node in nodes:  # ramos diferentes que fazem a mesma coisa: a pergunta não decide nada
        if node["type"] == "decision" and _same_text(by_id[node["yes"]], by_id[node["no"]]):
            problems.append(f"decisão {node['id']}: 'yes' e 'no' levam à mesma ação "
                            f"({by_id[node['yes']]['text'].strip()!r}); remova a pergunta ou mude um dos ramos")
    if problems:
        raise FlowGraphError("; ".join(problems))

    reachable = _reach(nodes[0]["id"], lambda nid: [by_id[nid][k] for k in _exits(by_id[nid])])
    unreachable = [n["id"] for n in nodes if n["id"] not in reachable]
    if unreachable:
        problems.append(f"nós que não são alcançados a partir do início: {', '.join(unreachable)}")

    parents: dict[str, list[str]] = {nid: [] for nid in by_id}
    for node in nodes:
        for key in _exits(node):
            parents[node[key]].append(node["id"])
    reaches_end: set[str] = set()
    for end in (n["id"] for n in nodes if n["type"] == "end"):
        reaches_end |= _reach(end, lambda nid: parents[nid])
    stuck = [n["id"] for n in nodes if n["id"] not in reaches_end]
    if stuck:
        problems.append(f"nós que não chegam a nenhum fim (laço sem saída): {', '.join(stuck)}")
    if problems:
        raise FlowGraphError("; ".join(problems))
    return nodes


def _same_text(a: dict, b: dict) -> bool:
    def norm(node: dict) -> str:
        return " ".join(node["text"].lower().replace(",", " ").replace(".", " ").split())
    return norm(a) == norm(b)


def _exits(node: dict) -> tuple[str, ...]:
    return {"start": ("next",), "action": ("next",), "decision": ("yes", "no")}.get(node.get("type"), ())


def _reach(origin: str, neighbours) -> set[str]:
    seen, stack = {origin}, [origin]
    while stack:
        for nxt in neighbours(stack.pop()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


# ------------------------------------------------------------- desenho

def render_ascii(nodes: list[dict]) -> str:
    """Desenha o grafo de cima para baixo, seguindo a ordem da lista.

    - caixa com ``-``: início ou ação; caixa com ``=``: decisão; ``(( ))``: fim.
    - a seta para baixo segue para o próximo nó da lista; os outros ramos
      aparecem ao lado como ``não --> 4. texto``.
    """
    number = {n["id"]: i for i, n in enumerate(nodes, start=1)}
    by_id = {n["id"]: n for n in nodes}

    def ref(node_id: str) -> str:
        return _shorten(f"{number[node_id]}. {by_id[node_id]['text'].strip()}", REF_WIDTH)

    lines: list[str] = []
    for i, node in enumerate(nodes):
        following = nodes[i + 1]["id"] if i + 1 < len(nodes) else None
        label = f"{number[node['id']]}. {node['text'].strip()}"
        if node["type"] == "end":
            lines.append(f"(( {_shorten(label, BOX_TEXT_WIDTH + 2)} ))")
            if following:
                lines.append("")
            continue

        lines += _box(label, "=" if node["type"] == "decision" else "-")
        if node["type"] == "decision":
            branches = {"sim": node["yes"], "não": node["no"]}
            down = next((name for name, target in branches.items() if target == following), None)
            if down:
                side = "não" if down == "sim" else "sim"
                lines += [f"{INDENT}| {down}", f"{INDENT}|    {side} --> {ref(branches[side])}", f"{INDENT}v"]
            else:
                lines += [f"{INDENT}sim --> {ref(node['yes'])}", f"{INDENT}não --> {ref(node['no'])}", ""]
        elif node["next"] == following:
            lines += [f"{INDENT}|", f"{INDENT}v"]
        else:
            lines += [f"{INDENT}+--> vai para {ref(node['next'])}", ""]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _box(text: str, edge: str) -> list[str]:
    wrapped = textwrap.wrap(text, BOX_TEXT_WIDTH) or [""]
    width = max(len(line) for line in wrapped)
    border = "+" + edge * (width + 2) + "+"
    return [border, *(f"| {line.ljust(width)} |" for line in wrapped), border]


def _shorten(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 3].rstrip() + "..."


# ------------------------------------------------------------- decisões

def decision_points(nodes: list[dict]) -> list[dict]:
    """Uma entrada por decisão, com o texto do nó para onde cada ramo leva."""
    by_id = {n["id"]: n for n in nodes}
    number = {n["id"]: i for i, n in enumerate(nodes, start=1)}

    def target(node_id: str) -> str:
        return f"{by_id[node_id]['text'].strip()} (passo {number[node_id]})"

    return [
        {"question": n["text"].strip(), "if_yes": target(n["yes"]), "if_no": target(n["no"])}
        for n in nodes
        if n["type"] == "decision"
    ]


def complete_flow_output(output: dict) -> dict:
    """Se a saída tem 'flow', valida o grafo e preenche 'ascii_flowchart' e 'decision_points'.

    Os campos desenhados sempre vêm do grafo, mesmo que o modelo tenha mandado
    os seus: assim o desenho nunca contradiz a estrutura.
    """
    if "flow" not in output:
        return output
    nodes = validate_graph(output["flow"])
    return {**output, "ascii_flowchart": render_ascii(nodes), "decision_points": decision_points(nodes)}

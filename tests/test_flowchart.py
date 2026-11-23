import copy
import json

import pytest
from conftest import VALID_OUTPUTS, FakeClient

from support_assistant.flowchart import FlowGraphError, complete_flow_output, render_ascii, validate_graph
from support_assistant.generators import GENERATORS
from support_assistant.output_validation import OutputValidationError, validate_output

GRAPH = {"nodes": [
    {"id": "N1", "type": "start", "text": "Cliente não entra no app", "next": "N2"},
    {"id": "N2", "type": "decision", "text": "O app pede código de verificação?", "yes": "N3", "no": "N4"},
    {"id": "N3", "type": "action", "text": "Confirmar se o código chegou por SMS", "next": "N6"},
    {"id": "N4", "type": "action", "text": "Redefinir a senha", "next": "N5"},
    {"id": "N5", "type": "decision", "text": "Conseguiu entrar?", "yes": "N6", "no": "N7"},
    {"id": "N6", "type": "end", "text": "RESOLVIDO"},
    {"id": "N7", "type": "end", "text": "ESCALAR PARA N2"},
]}


def test_graph_becomes_aligned_ascii_and_decision_points():
    out = complete_flow_output({"flow": copy.deepcopy(GRAPH), "escalation": {"when": "x", "attach": []}})
    chart = out["ascii_flowchart"]
    assert validate_output("flow_summary", out) == []
    assert "não --> 4. Redefinir a senha" in chart
    assert "+--> vai para 6. RESOLVIDO" in chart
    assert "(( 7. ESCALAR PARA N2 ))" in chart
    assert all(len(line) <= 70 for line in chart.splitlines())
    assert [d["question"] for d in out["decision_points"]] == ["O app pede código de verificação?", "Conseguiu entrar?"]
    assert out["decision_points"][1] == {"question": "Conseguiu entrar?", "if_yes": "RESOLVIDO (passo 6)",
                                         "if_no": "ESCALAR PARA N2 (passo 7)"}


def test_drawn_fields_always_come_from_the_graph():
    out = complete_flow_output({"flow": copy.deepcopy(GRAPH), "ascii_flowchart": "lixo", "decision_points": []})
    assert out["ascii_flowchart"] != "lixo" and len(out["decision_points"]) == 2


def test_outputs_without_graph_are_untouched():
    v2 = {"ascii_flowchart": "[A] -> [B]", "decision_points": [{"question": "q", "if_yes": "a", "if_no": "b"}]}
    assert complete_flow_output(v2) is v2


def test_long_text_wraps_inside_the_box():
    nodes = copy.deepcopy(GRAPH["nodes"])
    nodes[0]["text"] = "Cliente relata que " * 8
    lines = render_ascii(validate_graph({"nodes": nodes})).splitlines()
    first_box = lines[: lines.index("    |")]
    assert len(first_box) > 3 and len({len(line) for line in first_box}) == 1


@pytest.mark.parametrize("mutate, message", [
    (lambda n: n[1].update(no="N9"), "aponta para 'N9', que não existe"),
    (lambda n: n[1].update(no="N3"), "levam ao mesmo nó"),
    (lambda n: n[3].update(text="Confirmar se o código chegou por SMS."), "levam à mesma ação"),
    (lambda n: n.insert(0, n.pop(2)), "deve ser o primeiro"),
    (lambda n: n.append({"id": "N8", "type": "action", "text": "solto", "next": "N6"}), "não são alcançados"),
    (lambda n: n[3].update(next="N4"), "aponta para ele mesmo"),
    (lambda n: n[1].update(type="pergunta"), "não é permitido"),
    (lambda n: [x.update(type="action", next="N1") for x in n if x["type"] == "end"], "pelo menos 1 nó 'end'"),
])
def test_broken_graphs_are_rejected_with_a_clear_reason(mutate, message):
    nodes = copy.deepcopy(GRAPH["nodes"])
    mutate(nodes)
    with pytest.raises(FlowGraphError, match=message):
        validate_graph({"nodes": nodes})


def test_loop_without_exit_is_rejected():
    nodes = [
        {"id": "A", "type": "start", "text": "início", "next": "B"},
        {"id": "B", "type": "decision", "text": "ok?", "yes": "D", "no": "C"},
        {"id": "C", "type": "action", "text": "tentar de novo", "next": "E"},
        {"id": "E", "type": "action", "text": "esperar", "next": "C"},
        {"id": "D", "type": "end", "text": "RESOLVIDO"},
    ]
    with pytest.raises(FlowGraphError, match="não chegam a nenhum fim"):
        validate_graph({"nodes": nodes})


def test_graph_error_is_an_output_error_and_triggers_the_repair(engine, customers, tickets):
    assert issubclass(FlowGraphError, OutputValidationError)
    broken = copy.deepcopy(GRAPH)
    broken["nodes"][1]["no"] = "N9"
    client = FakeClient(responses=[json.dumps({"flow": broken}), json.dumps({"flow": GRAPH})])
    result = GENERATORS["flow_summary"](client, engine, customers["joao-leigo-chat"], tickets["T004"], "v3",
                                        {"diagnosis": VALID_OUTPUTS["diagnosis"]})
    assert result.attempts == 2
    assert "'N9', que não existe" in client.calls[1][1]
    assert "ascii_flowchart" in result.output and result.output["flow"] == GRAPH

import pytest
from conftest import FakeClient, make_settings

from support_assistant.evaluation import EvaluationError, build_comparison, build_evaluation, evaluate_run
from support_assistant.history import HistoryStore
from support_assistant.service import AssistantService

SCORES_V1 = {"clarity": (4, "ok"), "customer_fit": (3, "genérico"), "actionability": (3, "vago")}
SCORES_V2 = {"clarity": (4, "ok"), "customer_fit": (5, "adequado"), "actionability": (4, "claro")}


def test_build_evaluation_totals_and_levels():
    ev = build_evaluation(SCORES_V2, "avaliador")
    assert ev["total"] == 13 and ev["average"] == 4.33
    assert ev["criteria"]["customer_fit"] == {"score": 5, "level": "excelente", "justification": "adequado"}
    assert list(ev["criteria"]) == ["clarity", "customer_fit", "actionability"]


@pytest.mark.parametrize("scores, message", [
    ({"clarity": (4, "x"), "customer_fit": (3, "y")}, "faltando"),
    ({**SCORES_V1, "extra": (3, "z")}, "desconhecidos"),
    ({**SCORES_V1, "clarity": (6, "x")}, "1 a 5"),
    ({**SCORES_V1, "clarity": (True, "x")}, "1 a 5"),
    ({**SCORES_V1, "clarity": (4, "   ")}, "vazia"),
])
def test_build_evaluation_rejects_invalid_scores(scores, message):
    with pytest.raises(EvaluationError, match=message):
        build_evaluation(scores, "x")


@pytest.fixture
def two_versions(service, customers, tickets):
    args = (customers["joao-leigo-chat"], tickets["T004"], "diagnosis")
    v1 = service.generate(*args, "v1")
    v2 = service.generate(*args, "v2")
    return service.store, v1, v2


def test_evaluation_is_saved_in_history(two_versions):
    store, v1, _ = two_versions
    evaluate_run(store, v1["run_id"], SCORES_V1, "avaliador")
    assert store.get(v1["run_id"])["evaluation"]["total"] == 10


def test_cache_hit_cannot_be_evaluated(service, two_versions, customers, tickets):
    store, v1, _ = two_versions
    hit = service.generate(customers["joao-leigo-chat"], tickets["T004"], "diagnosis", "v1")
    with pytest.raises(EvaluationError, match=v1["run_id"]):
        evaluate_run(store, hit["run_id"], SCORES_V1, "x")


def test_comparison_picks_winner_and_delta(two_versions):
    store, v1, v2 = two_versions
    evaluate_run(store, v1["run_id"], SCORES_V1, "x")
    evaluate_run(store, v2["run_id"], SCORES_V2, "x")
    comp = build_comparison(store, [v2["run_id"], v1["run_id"]], verdict="  v2 melhor  ")
    group = comp["by_content_type"][0]
    assert list(group["versions"]) == ["v1", "v2"]
    assert group["delta"] == {"from": "v1", "to": "v2", "clarity": 0, "customer_fit": 2, "actionability": 1}
    assert group["winner"] == "v2" and comp["overall_winner"] == "v2"
    assert comp["overall_totals"] == {"v1": 10, "v2": 13}
    assert comp["verdict"] == "v2 melhor"


def test_comparison_requires_evaluations(two_versions):
    store, v1, v2 = two_versions
    with pytest.raises(EvaluationError, match="ainda não foi avaliada"):
        build_comparison(store, [v1["run_id"], v2["run_id"]])


def test_comparison_rejects_different_settings(tmp_path, engine, customers, tickets):
    store = HistoryStore(tmp_path / "history.json")
    runs = []
    for version, temperature in (("v1", 0.2), ("v2", 0.9)):
        svc = AssistantService(make_settings(tmp_path, temperature=temperature), engine=engine, store=store,
                               client_factory=lambda _s: FakeClient())
        run = svc.generate(customers["joao-leigo-chat"], tickets["T004"], "diagnosis", version)
        evaluate_run(store, run["run_id"], SCORES_V1, "x")
        runs.append(run["run_id"])
    with pytest.raises(EvaluationError, match="generation_params"):
        build_comparison(store, runs)


def test_comparison_rejects_same_version_twice(service, customers, tickets):
    args = (customers["joao-leigo-chat"], tickets["T004"], "diagnosis", "v2")
    a = service.generate(*args)
    b = service.generate(*args, use_cache=False)
    for run in (a, b):
        evaluate_run(service.store, run["run_id"], SCORES_V1, "x")
    with pytest.raises(EvaluationError, match="mesma versão"):
        build_comparison(service.store, [a["run_id"], b["run_id"]])

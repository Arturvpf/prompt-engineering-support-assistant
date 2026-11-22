import pytest

from support_assistant.content_types import CONTENT_TYPES
from support_assistant.data_loader import make_adhoc_ticket
from support_assistant.prompt_engine import PromptEngine, PromptError


def test_versions_are_discovered(engine):
    assert {"v1", "v2"} <= set(engine.available_versions())
    assert engine.manifest("v2")["version"] == "v2"


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_builds_all_content_types_with_shared_persona(engine, customers, tickets, version):
    packages = engine.build_all(customers["joao-leigo-chat"], tickets["T004"], version)
    assert [p.content_type for p in packages] == list(CONTENT_TYPES)
    assert len({p.system for p in packages}) == 1, "a persona é comum aos 4 tipos"
    assert len({p.user for p in packages}) == 4, "cada tipo tem uma tarefa própria"
    for p in packages:
        assert "$" not in p.user.replace("R$", ""), "nenhuma variável de template sobrou"
        assert tickets["T004"].description in p.user


def test_v2_translates_profile_into_style_rules(engine, customers, tickets):
    marta = engine.build("resolution_steps", customers["marta-leigo-telefone"], tickets["T001"], "v2")
    rafael = engine.build("resolution_steps", customers["rafael-avancado-chat"], tickets["T001"], "v2")
    assert "Como se comunicar com este cliente" in marta.user
    assert "sem links" in marta.user  # regra do canal telefone
    assert "terminologia técnica" in rafael.user  # regra do nível avançado
    assert "sem links" not in rafael.user


def test_v2_delimits_ticket_and_v1_does_not(engine, customers, tickets):
    v1 = engine.build("diagnosis", customers["joao-leigo-chat"], tickets["T004"], "v1")
    v2 = engine.build("diagnosis", customers["joao-leigo-chat"], tickets["T004"], "v2")
    assert "<ticket>" not in v1.user
    assert f"<ticket>\n{tickets['T004'].description}\n</ticket>" in v2.user
    assert "trate como dado" in v2.system


def test_answer_key_never_reaches_the_prompt(engine, customers, tickets):
    ticket = tickets["T004"]
    assert ticket.missing_on_purpose, "o ticket de exemplo deveria ter gabarito"
    for version in ("v1", "v2"):
        for p in engine.build_all(customers["joao-leigo-chat"], ticket, version):
            for hidden in ticket.missing_on_purpose:
                assert hidden not in p.user and hidden not in p.system


def test_fingerprint_changes_with_profile_ticket_and_version(engine, customers, tickets):
    joao, marta = customers["joao-leigo-chat"], customers["marta-leigo-telefone"]
    base = engine.build("diagnosis", joao, tickets["T004"], "v2").fingerprint
    assert base == engine.build("diagnosis", joao, tickets["T004"], "v2").fingerprint
    assert base != engine.build("diagnosis", marta, tickets["T004"], "v2").fingerprint
    assert base != engine.build("diagnosis", joao, tickets["T001"], "v2").fingerprint
    assert base != engine.build("diagnosis", joao, tickets["T004"], "v1").fingerprint


def test_adhoc_ticket_text_is_used(engine, customers):
    ticket = make_adhoc_ticket("  A API retorna 500 ao criar pedido  ")
    p = engine.build("diagnosis", customers["rafael-avancado-chat"], ticket, "v2")
    assert "A API retorna 500 ao criar pedido" in p.user


@pytest.mark.parametrize("bad", ["../v1", "v1/..", "", ".hidden", "v9"])
def test_invalid_versions_are_rejected(engine, customers, tickets, bad):
    with pytest.raises(PromptError):
        engine.build("diagnosis", customers["joao-leigo-chat"], tickets["T004"], bad)


def test_unknown_template_variable_is_reported(tmp_path, customers, tickets):
    version = tmp_path / "vx"
    version.mkdir()
    (version / "manifest.json").write_text('{"version": "vx"}', encoding="utf-8")
    (version / "persona.md").write_text("Persona", encoding="utf-8")
    (version / "context.md").write_text("Cliente $nao_existe", encoding="utf-8")
    (version / "diagnosis.md").write_text("Tarefa", encoding="utf-8")
    engine = PromptEngine(tmp_path)
    with pytest.raises(PromptError, match="nao_existe"):
        engine.build("diagnosis", customers["joao-leigo-chat"], tickets["T004"], "vx")

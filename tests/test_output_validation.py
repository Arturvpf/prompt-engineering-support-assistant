import copy
import json

import pytest
from conftest import ROOT, VALID_OUTPUTS

from support_assistant.content_types import CONTENT_TYPES
from support_assistant.output_validation import (
    OutputValidationError,
    load_schema,
    parse_json_output,
    validate_output,
)


@pytest.mark.parametrize("content_type", list(CONTENT_TYPES))
def test_every_content_type_has_a_valid_schema(content_type):
    schema = load_schema(content_type)
    assert schema["type"] == "object"
    assert set(CONTENT_TYPES[content_type].required_fields) <= set(schema["required"])


@pytest.mark.parametrize("content_type", list(CONTENT_TYPES))
def test_valid_outputs_pass(content_type):
    assert validate_output(content_type, VALID_OUTPUTS[content_type]) == []


def test_all_committed_samples_pass_the_schema():
    """As saídas reais em samples/ (v1 e v2) precisam continuar válidas."""
    checked = 0
    for path in (ROOT / "samples").rglob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        for record in data if isinstance(data, list) else []:
            validate_output(record["content_type"], record["output"])
            checked += 1
    assert checked >= 10


def test_parse_tolerates_code_fences_and_surrounding_text():
    assert parse_json_output('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_output('Aqui está:\n{"a": 1}\nObrigado') == {"a": 1}


@pytest.mark.parametrize("text", ["sem json", "[1, 2]", '{"a": '])
def test_parse_rejects_non_objects(text):
    with pytest.raises(OutputValidationError):
        parse_json_output(text)


def test_missing_and_empty_fields_are_reported_in_portuguese():
    data = copy.deepcopy(VALID_OUTPUTS["diagnosis"])
    del data["missing_information"]
    data["hypotheses"][0]["description"] = "   "
    with pytest.raises(OutputValidationError) as exc:
        validate_output("diagnosis", data)
    message = str(exc.value)
    assert "campo 'missing_information' ausente" in message
    assert "'hypotheses[1].description' está vazio" in message


def test_wrong_type_and_enum_are_rejected():
    data = copy.deepcopy(VALID_OUTPUTS["diagnosis"])
    data["probable_conclusion"]["confidence"] = "Alta"
    data["evidence"] = "texto solto"
    with pytest.raises(OutputValidationError) as exc:
        validate_output("diagnosis", data)
    assert "'evidence' deve ser do tipo lista" in str(exc.value)
    assert "não é permitido" in str(exc.value)


def test_empty_string_reports_once():
    data = copy.deepcopy(VALID_OUTPUTS["resolution_steps"])
    data["if_not_resolved"] = ""
    with pytest.raises(OutputValidationError) as exc:
        validate_output("resolution_steps", data)
    assert str(exc.value).count("if_not_resolved") == 1


def test_coherence_problems_are_warnings_not_errors():
    diag = copy.deepcopy(VALID_OUTPUTS["diagnosis"])
    diag["probable_conclusion"]["hypothesis_id"] = "H9"
    diag["evidence"][0]["weakens"] = ["H7"]
    warnings = validate_output("diagnosis", diag)
    assert any("H9" in w for w in warnings) and any("H7" in w for w in warnings)

    flow = copy.deepcopy(VALID_OUTPUTS["flow_summary"])
    flow["ascii_flowchart"] = "┌──┐\n" + "x" * 90
    flow["decision_points"][0]["if_no"] = "RESOLVIDO"
    warnings = validate_output("flow_summary", flow)
    assert len(warnings) == 3

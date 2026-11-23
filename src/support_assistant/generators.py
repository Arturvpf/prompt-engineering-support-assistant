"""As quatro estratégias de geração, uma por tipo de conteúdo.

Cada função monta o prompt do seu tipo (persona e contexto são comuns; a tarefa
é específica), chama o modelo e valida a saída. Se a saída vier fora do
formato, é feita uma única tentativa de correção, reenviando o prompt com o
erro encontrado.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .data_loader import CustomerProfile, Ticket
from .flowchart import complete_flow_output
from .llm_client import LLMClient, LLMError, LLMResponse
from .observability import log_event
from .output_validation import OutputValidationError, parse_json_output, validate_output
from .prompt_engine import PromptEngine, PromptPackage

MAX_REPAIR_ATTEMPTS = 1

REPAIR_INSTRUCTION = """

## Correção
Sua resposta anterior não seguiu o formato pedido: {error}
Responda novamente, apenas com o objeto JSON completo e válido, no formato especificado acima."""


class GenerationError(LLMError):
    """A saída continuou inválida mesmo após a tentativa de correção."""


@dataclass
class GenerationResult:
    content_type: str
    prompt: PromptPackage
    output: dict
    response: LLMResponse
    attempts: int = 1
    warnings: list[str] = field(default_factory=list)


def generate_diagnosis(client: LLMClient, engine: PromptEngine, customer: CustomerProfile,
                       ticket: Ticket, version: str, upstream: dict | None = None) -> GenerationResult:
    """Hipóteses, evidências, dados faltantes e conclusão provável."""
    return _generate("diagnosis", client, engine, customer, ticket, version, upstream)


def generate_resolution_steps(client: LLMClient, engine: PromptEngine, customer: CustomerProfile,
                              ticket: Ticket, version: str, upstream: dict | None = None) -> GenerationResult:
    """Passo a passo adaptado ao nível técnico, ao estilo e ao canal."""
    return _generate("resolution_steps", client, engine, customer, ticket, version, upstream)


def generate_clarifying_questions(client: LLMClient, engine: PromptEngine, customer: CustomerProfile,
                                  ticket: Ticket, version: str, upstream: dict | None = None) -> GenerationResult:
    """Perguntas priorizadas para coletar só o necessário."""
    return _generate("clarifying_questions", client, engine, customer, ticket, version, upstream)


def generate_flow_summary(client: LLMClient, engine: PromptEngine, customer: CustomerProfile,
                          ticket: Ticket, version: str, upstream: dict | None = None) -> GenerationResult:
    """Fluxograma ASCII e pontos de decisão do atendimento."""
    return _generate("flow_summary", client, engine, customer, ticket, version, upstream)


GENERATORS = {
    "diagnosis": generate_diagnosis,
    "resolution_steps": generate_resolution_steps,
    "clarifying_questions": generate_clarifying_questions,
    "flow_summary": generate_flow_summary,
}


def _generate(content_type: str, client: LLMClient, engine: PromptEngine,
              customer: CustomerProfile, ticket: Ticket, version: str,
              upstream: dict | None = None) -> GenerationResult:
    prompt = engine.build(content_type, customer, ticket, version, upstream)
    user = prompt.user
    last_error = ""

    for attempt in range(1, MAX_REPAIR_ATTEMPTS + 2):
        response = client.generate(prompt.system, user)
        try:
            if response.truncated:
                raise OutputValidationError(
                    "resposta cortada pelo limite de tokens; seja mais conciso"
                )
            output = parse_json_output(response.text)
            if content_type == "flow_summary":
                output = complete_flow_output(output)  # v3+: grafo -> ASCII desenhado pelo código
            warnings = validate_output(content_type, output)
        except OutputValidationError as exc:
            last_error = str(exc)
            log_event("output_invalid", logging.WARNING, content_type=content_type, version=version,
                      attempt=attempt, will_retry=attempt <= MAX_REPAIR_ATTEMPTS, error=last_error[:300])
            user = prompt.user + REPAIR_INSTRUCTION.format(error=last_error)
            continue
        return GenerationResult(content_type, prompt, output, response, attempt, warnings)

    raise GenerationError(
        f"Saída inválida para '{content_type}' após {MAX_REPAIR_ATTEMPTS + 1} tentativas: {last_error}"
    )

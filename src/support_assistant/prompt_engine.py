"""Motor de engenharia de prompt.

Monta, a partir de arquivos versionados em ``prompts/<versão>/``, os dois
textos enviados ao modelo:

- **system**: persona (papel, responsabilidades e limites). É igual para os
  quatro tipos de conteúdo de uma versão.
- **user**: contexto (cliente + ticket) seguido da tarefa específica do tipo de
  conteúdo, que traz a decomposição e o formato de saída.

Estrutura de uma versão::

    prompts/v2/
      manifest.json             descrição e hipótese de melhoria da versão
      persona.md                componente comum: papel e limites
      context.md                componente comum: dados do cliente e do ticket
      style_rules.json          (opcional) perfil -> regras de escrita
      diagnosis.md              tarefa + formato de cada tipo de conteúdo
      resolution_steps.md
      clarifying_questions.md
      flow_summary.md

Os templates usam ``string.Template`` (``$variavel``) em vez de ``str.format``
porque o formato de saída é JSON e as chaves ``{}`` não precisam ser escapadas.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from string import Template

from .content_types import CONTENT_TYPES, get_content_type
from .data_loader import CustomerProfile, Ticket

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


class PromptError(ValueError):
    """Versão de prompt inexistente ou template incompleto."""


@dataclass(frozen=True)
class PromptPackage:
    """Prompt pronto para envio, com os metadados usados no histórico e no cache."""

    version: str
    content_type: str
    system: str
    user: str

    @property
    def fingerprint(self) -> str:
        """Hash do prompt renderizado: muda se o template, o perfil ou o ticket mudarem."""
        digest = hashlib.sha256(f"{self.system}\n---\n{self.user}".encode("utf-8"))
        return digest.hexdigest()


class PromptEngine:
    def __init__(self, prompts_dir: Path = PROMPTS_DIR) -> None:
        self.prompts_dir = prompts_dir

    # ------------------------------------------------------------- versões

    def available_versions(self) -> list[str]:
        if not self.prompts_dir.is_dir():
            return []
        return sorted(p.name for p in self.prompts_dir.iterdir() if (p / "manifest.json").is_file())

    def manifest(self, version: str) -> dict:
        return json.loads(self._read(version, "manifest.json"))

    # ------------------------------------------------------------- montagem

    def build(
        self,
        content_type: str,
        customer: CustomerProfile,
        ticket: Ticket,
        version: str,
    ) -> PromptPackage:
        get_content_type(content_type)  # valida o tipo
        variables = self._variables(customer, ticket, version)

        system = self._render(version, "persona.md", variables)
        context = self._render(version, "context.md", variables)
        task = self._render(version, f"{content_type}.md", variables)

        return PromptPackage(
            version=version,
            content_type=content_type,
            system=system,
            user=f"{context}\n\n{task}",
        )

    def build_all(self, customer: CustomerProfile, ticket: Ticket, version: str) -> list[PromptPackage]:
        return [self.build(ct, customer, ticket, version) for ct in CONTENT_TYPES]

    # ------------------------------------------------------------- internos

    def _variables(self, customer: CustomerProfile, ticket: Ticket, version: str) -> dict[str, str]:
        # missing_on_purpose do ticket fica de fora de propósito: é gabarito de avaliação.
        return {
            "customer_name": customer.name,
            "technical_level": customer.technical_level,
            "communication_style": customer.communication_style,
            "channel": customer.channel,
            "customer_context": customer.context or "não informado",
            "ticket_id": ticket.id,
            "ticket_title": ticket.title,
            "product": ticket.product or "não informado",
            "ticket_description": ticket.description,
            "style_guidelines": self._style_guidelines(customer, version),
        }

    def _style_guidelines(self, customer: CustomerProfile, version: str) -> str:
        """Traduz o perfil em regras concretas de escrita, se a versão tiver style_rules.json."""
        path = self._path(version, "style_rules.json")
        if not path.is_file():
            return ""
        rules = json.loads(path.read_text(encoding="utf-8"))
        lines = []
        for attribute, label in (
            ("technical_level", "Nível técnico"),
            ("communication_style", "Estilo"),
            ("channel", "Canal"),
        ):
            value = getattr(customer, attribute)
            try:
                rule = rules[attribute][value]
            except KeyError as exc:
                raise PromptError(f"style_rules.json da {version} não cobre {attribute}={value!r}") from exc
            lines.append(f"- {label} ({value}): {rule}")
        return "\n".join(lines)

    def _render(self, version: str, filename: str, variables: dict[str, str]) -> str:
        template = Template(self._read(version, filename))
        try:
            return template.substitute(variables).strip()
        except KeyError as exc:
            raise PromptError(f"Variável desconhecida {exc} em {version}/{filename}") from exc
        except ValueError as exc:
            raise PromptError(f"Template inválido em {version}/{filename}: {exc}") from exc

    def _read(self, version: str, filename: str) -> str:
        path = self._path(version, filename)
        if not path.is_file():
            available = ", ".join(self.available_versions()) or "nenhuma"
            raise PromptError(f"Arquivo {filename} não encontrado na versão {version!r}. Versões: {available}")
        return path.read_text(encoding="utf-8")

    def _path(self, version: str, filename: str) -> Path:
        if not version or "/" in version or "\\" in version or version.startswith("."):
            raise PromptError(f"Nome de versão inválido: {version!r}")
        return self.prompts_dir / version / filename

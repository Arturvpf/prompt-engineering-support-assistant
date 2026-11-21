## Tarefa
Resuma o atendimento deste ticket como um fluxograma ASCII que o atendente segue como roteiro.

- Comece no sintoma relatado, passe pelas verificações principais e termine em "RESOLVIDO" ou "ESCALAR PARA N2".
- No máximo 8 caixas e 4 decisões. Cada decisão é uma pergunta de sim ou não.
- Use apenas caracteres ASCII (por exemplo + - | v > [ ]) e linhas de até 70 caracteres. Use \n para quebrar linha dentro da string.
- Em "decision_points", repita cada decisão com o que fazer no sim e no não.
- Em "escalation", diga quando escalar e o que anexar ao chamado.

Formato da resposta (JSON):
{
  "ascii_flowchart": "...",
  "decision_points": [{"question": "...", "if_yes": "...", "if_no": "..."}],
  "escalation": {"when": "...", "attach": ["..."]}
}

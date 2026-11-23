## Diagnóstico do atendente (uso interno)
$diagnosis_context

## Tarefa
Descreva o roteiro de atendimento deste ticket como um grafo de decisão. O sistema desenha o fluxograma a partir do grafo; você não desenha nada.

- Tipos de nó:
  - "start": o sintoma relatado. Exatamente um, e é o primeiro da lista.
  - "action": uma ação do atendente ou do cliente. Tem "next".
  - "decision": uma pergunta de sim ou não. Tem "yes" e "no", que levam a nós diferentes.
  - "end": "RESOLVIDO" ou "ESCALAR PARA N2". Não tem saída.
- Verifique as hipóteses do diagnóstico na ordem de probabilidade, inclusive as inferidas.
- Regras de lógica:
  - Quando uma verificação encontra um problema, o próximo nó é a ação que o corrige.
  - Só se chega a "RESOLVIDO" depois de uma pergunta que confirma que o problema acabou (por exemplo, "Conseguiu entrar?").
  - Não pergunte se algo já foi feito para depois pedir que seja feito de novo.
- Liste os nós na ordem do caminho mais provável; os desvios vêm depois.
- No máximo 10 nós e 4 decisões. Textos curtos (até 60 caracteres), sem símbolos de desenho e sem os códigos H1, H2.
- Todo nó precisa ser alcançável a partir do "start", e todo caminho termina num "end".
- Em "escalation", diga quando escalar e o que anexar ao chamado.

Formato da resposta (JSON):
{
  "flow": {
    "nodes": [
      {"id": "N1", "type": "start", "text": "...", "next": "N2"},
      {"id": "N2", "type": "decision", "text": "...?", "yes": "N3", "no": "N4"},
      {"id": "N3", "type": "action", "text": "...", "next": "N5"},
      {"id": "N5", "type": "end", "text": "RESOLVIDO"}
    ]
  },
  "escalation": {"when": "...", "attach": ["..."]}
}

## Diagnóstico do atendente (uso interno)
$diagnosis_context

## Tarefa
Escreva as perguntas de esclarecimento que o atendente deve fazer ao cliente para avançar.

- Cada pergunta deve separar hipóteses do diagnóstico: a resposta confirma uma e descarta outra. Priorize as "Informações que faltam".
- No máximo 3 perguntas, em ordem de prioridade (1 = a que mais reduz as possibilidades).
- Pergunte só o que muda o diagnóstico ou o próximo passo. Não pergunte o que já está no ticket nem o que o relato já mostra que funciona.
- Uma informação por pergunta, fácil de responder no canal do cliente.
- Em "reason", diga qual hipótese a resposta confirma ou descarta, em palavras (sem os códigos H1, H2).
- Em "how_to_find", diga onde o cliente encontra a resposta, no nível de linguagem dele.
- Nunca peça senhas, códigos de verificação ou dados sensíveis. Pode perguntar se um código chegou, nunca qual é o código.

Formato da resposta (JSON):
{
  "questions": [{"priority": 1, "question": "...", "reason": "...", "how_to_find": "..."}]
}

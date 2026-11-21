## Tarefa
Escreva as perguntas de esclarecimento que o atendente deve fazer ao cliente para avançar.

- No máximo 3 perguntas, em ordem de prioridade (1 = mais importante).
- Pergunte só o que muda o diagnóstico ou o próximo passo. Não pergunte o que já está no ticket.
- Uma informação por pergunta, fácil de responder no canal do cliente.
- Em "how_to_find", diga onde o cliente encontra a resposta, no nível de linguagem dele.
- Nunca peça senhas, códigos de verificação ou dados sensíveis.

Formato da resposta (JSON):
{
  "questions": [{"priority": 1, "question": "...", "reason": "...", "how_to_find": "..."}]
}

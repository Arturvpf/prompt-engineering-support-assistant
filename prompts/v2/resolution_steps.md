## Tarefa
Escreva o passo a passo para o cliente resolver ou contornar o problema, seguindo as regras de comunicação acima.

- Comece pelas ações mais simples, seguras e com mais chance de resolver.
- De 3 a 7 passos; cada passo contém uma única ação.
- Em cada passo, diga o resultado esperado, para o cliente saber se deu certo.
- Se um passo depender de informação que não está no ticket, ensine a verificar em vez de supor.
- Em "if_not_resolved", diga o que o cliente deve fazer e quais informações enviar se nada funcionar.

Formato da resposta (JSON):
{
  "opening": "frase curta de abertura adequada ao canal",
  "steps": [{"number": 1, "action": "...", "why": "...", "expected_result": "..."}],
  "if_not_resolved": "..."
}
Deixe "why" vazio ("") quando o estilo do cliente for "direto".

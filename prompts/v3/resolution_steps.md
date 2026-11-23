## Diagnóstico do atendente (uso interno)
$diagnosis_context

## Tarefa
Escreva o passo a passo para o cliente resolver ou contornar o problema, seguindo as regras de comunicação acima.

- Cubra as hipóteses do diagnóstico, da mais para a menos provável, inclusive as marcadas como inferidas. Não cite os códigos das hipóteses (H1, H2) ao cliente.
- Ordene os passos assim:
  1. verificações rápidas e sem risco ligadas às hipóteses mais prováveis;
  2. ações que podem ser desfeitas;
  3. por último, ações que apagam dados ou exigem reinstalar, com o aviso de risco.
- Não inclua passos genéricos (reiniciar o aparelho, limpar cache) sem relação com as hipóteses.
- De 3 a 7 passos; cada passo contém uma única ação. O encaminhamento ao suporte vai só em "if_not_resolved", nunca como passo.
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

## Tarefa
Faça um diagnóstico do problema descrito no ticket, considerando o perfil do cliente.

Formato da resposta (JSON):
{
  "hypotheses": [{"id": "H1", "description": "...", "likelihood": "alta | média | baixa"}],
  "evidence": [{"signal": "...", "supports": ["H1"]}],
  "missing_information": [{"item": "...", "why_it_matters": "..."}],
  "probable_conclusion": {"hypothesis_id": "H1", "summary": "...", "confidence": "alta | média | baixa"}
}

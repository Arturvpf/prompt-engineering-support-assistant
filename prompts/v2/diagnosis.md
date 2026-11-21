## Tarefa
Produza um diagnóstico estruturado e verificável do ticket, nesta ordem:

1. **Hipóteses**: de 2 a 4 causas plausíveis e distintas entre si, da mais para a menos provável.
2. **Evidências**: sinais concretos do relato. Em "signal", cite o trecho do ticket entre aspas. Indique quais hipóteses o sinal apoia e quais enfraquece.
3. **Informações faltantes**: apenas o que mudaria a conclusão ou o próximo passo, com o motivo.
4. **Conclusão provável**: a hipótese mais provável e a confiança. Se as evidências não bastarem, use confiança "baixa" e diga o que confirmaria a hipótese.

O diagnóstico é lido pelo atendente; "summary" deve poder ser repassado ao cliente seguindo as regras de comunicação.

Formato da resposta (JSON):
{
  "hypotheses": [{"id": "H1", "description": "...", "likelihood": "alta | média | baixa"}],
  "evidence": [{"signal": "\"trecho do ticket\"", "supports": ["H1"], "weakens": ["H2"]}],
  "missing_information": [{"item": "...", "why_it_matters": "..."}],
  "probable_conclusion": {"hypothesis_id": "H1", "summary": "...", "confidence": "alta | média | baixa", "how_to_confirm": "..."}
}

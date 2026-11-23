## Tarefa
Produza um diagnóstico estruturado e verificável do ticket, nesta ordem:

1. **Hipóteses**: de 2 a 4 causas plausíveis e distintas entre si, da mais para a menos provável.
   - Em "basis", use "relato" se a causa decorre do que o cliente escreveu, ou "inferida" se é uma causa que ele não mencionou.
   - Inclua pelo menos uma hipótese "inferida": pergunte-se o que mudou na situação do cliente e que efeito essa mudança costuma ter (por exemplo, verificações de segurança, permissões, dados que ficaram no aparelho antigo). Não a trate como fato.
2. **Evidências**: sinais concretos do relato. Em "signal", cite o trecho do ticket entre aspas. Indique quais hipóteses o sinal apoia e quais enfraquece. Só marque "weakens" quando o trecho realmente contradiz a hipótese.
3. **Informações faltantes**: apenas o que mudaria a conclusão ou o próximo passo, com o motivo. Inclua o que confirmaria ou descartaria cada hipótese "inferida".
4. **Conclusão provável**: a hipótese mais provável e a confiança. Se as evidências não bastarem, use confiança "baixa" e diga o que confirmaria a hipótese. Uma hipótese "inferida" nunca tem confiança "alta".

O diagnóstico é lido pelo atendente; "summary" deve poder ser repassado ao cliente seguindo as regras de comunicação.

Formato da resposta (JSON):
{
  "hypotheses": [{"id": "H1", "description": "...", "likelihood": "alta | média | baixa", "basis": "relato | inferida"}],
  "evidence": [{"signal": "\"trecho do ticket\"", "supports": ["H1"], "weakens": ["H2"]}],
  "missing_information": [{"item": "...", "why_it_matters": "..."}],
  "probable_conclusion": {"hypothesis_id": "H1", "summary": "...", "confidence": "alta | média | baixa", "how_to_confirm": "..."}
}

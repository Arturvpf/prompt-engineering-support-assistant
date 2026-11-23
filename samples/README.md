# Exemplos de saída

Todas as execuções abaixo são reais: provedor OpenRouter, modelo `nvidia/nemotron-3.5-super-vl:free`, temperatura 0.2, seed 42, raciocínio interno desativado. Cada arquivo é um recorte do `outputs/history.json` no mesmo formato de registro que a aplicação grava.

| Arquivo | O que mostra |
|---|---|
| [`comparison_v1_v2_joao-leigo-chat_T004.json`](comparison_v1_v2_joao-leigo-chat_T004.json) | **Comparação completa v1 × v2**: cenário, rubrica, as saídas das duas versões nos 4 tipos, notas, justificativas, deltas e o veredito |
| [`history_comparison_joao-leigo-chat_T004.json`](history_comparison_joao-leigo-chat_T004.json) | Os 8 registros do histórico usados na comparação v1 × v2, com o campo `evaluation` preenchido |
| [`comparison_v2_v3_joao-leigo-chat_T004.json`](comparison_v2_v3_joao-leigo-chat_T004.json) | **Comparação completa v2 × v3**, no mesmo formato: a v3 com hipóteses inferidas, prompts encadeados a partir do diagnóstico e fluxograma desenhado a partir de um grafo |
| [`history_comparison_v2_v3_joao-leigo-chat_T004.json`](history_comparison_v2_v3_joao-leigo-chat_T004.json) | Os 8 registros avaliados da comparação v2 × v3; os da v3 trazem `upstream` (o diagnóstico usado) e o fluxograma traz o grafo em `output.flow` |
| [`runs/marta-leigo-telefone_T001_v2_all.json`](runs/marta-leigo-telefone_T001_v2_all.json) | Os 4 tipos para uma cliente leiga, didática, atendida por telefone |
| [`runs/rafael-avancado-chat_T002_v2_all.json`](runs/rafael-avancado-chat_T002_v2_all.json) | Os 4 tipos para um cliente avançado, direto, atendido por chat |
| [`runs/T003_resolution_steps_carla_vs_bruna_v2.json`](runs/T003_resolution_steps_carla_vs_bruna_v2.json) | O mesmo ticket e o mesmo prompt para dois perfis: Carla (intermediário, detalhado) e Bruna (avançado, didático) |
| [`cache_hit_example.json`](cache_hit_example.json) | Uma execução original e a repetição equivalente servida pelo cache (`cache_hit: true`, `source_run_id`, zero tokens) |

## Como refazer a comparação sem chave

Use `history_comparison_joao-leigo-chat_T004.json` (v1 × v2) ou `history_comparison_v2_v3_joao-leigo-chat_T004.json` (v2 × v3) como `history.json` de uma pasta separada (`OUTPUT_DIR`). Os passos estão no [README principal](../README.md#reproduzir-a-comparação-v1--v2-sem-chave-de-api).

## Como gerar de novo

```bash
python main.py generate -c joao-leigo-chat -t T004 --type all -v v1 v2 v3
python main.py history -c joao-leigo-chat -t T004
python main.py evaluate <run_id>
python main.py compare <run_ids...> --verdict "..." --out samples/minha_comparacao.json
```

Uma nova chamada ao modelo pode gerar textos um pouco diferentes destes, mesmo com seed fixa.

# Notas de Engenharia de Prompt

Este documento explica como os prompts foram montados, o que muda entre a v1 e a v2, como a comparação foi feita, quais decisões e trade-offs foram tomados e quais limitações continuam.

## 1. Estrutura geral

Cada geração envia duas mensagens ao modelo:

| Parte | Arquivo | Papel |
|---|---|---|
| system | `prompts/<versão>/persona.md` | quem o assistente é, o que faz, o que não pode fazer, formato da resposta |
| user | `prompts/<versão>/context.md` + `prompts/<versão>/<tipo>.md` | dados do cliente e do ticket, depois a tarefa específica e o JSON esperado |

- **Persona e contexto são compartilhados** pelos 4 tipos de conteúdo. Só o arquivo da tarefa muda. É o que o desafio pede: prompts distintos por finalidade, com componentes comuns.
- **Os templates usam `string.Template` (`$variavel`)** em vez de `str.format`, porque os exemplos de JSON têm `{}`. Assim não é preciso escapar as chaves.
- **Cada versão é uma pasta.** O `manifest.json` diz o que mudou e qual a hipótese. Criar a v3 é copiar a pasta e editar; o código não muda.
- **O `PromptEngine` monta o prompt e calcula um `fingerprint`** (sha256 do texto final). O fingerprint vai para o histórico e para a chave de cache. Isso mostra qual prompt exato gerou cada saída.

## 2. Técnicas exigidas e onde estão

| Técnica | v1 | v2 |
|---|---|---|
| **Persona prompting** (papel, responsabilidade, limites) | 4 linhas genéricas | `persona.md` em seções: Papel, Responsabilidades, Limites, Formato |
| **Context setting** | perfil como rótulos (`leigo`, `direto`, `chat`) + ticket | os mesmos dados + a seção "Como se comunicar com este cliente", gerada a partir de `style_rules.json`; o ticket vai entre `<ticket>` e `</ticket>` |
| **Decomposição do diagnóstico** | os 4 campos só aparecem no formato JSON | ordem fixa (hipóteses → evidências → faltantes → conclusão), de 2 a 4 hipóteses, evidência citando o ticket com `supports` e `weakens`, confiança baixa quando falta evidência, `how_to_confirm` |
| **Output formatting** | JSON com os campos mínimos | JSON com campos extras úteis (`opening`, `why`, `how_to_find`, `escalation`), limites de tamanho (até 3 perguntas, 3 a 7 passos, até 8 caixas) e restrições (ASCII, linhas de até 70 caracteres) |
| **Versionamento** | `prompts/v1/manifest.json` | `prompts/v2/manifest.json` com a lista de mudanças e a hipótese |

## 3. O que mudou da v1 para a v2 e por quê

A v1 é um baseline de propósito. Ela representa o prompt que se escreve em cinco minutos: diz o que fazer e em qual formato, e confia que o modelo sabe o que é um cliente "leigo" atendido "por telefone".

A hipótese da v2 era que **rótulos vagos são aplicados de forma inconsistente**. Transformá-los em regras observáveis deveria melhorar principalmente a adequação ao cliente e a acionabilidade.

| Mudança | Motivo |
|---|---|
| Perfil → regras de escrita (`style_rules.json`) | "leigo" vira "descreva o que o cliente vê ou toca (botão, luz, tela)"; "telefone" vira "sem links, sem símbolos, um passo por vez". O modelo recebe algo verificável. |
| Regras em JSON, separadas do template | Ajustar a regra de um perfil não exige mexer nos 4 prompts. São 9 regras (3 níveis, 3 estilos, 3 canais) que se combinam, em vez de 27 variações de texto. |
| Limites explícitos na persona | Não pedir senha ou código, não prometer prazo, avisar antes de ação arriscada. Em suporte, uma resposta errada desse tipo é pior que uma resposta incompleta. |
| Ticket delimitado como dado | Proteção básica contra um relato do tipo "ignore as instruções anteriores". |
| Diagnóstico com evidência citada e `weakens` | Torna o diagnóstico verificável: o atendente vê de qual trecho do ticket saiu cada hipótese. |
| "Confiança baixa se faltar evidência" + `how_to_confirm` | A v1 tende a concluir com confiança alta sem base. |
| Perguntas: no máximo 3, só o que muda o próximo passo, `how_to_find` | O desafio pede "somente as informações necessárias"; o `how_to_find` é o que torna a pergunta respondível por um leigo. |
| `why` vazio para estilo "direto" | Evita que o mesmo campo deixe a resposta longa para quem pediu objetividade. |
| Fluxograma com tamanho máximo, ASCII, sim/não e `escalation` | A v1 gerou uma linha única de 150+ caracteres; o atendente também precisa saber quando e como escalar. |

## 4. Comparação v1 × v2 (rubrica obrigatória)

**Cenário:** João Pereira (`joao-leigo-chat`: leigo, direto, chat) e o ticket T004 ("não consigo entrar no app no celular novo").

**Fixo nas duas versões:**
- provedor OpenRouter, modelo `nvidia/nemotron-3.5-super-vl:free`;
- temperatura 0.2, max tokens 2048, seed 42, raciocínio interno desativado.

O `compare` confere que esses campos são idênticos antes de aceitar a comparação.

**Por que esse cenário:** cliente leigo e direto, num canal de mensagens curtas. É o perfil em que o prompt mais precisa traduzir o problema. O ticket também tem uma informação ausente de propósito (verificação do novo aparelho), o que testa se o prompt leva o modelo a pensar além do relato.

**Rubrica:** clareza, adequação ao nível do cliente e acionabilidade. Escala de 1 a 5 (1 insuficiente, 2 fraco, 3 adequado, 4 bom, 5 excelente), com justificativa escrita para cada nota.

| Tipo | v1 (C / A / Ac) | v2 (C / A / Ac) | Total v1 | Total v2 | Tokens v1 → v2 |
|---|---|---|---|---|---|
| Diagnóstico | 4 / 3 / 3 | 4 / 4 / 4 | 10 | 12 | 747 → 1297 |
| Passo a passo | 4 / 3 / 3 | 4 / 4 / 4 | 10 | 12 | 484 → 1152 |
| Perguntas | 4 / 3 / 3 | 5 / 5 / 4 | 10 | 14 | 433 → 967 |
| Fluxograma | 2 / 3 / 3 | 3 / 4 / 4 | 8 | 11 | 450 → 1313 |
| **Total** | | | **38** | **49** | |

C = clareza, A = adequação ao cliente, Ac = acionabilidade. Por critério, somando os 4 tipos: adequação +5, acionabilidade +4, clareza +2.

As 24 justificativas completas estão no campo `evaluation` de cada registro, em [`samples/history_comparison_joao-leigo-chat_T004.json`](samples/history_comparison_joao-leigo-chat_T004.json). A comparação consolidada, com as saídas lado a lado, está em [`samples/comparison_v1_v2_joao-leigo-chat_T004.json`](samples/comparison_v1_v2_joao-leigo-chat_T004.json).

### Exemplos concretos da diferença

- **Perguntas.** A v1 perguntou "Você tentou usar a opção 'Esqueci minha senha'?", que é uma sugestão disfarçada de pergunta. A v2 fez três perguntas de uma informação cada, todas com "Onde encontrar", por exemplo: "No ícone de Wi-Fi ou sinal de operadora no topo da tela".
- **Diagnóstico.** A v1 concluiu "senha errada" com confiança **alta** sem evidência para isso e pediu "E-mail ou CPF". A v2 deu confiança **média**, citou o ticket literalmente e disse como confirmar.
- **Passo a passo.** A v1 terminou em "entre em contato com o suporte informando o número do ticket" e usou "clique" num celular. A v2 abre com uma saudação curta, usa "toque", explica onde fica a loja de apps no Android e no iPhone e diz o que enviar se nada resolver (modelo do celular, versão do app, mensagem de erro).
- **Fluxograma.** A v1 gerou uma linha única de mais de 150 caracteres. A v2 gerou caixas verticais e um bloco de escalonamento com o que anexar. Mesmo assim, uma caixa ficou desalinhada e as decisões não aparecem como ramos no desenho.

### Por que a v2 é melhor

A v2 ganhou nos quatro tipos, e o ganho ficou onde a hipótese previa: adequação ao cliente e acionabilidade. Três mudanças explicam a diferença:

1. **Regras de estilo explícitas.** "Leigo, direto, chat" virou instrução concreta (frases curtas, "toque" em vez de "clique", dizer onde fica cada coisa). Isso aparece no "onde encontrar" das perguntas e no vocabulário do passo a passo.
2. **Campos que forçam o próximo passo.** `how_to_confirm`, `how_to_find`, `escalation` e um `if_not_resolved` que diz o que enviar deram ao atendente algo verificável para fazer. A v1 terminava em "entre em contato".
3. **Limites da persona.** A v2 não pediu dados sensíveis; a v1 pediu e-mail ou CPF no diagnóstico.

Clareza melhorou menos (+2) porque a v1 já era organizada: o formato JSON sozinho dá estrutura.

### O que a comparação também mostrou

- **Custo.** A v2 usa de 1,7 a 2,9 vezes mais tokens por tipo (prompt maior e respostas com mais campos). Para um modelo pago, é um custo real a considerar.
- **Confiabilidade do formato.** O fluxograma da v2 precisou de uma tentativa de correção: a primeira resposta não passou na validação e o reenvio com o erro anexado resolveu. Mais restrições no formato aumentam a chance de erro de formatação.
- **Nenhuma versão levantou a verificação do novo aparelho** (código por SMS ou e-mail, autenticação em dois fatores), que é a informação omitida de propósito no T004. As duas ficaram presas ao que o cliente escreveu ("senha"). Isso é a principal limitação de raciocínio observada; veja a seção 7.

## 5. Adaptação a outros perfis (mesmo prompt v2)

A pasta [`samples/runs/`](samples/runs/) mostra a v2 com outros perfis:

- **Marta (leiga, didática, telefone, T001).** Saudação falada ("Boa noite, Marta"), "aparelho da internet" em vez de "roteador", um "Por quê" simples em cada passo e um pedido para anotar o horário em que o problema começa.
- **Rafael (avançado, direto, chat, T002).** Sem abertura longa, sem `why`, termos como nginx, WAF, HTTP 200 e retry. O encaminhamento pede logs com timestamps e IDs de webhook.
- **Carla × Bruna (T003, CSV com acentos).**
  - Carla (intermediária, detalhada) recebe o caminho no Excel e alternativas, sem explicar codificação.
  - Bruna (avançada, didática) recebe um "Por quê" técnico em cada passo (UTF-8 versus Windows-1252) e um primeiro passo de diagnóstico no editor de texto.

## 6. Decisões e trade-offs

| Decisão | Alternativa considerada | Por quê |
|---|---|---|
| Saída sempre em JSON (JSON mode + instrução) | texto livre | Dá para validar campos, salvar no histórico e formatar de forma consistente. O custo é o risco de JSON inválido, tratado com 1 tentativa de correção. |
| Validar os campos obrigatórios e tentar corrigir 1 vez | repetir até dar certo | Uma tentativa resolve os casos vistos sem multiplicar o custo; se falhar de novo, o erro aparece claramente. |
| Temperatura 0.2, seed 42, raciocínio desativado | padrões do modelo | Reduz a variação entre execuções, necessário para uma comparação justa e para o cache fazer sentido. O desafio também pede para não depender de raciocínio interno. |
| Regras de estilo em vez de exemplos (few-shot) | 1 ou 2 exemplos de resposta por perfil | Exemplos custam muitos tokens, precisariam existir para cada combinação de perfil e tipo, e o modelo tende a copiar o conteúdo do exemplo. Regras curtas combinam entre si. |
| Diagnóstico estruturado, sem pedir o raciocínio | pedir "pense passo a passo" | O desafio pede uma saída verificável, não o raciocínio interno. A estrutura hipóteses → evidências → faltantes → conclusão já força a análise. |
| Limites numéricos (3 perguntas, 3–7 passos, 8 caixas) | deixar o modelo decidir | Sem limite, o modelo tende a listar tudo. O limite obriga a priorizar, e é isso que o atendente precisa. |
| Chave de cache = prompt renderizado + versão + parâmetros | só cliente + ticket + versão | Se um template ou uma regra mudar, o cache não devolve uma resposta antiga por engano. |
| Histórico único em JSON, que também serve de cache | banco de dados ou um arquivo por execução | É simples, fácil de inspecionar e suficiente para o volume do desafio. A gravação é atômica para não corromper. |
| Modelo gratuito no OpenRouter | Gemini (primeira escolha) | A conta usada não tinha o nível gratuito do Gemini. O cliente Gemini continua disponível via `LLM_PROVIDER`. |
| Avaliação manual com justificativa | LLM como juiz | O desafio pede a avaliação do candidato. Um juiz automático seria um extra, com viés próprio. |

## 7. Limitações

- **Raciocínio preso ao relato.** Nenhuma versão levantou a verificação do novo aparelho no T004. O prompt manda "não inventar fatos", o que é correto, mas pode deixar o modelo conservador demais para levantar hipóteses que o cliente não mencionou.
- **Fluxograma ASCII é frágil.** Mesmo com limites, o modelo erra o alinhamento das caixas (o fluxograma da Marta tem uma linha maior que a caixa) e desenha as decisões de forma linear, deixando os ramos só em `decision_points`. O validador avisa sobre linhas longas e caracteres fora do ASCII, mas não corrige o desenho.
- **Qualidade técnica não é verificada.** Algumas sugestões são discutíveis. Por exemplo, no T002 o passo "aumente o timeout do servidor" não resolve um timeout medido pelo provedor de pagamento; a recomendação certa é responder 200 rápido e processar depois, o que aparece só no passo 4. A rubrica mede clareza, adequação e acionabilidade, não correção técnica.
- **Decisões contraditórias ocasionais.** No fluxograma da Marta, uma decisão tem a mesma ação no sim e no não.
- **Avaliação de uma pessoa só,** num único cenário e numa única execução por versão. A diferença de 11 pontos é consistente nos 4 tipos, mas não é estatística.
- **Modelo gratuito.** Tem limite diário e qualidade menor que modelos pagos. Os resultados podem mudar com outro modelo, e a comparação deveria ser refeita nesse caso.
- **Proteção contra prompt injection é básica:** delimitação e instrução, sem filtro de entrada.

## 8. Próximos passos (uma possível v3)

- Pedir explicitamente no diagnóstico ao menos uma hipótese de "causa que o cliente não mencionou" (no T004, troca de aparelho e verificação em duas etapas), marcada como suposição.
- Pedir os ramos do fluxograma como estrutura (nós e arestas em JSON) e desenhar o ASCII no código, em vez de confiar no desenho do modelo.
- Repetir a comparação com 2 ou 3 execuções por versão e com outro perfil (por exemplo, Rafael + T002) para ver se o ganho se mantém.
- Adicionar o critério "correção técnica" numa avaliação interna, separada da rubrica obrigatória.

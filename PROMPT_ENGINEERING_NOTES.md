# Notas de Engenharia de Prompt

Este documento explica como os prompts foram montados, o que muda entre as versões, como as comparações foram feitas, quais decisões e trade-offs foram tomados e quais limitações continuam.

São três versões, cada uma guiada pelo que a comparação anterior mostrou:

| Versão | Ideia | Comparação | Resultado |
|---|---|---|---|
| v1 | baseline: o prompt que se escreve em cinco minutos | — | — |
| v2 | perfil traduzido em regras de escrita, persona com limites, saídas com limites e campos de próximo passo | v1 × v2 (seção 4) | 38 → 49 |
| v3 | hipóteses além do relato, prompts encadeados a partir do diagnóstico, fluxograma pedido como grafo e desenhado pelo código | v2 × v3 (seção 5) | 49 → 51 |

A versão padrão da aplicação é a v3.

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
- **Encadeamento declarado no manifest (v3).** `"depends_on": {"resolution_steps": ["diagnosis"], ...}` faz o motor exigir a saída do diagnóstico e colocar um resumo dela (hipóteses, o que falta, conclusão) em `$diagnosis_context`. O serviço pega esse diagnóstico da mesma rodada, do cache ou, se não houver, gera antes. O registro guarda o `run_id` do diagnóstico usado em `upstream`, e como o resumo entra no prompt, outro diagnóstico gera outra chave de cache.
- **Fluxograma desenhado pelo código (v3).** O modelo devolve um grafo (`flow.nodes`, com nós `start`, `action`, `decision` e `end`). O módulo `flowchart.py` valida o grafo e desenha o ASCII e os `decision_points`. Um grafo quebrado volta ao modelo com o erro, como qualquer erro de formato.

## 2. Técnicas exigidas e onde estão

| Técnica | v1 | v2 | v3 |
|---|---|---|---|
| **Persona prompting** (papel, responsabilidade, limites) | 4 linhas genéricas | `persona.md` em seções: Papel, Responsabilidades, Limites, Formato | + pode levantar causas não mencionadas, sempre como suposição; limites mais precisos (perguntar se um código chegou, nunca qual é; nada de CPF nem no encaminhamento) |
| **Context setting** | perfil como rótulos (`leigo`, `direto`, `chat`) + ticket | os mesmos dados + a seção "Como se comunicar com este cliente", gerada a partir de `style_rules.json`; o ticket vai entre `<ticket>` e `</ticket>` | + o resumo do diagnóstico entra no contexto das outras 3 tarefas (encadeamento) |
| **Decomposição do diagnóstico** | os 4 campos só aparecem no formato JSON | ordem fixa (hipóteses → evidências → faltantes → conclusão), de 2 a 4 hipóteses, evidência citando o ticket com `supports` e `weakens`, confiança baixa quando falta evidência, `how_to_confirm` | + `basis` (relato ou inferida), pelo menos uma hipótese inferida a partir do que mudou, inferida nunca com confiança alta |
| **Output formatting** | JSON com os campos mínimos | JSON com campos extras úteis (`opening`, `why`, `how_to_find`, `escalation`), limites de tamanho (até 3 perguntas, 3 a 7 passos, até 8 caixas) e restrições (ASCII, linhas de até 70 caracteres) | + fluxograma como grafo tipado; o desenho sai do código, não do modelo |
| **Versionamento** | `prompts/v1/manifest.json` | `prompts/v2/manifest.json` com a lista de mudanças e a hipótese | + `based_on`, `depends_on` e `evidence` (de qual comparação veio cada mudança) |
| **Encadeamento de prompts** | — | — | diagnóstico → passo a passo, perguntas e fluxograma |

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
- **Nenhuma versão levantou a verificação do novo aparelho** (código por SMS ou e-mail, autenticação em dois fatores), que é a informação omitida de propósito no T004. As duas ficaram presas ao que o cliente escreveu ("senha"). Foi o ponto de partida da v3 (seção 5).

## 5. Da v2 para a v3 (rubrica obrigatória)

### De onde veio cada mudança

A v3 não é uma reescrita: cada mudança responde a um problema visto na comparação v1 × v2. O `manifest.json` da v3 registra isso no campo `evidence`.

| Problema observado na v2 | Mudança na v3 |
|---|---|
| Nenhuma hipótese sobre o aparelho novo; o modelo ficou preso à palavra "senha" | Diagnóstico com `basis` e pelo menos uma hipótese **inferida** ("o que mudou na situação do cliente e que efeito isso costuma ter"), sempre como suposição e nunca com confiança alta |
| Os 4 tipos não conversavam: cada um era gerado sem ver os outros | **Encadeamento:** passo a passo, perguntas e fluxograma recebem o resumo do diagnóstico |
| Pergunta sobre internet, que o relato já descartava | Cada pergunta deve separar hipóteses; `reason` diz o que a resposta confirma ou descarta |
| Passo genérico (reiniciar o celular) antes dos passos ligados à causa | Ordem por risco: verificação sem risco → ação reversível → ação destrutiva com aviso; sem passos genéricos |
| Caixas desalinhadas, decisões desenhadas em linha reta, "Escalate" em inglês | Modelo devolve um **grafo**; o código valida e desenha; texto todo em português |

### A iteração dentro da v3

A primeira versão da v3 ainda não encadeava os prompts. O diagnóstico levantou "bloqueio de segurança por aparelho novo", mas o passo a passo e o fluxograma não usaram a hipótese, porque não a viam. O fluxograma também tinha erros de lógica ("Está conectado à internet? não → RESOLVIDO"). Isso levou a duas mudanças: o encadeamento e as regras de lógica do fluxograma ("só se chega a RESOLVIDO depois de confirmar que o problema acabou", "não pergunte se algo foi feito para pedir que seja feito de novo").

A segunda rodada mostrou mais dois problemas, e os dois viraram regra:
- **O encaminhamento pedia "seu CPF".** A persona agora diz que documentos pessoais não são pedidos nem no encaminhamento, porque o atendente já tem o cadastro.
- **Uma decisão levava à mesma ação nos dois ramos.** O validador do grafo passou a tratar isso como erro, e a tentativa de correção resolveu na rodada final.

As execuções avaliadas abaixo são da rodada final.

### Resultado

Mesmo cenário e configuração da seção 4 (João + T004, mesmo modelo, temperatura 0.2, seed 42).

| Tipo | v2 (C / A / Ac) | v3 (C / A / Ac) | Total v2 | Total v3 | Tokens v2 → v3 |
|---|---|---|---|---|---|
| Diagnóstico | 4 / 4 / 4 | 4 / 4 / 5 | 12 | 13 | 1297 → 1668 |
| Passo a passo | 4 / 4 / 4 | 3 / 4 / 4 | 12 | 11 | 1152 → 1612 |
| Perguntas | 5 / 5 / 4 | 5 / 4 / 5 | 14 | 14 | 967 → 1355 |
| Fluxograma | 3 / 4 / 4 | 5 / 4 / 4 | 11 | 13 | 1313 → 1752 |
| **Total** | | | **49** | **51** | |

Por critério, somando os 4 tipos: acionabilidade +2, clareza +1, adequação ao cliente −1. A comparação consolidada está em [`samples/comparison_v2_v3_joao-leigo-chat_T004.json`](samples/comparison_v2_v3_joao-leigo-chat_T004.json) e os 8 registros avaliados em [`samples/history_comparison_v2_v3_joao-leigo-chat_T004.json`](samples/history_comparison_v2_v3_joao-leigo-chat_T004.json).

### O que melhorou

- **O alvo foi atingido no diagnóstico e nas perguntas.** O diagnóstico levantou o bloqueio por aparelho novo como hipótese inferida e pediu exatamente o que a confirma: aviso de login novo e teste em outro aparelho. As três perguntas passaram a separar hipóteses: mensagem exata, aviso de login novo e acesso por outro aparelho.
- **O fluxograma deixou de ter erro de desenho.** Caixas alinhadas, ramos visíveis e a lista de decisões idêntica ao desenho, por construção. O mesmo grafo que gera o desenho passa por uma validação (nó solto, ligação quebrada, laço sem saída, decisão sem efeito), algo impossível de fazer sobre um desenho em texto.

### O que piorou ou não mudou

- **Passo a passo (−1).** Repetiu a reinstalação nos passos 4 e 5 e pôs a verificação de aparelho novo depois de redefinir a senha. O validador agora avisa sobre passos repetidos.
- **Fluxograma.** Mesmo recebendo o diagnóstico, não incluiu a verificação de aparelho novo. O encadeamento dá o contexto, mas não obriga o modelo a usá-lo.
- **Adequação (−1 nas perguntas).** Uma pergunta pede ao cliente leigo um teste trabalhoso (entrar por outro aparelho ou pelo site).
- **Custo.** De 29% a 40% mais tokens por tipo que a v2, e o diagnóstico vira uma dependência dos outros 3 tipos.

### Leitura honesta

A diferença é pequena (+2) e vem de uma execução por versão com um modelo gratuito que varia bastante. A rodada intermediária, com outro diagnóstico, teve outros acertos e erros. O que se sustenta em todas as rodadas da v3 é:
- o diagnóstico sempre levantou uma hipótese inferida sobre o aparelho novo (a v1 e a v2 nunca levantaram);
- o fluxograma nunca mais teve erro de desenho.

O resto oscila. Por isso a v3 virou padrão pelos ganhos estruturais (hipótese inferida, encadeamento, grafo validado), não pelos 2 pontos.

## 6. Adaptação a outros perfis (mesmo prompt v2)

A pasta [`samples/runs/`](samples/runs/) mostra a v2 com outros perfis:

- **Marta (leiga, didática, telefone, T001).** Saudação falada ("Boa noite, Marta"), "aparelho da internet" em vez de "roteador", um "Por quê" simples em cada passo e um pedido para anotar o horário em que o problema começa.
- **Rafael (avançado, direto, chat, T002).** Sem abertura longa, sem `why`, termos como nginx, WAF, HTTP 200 e retry. O encaminhamento pede logs com timestamps e IDs de webhook.
- **Carla × Bruna (T003, CSV com acentos).**
  - Carla (intermediária, detalhada) recebe o caminho no Excel e alternativas, sem explicar codificação.
  - Bruna (avançada, didática) recebe um "Por quê" técnico em cada passo (UTF-8 versus Windows-1252) e um primeiro passo de diagnóstico no editor de texto.

## 7. Decisões e trade-offs

| Decisão | Alternativa considerada | Por quê |
|---|---|---|
| Saída sempre em JSON (JSON mode + instrução) | texto livre | Dá para validar campos, salvar no histórico e formatar de forma consistente. O custo é o risco de JSON inválido, tratado com 1 tentativa de correção. |
| Validar os campos obrigatórios e tentar corrigir 1 vez | repetir até dar certo | Uma tentativa resolve os casos vistos sem multiplicar o custo; se falhar de novo, o erro aparece claramente. |
| JSON Schema por tipo (`schemas/`), separado do prompt | validar só no código | O schema é o contrato da saída: tipos, campos obrigatórios e valores permitidos (`alta/média/baixa`). Os campos da v2 são opcionais, então o mesmo schema valida as duas versões. Os erros voltam ao modelo em português, na tentativa de correção. Incoerências (conclusão apontando para uma hipótese inexistente, decisão com a mesma ação no sim e no não) viram avisos, não erros. |
| Temperatura 0.2, seed 42, raciocínio desativado | padrões do modelo | Reduz a variação entre execuções, necessário para uma comparação justa e para o cache fazer sentido. O desafio também pede para não depender de raciocínio interno. |
| Regras de estilo em vez de exemplos (few-shot) | 1 ou 2 exemplos de resposta por perfil | Exemplos custam muitos tokens, precisariam existir para cada combinação de perfil e tipo, e o modelo tende a copiar o conteúdo do exemplo. Regras curtas combinam entre si. |
| Diagnóstico estruturado, sem pedir o raciocínio | pedir "pense passo a passo" | O desafio pede uma saída verificável, não o raciocínio interno. A estrutura hipóteses → evidências → faltantes → conclusão já força a análise. |
| Limites numéricos (3 perguntas, 3–7 passos, 8 caixas) | deixar o modelo decidir | Sem limite, o modelo tende a listar tudo. O limite obriga a priorizar, e é isso que o atendente precisa. |
| Chave de cache = prompt renderizado + versão + parâmetros | só cliente + ticket + versão | Se um template ou uma regra mudar, o cache não devolve uma resposta antiga por engano. |
| Histórico único em JSON, que também serve de cache | banco de dados ou um arquivo por execução | É simples, fácil de inspecionar e suficiente para o volume do desafio. A gravação é atômica para não corromper. |
| Modelo gratuito no OpenRouter | Gemini (primeira escolha) | A conta usada não tinha o nível gratuito do Gemini. O cliente Gemini continua disponível via `LLM_PROVIDER`. |
| Avaliação manual com justificativa | LLM como juiz | O desafio pede a avaliação do candidato. Um juiz automático seria um extra, com viés próprio. |
| Fluxograma como grafo, desenhado pelo código (v3) | pedir o ASCII ao modelo, com mais regras | Modelos de linguagem erram alinhamento e contagem de caracteres; desenhar é trabalho determinístico. O grafo também pode ser validado (alcançabilidade, laços sem saída, decisões sem efeito). O custo é um formato a mais para o modelo seguir. |
| Encadear a partir do diagnóstico (v3) | um único prompt que gera os 4 tipos de uma vez | Um prompt único deixaria uma saída enorme e um erro de formato perderia tudo. Encadear mantém 4 prompts focados e reaproveita o diagnóstico do cache. O custo é a dependência: sem diagnóstico, os outros tipos não rodam (o serviço gera antes). |
| Hipótese inferida marcada como suposição (v3) | proibir qualquer coisa fora do relato | "Não invente fatos" deixava o modelo preso às palavras do cliente. Permitir a suposição, com a marca e a forma de confirmar, mantém o diagnóstico verificável. |

## 8. Limitações

- **Raciocínio preso ao relato, em parte resolvido.** A v3 levanta a hipótese do aparelho novo no diagnóstico, mas o passo a passo e o fluxograma nem sempre a usam, mesmo recebendo o diagnóstico.
- **Fluxograma.** Na v1 e na v2, o modelo errava o alinhamento das caixas e desenhava as decisões em linha reta. Na v3 o desenho sai do código e esse problema acabou. O que continua é a qualidade do roteiro: o grafo é validado quanto à estrutura, não quanto à lógica do atendimento.
- **Qualidade técnica não é verificada.** Algumas sugestões são discutíveis. Por exemplo, no T002 o passo "aumente o timeout do servidor" não resolve um timeout medido pelo provedor de pagamento; a recomendação certa é responder 200 rápido e processar depois, o que aparece só no passo 4. A rubrica mede clareza, adequação e acionabilidade, não correção técnica.
- **Decisões contraditórias ocasionais.** No fluxograma da Marta, uma decisão tem a mesma ação no sim e no não. O validador agora emite um aviso nesse caso, mas não força o modelo a corrigir.
- **Avaliação de uma pessoa só,** num único cenário e numa única execução por versão. A diferença de 11 pontos da v1 para a v2 é consistente nos 4 tipos; a de 2 pontos da v2 para a v3 não é. Nenhuma das duas é estatística.
- **Modelo gratuito.** Tem limite diário e qualidade menor que modelos pagos. Os resultados podem mudar com outro modelo, e a comparação deveria ser refeita nesse caso.
- **Proteção contra prompt injection é básica:** delimitação e instrução, sem filtro de entrada.

## 9. Próximos passos (uma possível v4)

Duas ideias da lista anterior viraram a v3: a hipótese inferida e o fluxograma como grafo. Para uma v4:
- **Cobertura obrigatória.** Pedir que cada hipótese do diagnóstico apareça em pelo menos um passo e num nó do fluxograma, e verificar isso no código (as hipóteses têm id; os passos e nós podem citar o id num campo interno que não aparece ao cliente).
- **Passos repetidos como erro**, não aviso, para acionar a correção automática, como já acontece com as decisões sem efeito no fluxograma.
- **Repetir a comparação** com 3 execuções por versão (usando `--no-cache`) e com outro perfil (por exemplo, Rafael + T002), para separar o efeito do prompt da variação do modelo.
- **Avaliar correção técnica** numa avaliação interna, separada da rubrica obrigatória.

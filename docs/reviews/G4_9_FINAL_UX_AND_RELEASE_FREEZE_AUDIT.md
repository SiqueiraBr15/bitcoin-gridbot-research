# G4.9 — Final UX repair and release freeze audit

Data: 27/10/2026. Escopo: revisão local final do Research Lab, exclusivamente PAPER/offline e dados sintéticos. Autor: executor técnico Codex; a decisão de publicação pertence ao orquestrador. Resultado: candidata local apta à revisão independente, sem publicação. Não constitui prontidão para trading real nem certificação universal de desempenho ou segurança.

Área de evidências desta fase: `C:/dev/github-portfolio-2026/audit/g4_9`. Os nomes de artefatos abaixo são relativos a essa área. Resultados anteriores são explicitamente históricos. A execução usa cópias Git isoladas e instalação wheel; não usa dados financeiros privados. Os arquivos públicos deste relatório e do changelog não incluem logs brutos, caminhos pessoais ou caches.

## 1. Estado inicial

Baseline verificada em `evidence/BASELINE.json`: checkout público na G4.8, HEAD `2e5346de4865be3c4ab6a60c336abbc67181133e`, branch `fix/g4-8-final-quality-and-ux`, árvore rastreada limpa e quatro relatórios históricos não rastreados preservados. G4.8 executável certificado: `f75bef168f9f7dba077f91870460a55f27a6b972`. A ancestralidade desde o head remoto informado foi comprovada.

Foram lidos integralmente o relatório e changelog G4.8, validado o CRC e conteúdo JSON de `G4_8_AUDIT_HANDOFF.zip`, e consultados os achados G4.7 e a auditoria G4.6. Os hashes desses documentos constam da baseline e foram reconferidos no encerramento. Nenhuma evidência histórica foi sobrescrita.

Leituras GitHub GET iniciais e finais confirmaram PR #2 aberto, não mesclado, head `bff062beea10bd0ccc614e852797b643aa887497`; main remota `88390ac0b3726c50b548e5087acfa39982d76342`. Main local permanece `a28e6f35b7b0acb42cee6dc97959cdf65f6022b0`. Estas referências diferentes são registradas, sem sincronização ou alteração de main. Actions permanece desativado; zero checks, statuses, reviews, tags e releases observados. Ausência de checks remotos não significa CI aprovada.

## 2. Branch

Criada e utilizada somente `fix/g4-9-final-ux-and-release-freeze`, derivada do HEAD final G4.8. Nenhum reset, rebase, exclusão de branch ou alteração de histórico anterior. As branches G4.6 e G4.8 e a main foram preservadas. Não houve push, merge, edição/comentário de PR, ativação de Actions, tag ou release.

## 3. HEAD de origem

Origem exata: `2e5346de4865be3c4ab6a60c336abbc67181133e`. Seu pai é o executável G4.8 certificado. O reparo executável G4.9 foi congelado em `cf1e9c9aba3072bbef80956852bc115e4b1b34b9`, antes das regressões finais e holdouts novos. Nenhuma alteração executável posterior ao congelamento foi permitida.

## 4. Equivalência f75bef → 2e5346d

`evidence/GATE_A_EQUIVALENCE.json` compara todos os blobs Git: os dois únicos arquivos adicionais são o relatório e o changelog G4.8. Cada blob preexistente é idêntico: Python, JS, CSS, HTML, contratos, testes, fixtures, dependências, scripts e configuração de coverage/build.

Também foi inspecionado `pyproject.toml`: versão estática, README principal como metadado; pacotes `src/gridbot`, `research_console`, `examples`; apenas `docs/G4_EVIDENCE_PACK_V1.md` e `docs/G4_RESEARCH_LAB.md` entram por force-include. Não há hook de build dependente dos novos relatórios. Portanto, a conclusão não decorre apenas da extensão Markdown. A comparação posterior dos wheels confirmou identidade de todos os payloads anteriores, exceto o CSS deliberadamente corrigido e seu RECORD. Equivalência de conteúdo não é uma nova medição global.

## 5. Problema G48-P3-004

Reprodução real no navegador sobre a baseline, antes do reparo: IDs contínuos excediam labels e legendas. Com IDs legítimos de 64/80 caracteres, o documento chegou a 522 px para áreas úteis de 305/360 px nas telas 320/375. A fixture histórica também reproduziu overflow; as medições DOM são mais precisas que uma captura isolada.

Título legítimo de 240 caracteres sem espaços revelou a mesma causa em heading e botão da biblioteca: documento de 2.494 px em área útil de 305 px. A navegação por teclado revelou ainda o readout do gráfico: span de aproximadamente 484 px em área de 253 px, documento de 520 px. Esses caminhos foram incluídos no mesmo reparo antes do congelamento.

Evidências: `BEFORE_ORIGINAL.json`, `BEFORE_MAX_IDS.json`, `BEFORE_TITLE.json`, `KEYBOARD_READOUT_BEFORE.json` e capturas `before-*`. As tabelas mantêm rolagem horizontal local intencional para preservar evidência exata; não são tratadas como defeito de overflow global. O Pareto é gráfico e tabela analítica, sem alteração de cálculos.

## 6. Causa raiz

Conteúdo de tamanho intrínseco, em elementos flex/grid e inline, sem oportunidade suficiente de quebra em strings contínuas e sem restrição de largura nos componentes afetados. O readout só expõe sua extensão quando uma marca é consultada. Não houve defeito de identidade, serialização ou geração financeira. Não foi necessário alterar JavaScript ou Python.

## 7. Correção

Uma regra de 11 linhas em `research_console/static/style.css`, restrita a seis seletores do Research Lab: labels dos controles, textos das legendas, spans do readout, headings h2/h3 dos painéis e botões de estudos. Usa `min-width: 0`, `max-width: 100%` e `overflow-wrap: anywhere`.

Não há diminuição de fonte, ellipsis, ocultação de identificadores, nova interpolação HTML, transformação de ID, alteração de hash/schema ou regra global indiscriminada. Tabelas conservam seu contêiner de rolagem local. Adicionados dois testes Node estruturais permanentes em `tests/console/long_identifier_layout.test.cjs`; a prova de geometria vem do navegador, além desses testes.

## 8. Testes em 320/375 px

Wheel recém-construído e instalado, análise efetivamente concluída, quatro contas e cursor de teclado ativos: documento `clientWidth == scrollWidth`, respectivamente 305 e 360 px. Labels e legendas quebram e mantêm seus textos completos. Os quatro IDs têm 16, 64, 80 e 80 caracteres; os últimos compartilham os primeiros 79 e diferem em A/B.

Holdout criado depois de congelar a candidata: dois outros IDs de 80 caracteres com prefixos iguais e título Unicode de 240 codepoints. Ambos permanecem distinguíveis e o risco continua explícito. Capturas finais focadas `captures/wheel-final-identities-320.png` e `wheel-final-identities-375.png` mostram os sufixos A/B, controles e rolagem somente nas tabelas. `WHEEL_FINAL_SCREEN_GEOMETRY.json` confirma 320/305/305 e labels dentro da largura.

## 9. Validação em outras resoluções

Matriz completa do wheel em 320, 375, 390, 768, 1366 e 1920 px: biblioteca, controles, análise/comparador, Pareto, risco e marcas; documentos úteis 305, 360, 375, 753, 1351 e 1905 px, sem excesso global. O readout foi ativado pelo teclado, evitando aprovar um componente ainda vazio.

`WHEEL_NATIVE_MATRIX.json` cobre também 24 estados, quatro painéis nativos (patrimônio/BTC/risco/PAPER) × seis resoluções, com duas contas reais da demonstração sintética. `WHEEL_IDENTIFIER_MATRIX.json` cobre os IDs máximos; `WHEEL_HOLDOUT_MATRIX.json` cobre a entrada nova em 320/375/390/1366. Replay e export foram acionados no navegador; grants e persistência foram revistos em navegação e novo processo.

Capturas preliminares de desenvolvimento feitas durante importação não foram aceitas como prova de análise pronta (`PRELIMINARY_BROWSER_CAPTURE_SCOPE.json`). Algumas capturas de holdout mostram escala/posição anterior ao redesenho; a geometria confirmada e as capturas finais focadas substituem essas imagens como prova visual móvel. Nenhum teste inconclusivo foi convertido em PASS.

## 10. Preservação dos IDs completos

Contrato existente: identificadores ASCII, primeiro caractere alfanumérico, demais alfanuméricos/underscore/ponto/hífen, máximo 80. IDs de 81/128/256, Unicode, espaços e HTML são rejeitados; não se ampliou schema para forçar aceitação. Títulos admitem Unicode até 240 codepoints, respeitando as restrições existentes de caracteres/controle.

Backend, estado, labels acessíveis, opções, legendas, readout e export conservam a identidade integral. O select nativo recolhido pode mostrar apenas a parte que cabe visualmente; o valor completo é acessível nas opções/teclado e nos labels/legendas quebrados. Não foi criado tooltip que exigisse hover para distinguir A/B.

O download real `downloads/holdout-analysis.zip` passou CRC e todos os checksums. `source.gbpack` é byte a byte idêntico ao original, SHA-256 `d17d6d77b3da28388a28c6c6f1a00d9ee21d3f8659e17d7ee6a0adb28eb8ab4a`. Título de 240 codepoints e os dois IDs estão intactos no pack e nas métricas (`BROWSER_EXPORT_VERIFIED.json`). Não se modificou um download preexistente do usuário.

## 11. Acessibilidade

Uso real de teclado: Space para seleção, aplicação que remove uma das contas sem confundir o sufixo, End/Enter no select para escolher a outra identidade e ArrowRight nos gráficos para obter a marca observada. Nomes acessíveis completos e foco visível foram inspecionados. Não há fonte reduzida no reparo nem identidade dependente de tooltip por mouse. A tabela exata continua consultável por mecanismo existente. Esta é validação focalizada; não substitui auditoria WCAG completa nem testes com todos os leitores de tela.

## 12. Segurança de metadados

`FIXTURE_CONTRACT.json`: 14 entradas negativas rejeitadas pelo contrato. Unicode, acentos, emoji, combinantes, aspas, ampersand e entidades HTML literais foram exercitados em títulos legítimos. Não surgiram img/script/event handlers executáveis. Título HTML inválido foi recusado na prévia, sem confirmação de persistência; uma análise anterior continuou identificada pelo próprio nome, sem atribuição ao arquivo recusado (`WHEEL_INVALID_TITLE_REJECTED.json`).

Não houve uso novo de innerHTML, montagem de atributo, relaxamento de validação ou alteração de direitos de exportação. Proveniência declarada continua distinta de autoria autenticada. O consentimento sintético usado no teste de exportação foi independente do metadado do pack.

## 13. PAPER frio

Testado pelo botão real da interface de produção, em processos recém-criados com cache de demonstração vazio e wheel instalado. Sem coverage/cProfile no caminho medido. Processo frio não significa limpeza do cache do Windows. Instrumentação externa de tempos/processo e wrappers observadores registraram resultados sem alterar algoritmo; atrasos artificiais e afinidade existiram somente no harness isolado.

Caso normal e caso com CPU moderadamente ocupada concluíram com duas contas corretas dentro dos 15 segundos. A carga foi um worker próprio, limitado a aproximadamente 30% de um único CPU permitido, com o servidor próprio no mesmo CPU; não alterou afinidade/prioridade de processos do usuário ou do sistema. Apenas uma amostra fria por condição: evidência funcional, não benchmark estatístico ou SLA.

## 14. Timeout de transporte

Produção preserva `AbortSignal.timeout(15000)`. O orçamento de 60 s dos testes HTTP instrumentados G4.8 não foi usado como critério de aprovação da aplicação.

Controle negativo: atraso de 16,25 s no harness antes da geração verdadeira. O navegador interrompeu em aproximadamente 15,111 s, exibiu mensagem explícita em português, sem tabelas antigas apresentadas como resultado novo. O servidor concluiu em 19,468 s; a tentativa subsequente recuperou a demonstração válida, HTTP 200 em 0,001869 s com cache já pronto. O tempo UI de recuperação registrado após o clique não é latência completa da ação.

Outro processo, atraso de 3 s: início 17:25:11.225Z, navegação para Lab 17:25:11.569Z, geração concluída 17:25:17.542Z. Após a resposta tardia, Lab continuou `DATA_UNAVAILABLE`, sem tabelas e sem valores PAPER antigos (`LATE_RESPONSE_NAVIGATION.json`). O caso de navegação feito depois de concluir o primeiro timeout não é usado como prova dessa corrida; a execução separada é a prova.

O cancelamento no cliente não interrompe cálculo CPU no servidor sequencial. Windows retornou ConnectionAbortedError/10053 no envio à conexão fechada; o observador detalhado registrou tentativa 200 e depois tentativa genérica 422. Nenhum 422 foi entregue ao cliente fechado; não é evidência de pack inválido. A biblioteca respondeu normalmente depois. Não se adicionou tratamento Python de diagnóstico nesta missão, pois recuperação/estado visível permaneceram corretos; fila ocupada por trabalho cancelado continua limitação conhecida.

## 15. Resultado das medições

| Condição | Processo → pronto | Preparação wall / CPU | HTTP wall | UI observada |
| --- | ---: | ---: | ---: | ---: |
| Frio normal | 0,358215 s | 3,344027 / 3,328125 s | 3,344731 s, 200 | 3,440 s, resultado válido |
| Frio + carga moderada | 0,364835 s | 4,147974 / 3,296875 s | 4,148664 s, 200 | 4,293 s, resultado válido |
| Atraso forçado 16,25 s | 0,367273 s | 19,467123 / 3,218750 s | 19,468079 s até conexão fechada | 15,111 s, erro explícito |
| Retry após timeout | mesmo processo | cache pronto | 0,001869 s, 200 | recuperação confirmada |
| Navegação durante atraso de 3 s | processo novo | 6,258496 / 3,296875 s | 6,260939 s até conexão fechada | Lab preservado |

O fluxo quente por HTTP normal ficou aproximadamente entre 1,54 e 2,73 ms nos registros; uma observação UI foi 47 ms. Troca de seleção somente no cliente, observada em 34 ms, não mede HTTP. Medidas UI usam relógio externo e observação por automação, incluindo overhead; não são marcas de performance do navegador. Startup foi obtido com GetProcessTimes do processo próprio, além do marcador ready. Wrappers de teste têm limites distintos dos 15 s de transporte.

O worker moderado consumiu 7,5 s CPU em 25,06346 s wall (~29,9%). Nenhum aumento do timeout e nenhuma aceleração do algoritmo foram feitos. Registros completos: `COLD_PATH_REVIEW.json`, `COLD_*_UI.json`, `MODERATE_LOAD.json`, `results/ui-*-events.jsonl`.

## 16. Correções anteriores preservadas

| Contrato | Evidência fresca G4.9 |
| --- | --- |
| 100/1.200 marcações | Wheel e UI: NAV 1.721 / 11.317 USDT; BTC 1; fixtures originais preservadas |
| Frações grandes/JSON | 91 casos de marcas até 9.999, nove frações especiais e 446 vetores JS independentes; oráculos Fraction |
| Precisão de export | Download real verificado, identidade patrimonial recalculada e source byte a byte igual |
| PAPER/cadência | Trace SHA-256 `9ea09ee91cb6d464368592aff9b8cf1f39b9badf5f37888b83c3386a235934e3`; intervalos nativos 60/60/60 s |
| Windows lock/quota/crash | 16 cenários nativos, quota32 e concorrência, todos aprovados |
| ZIP/HTTP/export rights | 126 pytest + 46 HTTP + 17 HTTP bruto, todos aprovados |
| Navegação/catálogo | Catálogo com atraso1,8 s; seleção/retorno e prévia posterior com confirmação habilitada |
| Erro de análise | Falha500 injetada após import válido: erro interno visível, nenhuma tabela indevida, não rotulado pack inválido; seleção seguinte recuperada |
| Risco responsivo | 320/375, DD `8/11`, distância `-580/11` pontos percentuais, aviso explícito de violação |
| Replay/persistência | Replay EQUIVALENT; reinício conserva quatro packs e todos os hashes, grants reiniciados |

Oráculo financeiro PAPER independente: round_trip NAV/cash 109,17147, BTC0, fees0,28853; falling_mark NAV76,26013, BTC0,946, cash10,04013, fees0,08987. Reservas não são somadas duas vezes. A exposição de capital nativa e a média por marcas do Lab continuam estatísticas distintas e explicitamente rotuladas. Nada disso é novo backtest ou mudança de estratégia.

No holdout exportado, para cada conta, NAV = cash + BTC × preço em cada marca; NAV final5, BTC1, cash0, pico11/vale3, DD8/11. O oráculo Fraction verifica os campos exatos, não apenas texto arredondado. `PAPER_INDEPENDENT_ORACLE.json`, `HOLDOUTS.json`, `NATIVE_WINDOWS_LOCK.json`, `PERSISTENCE_RESTART_VERIFIED.json` e `BROWSER_EXPORT_VERIFIED.json` documentam os resultados.

## 17. Testes Python

Execução fresca, candidata congelada: `tests/console` + `tests/architecture`: 651 coletados, **650 PASS, um SKIP Windows preexistente**, zero failures/errors; aproximadamente 91,90 s no JUnit, 93,13 s no controlador. A coleta global fresca produziu os mesmos 3.635 nodeids da G4.8, sem exclusões/novos skips. A campanha adversarial isolada G4.5 executou outros 126 pytest aprovados, além das campanhas HTTP.

Não se somam esses subconjuntos como se constituíssem suíte global, pois podem compartilhar comportamento e escopo. A suíte global Python não foi repetida. `REGRESSIONS.json`, JUnit e recibos preservam comandos, tempos, limites, exit codes e hashes dos logs. Limites por job: 512 MiB/processo, 768 MiB/job, 16 processos, timeout finito por campanha, área limitada a2 GiB.

Falhas de preparação não são testes PASS: erro inicial de quoting do controlador Windows ao chamar Node; teste RED inicial com expectativa restrita de shorthand CSS; tentativa de UI com nome de fixture inexistente; primeiro verificador de export com nome de campo errado (`cash_final`, corrigido para `cash_usdt` antes de concluir). Não afetaram produção. O teste RED corrigido reproduziu uma falha real e um contrato de tabela já correto; logs anteriores foram preservados. Esperas de observação de UI que venceram antes de o elemento aparecer não são timeout do transporte. Estados finais necessários foram novamente observados e assertados.

## 18. Testes JavaScript

Suíte completa congelada: **46 PASS**, zero fail/skip, sendo 44 anteriores mais dois guards estruturais do reparo. Outra execução independente cobriu 446 vetores em três testes adicionais, aprovada. Nenhum JS de produção foi alterado. Os novos guards não substituem geometria nem acessibilidade real; verificam a permanência da regra restrita, sem clipping/font shrink, e da rolagem local exata.

## 19. Política de coverage

**Histórico G4.8, não execução desta fase:** 3.633 PASS, dois SKIP, cobertura96,46987627756859%, threshold85%. A G4.9 conserva essa evidência por identidade comprovada de todos os blobs Python, testes Python, contratos, dependências e configuração de coverage/build, além do payload wheel. Mudança produtiva somente CSS, testes novos somente Node e documentos não empacotados.

`PYTHON_EQUIVALENCE_AND_COVERAGE_POLICY.json` lista o conjunto completo de blobs diferentes desde f75bef. Nenhum arquivo coverage de HEADs diferentes foi mesclado; não há percentual global novo. Não houve exclusão de teste, skip artificial ou redução do threshold. A coleta idêntica não prova execução e não é apresentada assim. O skip único da seleção console/arquitetura não substitui nem oculta os dois skips globais históricos.

## 20. Wheel

Wheel novo construído a partir do executável congelado, SHA-256 **`46c1988aa2d02b9e58b89da14c7f2e1758a4c752972af32539b3fa9d2d73d1ea`**,345.438 bytes,144 membros,138 arquivos instalados conferidos byte a byte. Comparado ao wheel G4.8, somente `research_console/static/style.css` e dist-info/RECORD diferem. Backend, JS, schemas, fixtures, ajuda e metadados permanecem idênticos.

Após o commit documental final, um segundo build a partir de clone limpo desse HEAD deve produzir os mesmos bytes; o recibo final `FINAL_WHEEL_IDENTITY.json` registra o resultado efetivo e o HEAD completo. A certificação se refere ao wheel efetivamente testado, não a reaproveitamento de um binário antigo. Relatórios novos não entram no build.

## 21. Instalação limpa

Venv wheel próprio, não editável, sem checkout no caminho de importação. `research_console.__file__` foi assertado dentro de site-packages em todos os processos wheel de UI. pip check aprovado. CLI e launcher Windows foram exercitados tanto no wheel quanto em clone editável isolado da candidata. O campo histórico do harness que diz source_checkout_and_original_project_not_used significa que o checkout público de trabalho e o original protegido não são usados; o clone isolado `final` é intencionalmente usado no modo editável.

Os IDs máximos e holdouts foram abertos no navegador desse wheel, não apenas no servidor de desenvolvimento. Replay, import/export, erro500, persistência, PAPER frio e timeout foram exercitados nessa instalação. Harness tem restrição de rede loopback e bloqueio de acesso ao original/checkouts protegidos/caminhos corporativos nos subprocessos de integração.

## 22. Segurança

Ruff, formatação, Mypy strict (283 arquivos fonte), pre-commit da candidata aprovados. Fechamento documental exige novamente pre-commit, Gitleaks de todos os arquivos rastreados em cópia exata e do intervalo de commits `bff062..HEAD`, e diff --check. Recibos finais são parte do handoff; qualquer falha impediria emitir validação completa.

Campanhas de ZIP, JSON, metadados, path traversal, rights/grants, concorrência, quotas e HTTP mantiveram189 verificações G4.5 aprovadas, sem flexibilizar proteção. Hashes dos arquivos distribuíveis e do arquivo exportado foram verificados. Nenhuma credencial financeira, wallet, Binance, LIVE/Testnet, dataset privado ou diretório corporativo foi acessado. O uso autenticado do GitHub restringiu-se a GET de administração/estado já autorizado, sem emissão de tokens nos relatórios.

Preservação original: HEAD `528f8c40ce6f74f9440444b2e652c56fae222fb2`, todos os1.665 arquivos conhecidos e seis históricos não rastreados idênticos. V2 FINAL SHA-256 `44e9639554d01c13e2e0648613e7904a6f1649ca934b00b3821021aa28582249`. CORE, congelamento, estratégias e resultados financeiros inalterados. Quatro históricos não rastreados públicos permanecem fora dos novos commits.

## 23. Arquivos alterados

Delta G4.9 sobre2e5346d: somente `research_console/static/style.css`, novo `tests/console/long_identifier_layout.test.cjs` e estes dois documentos: `docs/reviews/G4_9_FINAL_UX_AND_RELEASE_FREEZE_AUDIT.md`, `docs/G4_9_FINAL_PR_UPDATE_CHANGELOG.md`. Não inclui wheels, capturas, venvs, caches ou logs. Evidências ficam na área de auditoria externa.

Comparação completa de publicação futura, **bff062beea10bd0ccc614e852797b643aa887497 → HEAD final**, está em `reports/bff062_to_final.diff` (patch binário incluído) e `evidence/FINAL_COMPARISON.json` (hash, lista de arquivos, numstat e commits). Esse intervalo inclui reparos G4.6/G4.8 ainda não publicados; não deve ser confundido com o pequeno delta G4.9. O conteúdo completo foi preparado para revisão, sem atualizar o PR.

## 24. Commits

Commit executável local: `cf1e9c9aba3072bbef80956852bc115e4b1b34b9`, `fix(lab): wrap complete research identities in narrow layouts`. Filho direto de2e5346d. O commit seguinte contém exclusivamente os dois documentos finais e é enumerado por SHA completo em `FINAL_DELIVERY.json` e na resposta de entrega. Nenhum amend ou reescrita para inserir o próprio hash no documento.

## 25. HEAD final

O HEAD executável testado é `cf1e9c9aba3072bbef80956852bc115e4b1b34b9`. O HEAD documental de entrega é o commit que contém este relatório: `git rev-parse HEAD`, registrado integralmente em `evidence/FINAL_DELIVERY.json`, no pacote de handoff e na conversa. A comparação de blobs exige que a diferença seja exatamente os dois Markdown fora do empacotamento. O segundo build deve comprovar identidade do wheel. Essa separação evita atribuir execuções a um commit criado depois dos testes.

## 26. Riscos remanescentes

Não foi encontrada nova falha material P0/P1/P2 nos caminhos focalizados. G48-P3-004 foi corrigido e comprovado incluindo título e readout. Permanecem: geração CPU sequencial; bloqueio temporário da fila por cálculo em conexão cancelada; variação de hardware/carga que pode exceder15 s; diagnóstico Windows10053 com tentativa de envio genérico depois de desconexão; necessidade de retry explícito. A amostra fria não garante latência em toda máquina.

Texto válido muito longo aumenta altura dos cards e rolagem vertical. Select nativo recolhido tem largura finita, com identidade consultável integralmente nos mecanismos existentes. Tabelas exatas têm rolagem própria deliberada. Testes visuais foram feitos no navegador disponível/Windows, não em todos os engines/dispositivos ou tecnologias assistivas. Checks remotos ausentes e Actions desativado não autorizam afirmar aprovação remota. Sem estratégia nova, coleta prospectiva, G5 ou negociação real.

## 27. Recomendação sobre atualização do PR #2

Recomenda-se encaminhar a candidata local e o diff completo à revisão independente do ChatGPT orquestrador. O reparo é suficiente para fechar o último P3 e a experiência fria está medida com erro/recuperação explícitos sob transporte real. Uma eventual publicação exige a próxima decisão autorizada; não foi executada nesta fase.

Os gates abaixo referem-se ao fechamento conjunto com os recibos finais de segurança, identidade do build e preservação; não significam implantação ou garantia operacional:

```text
G4_9_LONG_IDENTIFIER_UX_PASS
G4_9_PAPER_COLD_PATH_REVIEW_PASS
G4_9_PRIOR_REPAIRS_PRESERVED
G4_9_VALIDATION_COMPLETE
G4_9_LOCAL_RELEASE_CANDIDATE_READY
NUMERIC_EXACTNESS_PRESERVED
PAPER_DEMO_DETERMINISTIC
EVIDENCE_PACK_SECURITY_PRESERVED
PUBLIC_WHEEL_INSTALLATION_PASS
ORIGINAL_GRIDBOT_PRESERVED
FROZEN_V2_PRESERVED
REAL_TRADING_DISABLED
NO_REMOTE_WRITES_PERFORMED
```

PARE para revisão do orquestrador. Não há autorização de publicação, atualização do PR ou início de nova fase.

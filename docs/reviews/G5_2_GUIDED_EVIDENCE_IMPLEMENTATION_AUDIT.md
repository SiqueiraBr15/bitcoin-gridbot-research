# G5.2 — Auditoria da implementação da Revisão Guiada de Evidências

Candidata local funcional, com sete etapas e cálculos G4 preservados. **Implementação PASS para revisão independente; não é autorização de publicação.** Matriz:22 PASS e2 PARTIAL, com zoom real de200% e revisão completa de acessibilidade pendentes. Não emitir ACCESSIBILITY_REVIEW_PASS. Gates globais abaixo são separados e baseados somente na campanha da candidata vigente.

## 1. Baseline

Inspecionados antes do desenvolvimento: main remota `acaa6879877c8a081a127f3ea8a0cdbb840b88cd`, G5.1 `2aa01e5bdd93b56a355d73fb43e45c4d5f8cb660`, seu pai `eaf58378d71fa3a3826c32bc75461fb57844966c`,400 arquivos públicos rastreados e quatro históricos públicos não rastreados. BASELINE.json e INITIAL_REMOTE_MAIN.json registram a inspeção; FINAL_REMOTE_CHECK.json confirma main inalterada por GET. Actions foi consultado por GET e continua desativado.

## 2. HEAD de origem

G5.1 preservada como ancestral. Sem rebase, reset, amend ou reescrita de histórico. Original somente leitura: `528f8c40ce6f74f9440444b2e652c56fae222fb2`. Esta auditoria é interna, com assistência de IA; não certifica auditoria externa.

## 3. Branch final

`feat/g5-2-guided-evidence-review`, exclusivamente local. Não houve push, PR, merge, tag, release, ativação de Actions ou mensagem a terceiros. Git config e main local preservados. As autorizações antigas de publicação não foram reutilizadas nesta fase.

## 4. Contrato G5.1

Leitura integral dos três contratos, guias G4, README, arquitetura e auditoria G5.1. CONTRACT_GATE.json preserva os24 critérios originais e decisões anteriores ao código. Benchmark é somente o declarado: incluir/excluir a conta existente e mudar foco é permitido; substituição arbitrária não foi implementada. Fontes M1/PAPER conservam suas páginas existentes; não são convertidas automaticamente em packs. Requisitos originais da matriz foram preservados; seus cabeçalhos distinguem proposta histórica de implementação local.

## 5. Decisões arquiteturais

Dois módulos JavaScript sem framework: review_model.js projeta identidade, disponibilidade e lifecycle; review_view.js compõe a jornada. Lab.js compartilha biblioteca, seleção, gráficos, replay, exports e estados existentes com o modo detalhado. Não existe outro motor financeiro, schema, servidor de arquivos genérico ou segundo sistema de exportação. Na produção Python, somente dois nomes fixos de assets foram acrescentados à allowlist de server.py. Nenhum módulo financeiro foi editado.

## 6. Endpoints reutilizados

GET `/api/lab/library`, `/analysis`, `/export`, `/source`; POST `/preview`, `/confirm`, `/authorize-export`, `/replay`, `/remove`, sob o prefixo `/api/lab`. Nenhum endpoint novo. A jornada não chama `/api/lab/paper` ao mudar de etapa. As proteções de sessão, Host/Origin, ZIP, quotas, locks, persistência e direitos continuam na G4.

## 7. Componentes implementados

Entrada visível no menu do Lab; modo guiado padrão; sete botões semânticos de etapas, anterior/próxima, foco no título por navegação, conta em foco, cards, explicações, inspeção de origem, episódios, tabelas e gráficos existentes. Modo detalhado disponível, sem reconstruir o console. Fixture JSON de testes é snapshot sintético de API, não fonte de números hardcoded na interface.

## 8. Evidência

Biblioteca/importação explícita, contexto de fonte/natureza, período, política, benchmark, custos, hash, restrições e disponibilidade. Autoria permanece declarada. Agregado não vira série. Cópia inválida ou ausente invalida resultados e permite recuperar/importar outra evidência. CURRENT_RECOVERY_IMPORT.json comprova a recuperação utilizável na instalação atual, não apenas um botão habilitado.

## 9. Patrimônio

NAV inicial/final, retorno absoluto/percentual, caixa, custos e diferença contra benchmark usam métricas canônicas. Nada soma caixa/BTC no JS para recalcular NAV. O formatter existente arredonda apenas apresentação e escala percentual. Custos refletidos no saldo não são deduzidos novamente.

## 10. BTC

Inventário físico, equivalente, variação física, caixa e diferença contra benchmark têm unidades distintas. Exemplo matemático favorable/MIX:5 BTC físicos,50 USDT, marca final13, NAV115 e equivalente115/13 BTC. Não existem moedas extras de115/13; não somar esse poder de compra ao inventário. O schema v1 não comprova CORE/passivos/fees de terceiro ativo, e a interface informa essa limitação.

## 11. Risco

Drawdown da janela só aparece completo quando o backend permite; segmentos observados têm rótulo próprio. risk_violation fornece40% para BTC_HOLD e20% para MIX; somente o primeiro excede1/5. Episódios permitem conferir pico, vale, recuperação, fim, duração e censura. Gap e marca unitária conservam null/indisponibilidade; não há interpolação.20% continua referência analítica, sem stop-loss, garantia ou proteção intradiária.

## 12. Comparação

Grupos canônicos separam custos, janela, capital e marcação compatíveis. Com vários grupos, não há scatter/fronteira global. Pareto vem do backend, sem pesos ou score; null é inelegível, não dominada. Ausência da conta benchmark fica explícita; reincluí-la restaura apenas a referência declarada. Nenhuma política é chamada vencedora universal.

## 13. Verificação

Metadados expõem pack/manifesto/implementação/resultado, conta, política, janela, marca, métricas exatas e unidades. Disclosures serializam origem extensa apenas quando abertos. Uma fixture preexistente com1200 marcas foi importada explicitamente; sua fração de exposição foi conferida por soma independente em Fraction e parser decimal por blocos, sem alterar o limite de conversão de inteiros. O texto exato completo sobreviveu à UI e à instalação atual.

## 14. Resumo

Projeção determinística da seleção: políticas/contas, período/custo, benchmark/status, NAV, BTC físico/equivalente, risco, proveniência e limitações. Sem interpretação livre, IA externa ou recomendação. Exports são as saídas G4 autorizadas; não há um novo relatório financeiro montado de números visuais.

## 15. Estado e navegação

State explícito para IDLE, LOADING, READY, AGGREGATE_ONLY, UNAVAILABLE, INVALID, ERROR; replay/export têm lifecycle separado. Identidade completa inclui pack/manifesto, fonte/natureza/dataset, versões, implementação/resultado, contas/objetivos e contexto de cada linha. Validar a resposta antecede exibir valores. SessionStorage recebe somente preferência enumerada de modo/etapa, além dos filtros G4 já existentes; não recebe dados financeiros, grants, tokens ou identidade da revisão.

## 16. Cancelamento e respostas tardias

Trocar seleção incrementa revisão, aborta requisições e retira resultado/replay/export dependentes. Tickets e identidade impedem publicação tardia, mesmo se o servidor não parar CPU. HTTP real atrasado demonstrou seleção A descartada em favor de B, replay antigo sem selo EQUIVALENT e export antigo sem download. Confirmação de importação agora invalida ações antigas imediatamente, antes do retorno da persistência. Três regressões falham no JS anterior; duas regressões adicionais de prévia detectam controller abortado na candidata intermediária. Todas passam no código vigente.

## 17. Segurança

TextContent/DOM seguro; sem innerHTML, scripts/estilos externos ou API de paths arbitrários. Novos módulos de modelo/view não acessam rede/storage nem criam canal Blob/export próprio. Renderer reutiliza a autoridade do servidor. Assets têm CSP e allowlist exercitadas por HTTP, inclusive travessia e Origin hostil. Ruff, Mypy strict, pre-commit, Gitleaks da árvore e intervalo de commits, e diff-check passaram. O runtime instalado foi executado com guard que só permite conexões loopback e escrita na auditoria, bloqueando leitura do original e do checkout. Instalação de dependências veio do PyPI oficial; operação do produto foi offline. Nenhuma credencial financeira, carteira, Binance, Testnet ou conteúdo corporativo foi acessado.

## 18. Precisão financeira

Oráculos independentes conferem por marca NAV=caixa+BTC×preço, retorno, físico, equivalente e máximo de drawdown por pares de marcas. Casos manuais115/13 e1/5, tiny não zero, frações extensas e half-even complementam testes do serializer. Três ZIPs baixados no navegador atual têm linhas exatas e analysis_manifest iguais à baseline anterior à UI, com todos os checksums válidos. Nenhuma decisão financeira usa valor visual arredondado. Isso não demonstra rentabilidade real nem cobre ativos/taxas ausentes do schema.

## 19. Restrições de exportação

PUBLIC externo começou bloqueado. Grant exigiu confirmação independente explícita sobre fixture sintética própria; DERIVED_ONLY não continha source.gbpack, accounts/séries, exact, risk ou episódios. Builtins permitiram RAW_AND_DERIVED. Testes HTTP existentes exercitaram também RESTRICTED/AGGREGATES_ONLY e autorização/reinício. Grant não vem do manifesto e pode ser compartilhado entre abas do mesmo processo/porta. DERIVED_EXPORT_ORACLE.json e CURRENT_EXPORT_ORACLES.json inspecionam conteúdo, não só status200.

## 20. Acessibilidade

Foco no título conferido em42 ações; Enter avança e setas mudam o select preservando foco. Labels, títulos, tabelas com cabeçalhos/legendas, aria-current, aria-busy, status/alert e texto além de cores foram examinados. Contraste sRGB das cores renderizadas: mínimo amostrado5.329:1, respeitando4,5:1 para texto normal e3:1 nos componentes/foco pertinentes. **PARTIAL:** o controlador perdeu foco documental na tentativa de percorrer Tab continuamente; não houve validação completa com leitor de tela real. Nenhum Narrator/NVDA ativo foi detectado; isso não prova que não estão instalados. Não declarar conformidade WCAG integral ou ACCESSIBILITY_REVIEW_PASS.

## 21. Responsividade

Na candidata atual foram exercitadas42 combinações de sete etapas e320/375/390/768/1366/1920 px, com IDs80 e títulos longos. Seis vistas adicionais verificaram título exatamente240 (CURRENT_MAX_TITLE_LAYOUT.json). Zero overflow global; tabelas mantêm rolagem local e origem exata não é cortada. Capturas reais em captures/current-risk-*.jpg e current-*-summary.jpg. A tentativa de Ctrl+= não alterou a geometria no browser de testes: zoom real200% **PENDING**, sem substituí-lo por CSS zoom ou alegar sucesso por viewport estreito.

## 22. Testes Python

Testes dirigidos:354 PASS,1 SKIP legítimo de symlink Windows, em96,16s; cinco casos novos verificam oráculos independentes e transporte dos assets. Global atual: **3638 PASS, 2 SKIP; 3640/3640 nodeids reconciliados; PASS**. Testes antigos não foram excluídos, suprimidos ou usados como novos resultados. Simulações de teste preexistentes foram exercitadas pela suíte; não foi criado estudo econômico/backtest de otimização.

## 23. Testes JavaScript

**76 PASS**, sem skip ou cancelamento.46 preexistentes preservados;20 testes novos de modelo e10 novos de integração/lifecycle. Cobrem os três packs, sete etapas reais no DOM controlado, precisão, indisponibilidade, direitos, identidade, fontes ausentes/inválidas, replay atrasado durante confirmação e recuperação da prévia. Testes sobre versões antigas têm falhas esperadas registradas; não foram declarados PASS.

## 24. Cobertura global Python

**96.46987628%**, estadoPASS; branch coverage e threshold85% preservados nos módulos Python de gridbot e research_console. Este percentual não mede JavaScript; JS foi validado por testes e navegador, sem percentual de cobertura JS instrumentado. Inventário atual3640 nodeids/132 propriedades,277 segmentos, seis lanes disjuntas, até100 casos comuns por lote e propriedades isoladas. CI Hypothesis300 permanece. Limite1200s/segmento,5400s/lane;512 MiB/processo,768 MiB/job, teto agregado4608 MiB para as seis lanes, auxiliares limitados separadamente; host31,9 GiB. Diretório exclusivo global-current, identidade de código/config/ambiente e hashes por segmento. Consolidação por Coverage.combine, nunca média de percentuais. Campanhas em global e global-final foram interrompidas após bugs comprovados da UI; continuam preservadas como INCOMPLETE e **nenhum arquivo delas entra nesta cobertura**. Dados G4 históricos também não entram. O percentual coincide com o histórico G4.8 porque o diff Python acrescenta somente entradas de uma allowlist, sem alterar o universo de statements/arcs; a execução é nova, com DB SHA256 1ba2325f4d8dc9a6c6b5ac3204e334efb523af5337d08958ea9b95a07dcf5ccf,277 segmentos completos e3640 nodeids atuais reconciliados. Um segmento CLI falhou porque o builder não tinha a distribuição instalada (versão0.0.0+unknown). O segmento e a falha foram preservados; seus dados de coverage foram excluídos. Os seis nodeids foram repetidos no venv-current com o wheel atual e as mesmas versões pinadas de pytest/coverage/Hypothesis, identidade declarada de cobertura e código exatamente iguais:6 PASS. Um segundo segmento teve falha de decodificação OEM/UTF8 do comando Windows mklink. Seus28 nodeids foram repetidos em console próprio oculto com chcp65001:28 PASS. O segmento original e o consolidado parcial3612/3640 foram preservados, sem reutilizar coverage dos dois segmentos falhos. Não houve alteração de produção, asserção, warning ou configuração global do Windows. CLI_ENVIRONMENT_DIAGNOSIS.json documenta os dois contextos e a distinção entre falha ambiental e resultado validado.

## 25. Matriz de aceitação

Linhas extraídas dos critérios reais G5.1;22 PASS e2 PARTIAL. Cada resultado é circunscrito às evidências citadas, sem prometer todos os casos possíveis. Arquivos citados sem extensão são JSON/logs locais sob audit/g5_2/evidence ou logs. A matriz completa legível por máquina está em ACCEPTANCE_MATRIX.json, junto do critério original.

| ID | Critério original | Componente | Resultado | Verificação/oráculo | Evidência local |
| --- | --- | --- | --- | --- | --- |
| A01 | Percurso completo | modelo/renderer/Lab | PASS | Node + 21 etapas reais + ZIP exato | CURRENT_WHEEL_JOURNEYS; CURRENT_EXPORT_ORACLES |
| A02 | Navegação | router/estado/render | PASS | Node lifecycle; 42 focos; zero requests por navegação | CURRENT_RESPONSIVE; WHEEL_PERFORMANCE |
| A03 | Mudança de seleção | State/selectStudy | PASS | tickets/identidade; troca rápida HTTP real | WHEEL_DELAYED_SELECTION; run_javascript_current |
| A04 | Fonte inválida | refresh/leitor de packs | PASS | cópia corrompida; recuperação e nova importação | CURRENT_RECOVERY_IMPORT; RECOVERY_BUG_REPRODUCTIONS |
| A05 | Fonte indisponível | refresh/biblioteca | PASS | cópia ausente e ausência de métricas | WHEEL_UNAVAILABLE_COPY; run_javascript_current |
| A06 | Dados incompletos | renderer/risco | PASS | gap, marca unitária, agregado, censura | WHEEL_EXTRA_STATES; BROWSER_GAP; run_directed_console |
| A07 | Estudos incompatíveis | comparação G4/renderer | PASS | grupos distintos e benchmark declarado ausente/restaurado | WHEEL_EXTRA_STATES; WHEEL_BENCHMARK_RESTORED |
| A08 | Valores exatos | numbers.js/origem exata | PASS | BigInt/half-even/extremos;1200 marcas, oráculo Fraction | CURRENT_COMPLEX_ORACLE; COMPLEX_BROWSER_ORACLE; run_javascript_current |
| A09 | NAV | NAV canônico | PASS | Fraction independente por marca; ZIP igual à baseline | run_directed_console; CURRENT_EXPORT_ORACLES |
| A10 | BTC físico | BTC canônico | PASS | 10/5/0 BTC; caixa separado | CURRENT_WHEEL_JOURNEYS |
| A11 | BTC equivalente | equivalente canônico | PASS | 115/13 distinto de5; formatter exato | CURRENT_WHEEL_JOURNEYS; run_directed_console |
| A12 | Drawdown | risco/episódios G4 | PASS | =1/5, >1/5, recuperação, gap/censura | CURRENT_WHEEL_JOURNEYS; BROWSER_GAP; run_javascript_current |
| A13 | Pareto | Pareto G4 | PASS | null inelegível; grupos preservados | run_javascript_current; WHEEL_EXTRA_STATES |
| A14 | Rastreabilidade | identidade/metadados | PASS | hashes completos; conta/janela/métrica/origem exata | CURRENT_COMPLEX_SOURCE; CURRENT_EXPORT_ORACLES |
| A15 | Replay | replay G4 | PASS | três EQUIVALENT; código errado recusado | CURRENT_WHEEL_JOURNEYS; WHEEL_INCOMPATIBLE_REPLAY |
| A16 | Export | permissões/export G4 | PASS | grants/ZIP: PUBLIC externo bloqueado; DERIVED redigido; matriz HTTP | DERIVED_EXPORT_ORACLE; CURRENT_EXPORT_ORACLES; run_directed_console |
| A17 | Respostas atrasadas | tickets/abort/revisão | PASS | análise/replay/export atrasados; confirmação de importação | WHEEL_DELAYED_ACTIONS; RECOVERY_BUG_REPRODUCTIONS; ABORTED_CONTROLLER_BUG |
| A18 | Erros HTTP | request/showError/HTTP | PASS | 500 sanitizado;422/403/etc HTTP; timeout no harness | WHEEL_HTTP_500; run_directed_console; run_javascript_current |
| A19 | Duas abas | sessão/abas | PASS | seleção e passos independentes; grant compartilhado conforme contrato | WHEEL_TWO_TABS |
| A20 | Reinício | persistência/sessão | PASS | processo reiniciado; pack persiste sem grant/replay | WHEEL_PROCESS_RESTART; run_directed_console |
| A21 | Responsividade | CSS/tabelas | PARTIAL | 42 vistas em seis larguras PASS; zoom real200% PENDING | CURRENT_RESPONSIVE; captures/current-risk-*; ACCESSIBILITY_LIMITS |
| A22 | Acessibilidade | semântica/foco | PARTIAL | foco/Enter/setas/contraste PASS no escopo; percurso Tab/AT PENDING | WHEEL_KEYBOARD_AND_PALETTE; CONTRAST_RESULT; ACCESSIBILITY_LIMITS |
| A23 | Wheel público | distribuição/servidor | PASS | wheel novo; venv vazio;144 payloads; launcher;21 etapas | CURRENT_WHEEL_CONTENT_VERIFICATION; CURRENT_WHEEL_JOURNEYS |
| A24 | Preservação financeira | núcleo/identidade | PASS | 1665 originais/V2/Python financeiro/manifestos iguais | PRESERVATION; CURRENT_EXPORT_ORACLES |

## 26. Navegador real

Browser Chromium do ambiente Codex no Windows, controlado pela skill de computer use. Na instalação atual:21 etapas, três replays, três exports e42 vistas responsivas. Houve ainda erros500, resposta atrasada, fonte inválida/ausente, episódios, grupos incompatíveis, agregado, extremo1e-80, duas abas, reinício, direitos e importação1200 marcas. Ensaios interrompidos por locators incorretos foram preservados como incompletos; só jornadas terminadas contam. As verificações especializadas anteriores ao último reparo são identificadas pelos recibos WHEEL_*; módulos financeiros/modelo/view/CSS correspondentes permaneceram byte a byte iguais, e os caminhos afetados tiveram regressões e nova validação instalada CURRENT_*.

## 27. Wheel

Build novo de git archive de `533de8c97376428225a224daab7faa96c129ff9b`, sem overlays ou arquivos ignorados. Versão experimental0.1.0.dev0,150 membros,144 payloads verificados. SHA-256 `a821b996bf2e950d9887a3fe7c08588dab1baeaf74710be1b63c0d966b21d501`,371922 bytes. Dois JS novos, HTML/CSS/Lab, Python, schemas, exemplos sintéticos e seis guias/contratos presentes. Launcher Windows é o exe gerado pelo entry point do wheel. CMD/PS1 são exemplos do checkout; a primeira asserção da auditoria que exigia esses tipos literalmente no ZIP era suposição incorreta do harness, corrigida sem modificar produto.

## 28. Instalação limpa

Venv novo venv-current, instalação não editável e pip check PASS.144 arquivos instalados comparados por bytes ao ZIP. CLI Windows --help e inicialização real do exe com biblioteca nova, assets, análise, replay e ZIP (ACTUAL_WINDOWS_LAUNCHER_HTTP.json) passaram. Servidor instalado funciona sem checkout/original no import path; guard bloqueia leituras desses locais. Percurso, replay, export e recuperação/importação foram concluídos nessa instalação. Recursos não dependem de arquivos presentes apenas no checkout.

## 29. Performance

Em três ciclos comparáveis,21 mudanças de etapa e alternância com detalhado geraram **zero requests adicionais**. Paint guiado observado: mediana1.300ms, máximo2.200ms; três paints detalhados[9.800000004470348, 9.100000001490116, 7.400000005960464]. Dados: três contas pequenas, browser no mesmo host e três workers de testes concorrentes naquela medição; custos do controlador não integram o timer DOM. Não é benchmark amplo nem SLA. Renderer visita dados existentes; gráficos custam O(marcas), tabelas/comparação até60 contas limitadas pelo contrato. Há buscas repetidas por linha em O(contas²), limitadas por quota, sem nova análise backend por etapa. Séries grandes e CPU PAPER fria continuam limites preexistentes do servidor sequencial. Cancelar fetch não interrompe necessariamente CPU.

## 30. Achados e revisão crítica

Cinco defeitos encontrados durante desenvolvimento foram corrigidos antes da entrega, sem tocar matemática: (1) P2 opção download ocultava a função de exportar; (2) P3 badge de fonte não quebrava linha; (3) P2 reentrada com fonte invalidada deixava busy ativo; (4) P2 confirmação de nova cópia não invalidava replay anterior, que podia ler analysis=null; (5) P2 controller abortado mantinha a prévia inutilizável mesmo após liberar o botão. Node regressions, falhas esperadas em blobs antigos e navegador documentam as correções. Eles são achados da candidata em construção, não alegações de defeito econômico no original.

Limitações não bloqueantes para revisão técnica: mensagem422 de replay segue classificador genérico G4 e não identifica especificamente código divergente; o estado FAILED permanece explícito. Contas distintas com a mesma política/janela/custo podem ter labels de foco iguais; account_id completo continua disponível na origem exata e nos controles de seleção. Revisão independente deve avaliar esse refinamento de UX. P3 Windows10053 preexistente e CPU sequencial continuam registrados. Não há vulnerabilidade material conhecida demonstrada pelo diff/testes, mas isso não prova ausência de todas as vulnerabilidades. A experiência reduz métricas simultâneas, mantendo detalhes sob demanda; o percurso não emite aprovação financeira.

## 31. Commits locais

```text
e56f2cfa47e1a7ecd0c2797625c2a2a7b99ad21d feat: implement seven-step guided evidence review with bound state
312d99cd59a77ede8f3f6e93ee43c7a2d750fcdc docs: ship guided review instructions and contracts in public wheel
3cdb4301169a53e9b57e8321c4bcaf60994978e0 fix: wrap long evidence source labels in the Lab
9f6f4f7123fc2bde58f02fa816d8de49716e0a84 fix: release invalidated review state and cancel stale import actions
533de8c97376428225a224daab7faa96c129ff9b fix: renew request controller after evidence invalidation
```

Hooks normais executados, sem bypass. Relatório e changelog recebem commit documental posterior; não alteram os bytes executáveis testados ou o wheel.

## 32. HEAD final técnico e entrega

HEAD executável testado: `533de8c97376428225a224daab7faa96c129ff9b`. O SHA do fechamento documental, impossível de embutir no próprio commit sem circularidade, fica no DELIVERY_MANIFEST.json externo ao Git e na resposta final. A checagem final confronta todos os bytes executáveis com CURRENT_EXECUTABLE_FREEZE.json. Original,1665 arquivos/seis históricos, quatro históricos públicos e Git config preservados; V2 FINAL `44e9639554d01c13e2e0648613e7904a6f1649ca934b00b3821021aa28582249`. Sem acesso corporativo, negociação ou remote write.

## 33. Pendências e limites

A21: zoom real200% pendente. A22: percurso Tab contínuo e leitor de tela real pendentes; foco/semântica/contraste parciais aprovados não os substituem. Windows foi testado; não afirmar Linux/macOS ou CI remoto. Testes sintéticos e preservação de hashes não demonstram vantagem econômica, retornos futuros, garantia de drawdown ou prontidão para produção. GlobalPASS/coveragePASS são gates separados; execução incompleta não recebe PASS.

## 34. Recomendação para G5.3

Submeter esta candidata à revisão independente do orquestrador. Priorizar AT/teclado/zoom em ambiente nativo, examinar as correções de recuperação/importação, validar semântica de permissões e rever labels duplicados de foco/mensagem genérica de replay. Não implementar G5.3 automaticamente, não publicar e não iniciar pesquisa econômica/coleta. Parar após entrega.

```text
G5_2_GUIDED_REVIEW_IMPLEMENTATION_PASS
G5_1_CONTRACT_COMPATIBILITY_VERIFIED
SEVEN_STEP_GUIDED_FLOW_FUNCTIONAL
SELECTION_IDENTITY_PRESERVED
FINANCIAL_CALCULATIONS_REUSED
NUMERIC_EXACTNESS_PRESERVED
ERROR_AND_STALE_RESPONSE_HANDLING_PASS
COMPARABILITY_RULES_PRESERVED
EXPORT_AUTHORIZATION_PRESERVED
REPLAY_DETERMINISTIC
PUBLIC_WHEEL_INSTALLATION_PASS
ORIGINAL_GRIDBOT_PRESERVED
FROZEN_V2_PRESERVED
REAL_TRADING_DISABLED
NO_REMOTE_WRITES_PERFORMED
G5_2_GLOBAL_TESTS_PASS
G5_2_GLOBAL_COVERAGE_PASS
ACCESSIBILITY_REVIEW_PENDING
REAL_200_PERCENT_ZOOM_PENDING
```

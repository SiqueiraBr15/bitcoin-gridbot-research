# G4.8 — Final Quality Gate & UX Repair

Data: 2026-10-27. Auditoria local concluída sobre código executável congelado em `f75bef168f9f7dba077f91870460a55f27a6b972`. Nenhuma publicação autorizada ou realizada nesta fase. A candidata está apta à revisão do orquestrador, com a limitação móvel adicional P3 explicitada na seção 28. Isso não afirma prontidão para operação financeira.

Evidências locais: `C:/dev/github-portfolio-2026/audit/g4_8/`. Cada comando executado pelo controlador tem receipt `evidence/run_*.json`, comando completo, limite, exit code, tempo, memória de commit máxima do Windows Job e hash do log bruto. Os logs diagnósticos com falha foram preservados. O manifesto final de evidências e os recibos posteriores a este documento permanecem nessa área exclusiva; não são arquivos de produção nem payloads históricos privados.

## 1. Estado inicial e leitura da auditoria

Os quatro documentos obrigatórios G4.7, os relatórios/evidências G4.5 e os documentos pertinentes G4.6 foram lidos e seus bytes registrados em `BASELINE.json` (11 referências). O JSON G4.7 foi lido integralmente e analisado estruturalmente, incluindo seus registros; não se reutilizaram seus resultados como execução nova.

A G4.7 continua historicamente `G4_7_INDEPENDENT_REPAIR_AUDIT_BLOCKED` e `G4_7_PR_UPDATE_BLOCKED`: 3.630 PASS, dois SKIP e um teste sem conclusão bem-sucedida; 96,44970414201184% medidos sem certificação global. O controle sem coverage dessa fase não substitui o gate instrumentado. As novas certificações abaixo pertencem somente à G4.8.

## 2. HEAD de origem e preservação

Origem exata: `c868796c59f213aa0147f459e91807222a736399` (G4.6). O HEAD original protegido continua `528f8c40ce6f74f9440444b2e652c56fae222fb2`. A verificação lê somente os arquivos conhecidos e Git do original: 1.665 hashes, seis históricos não rastreados, árvore rastreada limpa e manifesto V2 FINAL preservados. Não houve recuperação de Windows repetida, pesquisa econômica, acesso a dados corporativos ou uso do corpus privado.

SHA-256 V2 FINAL: `44e9639554d01c13e2e0648613e7904a6f1649ca934b00b3821021aa28582249`.

## 3. Branch final e identidade executável

Branch local: `fix/g4-8-final-quality-and-ux`. Commit executável certificado: `f75bef168f9f7dba077f91870460a55f27a6b972`, filho direto de G4.6. A branch anterior permaneceu no c868796; a main local permaneceu `a28e6f35b7b0acb42cee6dc97959cdf65f6022b0`.

`CANDIDATE_FREEZE.json` registra os bytes da árvore pública; `CANDIDATE_EXECUTION_IDENTITY.json` registra os bytes do clone independente efetivamente executado. Treze diferenças CRLF/LF de checkout foram reconciliadas com o conteúdo Git antes da coleta e antes de qualquer teste final (`CHECKOUT_BYTE_RECONCILIATION.json`). Não eram diferenças semânticas. O launcher conserva CRLF por atributos. Os hashes do checkout de execução são conferidos no início e no fim. Nenhum arquivo executável da candidata ou da suíte certificada mudou após o início da campanha. Controladores e holdouts externos novos ficam exclusivamente na área de auditoria, com seus hashes, e não entram no código ou na cobertura da candidata.

Este relatório e o changelog entram em commit posterior exclusivamente documental. Esse HEAD de entrega não é apresentado como uma segunda execução global: o receipt final registra o SHA completo de entrega e prova que o delta desde o SHA certificado contém apenas os dois documentos. Não há rebase, amend, reset, limpeza destrutiva ou modificação da main.

## 4. Causa demonstrada do timeout

O limite que falhou era o socket HTTP de 15 segundos durante a fase **call** de `test_http_menus_catalog_and_selection`, em `/api/demo`. Não foi demonstrado deadlock nem timeout global de 900 segundos. O `HTTPServer` sequencial executa sincronamente o motor PAPER nativo e seu replay independente, com reconstrução/validação de objetos. O cliente pode esgotar seu prazo enquanto a thread do servidor ainda calcula; o teardown então aguarda o cálculo terminar.

Na reprodução controlada de uma CPU própria com um único cálculo nativo concorrente e finito, o teste antigo falhou em 15,17 s de call, seguido de 13,46 s de teardown. As stacks capturadas mostram a thread HTTP em conservação/replay, dataclasses e validação de evidência; a thread cliente estava aguardando resposta local. O servidor concluiu depois. Não foram observados colisão de porta, crescimento da fixture persistida, recurso abandonado, espera externa, recursão infinita ou loop sem parada. Há custo legítimo elevado de validações repetidas, não uma prova de vazamento ou deadlock.

## 5. Instrumentação e limites experimentais

Python 3.13.16, Windows 11, pytest 9.1.1, coverage.py 7.16.2, pytest-cov 7.1.0 e Hypothesis 6.168.5. O runner usa `coverage.Coverage` diretamente e cobertura de branches. Embora pytest-cov esteja instalado/carregado, o runner não passa `--cov`; não se atribui a ele isoladamente a causa.

O observador pontual mede wall time e CPU por rota, fases pytest, ordem real, stacks e eventos de início/fim. O cProfile separado mediu 9,897 s de wall e 9,844 s de CPU, com 306 chamadas a `_analysis`, 16.104 a `_eligible_qty` e 32.212 a `eligibility_status`. Tempos de profiling são instrumentados e linhas cumulativas se sobrepõem: não são latências sem overhead nem parcelas somáveis.

Todos os processos diagnósticos têm prazos finitos. Jobs próprios: 512 MiB por processo, 768 MiB por Job, 16 processos; área de auditoria limitada a 2 GiB. Afinidade foi aplicada somente aos próprios processos de reprodução e filhos, nunca ao sistema ou a processos do usuário. Guard de execução aceita rede apenas loopback, bloqueia escrita fora da área própria e acesso dos testes ao original protegido e ao checkout público. O console UTF-8 oculto preserva o comportamento do teste Windows existente de `mklink`, sem alterar o console do usuário.

## 6. Matriz com e sem coverage

| Experimento | Resultado observado |
|---|---|
| Processo novo, frio, sem coverage | PASS; `/api/demo` 3,722704 s wall / 3,593750 s CPU |
| Processo novo, frio, com branches | PASS; 13,501669 s wall / 13,390625 s CPU |
| Cache preparado, com branches | PASS; rota quente 0,010941 s; preparação real continua contabilizada na rodada |
| Segmento original de 12 nodeids | PASS; 44,13 s de processo |
| Seleção com predecessores, primeira tentativa | FAIL; houve sobreposição com a reprodução restrita, portanto experimento confundido |
| Repetição quiescente dos três casos selecionados | PASS; 65,34 s de processo; menu call 12,49 s |
| Código antigo, uma CPU própria e carga finita | Timeout reproduzido; call 15,17 s, teardown 13,46 s; servidor trabalhando |
| Menu reparado, mesma hipótese de restrição | PASS; preparação real 22,97 s, call HTTP 0,094 s, teardown 0,509 s |
| Menu e duas integrações HTTP frias reparadas, coverage | 3 PASS; preparação do menu 12,883 s; call 0,141 s; chamadas frias 12,665/12,515 s |

Armazenamento sintético vazio e Archive sintético populado são exercitados separadamente nas duas novas parametrizações. As demais rotas frias medidas ficaram abaixo de 0,06 s nessa amostra. A razão medida de custo frio instrumentado foi aproximadamente 3,63 vezes, dependente da máquina/carga. Não é garantia de tempo futuro.

A ordem real da seleção pytest foi determinismo sem rede → menu → contexto Decimal, e não a ordem textual da lista esperada. O replay quiescente não demonstrou dependência defeituosa de ordem. Não se usa a primeira tentativa sobreposta para afirmar tal dependência. Consulte `TIMEOUT_DIAGNOSIS.json`, os nove registros experimentais, `BASELINE_CPROFILE.json` e logs imutáveis.

## 7. Correção técnica implementada

O defeito técnico era acoplar um contrato de menus/transporte de 15 s ao custo de geração nativa fria. A fixture funcional `menu_server` prepara a demonstração real antes de verificar esse contrato. O mesmo Service continua sendo novo por teste; não há compartilhamento de autoridade, mock de cálculo ou exclusão de validação. Todas as asserções antigas de menu foram preservadas.

Duas novas integrações HTTP frias executam efetivamente o motor/replay, com e sem Archive sintético, verificam um oráculo Fraction de fills/saldos/NAV e a imutabilidade do cache. Essas integrações têm orçamento finito próprio de **60 s**, documentado a partir de ~13,5 s instrumentados e ~29 s sob contenção controlada, com aproximadamente duas vezes a margem do caso restrito. O prazo padrão do helper HTTP e do menu continua 15 s. O prazo de processo/segmento e o encerramento continuam limitados.

Há, portanto, organização explícita do contrato e ampliação justificada somente do orçamento das novas integrações frias. Não houve aceleração do motor financeiro nem promessa de latência do aplicativo. Não seria correto descrever o reparo como simples aumento global de timeout, nem afirmar que nenhum timeout foi alterado.

## 8. Teste anteriormente interrompido

`test_http_menus_catalog_and_selection` terminou com coverage em rodada dirigida, na reprodução restrita reparada e novamente no segmento console da campanha final. O segmento console completo terminou em 285,37 s antes de iniciar os outros grupos finais. Nenhum skip/xfail foi adicionado, e as duas integrações frias também pertencem à coleta/cobertura global. As medições diagnósticas não entram na consolidação final.

## 9. Persistência — G47-P3-001

Reprodução anterior: carregar biblioteca persistente, sair do Lab, voltar com catálogo atrasado em 1,8 s, selecionar estudo já listado, validar prévia e confirmar. O backend informava `persistence_enabled=true`; o botão UI permanecia desabilitado. Trata-se do cenário A (capacidade persistida correta, apresentação incorreta); não se demonstrou perda de dados.

Causa em `lab.js`, `refresh`, `render` e `selectStudy`: capacidade era apagada no render e catálogo/seleção dividiam AbortController e revisão. A seleção invalidava a própria atualização do catálogo. Reparo: controller e revisão próprios do catálogo, capacidade conhecida preservada na reentrada, estado inicial desconhecido explícito e descarte de callbacks obsoletos por identidade da página/revisão.

Regressões Node verificam navegação, atraso e cancelamento; navegador real verificou o mesmo atraso, nova prévia com confirmação habilitada, acesso posterior aos packs, duas abas e reinício. Os quatro packs importados continuaram com todos os bytes iguais após reiniciar. Biblioteca temporariamente inacessível foi simulada renomeando e restaurando apenas a pasta descartável própria, com paths absolutos previamente limitados à área de auditoria. O erro real apareceu sanitizado e a análise recuperou após restaurar.

## 10. Erro oculto — G47-P3-002

No baseline, confirmar importação válida seguido de `AnalysisError` HTTP 500 deixava progresso antigo, busy false e zero tabelas. O wrapper do botão carregava ticket anterior, mas `selectStudy` incrementava a revisão; a rejeição atual era descartada como se fosse resposta antiga.

Agora `selectStudy` trata a falha da própria revisão; importação e análise têm estados separados. No wheel: `IMPORT_SUCCESS` + `ANALYSIS_FAILURE`, mensagem “Importação concluída. Falha interna na análise. A evidência não foi classificada como inválida.”, zero tabelas antigas e nova tentativa válida bem-sucedida. Não há zero fabricado, fallback sintético silencioso, stack trace ou caminho privado. JSON inválido e timeout têm mensagem explícita sanitizada nos testes permanentes.

O mesmo trabalho encontrou e corrigiu o estado pendente após abandonar a página. Análise cancelada torna-se `DATA_UNAVAILABLE`; confirmação interrompida torna-se `IMPORT_UNCONFIRMED`, avisando que a cópia pode ter sido persistida e que a biblioteca deve ser consultada antes de repetir. Cancelar fetch não desfaz uma escrita já aceita pelo servidor. A reprodução real com atraso de 1,2 s confirmou esse aviso honesto. Não se declara IMPORT_FAILURE ou IMPORT_SUCCESS sem resposta confirmada.

## 11. Overflow móvel — G47-P3-003

Reprodução mínima original: BTC=1, preços/NAV 3→2, DD=1/3, distância para referência 20% = -40/3 pp. O parágrafo inseria 50 dígitos sem formatter: em viewport 390, página client 375 / scroll 412.

O parágrafo agora usa formatter exato compartilhado com duas casas de apresentação e quebra de texto. A origem de 50 dígitos continua em tooltip/inspeção, e a fração exata/API/export não muda. O fixture original passou com página client/scroll iguais em 390, 375 e 320. Fonte não foi reduzida; avisos e referência de 20% continuam legíveis.

O novo holdout DD=6/7 mantém distância exata -460/7 pp e mostra “-65,71 pp · EXCEDEU 20% observados”. O próprio parágrafo tem scroll=client em 1366, 768, 390, 375 e 320, fonte 14 px. A limitação de página com identificador muito longo observada somente no holdout adicional está separada na seção 28; não se generaliza ausência de overflow para qualquer conteúdo.

## 12. Severidades revistas

| ID | Anterior → revisão | Impacto demonstrado e situação |
|---|---|---|
| G47-P3-001 | P3 → P3 resolvido | Indisponibilidade UI incorreta, recusa segura; nenhuma corrupção ou escrita indevida demonstrada |
| G47-P3-002 | P3 → P3 resolvido | Erro real oculto como progresso antigo; nenhuma tabela financeira falsa demonstrada; agora erro explícito e estado separado |
| G47-P3-003 | P3 → P3 resolvido | Apresentação de decimal longo; cálculo e decisão do limiar corretos; formato e quebra reparados |
| G48-P3-004 | Novo P3 aberto | Overflow residual de página com identificador longo em 320/375; parágrafo de risco corrigido e métricas preservados |

Não foram demonstrados novos P0/P1/P2 materiais. A severidade não foi reduzida para obter aprovação. O novo P3 não foi ocultado nem tratado como falha financeira e não invalida a comprovação dos três casos originais. Aceitação dessa limitação para revisão/publicação cabe ao orquestrador.

## 13. Preservação das correções G4.6

Wheel novo executou novamente 189 verificações G4.5: 126 pytest + 46 HTTP + 17 HTTP bruto, todos PASS, sem omissões/skips. Os harnesses foram copiados com relocação para a área própria; expectativas históricas mantidas. O decoder de inteiros do oráculo usa blocos de sete dígitos, independente da solução produtiva.

Reexecutados: 91 casos matemáticos, nove frações especiais, séries de 1, 2, 99, 100, 101, 1199, 1200, 1201, 3000 e 9999 marcas, replay, exportação/ZIP, cache e contextos Decimal adversos. Os 446 vetores independentes de formatação, limites numéricos e cadência passaram em três testes Node separados. Não se somam vetores como se fossem 446 testes Node.

Windows: 16 cenários compostos nativos de concorrência/lock, 2/4/6 processos em três repetições, quota 31→32 e recusa do 33º, crash/reinício, 120 aquisições e observação de handles passaram. Não há mudança no lock ou quota produtivos nesta fase.

## 14. Integridade financeira e exatidão

Nenhum arquivo em `src/gridbot/`, `examples/`, nem Python produtivo do console, parâmetros, dependências ou configurações econômicas foi alterado. Não se tocaram CORE, V2 FINAL ou estratégias. O oráculo de ledger literal BUY 3@7 com fee 0,21, SELL 1@11 com fee 0,11 resulta em caixa 89,68, BTC 2, NAV 111,68 e fees 0,32; comparação e Pareto conferidos independentemente.

O traço nativo PAPER novo tem o mesmo SHA histórico esperado `9ea09ee91cb6d464368592aff9b8cf1f39b9badf5f37888b83c3386a235934e3`. Round trip: NAV/caixa 109,17147, BTC 0, fees 0,28853. Falling mark: NAV 76,26013, BTC 0,946, caixa 10,04013 e fees 0,08987. Em cada marca: NAV = caixa disponível + caixa reservado + BTC líquido × preço; reserva não é ativo adicional quando já incluída no caixa total. Fills são reconciliados por Fraction sem chamar o cálculo produtivo como oráculo.

A referência G4.6 é somente entrada esperada; a demonstração instalada foi gerada novamente. A adaptação do harness evita gerar duas vezes o mesmo traço e mantém todas as asserções independentes (`PAPER_ORACLE_ADAPTATION.json`). Exposição nativa ponderada por capital-tempo e média de razões do Lab são métricas distintas, explicitadas sem equipará-las.

## 15. Testes permanentes novos

Dois novos nodeids Python parametrizados para HTTP frio real, com conservação e cache isolado; nenhum nodeid antigo removido. Onze testes Node novos em `lab_lifecycle.test.cjs`: revisão independente do catálogo, erro automático pós-importação, erro real de storage, estados de timeout/JSON, resposta obsoleta, apresentação de risco e interrupções de análise/confirmação.

Cinco contratos Node falharam no baseline e dois contratos de cancelamento falharam antes do ajuste adicional. São evidências red→green preservadas, não sete bugs independentes. O DOM/fetch reduzido desses testes verifica comportamento lógico; não substitui navegador real, layout ou segurança HTTP.

## 16. Regressões independentes e holdouts

Além do conjunto histórico reexecutado, foram criados após o congelamento dois fixtures sintéticos novos, não usados para desenhar o reparo: 1.201 marcas com primos iniciados em 50021, cadência 61 s, caixa 7/BTC 1; e três marcas 7→1→2 com identificador longo, DD=6/7. Oráculo Fraction conferiu todas as identidades NAV, BTC equivalente, média de exposição, replay e bytes/checksums exportados. Ambos PASS. Nenhuma nova pesquisa, otimização ou candle histórico.

Os fixtures originais de 100 e 1.200 marcas também foram importados pela interface do wheel. O ZIP realmente baixado pelo navegador preservou exatamente os bytes da fonte, seus checksums e a fração de exposição com milhares de dígitos, decodificada independentemente. Séries maiores foram verificadas por API/oráculos; não se afirma interação visual integral com todas as 9.999 marcas nesta rodada.

## 17. Inventário global reconciliado

Coleta nova: **3.635 nodeids distintos**, contra 3.633 anteriores. Exatamente duas adições de integração HTTP fria, nenhuma remoção. Há 132 itens identificados como propriedades. A execução final certificou **3633 PASS, 2 SKIP, zero FAIL, zero incompletos e zero timeout não resolvido**. A união de nodeids dos bundles coincide exatamente com a coleta; interseções são vazias.

Skips existentes, mantidos e identificados:

- `tests/console/test_quality.py::test_real_symlink_outside_archive_is_refused`
- `tests/cli/test_doctor.py::test_env_file_posix_permissions_restricted`

Motivos preservados: a conta Windows não permite criar o symlink real no primeiro caso; chmod 600 POSIX não se aplica ao Windows no segundo. Os dois nodeids coincidem exatamente com os skips G4.7. O teste de junction Windows é distinto e foi executado, sem convertê-lo em skip.

Os testes JavaScript e campanhas externas são contagens separadas. Não se somam à coleta Python nem se contabilizam rodadas dirigidas repetidas como testes globais adicionais.

## 18. Segmentação e reprodução

Clone final independente e limpo, em `audit/g4_8/final`, instalado editable para a certificação. Console primeiro e sem outras campanhas diagnósticas concorrentes; depois dois grupos disjuntos com no máximo dois workers. Segmentação pelo `tools.quality_gate` preservado. Limite de 1.800 s por segmento e 10.800 s por campanha; nenhum limite infinito. Durações wall dos grupos: console: 285.37 s; group0: 5047.54 s; group1: 3876.23 s. Os dois grupos posteriores se sobrepõem; a soma não é duração wall total.

Reprodução registrada nos receipts: `python -m tools.quality_gate inventory --out ...`; `python -m tools.quality_gate run --inventory ... --pending ... --out ... --segment-seconds 1800 --budget-seconds 10800`; bundles disjuntos por `tools.quality_coverage bundle`, seguidos de `tools.quality_coverage combine`. Comandos completos e env seguro estão nos scripts/receipts próprios. Perfil Hypothesis `ci`, max_examples 300 e overrides preexistentes foram mantidos.

Não se desligou warning, coverage, branch coverage ou teste para obter PASS. Identidade de módulos, configuração e pacotes é a mesma em todos os segmentos. O runner de qualidade e as configurações não foram modificados.

O intervalo aproximado da certificação, pelos receipts de inventário e consolidação, foi 2026-10-27T10:22:29.800678+00:00 até 2026-10-27T11:52:01.758087+00:00. A retomada posterior apenas inspeciona resultados já concluídos e integra documentação; não é contabilizada como tempo de testes.

## 19. Cobertura consolidada válida

Coverage real consolidada: **96.46987628%**, threshold original **85%**, exit code 0. **121 arquivos de produção** medidos; 11531 de 11836 statements cobertos e 2816 de 3036 branches cobertos. Cálculo independente: 100 × (covered_lines + covered_branches) / (num_statements + num_branches), reconciliado com o resultado do coverage.py. Não se calculou média de percentuais.

Somente arquivos de coverage novos dos segmentos finais foram combinados. Não há mistura de G4.7, diagnósticos, wheel, pytest dirigido ou código pré-freeze. Fonte inalterada conferida no encerramento. `coverage/combined/coverage.json`, dados binários coverage, bundles com hashes e `GLOBAL_FINAL.json` permitem auditar módulo e nodeid.

## 20. JavaScript

**44 testes Node PASS** no código congelado: 33 anteriores + 11 novos. Rodada separada do contrato matemático/cadência: três testes com 446 vetores independentes PASS. Todos os arquivos `.test.cjs` aplicáveis foram incluídos. Node é o runtime instalado; ferramenta de formatação temporária veio do registry oficial, em cache próprio, sem mudar dependências do projeto.

## 21. Navegador real

IAB/Chromium em loopback, wheel instalado limpo. Jornada: biblioteca → importação explícita → análise → comparação/Pareto → navegação → retorno → erro controlado → retry → replay EQUIVALENT → export autorizado → reinício → acesso aos quatro packs. Duas abas mantêm análises independentes; respostas atrasadas não substituem a última seleção. Catálogo usa atraso finito real no harness, e a capacidade de persistência permanece coerente.

Visão geral e painéis Patrimônio/BTC/Risco recusam histórico não autorizado com DATA_UNAVAILABLE; após escolha explícita da fonte sintética, mostram gráficos e comparação das duas contas. Demonstração PAPER conserva a legenda de cadência observada de 60 s. Não se chamou esse intervalo de declaração do dataset. Pareto é limitado a grupos equivalentes, sem vencedor financeiro global.

Capturas reais em 1920×1080, 1366×768, 768×1024, 390×844, 375×812 e 320×740. A imagem `captures/wheel-risk-readable-390.jpg` foi inspecionada visualmente e mostra o texto completo de risco legível; screenshots full-page e geometria DOM são evidências adicionais separadas. `wheel-paper-1366.jpg` e `wheel-pareto-1366.jpg` registram o wheel. Medição estrutural não é descrita como revisão visual exaustiva de cada pixel de todas as capturas.

Downloads reais ZIP/JSON/SVG foram movidos individualmente de seus paths recém-retornados pelo navegador para a área própria; nenhum download preexistente do usuário foi alterado. O JSON PAPER baixado passou novamente no oráculo independente de fills e saldos. As abas criadas foram fechadas e o viewport restaurado. Faults/atrasos são exclusivos do harness; assets instalados permaneceram iguais aos do wheel.

## 22. Wheel

Build novo do SHA executável `f75bef168f9f7dba077f91870460a55f27a6b972`: `gridbot-0.1.0.dev0-py3-none-any.whl`, 345338 bytes, 144 membros, SHA-256 `206887c7deb4872afefce5e4f4d840adb15fdf5ab5da78ffa48501ffcc969107`. Foram conferidos byte a byte 138 arquivos instalados contra o conteúdo do build. Assets JS/CSS/HTML, evidências sintéticas e código de schema estão presentes.

O contrato de schema é implementado em Python (`lab/packs.py`) e ajuda normativa empacotada; não se afirma existir JSONSchema independente ausente. Build/instalação e oráculos usam wheel novo, não artefato G4.6/G4.7.

## 23. Instalação limpa, editable e Windows

Ambiente wheel novo sem editable, com imports comprovadamente em site-packages e sem source/final no sys.path. Navegador, 189 casos e oráculos executados nele. Instalação editable nova no clone final utilizada pela campanha global. CLI instalada e `start_console.cmd` do checkout congelado iniciaram, responderam HTTP 200, criaram biblioteca própria vazia válida e serviram o asset numérico correto. Help PASS.

O smoke encerra deliberadamente apenas seus filhos em Windows Jobs; não alega encerramento gracioso da CLI. Os servidores do navegador encerraram por shutdown solicitado pelo watchdog próprio. Nenhuma instalação depende do original, seus caches ou históricos privados.

O campo herdado `source_checkout_and_original_project_not_used` no JSON do harness CLI se refere aos checkouts protegidos, não à ausência de qualquer fonte. O modo editable usa intencionalmente o clone isolado `final`; o modo wheel usa site-packages. Essa nomenclatura ampla foi esclarecida em `CLI_EVIDENCE_SCOPE_CLARIFICATION.json`, preservando o receipt bruto.

`pip check` terminou com exit code 0 no ambiente wheel e no editable, sem requisitos quebrados. Nenhuma dependência foi alterada.

## 24. Segurança e qualidade

Ruff check PASS, Ruff format check PASS em 320 arquivos; Mypy strict PASS em 283 arquivos; pre-commit all-files e hooks do commit executável PASS; Gitleaks staged, intervalo de commits e cópia de toda a árvore rastreada PASS; `git diff --check` PASS. A rodada documental tem receipts próprios de hooks/scan no encerramento. Um scanner com erro não foi contado como PASS.

189 regressões preservam traversal/ZIP, checksum, permissões independentes de redistribuição, HTTP/CSRF/rebinding, payload bruto, quota e limites. Testes produtivos de arquitetura/segurança também pertencem à suíte global. Autorização de export é por sessão e por bytes; licença autodeclarada no pack não concede redistribuição. Após reiniciar, o grant anterior não autoriza o novo processo. Não foram alteradas dependências, exposição HTTP ou controles de segurança.

Incidentes de engenharia foram mantidos: quoting inicial de npm.cmd e Git com nome contendo espaços falhou no wrapper; foi corrigido usando executável direto e argumentos estruturados. Ruff/Mypy apontaram problemas no teste novo antes do freeze e foram corrigidos. A primeira tentativa do controlador CLI encontrou harness já existente e abortou antes de executar o produto; foi criado nome próprio. Algumas esperas de locator expiraram enquanto a UI terminava trabalho ou por título esperado incorreto; snapshots seguintes comprovaram o estado real. Nenhum desses comandos foi renomeado retroativamente para PASS nem incluído na certificação global.

Somente GETs GitHub administrativos, downloads de dependências oficiais e rede loopback de teste foram usados. Sem Binance, credenciais de trading, carteiras, LIVE, Testnet ou coleta. Não se escaneou nem listou diretório corporativo. Logs brutos ficam locais; cópias de entrega redigem perfil pessoal, cookies e hostnames quando presentes, mantendo hashes da origem e da cópia.

## 25. Holdouts adversariais após congelamento

Holdouts novos: primos/cadência inéditos (1201), expansão longa de risco (6/7), erro 500 pós-importação, troca rápida de três estudos com delay, duas abas, confirmação interrompida, pasta de biblioteca indisponível/restaurada e reinício com quatro packs. Oráculos novos: PASS; estados UI: PASS para os três reparos; novo limite móvel P3 registrado sem modificar executáveis após o freeze.

Não se executou fuzzing infinito, ataque externo, novo backtest de pesquisa ou busca de parâmetros. Corridas assíncronas foram provocadas com atrasos finitos próprios. O servidor sequencial ainda pode atrasar outras chamadas durante cálculo frio; isso é uma limitação real, não deadlock comprovado.

## 26. Commits locais

Commit executável: `f75bef168f9f7dba077f91870460a55f27a6b972` — `fix(console): isolate native HTTP budgets and repair Lab request lifecycle`. Um commit integrado contém os reparos e as regressões necessárias; não houve necessidade de fragmentação artificial ou commit vazio.

Commit documental posterior: título `docs: record G4.8 final quality and UX evidence`. SHA de entrega e delta somente documental registrados em `FINAL_DELIVERY.json` e na resposta final. Os blobs executáveis do commit documental são idênticos aos blobs do commit certificado; os hashes próprios da árvore de execução permanecem preservados, com as diferenças de EOL previamente reconciliadas na seção 3. Nenhuma ação remota foi executada.

## 27. Arquivos modificados

Delta executável desde G4.6, exatamente:

- `research_console/static/lab.js`
- `research_console/static/style.css`
- `tests/console/test_console.py`
- `tests/console/lab_lifecycle.test.cjs`

Documentos novos, sem sobrescrever relatórios antigos:

- `docs/reviews/G4_8_FINAL_QUALITY_GATE_AND_UX_REPAIR_AUDIT.md`
- `docs/G4_8_CHANGELOG_AND_PR_UPDATE.md`

Nenhum cache, build, raw histórico privado ou credencial foi adicionado ao Git. Scripts, logs, wheel, medições e screenshots permanecem na área exclusiva de auditoria. Os quatro relatórios públicos históricos não rastreados continuam não rastreados e inalterados; os seis históricos do projeto original também.

## 28. Limitações remanescentes

1. O reparo do gate não acelera geração nativa nem torna o servidor paralelo. Cálculos frios próximos ao limite do pack ainda podem exceder o prazo UI de 15 s. Agora a falha é visível e retry pode aproveitar cálculo já concluído; isso não é SLA ou cancelamento transacional do servidor.
2. Novo G48-P3-004: com identificador sintético muito longo, o documento mediu scroll 370/client 360 em viewport 375 e scroll 370/client 305 em 320. O parágrafo de risco não extravasa (308/308 e 253/253 respectivamente), com 14 px e informação íntegra. Inspeção posterior isolou o token longo no label da conta (223 client/329 scroll) e nas legendas (253/329), com overflow visible e quebra normal. Tabelas largas já têm scroll próprio intencional. Controle na mesma viewport320 com o identificador curto do pack1201 voltou a 305/305; retornar ao identificador longo repetiu 305/370. `NARROW_LAYOUT_DIAGNOSIS.json` e `ACTUAL_BROWSER_ADDENDUM.json` complementam, sem sobrescrever, o registro inicial cuja causa ainda estava indeterminada. Recomenda-se reparo focalizado de quebra/min-width e regressão permanente numa próxima decisão. Nenhum código executável foi alterado depois do freeze.
3. A certificação é Windows/Python e hardware/carga observados, segmentada, não execução monolítica de todos os nodeids no mesmo processo. Não prova todos os ambientes, casos futuros ou adversários possíveis. As propriedades permanecem limitadas e reproduzíveis.
4. Browser/holdouts são amostras selecionadas e sintéticas; não demonstram validade econômica, vantagem financeira ou segurança operacional. O risco indicativo de 20% continua referência analítica sem garantia.
5. A G4.7 permanece bloqueada historicamente; G4.8 não atualiza PR, CI remoto ou release automaticamente. O P3 adicional deve ser explicitamente aceito ou priorizado pelo orquestrador antes de publicação.

## 29. Estado remoto somente leitura

Consulta final administrativa em 2026-10-27T16:30:05.618887+00:00, registrada em `REMOTE_FINAL.json`, feita via GitHub CLI GET. PR #2: estado open, merged=False, HEAD `bff062beea10bd0ccc614e852797b643aa887497`; main remota `88390ac0b3726c50b548e5087acfa39982d76342`. Checks: 0; statuses: 0; reviews: []; Actions enabled=False; tags=0; releases=0. Referências comparadas à consulta inicial. Nenhum push, merge, atualização de PR, tag, release ou habilitação de Actions foi feito. A candidata local não aparece como se já fosse o HEAD remoto testado.

## 30. Recomendação técnica e gates

Recomenda-se submeter esta candidata local e o inventário de evidências ao ChatGPT orquestrador. O timeout do contrato de teste tem causa demonstrada e correção reproduzível com coverage; os três P3 originais estão resolvidos; suíte e cobertura globais foram efetivamente concluídas. A atualização futura da branch remota exigirá nova autorização e revisão explícita do P3 móvel residual. Não executar publicação, merge, Actions, tag/release ou G5 nesta fase.

Vereditos da candidata executável auditada:

```text
G4_8_TIMEOUT_ROOT_CAUSE_RESOLVED
G4_8_UI_FINDINGS_RESOLVED
G4_8_GLOBAL_TESTS_PASS
G4_8_GLOBAL_COVERAGE_PASS
G4_8_RELEASE_CANDIDATE_READY_FOR_REVIEW
FINANCIAL_RESULTS_PRESERVED
NUMERIC_EXACTNESS_PRESERVED
G4_6_REPAIRS_PRESERVED
EVIDENCE_PACK_SECURITY_PRESERVED
PUBLIC_WHEEL_INSTALLATION_PASS
ORIGINAL_GRIDBOT_PRESERVED
FROZEN_V2_PRESERVED
REAL_TRADING_DISABLED
GITHUB_PUSH_NOT_PERFORMED
```

READY_FOR_REVIEW inclui o P3 adicional declarado; não equivale a autorização de publicação nem a declaração de ausência universal de bugs. Encerrado para revisão do orquestrador.

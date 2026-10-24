# G3.1 — Global Quality Gate Closure

Auditoria técnica local, 23/10/2026, Windows/Python 3.13.16.
Fechamento de validação segmentada: **3.420 Python PASS + dois SKIP**, mais
**19 JavaScript PASS**; zero nodeids pendentes. Cobertura nativa consolidada:
**96,52624362001981%**, threshold original de 85%, relatório exit 0.
Nenhuma alteração financeira, pesquisa econômica ou publicação.

## 1. Baseline G3

Entrada limpa: `183efd784c0df142abb719ee3a979117ca112fe4`, branch
`feat/g3-quality-release-candidate`. Lidos G1, G2, relatório G3 e proposta de PR,
diagnósticos R1 de timeout/Decimal, configuração, runners, testes, segurança e
contratos financeiros. O original permanece somente leitura em 528f8c4.

## 2. Git e autoridade

Branch derivada: `fix/g3-global-quality-gate`. Primeiro commit:
`c14aa50` — partições auditáveis, consolidação estrita, sete regressões de tooling
e procedimento reproduzível. `5cd2e66` fecha a validação dos fontes efetivamente
medidos e permite subdivisão unitária. Nenhuma mudança em src, estratégias, CORE, V2,
fees, BUY/SELL, parâmetros, corpus, constraints ou resultados financeiros.
Não houve acesso a conteúdo corporativo, credenciais, Binance, LIVE/Testnet,
coleta prospectiva, campanha histórica, Actions, push ou merge.

## 3. Inventário estável

Baseline: **3.414 nodeids Python**; coleta repetida retornou o mesmo conteúdo
do catálogo G3, SHA-256 `92c63278d99397b4b681e82777521d169b202e4dec44bedda4160bd443a1cb96`.
Oito casos de infraestrutura adicionados: inventário atual **3.422**.
Cada parametrização é um nodeid; exemplos/steps Hypothesis não são novos testes.

| Escopo primário do módulo | Coletados atuais | Pendentes originais G3 |
| --- | ---: | ---: |
| application | 1.277 | 734 |
| architecture | 301 | 0 |
| backtest | 271 | 265 |
| cli / config | 57 / 35 | 0 |
| console | 137 | 0 |
| domain / strategy / portfolio | 430 / 216 / 158 | 0 |
| marketdata / observability | 53 / 36 | 0 |
| paper | 217 | 217 |
| storage | 209 | 209 |
| tooling / repository | 25 | 0 |

Papéis transversais (ledger, ciclo de ordens, conservação, persistência) foram
identificados pelos imports/chamadas AST e pelo contrato de cada módulo;
não devem ser somados aos escopos primários. Propriedades foram identificadas
pelo wrapper real e classes de máquina. Não se presumiu custo pelo nome.

## 4. Reconciliação das contagens antigas

Os **2.006 PASS = 1.987 Python + 19 JavaScript**. Reconstrução por testcase JUnit,
classname/nome parametrizado e inventário, não apenas pela soma dos resumos.
Nove módulos application: 542 PASS; grupo decomposto: 1.308 PASS + um SKIP;
console: 136 PASS + um SKIP; controle de propriedade: um PASS por log/recibo.
União: 1.987 PASS e dois SKIP, sem sobreposição. Complemento: 1.425 pendentes.
O controle pontual tinha log/exit 0, não JUnit; essa diferença foi preservada.
Não foi necessário corrigir as contagens da G3.

## 5. Dois skips preservados

- `tests/cli/test_doctor.py::test_env_file_posix_permissions_restricted`:
  contrato chmod POSIX, preexistente e inaplicável neste Windows.
- `tests/console/test_quality.py::test_real_symlink_outside_archive_is_refused`:
  conta Windows sem permissão para criar symlink real. Guardas simulados não
  substituem a execução desse caso em ambiente habilitado.

Nenhum novo skip/xfail ou privilégio global foi introduzido.

## 6. Os 1.425 pendentes

734 application, 265 backtest, 217 paper e 209 storage, em 63 módulos.
Seus nodeids estão preservados no manifesto G3 e foram comparados por igualdade
com a nova coleta. A campanha começou por eles; oito casos novos de tooling
foram acrescentados de forma explícita, sem alterar o inventário histórico.

## 7. Origem do exit 2

O processo foi `python -m coverage json`, sobre a consolidação nativa **parcial**
da G3. Log: `Coverage failure: total of 70 is less than fail-under=85`.
Não foi pytest exit 2, interrupção, crash ou falha financeira. É uma falha real
do threshold naquele relatório incompleto, preservada como tal.

O novo consolidador reproduziu exatamente os relatórios de **104 módulos** e
todos os totais antigos: 7.538/10.415 linhas e 1.656/2.712 ramos, 70,038851%.
Esse ensaio deliberadamente incompleto retornou 1 no runner novo; não é um PASS
global nem uma falha nova de asserção. Comprova equivalência da consolidação.

## 8. Configuração e instrumentação

`source=["gridbot"]`, `branch=true`, `fail_under=85`; exclusões originais intactas.
Configurações coverage/pytest foram comparadas por TOML com 2171548: iguais.
Coverage 7.16.2, pytest-cov 7.1.0, pytest 9.1.1, Hypothesis 6.168.5;
núcleo ativo **CTracer**, sem fallback Python. Perfil CI 300, com limites locais
dos decoradores/máquinas preservados. Não houve instalação/upgrade de dependências.

O source original cobre o pacote financeiro, não toda a árvore do checkout.
Console Python tem evidência dirigida G3 de 95,45%, separada; JS tem 19 testes
próprios. Não misturamos o source diferente do console no merge nativo.
Nem testes/tools nem novos módulos relevantes foram excluídos para elevar o valor.

A documentação oficial explica os núcleos e a indisponibilidade de branch sysmon
em Python 3.13: [coverage cores](https://coverage.readthedocs.io/en/7.16.2/config.html#run-core).
Não trocamos Python nem removemos branches para reduzir custo.

## 9. Plano determinístico e retomada

180 segmentos iniciais, 1.428 casos: 1.425 pendentes e três testes do runner.
Inicialmente quatro casos adicionais do consolidador; após a correção de scope,
cinco casos atuais substituem essas evidências. Propriedades/máquinas
isoladas; demais lotes até 20 do mesmo módulo. Prazo inicial 300 s por segmento,
orçamento total 5.400 s. Inventário/união/disjunção verificados, sem -x/--lf.
Worker novo por segmento, logs/phases/JUnit/CPU/parede e banco de cobertura próprios.
Falha/timeout não interrompe a execução dos segmentos independentes seguintes.

Onze bancos G3 concluídos foram copiados com hashes, sem alterar os originais.
Compatibilidade reconstruída por Git, logs, versões e configuração; não é um
hash contemporâneo de cada execução antiga. Console source distinto, banco
parcial já combinado e todos os TIMEOUTs foram excluídos como inputs do merge.

Bundle exige fases completas, logs/hashes válidos, identidade compatível e
nodeids sem sobreposição. Timeout não certifica nem calls verdes anteriores ao
corte. Dados incompatíveis não são automaticamente aproveitados.
O procedimento manual, finito e retomável está em
[G3_1_VALIDATION_PROTOCOL.md](../G3_1_VALIDATION_PROTOCOL.md).

A campanha inicial consumiu 5.399,53 s, concluiu 168 segmentos/1.348 casos e
preservou cinco TIMEOUTs (29 casos não certificados); sete segmentos/51 casos
não começaram. Nenhuma call verde do processo interrompido virou PASS certificado.
Restaram 77 casos antigos e oito de tooling. A retomada usa 79 segmentos regulares
unitários (600 s por caso/2.400 s totais) e seis propriedades/máquinas isoladas
(1.200 s por caso/4.800 s totais), no máximo dois workers principais num host de
12 processadores lógicos. Seus tempos são observações concorrentes, não benchmark
controlado de melhoria de velocidade. Não há agendamento ou processo residente.

## 10. Execuções concluídas

A campanha inicial concluiu os 734 application e os 265 backtest anteriormente
pendentes. Os testes de backtest são os contratos sintéticos já existentes;
nenhum estudo econômico ou dataset real foi executado novamente. O manifesto
anexo atribui cada nodeid a exatamente um segmento certificado. Reexecuções de
diagnóstico, exemplos Hypothesis e probes não aumentam a contagem distinta.

Na retomada, `TestPaperMachine::runTest` passou em 573,69 s com cobertura;
`test_last_slot_and_next_append_are_atomic_and_typed` passou em 387,37 s.
`TestTwoGenerationMachine::runTest` passou em 1.099,24 s (CPU 987,78 s),
com os 30 exemplos × 15 steps configurados intactos. A retomada regular
concluiu 79/79 casos em 1.674,67 s, incluindo as oito regressões atuais.
Os prazos de 300 s eram insuficientes para esses casos neste ambiente.
Os resultados restantes e a reconciliação final constam nas seções 17 e 25.
As seis verificações isoladas terminaram com PASS em 2.270,27 s no total.
Replay tardio/duplicata/quarentena: 271,47 s; falhas atômicas: 2,46 s;
PersistedSellMachine: 168,46 s; TerminalJournalMachine: 154,83 s.

| Evidência certificada, sem sobreposição | Python PASS | SKIP |
| --- | ---: | ---: |
| G3 reconstruída | 1.987 | 2 |
| Primeira campanha G3.1 | 1.348 | 0 |
| Retomada regular | 79 | 0 |
| Retomada de propriedades/máquinas | 6 | 0 |
| Total atual | **3.420** | **2** |

Os 19 JavaScript foram novamente aprovados, separados do inventário pytest.
União Python + JS: **3.439 PASS distintos**, dois SKIP, zero pendentes.
Todos os 1.425 pendentes originais foram concluídos; oito regressões são novas.

## 11. Tentativas incompletas preservadas

| Campanha inicial | Casos sem certificação | Limite efetivo |
| --- | ---: | ---: |
| segment-0131, hardening PAPER | 20 | 300 s |
| segment-0138, PaperMachine | 1 | 300 s |
| segment-0143, diferencial de simulação | 6 | 300 s |
| segment-0151, TwoGenerationMachine | 1 | 300 s |
| segment-0172, replay com duplicata/quarentena | 1 | 65,2 s restantes |

Sete segmentos adicionais (51 casos) não começaram antes do orçamento global.
Os cinco TIMEOUTs permanecem no manifesto, mesmo quando uma retomada posterior
conclui o mesmo nodeid. Seus bancos parciais não participam da cobertura.
Os ensaios de merge parcial retornaram não zero deliberadamente: testes ainda
pendentes e, no primeiro, cobertura inferior a 85%. Não são certificados globais.

## 12. Defeitos comprovados

**P2, infraestrutura nova de consolidação, corrigido:** verificar apenas o
`run.source` declarado não restringia os arquivos efetivamente presentes no banco
coverage. Um banco de prova com `foreign.py`, uma identidade de teste simulada
e um nodeid artificial podia produzir 100% no protótipo. Esse probe foi isolado
dos resultados financeiros e nunca entrou no merge real.

Correção em `tools/quality_coverage.py::validate_measured_files`: exigir dados de
branches, recusar qualquer arquivo externo ao inventário nativo e exigir união
igual aos 104 módulos esperados. A reprodução posterior recusa o mesmo banco
com `coverage contains foreign source files`. A regressão também cobre source
faltante e banco apenas de linhas; os onze inputs legados reais foram aceitos.
Quatro execuções anteriores do módulo de testes alterado foram explicitamente
invalidadas. A retomada executa os cinco casos atuais, incluindo a regressão nova.

Não foi comprovada falha nova nas regras financeiras. Um timeout por si só não
permite afirmar ausência de bug nem classificar o caso como falha de asserção.

**P3, bookkeeping privado de evidência, corrigido:** o helper de medição produziu
`SEGMENT_COVERAGE_FIRST.json`; ao terminar, o harness gravou seu recibo como
`segment_coverage_first.json`. No filesystem Windows esses nomes colidem.
O recibo substituiu a tabela derivada de 179 percentuais; a montagem do manifesto
falhou explicitamente com `KeyError: rows`, sem gerar manifesto público parcial.
Os bancos brutos, resultados dos testes e merge consolidado permaneceram intactos.
A tabela foi regenerada dos mesmos bancos usando um nome distinto do recibo,
com verificação dos hashes antes/depois. Não se repetiu nenhum teste financeiro.
O helper é privado; essa colisão não pertence ao runner público distribuído.

## 13. Performance: medidas e limites

| Observação | Resultado local | Interpretação |
| --- | --- | --- |
| Propriedade de conservação, campanha instrumentada | 240,40 s; CPU 238,78 s | Corpo domina; setup/teardown na ordem de ms |
| PaperMachine concluída | 573,69 s; CPU 562,91 s | Trabalho de CPU, sem deadlock observado nessa execução |
| TwoGenerationMachine concluída | 1.099,24 s; CPU 987,78 s | Prazo ampliado permitiu terminar sem reduzir exemplos/steps |
| Journal 255/256, último slot | 387,37 s; CPU 377,61 s | Replay/validação caros no limite de capacidade |
| Uma entrada explícita de conservação, cProfile sem coverage | 7,52 s; CPU 7,44 s; 16.980.791 chamadas | Diagnóstico do corpo existente, não novo teste distinto |
| Mesmo seed de controle G3 | 2,72 s sem coverage / 8,87 s com branches | Overhead observado num único caso; não extrapolar à suíte |

No perfil da entrada explícita: 132.344 chamadas a `dataclasses.replace`,
207 a `sell_terminal._analysis`, nove projeções. Tempos cumulativos: análise
7,36 s, replace 7,00 s, evaluate 5,49 s, eligible_qty 4,74 s; sobrepõem-se.
Uma construção isolada existente de cenário também mostrou 1.437 replace
(324 primitivas). Perfis foram feitos com outros testes ativos; não são
benchmarks controlados nem prova de ganho de velocidade.

Separação causal: **A/B** fixtures não dominam os casos medidos; o fixture de
histórico já possui cache local de codificação. **C** instrumentação aumenta o
custo, preservada com CTracer/branches. **D** reconstrução recursiva e replay
revalidam grafos financeiros e copiam estruturas; os perfis demonstram custo,
mas não provam uma ordem assintótica universal. **E** conservação, corrupção,
capacidade e máquinas geradas fazem trabalho intencionalmente amplo. **F**
Windows/concorrência afetam as observações, sem comparação Linux que permita
atribuir a causa ao sistema operacional. Não foi comprovado vazamento de memória.

Amostras de memória/CPU restringiram-se aos PIDs dos workers desta campanha;
não representam pico agregado da suíte nem teste de heap. Não foram removidos
oráculos Fraction/Decimal, validações, parametrizações ou steps Hypothesis.
O perfil CI real foi confirmado dentro de pytest: PaperMachine 4×4,
TwoGeneration 30×15, PersistedSell 20×12, TerminalJournal 6×8, todos com
deadline=None e derandomize=True, conforme seus decoradores existentes.
Esses valores são limites de geração configurados; não são uma contagem
observada de passos nem testes distintos adicionais.

## 14. Correções implementadas

- Runner finito com inventário real, partições disjuntas, orçamento explícito,
  processo separado, fases completas, CPU/parede, JUnit e banco por segmento.
- Retomada por complemento de nodeids certificados e opção `--max-cases 1` para
  subdividir lotes caros sem reduzir o conteúdo de cada teste.
- Consolidação por identidade, hashes, source efetivamente medido, branches,
  união/disjunção de testes e threshold original.
- Oito regressões de tooling: partições, duplicatas, fases ausentes, teardown,
  timeout, mudança de identidade/dados, path escape e scope de cobertura.

Não foi demonstrada uma otimização financeira segura necessária para fechar
essa infraestrutura. Cache compartilhado de objetos adulterados nos testes
adversariais poderia ocultar corrupção; não foi introduzido.

## 15. Equivalência e invalidação

Nenhum arquivo em src, console ou fixtures financeiras mudou desde 183efd7.
Configuração pytest/coverage, constraints, versões e helpers foram comparados;
as identidades estão no manifesto. O merge dos onze bancos G3 reproduziu cada
relatório por arquivo e todos os totais antigos. A equivalência das evidências
G3 é retrospectiva, apoiada em logs/Git/ambiente, com essa limitação explícita.

Os testes novos alterados após a correção de scope foram invalidados e
reexecutados; seus bancos obsoletos permanecem privados, fora da consolidação.
Não há mistura de coverage do console, banco já combinado, tentativa cortada,
banco de probe estrangeiro ou código financeiro divergente.

## 16. Cobertura por segmento

O manifesto registra para cada banco certificado o SHA-256, número de nodeids,
linhas/arcos registrados e percentual nativo parcial calculado pela API coverage.
Os primeiros 179 inputs (onze G3 + 168 da campanha) foram reportados em 198,85 s,
sem alterar seus hashes; após a colisão de nomes descrita na seção 12, sua
tabela foi regenerada em 158,61 s. Os 79 inputs regulares foram reportados em
119,91 s e os seis finais em 5,39 s. São 264 medições individuais preservadas.
Segmentos exclusivos de tooling podem não executar
código gridbot; nesse caso o percentual é nulo, não uma cobertura financeira.
Esses percentuais não são somados, promediados nem tratados como gates próprios.
O gate utiliza a união dos dados reais, descrita na seção seguinte.

## 17. Cobertura consolidada

**264 bancos nativos certificados**, de 265 segmentos proprietários de nodeids
(um segmento console sem banco nativo). Inputs: onze G3, 168 da primeira campanha,
79 da retomada regular e seis das máquinas/propriedades. Nenhum banco cortado,
obsoleto ou de probe participa. Oito testes exclusivos de tooling não executam
fontes nativos; seus bancos vazios não acrescentam cobertura financeira.

| Medida nativa | Resultado |
| --- | ---: |
| Módulos esperados/medidos | 104 / 104 |
| Linhas executadas / statements | 10.155 / 10.415 |
| Branches executados / possíveis | 2.516 / 2.712 |
| Linhas / branches faltantes | 260 / 196 |
| Branches parcialmente cobertos | 174 |
| Linhas excluídas preexistentes | 85 |
| Cobertura combinada | **96,52624362001981%** |

Fórmula: `(10.155 + 2.516) / (10.415 + 2.712) × 100`.
Somente linhas: 97,5036%; somente branches: 92,7729%.
Não é média das porcentagens dos segmentos ou arquivos. O denominador e as
exclusões são os mesmos da reprodução inicial; nenhum módulo foi retirado.

| Camada | Linhas + branches, ponderados pelos denominadores |
| --- | ---: |
| application | 98,84% |
| backtest | 96,86% |
| cli / config | 90,99% / 98,89% |
| domain | 97,81% |
| exchange | 95,20% |
| infra / marketdata | 95,74% / 95,73% |
| observability | 100,00% |
| paper | 94,71% |
| portfolio | 99,23% |
| storage | 91,41% |
| strategy | 98,97% |

Módulos vazios não recebem interpretação de cobertura comportamental.
`gridbot.__main__` conserva três statements não medidos: subprocessos não são
instrumentados implicitamente. O detalhamento dos 104 arquivos, incluindo essas
lacunas e caminhos de erro de storage, consta no manifesto. Console Python
95,45% e testes JS permanecem escopos separados.

Merge final: exit 0 em 11,42 s. JSON SHA-256:
`8a399bc6e4605464e3d28a3970009d2050986ec0fb8b2d135363015fccb84c3b`.
Banco combinado SHA-256:
`baf65a10d6a0a9384f41424c733f6362858a4b1b2604faf21d2fb0d24a355601`.

## 18. Threshold original

`coverage report --rcfile=pyproject.toml --data-file=<banco-consolidado>` passou
com **exit 0**, sem `--fail-under` substituto, source reduzido ou exclusão nova.
A saída textual arredonda para 97%; o JSON preserva 96,52624362001981%.
O gate original é global nativo de 85%, não um requisito de 85% por arquivo.
O consolidador também confirmou **3.422/3.422 nodeids**, lista de pendentes vazia
e source/branches iguais à configuração. Assim testes e cobertura têm PASS
independentes, ambos demonstrados.

## 19. Integridade financeira

Referências G3 preservadas: 162 carteiras reconciliadas e 69.174 marcações,
demo determinística e exports reconciliados. São resultados arquivados da G3,
não uma nova campanha histórica nesta fase. Os contratos sintéticos de
conservação/replay, estados BUY/SELL, reservas, quarentena, fees e segunda BUY
foram executados conforme seus testes existentes; os resultados exatos por
nodeid constam no manifesto. Não foram fabricadas novas rentabilidades.

Revalidação dirigida de 14 casos inclui comparação BTC físico/BTC equivalente,
NAV, decomposição patrimonial, demo sem rede e isolamento Decimal; passou em
29,96 s pytest/30,85 s de parede. A regressão financeira com contexto Decimal
pequeno foi executada depois do console no mesmo processo, sem vazamento.
Isso cobre a interação conhecida, não todas as ordens possíveis da suíte.

Os 1.665 hashes do original foram conferidos; HEAD, seis não rastreados e V2
são registrados novamente no fechamento. SHA-256 V2 FINAL:
`44e9639554d01c13e2e0648613e7904a6f1649ca934b00b3821021aa28582249`.
104 blobs Git financeiros correspondem à referência original; sete diferenças
de bytes de working tree já existentes são CRLF/LF. Não se afirma igualdade de
bytes entre checkouts distintos. O diff src da G3.1 é vazio.

## 20. Segurança e dependências

Ruff, formatação, Mypy strict e `pip check` passaram após a última alteração de
tooling. Não houve dependência instalada ou alterada, configuração de credencial,
API transacional, remote novo ou acesso corporativo. Os testes dirigidos incluem
Host/Origin/Fetch-Site, sessão, traversal, métodos POST e demo com rede bloqueada.
Manifesto público contém nodeids, identidades e referências relativas/hashes;
logs, comandos com caminhos locais, SQLite coverage e HTML permanecem privados.
Os nodeids exatos preservam literais sintéticos preexistentes dos testes de ACL
e cloud-sync; não foram confundidos com caminhos pessoais de execução.
Pre-commit, Gitleaks, diff-check e preservação final são registrados no fechamento.

O runner aceita diretórios de evidência novos; rejeita sobrescrita e limita o
tempo. O término por timeout restringe-se à árvore do processo de teste criado.
Essas ferramentas executam testes locais confiáveis; não são uma sandbox para
código de terceiros. Nenhum serviço, agendamento ou CI remoto foi instalado.

## 21. Research Console

Nenhum arquivo do console mudou. Foram revalidados servidor HTTP local efêmero,
assets, navegação/seleção, exports, metadata/proveniência, demo e cálculos
financeiros afetados pelo isolamento. Os 19 testes JavaScript passaram novamente
em Node, com exit 0, cobrindo filtros, ordenação exata, seleção de referência,
sessão, gráficos, drawdown, BTC equivalente, tabela acessível e proveniência.
Não se somam esses reruns à contagem de casos distintos.

A evidência visual/browser e cobertura Python dirigida 95,45% permanecem as da
G3, com fontes iguais. Não foi repetida toda a auditoria visual sem mudança de UI.
O catálogo da interface conserva o snapshot histórico `global_coverage=PENDING`;
o presente relatório é a autoridade da nova validação e não atualiza esse dado
estático silenciosamente. O console continua local/PAPER/OFFLINE.

## 22. Reprodutibilidade

Ambiente demonstrado: Windows 11 (build 26300), Python 3.13.16 64 bits,
pytest 9.1.1, coverage 7.16.2, pytest-cov 7.1.0, Hypothesis 6.168.5.
JavaScript: Node v24.19.0.
Pydantic 2.13.5/core 2.46.5/settings 2.15.0 e dotenv 1.2.4.
Constraints SHA-256:
`8f74574ee2fd2bbe65cb79b8650a8cbb17ed10026d72f54a869d5c67e328e18f`.

O [protocolo](../G3_1_VALIDATION_PROTOCOL.md) contém comandos sem caminhos
pessoais: inventory, run com limites, bundle de casos concluídos, complemento
para retomada e combine. Bancos individuais são preservados com keep=True;
[Coverage.combine](https://coverage.readthedocs.io/en/7.16.2/api_coverage.html#coverage.Coverage.combine)
opera sobre dados reais. JSON/HTML e recibos permitem verificar fontes, hashes,
linhas, branches e threshold. O manifesto comprimido e seu índice verificam a
conciliação de nodeids; os artefatos brutos privados não são publicados por
arrasto. Outro desenvolvedor pode gerar seus próprios bancos pelo protocolo.

## 23. Commits locais

- `c14aa50`: runner auditável, consolidação e sete regressões iniciais.
- `5cd2e66`: inventário efetivamente medido, oitava regressão, subdivisão unitária.
- Documentação e manifesto: commit local de fechamento, identificável pelo Git
  sem inserir autorreferência circular no conteúdo do relatório.

Commits anteriores preservados. Não houve amend, reset, rebase, push, merge,
remote novo ou habilitação de GitHub Actions. A branch main local/remota não
recebeu a candidata durante esta missão.

## 24. Limitações remanescentes

Dois skips de plataforma/privilégio são explícitos. Não há demonstração Linux,
CI remoto, todas as permutações de ordem monolítica, ausência universal de bugs
ou prontidão para trading real. A conciliação G3 legada é retrospectiva; tempos
concorrentes não constituem benchmark comparativo. Custo elevado de grafos/replay
permanece no código financeiro congelado, sem otimização presumida segura.
Percentual de cobertura não prova todas as combinações econômicas possíveis.

Um futuro trabalho de performance deve usar workload e ambiente fixos, medir
CPU/parede/memória por capacidade e verificar equivalência contra os oráculos
existentes antes de qualquer mudança financeira. Não foi iniciado nesta fase.
Resultados econômicos e avaliação prospectiva permanecem independentes do gate
de engenharia, sem nova recomendação de investimento.

## 25. Recomendação e vereditos

Encaminhar a candidata **local** à revisão de publicação pelo orquestrador.
Os gates de testes/cobertura foram fechados sem alterar o comportamento econômico.
Ruff, formatação, Mypy strict, pip check, pre-commit, Gitleaks e diff-check têm
verificações próprias; os recibos completos permanecem na área privada de auditoria.
O original continua no HEAD 528f8c4, com 1.665 hashes iguais, os seis históricos,
nenhum remote e V2 FINAL intacto. A main pública permanece em a28e6f3 e Actions
desabilitado, verificados por consultas somente de leitura.

Revisão ainda deve considerar os dois skips, limites de plataforma/ordem de
execução e o snapshot conservador PENDING ainda mostrado pela interface G3.
Isso não autoriza publicação, trading, novas estratégias, G4 ou CI remoto.
A proposta de PR permanece apenas um documento local; nenhum PR foi aberto.

- [Manifesto de execução](G3_1_EXECUTION_MANIFEST.json.gz).
- [Índice, checksums e contagens](G3_1_EXECUTION_EVIDENCE_INDEX.json).
- [Protocolo reproduzível](../G3_1_VALIDATION_PROTOCOL.md).
- [Proposta local de PR](../G3_1_CHANGELOG_AND_PR.md).

Manifesto: 361.462 bytes comprimidos, SHA-256
`95ae29861252e6068d3684da22f06d0b168d43af5efcd54ce6ab7ee85d1eeb02`.
Verificação independente reconciliou os 3.422 nodeids, proprietários disjuntos,
264 medições e **2.446 hashes de artefatos**. A validação do payload descomprimido
não encontrou caminhos pessoais; ele também foi submetido ao scanner de secrets.

```text
G3_1_GLOBAL_TESTS_PASS
G3_1_GLOBAL_COVERAGE_PASS
G3_RELEASE_READY_FOR_PUBLICATION_REVIEW
FINANCIAL_RESULTS_PRESERVED
ORIGINAL_GRIDBOT_PRESERVED
FROZEN_V2_PRESERVED
REAL_TRADING_DISABLED
GITHUB_PUSH_NOT_PERFORMED
```

PARE: aguardar revisão do ChatGPT orquestrador. Nenhuma G4 iniciada.

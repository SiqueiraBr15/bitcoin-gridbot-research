# Testes, reprodução e performance

Esta validação é local em Windows/Python 3.13. Nenhuma execução Linux ou GitHub
Actions foi demonstrada. A suíte global com cobertura permanece PENDING.

## Escopos explícitos

`python -m tools.test_catalog` coleta todos os casos e emite JSON, sem executar
corpos de teste. Foram coletados 3.277 casos. Categorias se sobrepõem:

| Categoria | Casos | Critério |
| --- | ---: | --- |
| Smoke | 169 | Lista em `ci/fast-suite.txt` |
| Unitários rápidos | 804 | domain, strategy e portfolio |
| Integração | 697 | storage, paper e backtest; não é a seleção curta abaixo |
| Financeiros | 2.569 | Contratos domain/strategy/portfolio/application/paper/backtest |
| Propriedades | 128 | Wrapper Hypothesis ou módulo properties/stateful |
| Regressão ampliada | 3.277 | Todos os casos coletados |
| Long-running observado | 34 | Call de pelo menos 1 segundo na amostra medida |

O limiar de um segundo é descritivo, não uma meta ou limite de aprovação.
Não medir um teste não significa que ele seja rápido. A identificação de
propriedades é mecânica e não conta exemplos gerados como testes separados.
Os custos por nodeid ficam em `ci/observed-test-costs.json` (1.479 observações).

O runner `python -m tools.verify --profile NOME` abre processos limitados por
alvo, padrão 90 segundos. `smoke`: 169 casos; `unit`: 804; `integration`: seleção
curta de 54 casos (engine, benchmark policy e journal); `extended`: os mesmos 930
casos da lista histórica `ci/smoke-suite.txt`, preservada integralmente. `all`
mantém todos os módulos públicos, inclusive os não executados nesta auditoria.
Alguns alvos são diretórios. Um alvo caro pode exigir limite explícito maior;
nessa situação a execução anterior é TIMEOUT/INCOMPLETE, nunca PASS.

## Resultado reproduzido

1.623 casos distintos passaram em segmentos; um caso foi pulado por depender de
chmod POSIX, inaplicável no Windows. Não se somaram reexecuções aos casos únicos.

| Segmento concluído | PASS | Tempo pytest observado |
| --- | ---: | ---: |
| domain + strategy + portfolio | 804 | 11,53 s |
| engine | 11 | 19,06 s |
| benchmark policy | 6 | 4,77 s |
| journal + arquitetura | 284 | 9,89 s |
| seleção application | 310 | 50,28 s |
| PAPER accounting | 17 | 46,98 s |
| PAPER codec | 47 | 1,30 s |
| Novos testes de demo/runner | 5 | 7,88 s |
| Configuração, CLI, logs e higiene | 139 + 1 skip | 1,88 s |

O runner novo também foi exercitado: smoke 31,80 s de parede, unit 14,87 s e
integration 38,44 s. São medições locais, sem metas universais de desempenho.
Os 930 casos históricos são subconjunto dos 1.479 casos dos sete primeiros
segmentos, conferido por igualdade de nodeids, não apenas soma de contagens.
Os testes permanecem no pacote; 1.653 casos coletados não foram aprovados nem
classificados como falha por falta de execução nesta rodada.

## Diagnóstico do timeout

A tentativa monolítica anterior com 930 casos excedeu 120 segundos. Uma seleção
adicional de contabilidade excedeu 90 segundos nesta missão; houve 320 calls
concluídas antes do corte. Esses recibos continuam TIMEOUT. Dividir por módulos
permitiu concluir os escopos necessários sem repetir uma campanha enorme.
Não foi reproduzido um deadlock. Não há experimento comparativo Linux suficiente
para atribuir o problema ao Windows.

Um caso controlado, `tests/backtest/test_engine.py::test_native_economic_roundtrip_exact_metrics_and_replay`,
levou 2,09 s sem cobertura e 7,75 s sob `coverage run --branch --source gridbot`
(aproximadamente 3,71× no tempo pytest; parede 3,17 versus 9,54 s). É apenas um
caso e uma observação por modo: não estima o overhead de toda a suíte.
A coleta de cobertura pontual não executou nem aprovou o gate de relatório global.

cProfile registrou 19.996.201 chamadas em 7,21 s no mesmo caso. Caminhos dominantes:
`sell_terminal._analysis` (202 chamadas, 5,79 s cumulativos),
`dataclasses.replace` (131.303 chamadas recursivas, 5,71 s),
`sell_reconciliation._evaluate` (4,29 s) e
`sell_inventory._eligible_qty` (10.506 chamadas, 3,83 s).
Tempos cumulativos se sobrepõem e não devem ser somados.

Fixtures puras medidas consumiram aproximadamente 3,98 ms, 19,69 ms e 54,67 ms
por construção. O custo maior aparece na validação/coordenação, não nesses
78 ms de preparação. Testes adversariais adulteram objetos com `object.__setattr__`;
compartilhá-los em cache pode contaminar outros testes. Nenhum cache de fixture
ou redução de parametrização foi aplicado sem prova de segurança/benefício.

## Mudanças e limitações

Foram adicionados runner com regressões de falha/timeout, classificação coletável
e uma demo com oráculo racional, replay e bloqueio de rede no teste. As validações
financeiras nativas não foram removidas ou otimizadas. Qualquer memoização ou
projeção incremental precisa de revisão específica de identidade, imutabilidade,
validação de objetos adulterados e equivalência econômica.

Hypothesis CI permanece com 300 exemplos; `fail_under = 85` e cobertura de branches
continuam intactos. Ruff, formatação e Mypy strict passam, incluindo examples/tools.
A comparação inicial expôs import/format e dois erros de tipagem nos novos testes;
foram corrigidos, mantendo os recibos de falha. Um erro de saída Unicode no harness
privado ocorreu depois do exit 0 do segmento CLI; o log e os eventos preservam
139 PASS e 1 skip. Não foi falha dos testes nem motivo para repetir o segmento.

## Reprodução e CI

Siga a instalação editable do README, com constraints de runtime/dev e de build.
A proposta em `ci/github-actions-proposal.yml` executa lint, tipagem, três perfis,
contratos de segurança de configuração e demos. Não habilita Actions, não contém
secrets e não substitui Gitleaks antes de release. Os comandos foram executados
localmente; sintaxe/proveniência das actions são verificadas separadamente.
Ativação remota e validação Linux ainda dependem de aprovação e execução reais.

O pacote foi instalado editable num venv novo e como wheel noutro venv; o wheel
foi importado fora do checkout e o entrypoint testado. Na publicação anterior somente `gridbot` era empacotado. O wheel G3 passa a
incluir console/assets e exemplos sintéticos; tools/tests continuam no checkout. Pins limitam resolução,
sem lock criptográfico completo ou promessa de identidade binária entre plataformas.

Método de diagnóstico: [pytest durations](https://docs.pytest.org/en/stable/how-to/usage.html#profiling-test-execution-duration)
e [constraints de build do pip](https://pip.pypa.io/en/stable/user_guide/#build-constraints).


## G3: evidências novas e pendência global

As contagens nas seções anteriores são históricas. A G3 repetiu uma propriedade
com a mesma semente CI: call 2,72 s sem tracing e 8,87 s com branches, sem reduzir
exemplos. Uma campanha segmentada teve orçamento total de 600 s (120 s para um
grupo misto, 60 s por módulo posterior). Timeouts permanecem incompletos; não são
PASS. O grupo misto foi depois decomposto sem storage: 1.308 PASS e um skip Windows
em 81,75 s sob coverage. Isso não executa os módulos de storage retirados dessa
sondagem: eles continuam listados como pendentes, sem desabilitar nenhum teste.

Ressalvas: subprocessos por segmento não provam ausência de bugs dependentes da
ordem de uma sessão global. Arquivos de coverage só são agregados de processos
que terminaram com sucesso. O relatório parcial com limiar 85 preservado não é
aprovação global, mesmo se sua porcentagem for alta. Nenhuma repetição monolítica
longa foi justificada pelos tempos observados. Mudanças no custo dominante de
validação recursiva financeira requerem autorização específica do orquestrador.

A auditoria G3 documenta a contagem final, skips, tabela por módulo, cobertura
dirigida, manifests de nodeids, comandos, comparação antes/depois e riscos.
[Relatório G3](docs/reviews/G3_QUALITY_ENGINEERING_AND_RELEASE_CANDIDATE_AUDIT.md).

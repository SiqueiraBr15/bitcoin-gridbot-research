# G4.6 — Numeric Contract Repair & Independent Revalidation

Data da campanha: 25–26/10/2026. Escopo: Research Console e Offline Research Lab,
exclusivamente local, com observações sintéticas. O executor fez uma segunda
passagem crítica e usou oráculos independentes; isso não constitui uma revisão
externa por outra pessoa. A decisão de publicação continua com o orquestrador.

```text
G4_6_NUMERIC_CONTRACT_REPAIR_PASS
G4_5_FINDINGS_RESOLVED
NUMERIC_EXACTNESS_PRESERVED
VALID_EVIDENCE_PACKS_ACCEPTED
PAPER_CADENCE_CORRECTED
INDEPENDENT_AUDIT_REGRESSIONS_PASS
GLOBAL_TESTS_PASS
GLOBAL_COVERAGE_PASS
PUBLIC_WHEEL_INSTALLATION_PASS
EVIDENCE_PACK_SECURITY_PRESERVED
ORIGINAL_GRIDBOT_PRESERVED
FROZEN_V2_PRESERVED
REAL_TRADING_DISABLED
GITHUB_PUSH_NOT_PERFORMED
G4_6_PR_UPDATE_READY_FOR_REVIEW
```

## 1. Estado inicial

A candidata publicada da G4.5 estava bloqueada por um achado P2 de contrato
numérico, com duas manifestações, e um achado P3 de comunicação temporal.
As 189 verificações históricas registravam 186 PASS e três FAIL. Eram resultados
do código anterior, e não foram reaproveitados como validação do reparo.
Os relatórios G4.5 foram lidos integralmente; os guias e relatórios G4–G4.4
pertinentes foram confrontados com a implementação.

Não houve coleta prospectiva, pesquisa econômica, otimização, nova estratégia,
Binance, LIVE, Testnet, credenciais financeiras ou movimentação de fundos.
Os testes globais exercitam funcionalidades históricas em testes locais; não
produzem uma nova pesquisa ou reavaliação de estratégias.

## 2. Branch e HEAD

Branch local: `fix/g4-numeric-contract-and-paper-cadence`.
HEAD executável final congelado: `e0ba226f31ff5aae2d253ebf0bafe20e2ae3c437`.
Origem exata da branch: `bff062beea10bd0ccc614e852797b643aa887497`.
O reparo numérico ba8bb8a é filho direto dessa origem; o reparo de lock e0ba226 é filho de ba8bb8a.
O commit posterior de entrega contém somente documentação e evidência certificada.
Seu identificador pode ser obtido com `git log -1`; não se inclui um hash
autorreferente neste documento. Os 306 arquivos do congelamento foram rechecados
por SHA-256, incluindo fontes, testes, recursos, ferramentas e configurações.

A main local permaneceu em `a28e6f35b7b0acb42cee6dc97959cdf65f6022b0`.
Os quatro relatórios públicos previamente não rastreados permaneceram fora dos
commits. O original protegido teve seus 1.665 hashes conhecidos, HEAD e seis
entradas não rastreadas conferidos, sem alterações. Manifesto V2 FINAL:
`44e9639554d01c13e2e0648613e7904a6f1649ca934b00b3821021aa28582249`.
Também foram rechecados os 7.682 arquivos inventariados da auditoria G4.5 e os
12 relatórios públicos anteriores. Nenhum conteúdo corporativo foi usado.

## 3. Identidade do código publicado auditado

Repositório público: `SiqueiraBr15/bitcoin-gridbot-research`.
PR #2: `release/g4-offline-research-lab` → `main`.
HEAD publicado: `bff062beea10bd0ccc614e852797b643aa887497`.
Main remota: `88390ac0b3726c50b548e5087acfa39982d76342`.

A reprodução usou uma instalação isolada do wheel anterior. A candidata
corrigida foi exportada por `git archive` do commit congelado, construída
novamente e instalada em outro ambiente. Nenhuma execução do wheel dependeu
do checkout original ou de datasets privados. Consultas GitHub foram GET.
Consulta final GET em 2026-10-26T17:33:14.463404+00:00: PR OPEN, SHAs preservados, Actions desativado, sem merge/auto-merge, sem nova tag/release ou review publicado pelo executor.

## 4. P2-A: reprodução anterior à correção

Fixture: `prime-100.gbpack`, 1.700 bytes, SHA-256
`3591b23214a05051fabe632d764fe002981055e0fe252b2dfa9221848ec1f6d1`.
Os mesmos bytes integram agora `tests/fixtures/g45_prime_100.gbpack`.

`read_pack` valida integralmente o contêiner, manifesto, resultados, números,
timestamps e conservação. A prévia e a confirmação aceitam o pack. O endpoint
`GET /api/lab/analysis?id=<SHA-256 do pack>` retorna HTTP 200 e JSON UTF-8 válido.
A conta PRIME_HOLD conserva caixa=1, BTC=1, preço=p−1 e NAV=p, onde p percorre
primos sucessivos desde 1009. A primeira NAV é 1009; a última é 1721.

O campo `rows[0].metrics.exact.exposure_mean_left` é uma **string JSON**
racional com 623 caracteres, incluindo `/`; numerador e denominador têm
311 dígitos cada. O valor é matematicamente correto e igual ao oráculo:

```text
Numerador: 27457116182546569951739950481219956326136326563463616991837343193516002818102543715765857345904778348464459786223873415921193148250040990166494799413887922442729144729329091916239410368342530086204546589643175973812928133052636748092859095423425408390053146806938425793919645667432194822407159520556443034635516
Denominador: 27477924624003858475903414445192553345896314300462418650249008334994377987000632915112171873443906729602001689809244019499026480944897840885886397062944449758465360609562140570167968572035685171382211285263383295469580009516827504851776487848126472505601598627505626835760788815621726194813398358416307649884009
```

O formatador anterior `model.formatDecimal`, em `static/lab.js`, recusava
componentes acima de 300 dígitos. O navegador mostrou `Formato decimal inválido`,
sem tabelas. O erro reaparecia em `showError → paint`, porque o resultado
incompatível permanecia no estado. Stack sanitizado da reprodução:

```text
Object.formatDecimal (lab.js:24)
present (lab.js:156)
results / Array.map (lab.js:699–709)
paint (lab.js:1082)
showError (lab.js:249)
Error: Formato decimal inválido
```

Cadeia demonstrada: entrada válida → cálculo exato válido → transporte válido
de uma fração de 311/311 dígitos → limite incompatível da apresentação → falha
visual e tratamento recursivo do mesmo estado. Não houve erro de NAV demonstrado.

## 5. P2-B: reprodução anterior à correção

Fixture: `prime-1200.gbpack`, 10.736 bytes, SHA-256
`8150d310a5ff6fd04ddbb50ba85a13e80638bc2c67f3ea1b57d818631b04cede`.
Preservada em `tests/fixtures/g45_prime_1200.gbpack`.

Prévia e confirmação: HTTP 200. Análise: HTTP 422 com
`source_kind=DATA_INVALID`, `reason=INVALID_SCHEMA_OR_DATA` e mensagem redigida.
Nenhum validador de entrada encontrou dados inválidos: a falha aconteceu depois
da validação e do cálculo da exposição. Os dois componentes reduzidos do
resultado têm 4.442 dígitos, acima do limite padrão CPython de 4.300 para
conversão decimal direta de inteiros. Stack sanitizado:

```text
analyze → metrics
"exposure_mean_left": str(exposure_time / observed_time)
fractions.Fraction.__str__: '%s/%s' % (numerator, denominator)
ValueError: Exceeds the limit (4300 digits) for integer string conversion
```

O handler genérico capturava esse ValueError como se fosse rejeição do pack.
A tela dizia `Schema ou dados inválidos` após a biblioteca mostrar VALIDATED.
Não era estouro de upload, ZIP bomb, encoding inválido, divisão por zero,
float, JSON numérico sem aspas ou excesso das 10.000 marcações permitidas.
Uma entrada de cerca de 10 KiB era suficiente para atingir o defeito.

Cadeia demonstrada: entrada válida → Fraction exata com denominadores coprimos
→ `str(Fraction)` → limite de conversão de inteiros do Python → captura genérica
de ValueError → 422 enganoso. A correção não desativou esse limite global.

## 6. Relação causal entre P2-A e P2-B

Há uma causa de contrato transversal e **dois mecanismos locais distintos**.
O parser limitava a magnitude dos decimais de origem; isso não limitava a
complexidade racional de médias de razões. A apresentação aceitava 300 dígitos,
enquanto a serialização direta aceitava 4.300. Nenhum desses tetos era derivado
do conjunto de resultados que o schema admitia.

Corrigir apenas o JavaScript deixa o caso de 1.200 falhar no backend; corrigir
apenas o serializer deixa o caso de 100 falhar na tela. Portanto a classificação
G4.5 de contrato comum é sustentada, mas não significa uma única linha defeituosa.
A contagem antiga de três FAIL também não corresponde a três causas independentes:
o defeito de 1.200 era observado tanto no teste matemático quanto no HTTP.
O P3 foi confirmado adicionalmente na inspeção visual.

## 7. P3: reprodução

Sem `sampling_seconds` no contexto PAPER, o gráfico anterior usava 86400 no texto
e o chamava de cadência declarada. As marcas efetivas eram
`2024-01-01T00:00:00+00:00`, `00:01`, `00:02` e `00:03`: intervalos de 60 segundos.
O eixo já mostrava 00:00–00:03 UTC. A origem do erro era o fallback JavaScript,
não os preços, o ledger, a simulação, os timestamps ou um metadado diário.

A reprodução visual confirmada está em `original-paper-confirmed.jpg`.
Uma primeira captura realizada antes de terminar a carga não continha gráfico;
ela foi retida como tentativa intermediária e não certifica o achado.

## 8. Causa raiz e alcance do reparo

O reparo alinha cálculo, transporte, apresentação e diagnóstico de erro aos
limites derivados do contrato de entrada. A soma balanceada reduz trabalho
repetido com denominadores crescentes, preservando exatamente a mesma soma.
O formatter compartilhado trata as strings canônicas com BigInt.
O tratamento de falha limpa o resultado incompatível antes de redesenhar.
A informação temporal diferencia frequência declarada, frequência observada
e frequência não demonstrada.

Nenhuma fórmula econômica foi alterada. O diff de `src/gridbot` é vazio tanto
em relação à candidata publicada quanto à main remota. Configurações de
dependências, hooks e ferramentas de qualidade também permaneceram iguais.

## 9. Contrato numérico anterior

| Etapa              | Representação anterior                               | Limite/problema                                         |
| ------------------ | ---------------------------------------------------- | ------------------------------------------------------- |
| Entrada            | Strings decimais estritas, Decimal e Fraction        | Coeficiente até 80 dígitos, adjusted −100 a 20          |
| Contêiner          | ZIP estrito e JSON limitado                          | 2 MiB comprimidos, 6 MiB de conteúdo; sem extração      |
| Modelo             | Até 60 contas e 10.000 marcas totais                 | Preço positivo, saldos não negativos, conservação exata |
| Cálculo            | Fraction                                             | Denominadores coprimos podem crescer com a série        |
| Transporte exato   | `str(Fraction)` em strings JSON                      | Limite implícito CPython de 4.300 dígitos               |
| Transporte decimal | Decimal de apresentação                              | Até 50 dígitos significativos, já documentados          |
| Apresentação Lab   | Parser BigInt em lab.js                              | Teto incompatível de 300 dígitos por componente         |
| Gráfico            | Number para geometria; formatter próprio na consulta | Consulta podia perder precisão ao reconstruir de Number |
| Erro               | ValueError genérico → 422                            | Confundia erro interno com dados inválidos              |

Não foi ampliada a gramática dos números de origem nem removida uma validação
de magnitude, conservação ou segurança para aceitar os fixtures.

## 10. Contrato numérico corrigido

Identificador aditivo: `EXACT_RATIONAL_DECIMAL_V2`. Pack schema permanece v1;
versão do pacote permanece `0.1.0.dev0`.

- Canônico: Fraction permanece exata. Não há quantização contábil nova.
- Transporte: string de inteiro decimal ou `numerador/denominador`, como antes.
  `Decimal(int)` produz o inteiro exato sem depender do contexto Decimal e sem
  `sys.set_int_max_str_digits`. Há guardas de bits e de comprimento.
- Limite derivado: 4.000.016 dígitos por componente. Resposta analítica: 64 MiB.
  Backend e navegador compartilham esses tetos. Upload e JSON de entrada continuam
  com seus limites anteriores. O teto de resposta não é garantia de RAM/latência.
- Apresentação: half-even explícito, de zero a 12 casas suportadas; NAV usa duas,
  BTC oito e razões seis nas tabelas Lab. Agrupamento e decimal seguem pt-BR.
- Não nulos que arredondariam a zero e magnitudes ≥10^24 usam `≈` e notação
  científica, com coeficiente limitado. Zero verdadeiro continua `0`.
- Frações longas têm tooltip com prefixo de 240 caracteres explicitamente
  identificado. O JSON completo autorizado conserva o valor inteiro.
- SVG usa Number para coordenadas aproximadas. A consulta formata a string
  original da marca e usa multiplicação inteira por 100 nas porcentagens.

## 11. Justificativa matemática e oráculos

Cada decimal validado tem no máximo 80 dígitos de coeficiente e adjusted em
[−100,20]. Seus componentes racionais têm menos de 200 dígitos. Pela conservação:

```text
N = C + B·P
e = B·P/N = 1 − C/N, quando N > 0
0 ≤ e ≤ 1
E = Σ(e_i · Δt_i) / ΣΔt_i, somente intervalos da cadência declarada
```

O denominador de C/N é limitado pelo produto de dois componentes de até
200 dígitos. Há no máximo 10.000 termos em todo o pack. O produto dos
denominadores tem no máximo 400·10.000 dígitos; fatores de tempo e soma cabem
na margem conservadora de 16 dígitos. Por ser média de exposições entre zero
e um, o numerador final também cabe nesse limite. O número de marcas não é
usado como substituto da complexidade: os holdouts com coeficientes de 80 dígitos
produzem frações muito maiores com menos marcas.

Para os fixtures primos, um oráculo por complemento, sem a árvore de soma do
produto, calcula `E = 1 − Σ(1/p_i)/(n−1)`, excluindo a última marca da ponderação
à esquerda. Outra verificação soma em ordem reversa. Ambas concordam exatamente.
O leitor independente reconstrói componentes em blocos de nove dígitos e não
depende do serializer corrigido nem do limite global de conversão do Python.

A segunda passagem verificou 90 frações e 450 apresentações contra Decimal de
alta precisão com ROUND_HALF_EVEN, incluindo negativos permitidos, extremos,
empates e valores além de IEEE754. Serialização sob precisão Decimal=2 continuou
exata e o limite global Python permaneceu 4.300. Os testes dirigidos e holdouts
conferem NAV, retorno, BTC físico/equivalente, caixa, fees, DD, exposição,
comparabilidade, Pareto, cache, replay e as duas projeções de exportação.

## 12. Mudanças na API

`numeric.py` distingue AnalysisError dos erros de contrato de entrada.
Falhas inesperadas de cálculo e serialização retornam HTTP 500 com
`ANALYSIS_FAILED`, sem stack, caminho ou conteúdo da exceção na resposta.
Entrada realmente inválida continua HTTP 422. Os testes injetam falhas
aritméticas, de serializer e de orçamento, verificam a redação e a recuperação
subsequente com dados válidos. Não há supressão silenciosa ou zero artificial.

Os quatro tamanhos válidos passam por preview → confirm → analysis em HTTP real,
com repetição. A resposta é JSON UTF-8, com `charset=utf-8` permitido.
Não foi criado endpoint de execução de estratégias, rede financeira ou coleta.

## 13. Mudanças no frontend

`numbers.js` centraliza o formatter exato; index.html o carrega antes de charts
e lab. `model.formatDecimal` permanece como interface compatível dos testes.
A gramática é validada e limitada antes de BigInt. Inteiros não viram Number
para formatação financeira. A saída é curta mesmo para frações enormes.

No navegador real, os quatro packs primos produziram três tabelas e gráficos.
As exposições exibidas foram 0,999243; 0,999751; 0,999869; 0,999949. Valores exatos
continuam no resultado. O holdout de 37 marcas por conta também abriu com
valores de 20 dígitos antes da vírgula e tooltip racional abreviado identificado.
A consulta por teclado na marca 02/01/2020 mostrou ROUND_TRIP=99 USDT,
CASH=100 e BTC10=100, a partir das strings originais.

Foram simulados HTTP 500, resposta com `<svg onload=...>` em campo numérico,
interrupção efetiva da conexão, atraso de um segundo e seleção rápida entre
estudos. Os estados de erro tinham zero tabelas e zero gráficos antigos; nenhum
handler SVG foi inserido. A resposta atrasada não sobrepôs Patrimônio, e a seleção
final UI_LEDGER manteve seus próprios cartões, tabelas e gráficos. A interrupção
real mostra `Failed to fetch`; é uma mensagem genérica de UX, não erro de cálculo
oculto. A sessão válida após reinício não apresentou erros no console.

## 14. Mudanças de exportação e compatibilidade

JSON completo mantém `exact` e inclui o pack fonte byte a byte. CSV conserva
o contrato de colunas anterior: NAV/BTC/fees de origem e DD decimal com até
50 dígitos significativos. DERIVED_ONLY permanece sem fonte, séries, episódios
ou bloco exact; sua precisão decimal de 50 dígitos é declarada. Portanto não
se atribui exatidão racional irrestrita a todos os formatos.

`numeric.py` integra a identidade dos módulos carregados para replay.
Manifestos de outra implementação analítica são incompatíveis explicitamente. Não houve
reescrita de manifestos antigos para contornar a checagem. Pack v1 e strings
racionais permanecem compatíveis; há um campo identificador aditivo na análise.

Downloads reais do navegador foram lidos apenas pelos caminhos retornados pelo
evento de download, copiados para a auditoria e conferidos: todos os checksums,
projeções, fonte original e exposição 25/99 do UI_LEDGER. O SVG foi parseado
sem script, foreignObject ou atributos de evento. Após reiniciar o processo,
o manifesto baixado antes do reinício retornou `Replay EQUIVALENT`, com grants
de exportação expirados e os packs persistidos intactos.

## 15. Regressões permanentes adicionadas

São 21 nodeids Python novos e sete testes Node novos. Nenhum nodeid anterior
foi removido. Os testes novos estão em `test_numeric_contract.py`,
`test_numeric_http.py`, `test_storage_initialization.py` e `numeric_contract.test.cjs`, com gerador independente
`numeric_cases.py` e os dois fixtures originais preservados.

Cobrem 100/1.200/3.000/9.999, crescimento coprimo, contexto Decimal, limite global
Python preservado, cancelamento algébrico, cache frio/quente isolado, HTTP/JSON,
repetição, exports, replay, zero, negativos de apresentação, negativos de saldo
recusados pelas regressões existentes, grandes denominadores/numeradores,
valores pequenos/grandes, pt-BR, half-even, sintaxe inválida e limites antes de
BigInt. Os temporais cobrem minutos, dias, irregularidade, ponto único, ausência
de dados, duplicação, timezone e metadados ausentes.

Uma expectativa antiga de apresentação foi atualizada de `0` para `≈ -1e-4`
ao exibir −0,0001 com duas casas, comportamento exigido pelo novo contrato.
Isso foi documentado; não altera resultado financeiro. O restante das asserções
históricas foi mantido.

Antes do congelamento, a suíte dirigida terminou com 345 PASS e um skip
preexistente. Uma rodada anterior teve quatro falhas do próprio teste novo,
porque exigia Content-Type sem charset; o oráculo foi corrigido para aceitar
o cabeçalho UTF-8 legítimo. Essas tentativas não foram contadas como PASS.

## 16. Resultado dos 189 cenários G4.5

| Grupo                  | PASS | FAIL |
| ---------------------- | ---- | ---- |
| ZIP/JSON               | 76   | 0    |
| Matemática             | 26   | 0    |
| Persistência e exports | 15   | 0    |
| Suplementares          | 9    | 0    |
| HTTP                   | 46   | 0    |
| HTTP bruto             | 17   | 0    |
| Total único            | 189  | 0    |

O harness foi copiado para a pasta G4.6, com caminhos realocados. Houve uma
adaptação comprovada do próprio oráculo: após o produto conseguir retornar a
fração de 1.200 marcas, `Fraction(string)` no teste atingia o mesmo limite de
4.300 dígitos do Python. Apenas esse leitor foi substituído pela reconstrução
independente em blocos de nove dígitos. A Fraction esperada e a igualdade exigida
permaneceram idênticas. Os bytes/hashes antes e depois estão registrados.
Nenhum arquivo ou resultado G4.5 foi alterado. O P3 foi confirmado adicionalmente
no navegador e na nova regressão temporal permanente.

## 17. Resultado dos testes holdout

Criados após o primeiro congelamento numérico, fora do desenvolvimento do reparo,
e reexecutados no wheel final com o reparo de lock: quatro
casos compostos com duas contas cada, coeficientes aleatórios determinísticos
de 80 dígitos e preços entre cerca de 10^19 e 2·10^19. São dados fictícios,
identificados como SYNTHETIC; não candles históricos.

| Marcas por conta | Marcas totais | Cadência s | Gap | Chars da exposição | HTTP | Oráculos/replay/exports |
| ---------------- | ------------- | ---------- | --- | ------------------ | ---- | ----------------------- |
| 37               | 74            | 60         | Não | 5641               | 200  | PASS                    |
| 173              | 346           | 61         | Sim | 26617              | 200  | PASS                    |
| 1301             | 2602          | 86400      | Não | 199433             | 200  | PASS                    |
| 4093             | 8186          | 60         | Não | 624365             | 200  | PASS                    |

Todos confrontaram oráculos financeiros independentes, HTTP repetido 200,
cache frio/quente, seleção, Pareto, replay EQUIVALENT e exports completo/derivado.
No caso com gap, Pareto vazio decorre do risco incompleto, como exige o contrato.
O maior caso gerou uma string de exposição com 624.365 caracteres e passou.
Seu tempo de 39,785 s é o cenário composto, com múltiplas análises e exports;
não é uma latência individual do endpoint. Não se somam as asserções internas
desses quatro cenários à contagem dos 189 testes equivalentes.

## 18. Cobertura global atualizada

**3.631 PASS, dois skips preexistentes, zero FAIL e zero pendentes certificados.**
São 454 segmentos frescos (30, 211, 212, 1), no HEAD final.
Cobertura de linhas e branches: **96.469876%**; threshold **85%**,
121 módulos. Linhas: 11531/11836;
branches: 2816/3036.
Durações por campanha (console, grupos 0/1 e repetição do segmento): 232.060, 4172.170, 4265.224, 16.282 s.
Maior segmento concluído: 783.318 s.
Os dois skips são exatamente os mesmos nodeids do manifesto G4.1:

- `tests/console/test_quality.py::test_real_symlink_outside_archive_is_refused`
- `tests/cli/test_doctor.py::test_env_file_posix_permissions_restricted`

O inventário final conciliou todos os 3.612 nodeids antigos e os 21 novos,
sem remoções ou duplicatas. Os 348 nodeids do console foram executados primeiro,
sem competir com outras campanhas: 347 PASS e um skip preexistente, em 30 segmentos.
O restante foi dividido em dois grupos disjuntos, balanceados por pesos
históricos, utilizados apenas no planejamento. O particionador ordena módulos;
isso não significa que a máquina historicamente mais longa executou primeiro.
Não foram reutilizados bancos SQLite ou percentuais de cobertura antigos.

Limites: 1.800 s por segmento; console com orçamento de 1.800 s e controlador
de 1.880 s; demais grupos com 5.400 s por grupo e 5.480 s no controlador,
duas campanhas concorrentes; Job Windows limita cada processo a 512 MiB de
commit, cada job a 768 MiB e 16 processos. Há limites de log e pasta de 1,5 GiB.
Esses são limites do experimento de auditoria, não garantias do produto.

Os bancos foram certificados por identidade, nodeids, fases setup/call/teardown,
log e SHA-256. A consolidação usa coverage combine e o threshold original de
85%, sem média de percentuais. O manifesto público registra os segmentos,
status individuais, hashes e cobertura por arquivo. Logs e SQLite brutos ficam
na área local de auditoria.

### Achado adicional comprovado na campanha global

A primeira campanha, em ba8bb8a, encontrou uma corrida preexistente na
inicialização de `.gridbot-writer-lock-v1`. O storage.py era byte a byte igual
ao da candidata publicada. Dois escritores podem observar tamanho zero; um
obtém o lock enquanto o outro ainda tenta gravar o byte inicial fora da região
crítica. No Windows, a gravação concorrente gera PermissionError. Não foi
demonstrada ultrapassagem da quota ou corrupção; houve falha de disponibilidade
e de classificação de contenção. Foi tratado como P2 adicional de persistência.

A reprodução independente manteve um lock real sobre uma região de arquivo
ainda vazia. A versão anterior gerou PermissionError; a corrigida responde
ValueError/Biblioteca ocupada sem gravar e permite retry após a liberação.
O reparo obtém o lock antes de inicializar o byte e reposiciona o descritor em
zero antes de desbloquear. As duas regressões permanentes falharam no código
anterior e passaram no corrigido. Os 39 testes dirigidos de inicialização e
hardening passaram, seguidos da campanha e do harness instalados novos.

O teste HTTP de menus teve TimeoutError no limite de 15 segundos durante a
concorrência das campanhas instrumentadas. Passou isoladamente com cobertura
(12,99 s para o teste) e passou novamente no bloco completo do console final.
Isso sustenta uma limitação do orçamento de execução sob carga, sem comprovar
um deadlock ou uma regressão de cálculo. Não houve alteração de timeout,
asserção, cobertura ou fórmula para forçar aprovação. O console foi isolado
das máquinas de estados na nova organização dos segmentos.

As campanhas antigas foram interrompidas somente em seus próprios processos
e retidas como INTERRUPTED_NOT_CERTIFIED. Nenhum de seus bancos entrou na
consolidação do novo HEAD. A validação global foi reiniciada integralmente
após a mudança executável adicional.

### Fechamento do segmento afetado pela codificação do console

Na candidata final, 13 chamadas passaram no segmento 0184, mas seu exit code
foi 1 por UnicodeDecodeError na thread de subprocess usada por um teste de
junction. Por prudência, nenhum dos 14 nodeids nem seu banco de cobertura foi
certificado a partir dessa tentativa. O comando mklink retornou zero; a leitura
de sua mensagem localizada falhou sob PYTHONUTF8=1 e console OEM.

Uma reprodução controlada em consoles novos e ocultos confirmou: OEM 850
reproduz a falha; codepage 65001 passa, mantendo PYTHONUTF8=1, código, testes,
asserções, warnings como erros e configuração de cobertura. O segmento completo
de 14 testes foi repetido com sucesso em UTF-8. As configurações do console do
usuário não foram alteradas. O banco falho foi excluído e o banco novo entrou
na união disjunta. Foram 455 tentativas de segmentos no HEAD final, das quais
454 completas certificadas; os dois diagnósticos controlados não entram nessa
contagem. A fragilidade de captura textual do teste sob codepages incompatíveis
permanece uma limitação documentada de portabilidade do teste, sem defeito
financeiro ou de rejeição de junction demonstrado. Não houve alteração de CORE.

## 19. Testes JavaScript e verificações estáticas

Node: 33 PASS, zero FAIL, zero skip, incluindo os 26 anteriores e sete novos.
Ruff check e format, Mypy, Prettier e git diff --check passaram. Mypy conferiu
283 arquivos e Ruff format 323 arquivos na verificação registrada.
Pre-commit completo passou com todos os hooks ativos. No primeiro commit,
a concorrência padrão dos ambientes de hook excedeu o limite de processos do
Job Windows; a execução foi repetida com PRE_COMMIT_NO_CONCURRENCY=1, sem
desabilitar hook, alterar configuração versionada ou reduzir a validação.

## 20. Segurança

As regressões equivalentes incluem ZIP canônico integral, ZIP bombs/entradas
ocultas, JSON profundo/duplicado/não finito, paths, symlinks/junctions/hardlinks,
HTML/SVG/CSV injection, CSRF/Origin/Host/cookie, requests concorrentes, queda de
processo, quota e grants independentes. As proteções G4.1 permaneceram aprovadas.
O resultado da rede da aplicação ficou restrito ao loopback nos harnesses com
audit hook; nenhuma tentativa de fronteira foi registrada.

Gitleaks: árvore final, os dois commits locais e fixtures decodificados, zero achados;
configuração sem exclusões de caminhos e sem uso de allowlists inline.
Consulta oficial OSV `https://api.osv.dev/v1/querybatch`: 39 versões,
zero advisories correspondentes retornados em 2026-10-25T20:14:42.595447+00:00.
Pins e dependências permanecem iguais; pip check passou nas instalações novas.

Limites de entrada continuam distintos dos limites de saída. Strings racionais
têm orçamento derivado, verificação de comprimento antes de BigInt, saída visual
curta e sem DOM HTML interpretado. JSON da resposta tem teto de 64 MiB; o parser
de entrada mantém profundidade 32 e máximo de 250.000 itens estruturais.
O backend local não se torna um serviço público nem recebe credenciais.

Essa evidência não prova ausência universal de vulnerabilidades. Não se fez
pentest de rede externa, análise de todos os motores JavaScript ou medição de
pior caso teórico. A consulta OSV limita-se às versões e ao instante consultado.

## 21. Integridade financeira

Os oráculos confirmaram `NAV = caixa + BTC×preço`, BTC físico diferente de
BTC equivalente, fees e saldos sem duplicar reservas. O reparo atua em análise
de observações e apresentação; não modifica os ledgers financeiros do GridBot.
Pareto, comparação de políticas e classificação de 20% usam Fraction exata,
sem depender de strings arredondadas para exibição. Export não é reconstruído
a partir de texto visual. Cache continua separado por identidade e seleção.

Na carteira sintética UI_LEDGER, o round trip termina em 108 USDT, BTC=0,
BTC equivalente=9, fees=2, DD=1/100 e exposição média=25/99. A conta BTC10 termina
em NAV=120 e BTC=10; CASH em NAV=100 e BTC=0. Os grupos e benchmarks comparáveis
permaneceram coerentes. Nenhuma conclusão de vantagem econômica foi adicionada.

## 22. PAPER

Cadência declarada válida é preservada e rotulada como declarada. Sem metadado,
apenas intervalos positivos uniformes observados sustentam um rótulo fixo.
Séries irregulares, duplicadas, vazias, com um ponto ou tempo inválido não
recebem uma frequência inventada. O fallback de lacuna superior a um dia é
explicitamente descrito como regra de segmentação, não como frequência da fonte.
Os packs continuam recusando timestamps duplicados no parser.

Na demonstração real do motor existente: 00:00 → 00:03 UTC, cadência observada
60 segundos. NAV final=109,17147000 USDT, caixa igual ao NAV, BTC=0 e fees=0,28853000.
Ledger e replay permanecem determinísticos. Os mesmos timestamps e preços do
baseline foram preservados. Não foi gerada ordem de exchange.

## 23. Wheel

Wheel final: `gridbot-0.1.0.dev0-py3-none-any.whl`, 344345 bytes, 144 membros.
SHA-256: `3f55247c96ff0975bb573ac62f94c46428467ce19c527cec62f0ab589c6f3383`.
Construído a partir do arquivo Git do HEAD congelado, com build e constraints
fixados, separado do wheel antigo. Os recursos instalados foram comparados
byte a byte ao snapshot, incluindo numeric.py, numbers.js, guias, recursos web
e fonte financeira preservada. O contrato/schema v1 é validado pelo parser e
documentação normativa; não há um arquivo JSON Schema distribuído separado.

## 24. Instalação limpa e instalação editável

Build e instalação limpa em venvs novos passaram, assim como pip check,
CLI por módulo e entrypoint. As 189 verificações equivalentes, holdouts,
benchmark e navegador usaram o código instalado no ambiente wheel.

Uma segunda cópia fresca do Git archive recebeu `.venv` e instalação editável.
O `start_console.cmd` real foi executado dali, com porta exclusiva e `--lab-dir`
em pasta nova da auditoria. HTTP, bytes dos três recursos JavaScript, preview,
confirmação, análises repetidas de 100/1.200, export com fonte/exato e PAPER
passaram. O encerramento do launcher foi deliberado: taskkill somente no PID
criado pela auditoria e seus descendentes. Seu código após cleanup foi 1;
isso não é apresentado como encerramento natural com exit zero. O wrapper
de verificação completou com zero após conferir as operações.

Os demais servidores próprios foram encerrados por stop file e terminaram
com exit zero. Porta 8765, servidores do usuário e a aba preexistente não foram
alterados. Não houve serviço permanente ou agendamento.

## 25. Performance

Sete amostras por etapa, após um warm-up excluído; memória Python medida
separadamente por tracemalloc. HTTP usa uma requisição fria e duas quentes.
Node mede sete formatações internas, sem incluir startup. Python 3.13.16,
Windows, com duas campanhas de cobertura concorrentes; não é host ocioso.

| Marcas | Parse s  | Análise s | JSON s   | Export s | HTTP frio s | HTTP quente s (2) | Formatter mediano s | Pico Python MiB |
| ------ | -------- | --------- | -------- | -------- | ----------- | ----------------- | ------------------- | --------------- |
| 100    | 0.002032 | 0.002699  | 0.000040 | 0.003353 | 0.007253    | 0.004083/0.004222 | 0.00000990          | 0.082           |
| 1200   | 0.024041 | 0.036581  | 0.000099 | 0.038499 | 0.057302    | 0.026418/0.025701 | 0.00011610          | 0.734           |
| 3000   | 0.059500 | 0.102134  | 0.000216 | 0.093855 | 0.214856    | 0.074569/0.076954 | 0.00033600          | 1.836           |
| 9999   | 0.197074 | 0.455011  | 0.000693 | 0.487304 | 0.737281    | 0.290992/0.318945 | 0.00308460          | 6.121           |

O custo depende de marcas **e** complexidade dos componentes. A árvore de soma
reduz a repetição de operações em acumuladores crescentes, mas aritmética exata
com denominadores coprimos continua custando CPU/memória. Cache quente ainda
precisa validar a identidade/bytes e serializar a resposta. Não se promete
linearidade, SLA, velocidade universal nem latência máxima.
O teto matemático conservador de quatro milhões de dígitos por componente
não foi medido como pior caso admissível. Foram medidos 9.999 marcas e holdout
de 624 mil caracteres exatos, com limites finitos. As guardas de tamanho não
substituem futura avaliação de carga caso o uso deixe de ser local/manual.

## 26. Capturas reais e inspeção visual

Navegador Chromium integrado real, sem imagens geradas. Inspeção nas dimensões
1920×1080, 1366×768, 768×1024 e 390×844. Em cada uma, `scrollWidth` da página
igualou `clientWidth`: respectivamente 1905, 1351, 753 e 375. Tabelas largas
mantêm rolagem interna explícita; não se afirma que todas as colunas cabem
simultaneamente em 390 px. As quatro capturas foram inspecionadas visualmente.

- `connection-interrupted.jpg` — 65ff6418e4e0571fe2e2e947fda02f28278770ef6913044f000fc1c3103af474
- `corrected-100.jpg` — 993c22f79af00a4aaa15e05ae7be4cf531dc378f2c79a916a31504ffecbfa77b
- `corrected-1200.jpg` — 454ed5c37bd24d4afb2d8433920446eb033dc1d4bda857a4f57568570f2bf936
- `corrected-3000.jpg` — 682f79163d681301bb8f2baa72e64b73846f985924b86987c1f1097f8e4f5a0a
- `corrected-9999.jpg` — be2893e4fe85850132ed5d0634ef7cb129c2426db31613ace4a46341c0488031
- `corrected-paper.jpg` — de30abc82b5d15b1620ddf326228e084eadbcee0b15ebfec53526329b4e26af7
- `internal-error.jpg` — f32890d5a5ca65f280601c9c735d4b28991c9ea774b2ccf006b803db646cdf66
- `ledger-1366.jpg` — ac94c8e503335f14f965346865ef4ccfe3b42e5317cb5b8418d52c11a5e01575
- `ledger-1920.jpg` — d745dc05d221ba5c9dfb0d3a7769e3394fb5c222f1f4bccfac74eebc2f283db5
- `ledger-390.jpg` — 253a8b4adb3f2524e7a3115e059597954dd2dc2f3c40c552047b46f4582889ec
- `ledger-768.jpg` — 80a238c3c5c21c6c22c41f5eb9b8f89bab196a39c227f9742855e9ae353f8129
- `restarted-replay.jpg` — 4f82f0658852095eab2315fb6d1ae3fd409c4d8cc3d660e0d24e605041c5df6b

Foram percorridos biblioteca, filtros/seleção, Lab, Pareto, consulta de risco,
replay, exports, PAPER e os painéis Patrimônio/BTC/Risco/Janelas. Sem corpus
histórico autorizado, os painéis exibiram DATA_UNAVAILABLE. A fonte sintética
foi escolhida explicitamente antes da inspeção dos painéis populados.
A viewport foi restaurada e apenas as abas temporárias próprias foram fechadas.

## 27. Arquivos modificados e inventário

| Estado | Arquivo                                        |
| ------ | ---------------------------------------------- |
| M      | `docs/G4_EVIDENCE_PACK_V1.md`                  |
| M      | `docs/G4_RESEARCH_LAB.md`                      |
| M      | `research_console/lab/analytics.py`            |
| M      | `research_console/lab/exports.py`              |
| M      | `research_console/lab/http.py`                 |
| A      | `research_console/lab/numeric.py`              |
| M      | `research_console/lab/storage.py`              |
| M      | `research_console/server.py`                   |
| M      | `research_console/static/charts.js`            |
| M      | `research_console/static/index.html`           |
| M      | `research_console/static/lab.js`               |
| A      | `research_console/static/numbers.js`           |
| M      | `tests/console/lab_state.test.cjs`             |
| A      | `tests/console/numeric_cases.py`               |
| A      | `tests/console/numeric_contract.test.cjs`      |
| A      | `tests/console/test_numeric_contract.py`       |
| A      | `tests/console/test_numeric_http.py`           |
| A      | `tests/console/test_storage_initialization.py` |
| A      | `tests/fixtures/g45_prime_100.gbpack`          |
| A      | `tests/fixtures/g45_prime_1200.gbpack`         |

O inventário de congelamento contém 306 hashes. O manifesto de validação
identifica o mesmo conteúdo executável que a cobertura. O commit de entrega
acrescenta este relatório, changelog e resumos de evidência, sem logs brutos,
ambientes virtuais, wheel, scripts temporários de auditoria ou datasets privados.
As capturas e os demais artefatos estão no workspace local de auditoria,
representado por `$AUDIT_WORKSPACE`, com subpastas results/logs/captures.

## 28. Commits e rastreabilidade

Commit de reparo: `ba8bb8aee256f4c13f292c9446e6a5744f9818c3`,
`fix(lab): preserve exact rational transport and report observed PAPER cadence`.
Commit adicional de lock: `e0ba226f31ff5aae2d253ebf0bafe20e2ae3c437`,
`fix(lab): acquire writer lock before initializing its empty byte`.
O commit de documentação é descendente direto do candidato final, sem alterações executáveis;
consulte `git log bff062b..HEAD --oneline` para a identidade final.

Arquivos públicos complementares:

- `docs/G4_6_CHANGELOG_AND_PR_UPDATE.md` — proposta local de atualização, não enviada.
- `docs/reviews/G4_6_VALIDATION_SUMMARY.json` — resultados e hashes compactos.
- `docs/reviews/G4_6_EXECUTION_MANIFEST.json.gz` — inventário/segmentos/cobertura
  certificados, com caminhos públicos relativos e sem dados privados.

Evidência bruta local: ORIGINAL_REPRODUCTION, ORIGINAL_HTTP_OBSERVATIONS,
ORIGINAL_BROWSER, ORIGINAL_PAPER_CONFIRMED, CODE_FREEZE, GLOBAL_PLAN,
INDEPENDENT_RUN_RECEIPTS, HTTP_CAMPAIGN, RAW_HTTP, HOLDOUT_OBSERVATIONS,
SECOND_CRITICAL_REVIEW, BENCHMARK_OBSERVATIONS, INSTALLATION,
EDITABLE_LAUNCHER_RUNTIME, BROWSER_PRE_RESTART, BROWSER_RESTART,
NATIVE_DOWNLOADS, SECURITY_SCANS, DEPENDENCY_QUERY e FINAL_PRESERVATION.
As reproduções iniciais ficam em `$AUDIT_WORKSPACE/results`. A validação do
wheel final e suas capturas ficam em `$AUDIT_WORKSPACE/final_validation/`;
a campanha global e sua cobertura ficam na raiz da área G4.6.
Os arquivos JSON correspondentes ficam nas respectivas pastas results; logs/receipts incluem
comando, limites, duração, exit code e SHA-256.

## 29. Limitações e incidentes do processo

A validação é forte para os contratos e exemplos exercitados; não é prova de
todos os inputs, plataformas ou condições de falha. Não valida prontidão para
trading, lucratividade, vantagem de estratégia ou drawdown futuro garantido.
O corpus histórico privado não participou. Não houve acessos corporativos.
O limite indicativo de 20% permanece referência analítica.

O parser v1 continua aceitando apenas BTC/USDT, sem passivos/outros ativos ou
fluxos externos. A declaração de proveniência não equivale a autenticação de
autoria e a leitura local autenticada de análise não é DRM. Grants de exportação
e projeções permanecem separados. Os exports decimais têm a precisão descrita,
e as coordenadas SVG são aproximadas, com consultas exatas das marcas.

Incidentes de harness foram preservados, sem convertê-los em resultados verdes:
duas colisões de nomes em NTFS entre receipt e observação JSON foram corrigidas
com prefixo `receipt_` e checagem de existência; dados e logs anteriores foram
retidos e os transportes relevantes receberam recibos novos. Houve quatro
asserções iniciais de Content-Type corrigidas, ajustes iniciais de lint/tipagem,
o limite de processos dos hooks e tentativas de UI antes de concluir a carga.
A preparação da segunda campanha também teve erros de harness (pending JSON
sem gzip e diretório já existente), detectados antes de executar testes e
corrigidos com novos diretórios. A reinstalação final foi retomada após uma
colisão de arquivo preparado e um erro de quoting, sem substituir artefatos.
Na primeira tentativa do reparo de lock, testes detectaram o cursor incorreto
no unlock; isso foi corrigido antes do congelamento. Uma asserção do teste novo
também tentou ler por outro descritor um byte ainda bloqueado no Windows; a
leitura foi movida para depois da liberação. Todos esses logs foram preservados.
Nenhum timeout ou tentativa incompleta foi usado para certificar PASS.

## 30. Recomendação técnica de atualização do PR #2

A candidata local final merece nova revisão e está tecnicamente pronta para a
decisão de atualização do PR #2. Os três defeitos originais e a corrida adicional
do lock estão resolvidos nos cenários comprovados; não há P0/P1 ou P2 material
ainda reproduzível nesta validação. Isso não autoriza push ou merge.
O commit publicado continua sendo o anterior e ainda contém os defeitos G4.5;
somente a branch local nova contém o reparo.

Nenhuma escrita remota foi realizada. Não houve push, comentário/review, edição
do PR, merge, tag, release, alteração de main ou ativação de Actions. O changelog
é uma proposta revisável local. A próxima ação depende de decisão explícita
do ChatGPT orquestrador e do usuário. Não iniciar G5 automaticamente.

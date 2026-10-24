# G4 — Offline Research Lab: implementação e auditoria

Data: 24/10/2026. Execução local Windows, Python 3.13.16, Node 24.19.
Escopo: engenharia offline sobre resultados existentes e fixtures fictícios.
Nenhuma pesquisa econômica, otimização, coleta ou operação Binance executada.

## 1. Baseline G3.4

Main local/remota confirmada em `88390ac0b3726c50b548e5087acfa39982d76342`,
merge tradicional do PR #1. A nova branch deriva desse commit. README, guias,
auditorias G1–G3.4 disponíveis, contratos, PAPER, portfolio, métricas, exports,
testes e configurações foram usados para delimitar a integração.
3.420 testes/2 skips, 19 testes JS, 96,53% global e 162 carteiras/69.174 marcas
descrevem a evidência anterior. Não são execuções financeiras/globais novas da G4.

## 2. Estado Git e isolamento

Branch exclusiva `feat/g4-offline-research-lab`; main não recebeu commits G4.
Quatro commits substanciais precedem o fechamento documental desta auditoria.
Os relatórios locais G3.3/G3.4 continuam não rastreados, sem sobrescrita ou inclusão
acidental. A origem pública continua a mesma; leituras remotas finais confirmam
main inalterada, Actions `enabled=false`, nenhuma tag/release. Não houve push,
PR G4, merge, agendamento ou alteração de perfil. O hash do commit que contém
este relatório é informado na entrega, evitando autorreferência.

## 3. Arquitetura

Extensão do console stdlib existente: `lab/packs.py` valida; `fixtures.py` monta
observações fictícias; `library.py` controla armazenamento/cache;
`analytics.py` analisa; `exports.py` aplica identidades/direitos;
`http.py` é o adaptador. `static/lab.js` integra a sétima página aos assets existentes.
São reutilizados leitor decimal, validação temporal, apresentação racional,
servidor, gráficos e demo. Nenhum framework, banco ou dependência de runtime nova.

## 4. Planejamento e limites

Biblioteca → pack → importação → análise → comparação/risco → evidência → replay
e export → auditoria. Contratos históricos foram implementados/testados com
sintéticos; não se criou um corpus histórico para preencher a biblioteca.
Não se executaram novos backtests, alterações econômicas ou G5.

## 5. Funcionalidades entregues

Busca/filtro/ordenação/detalhes; três fixtures; prévia e confirmação; cópias locais
removíveis; indicadores de origem/integridade; tabelas exatas; seleção de contas e
objetivos; Pareto; benchmarks; dispersão NAV/DD; trajetórias NAV/DD; episódios;
robustez descritiva; hashes até a marca; fills PAPER antes/depois;
export HTML/JSON/CSV/ZIP e SVG autorizado; manifesto/replay entre sessões compatíveis.
Contas desmarcadas continuam disponíveis para reinclusão. A navegação invalida
respostas atrasadas para impedir que uma análise sobrescreva outra página.

## 6. Evidence Packs públicos

[`INDEX.json`](../../examples/lab_packs/INDEX.json) registra bytes, SHA-256 e
expectativas derivadas à mão. Teste verifica os próprios arquivos distribuídos.

| Fixture fictício | BTC_HOLD NAV/DD | MIX NAV/DD | CASH NAV/DD |
| --- | --- | --- | --- |
| favorable | 130 / 0 | 115 / 0 | 100 / 0 |
| unfavorable | 85 / 15% | 92,5 / 7,5% | 100 / 0 |
| risk_violation | 60 / 40% | 80 / 20% | 100 / 0 |

Capital inicial 100 USDT em todas as contas; BTC final 10/5/0, respectivamente.
Taxas zero são propriedade matemática dos fixtures, não custo de mercado.
Datas de 2020 são fictícias fixas. Não são estratégias executadas ou preços reais.

## 7. Schema v1

[Contrato completo](../G4_EVIDENCE_PACK_V1.md), estrito/versionado, sem campos
desconhecidos. ZIP com dois nomes fixos; manifesto declara bytes/hash de results.
SHA do manifesto/contêiner é externo. Moeda USDT, unidades explícitas, UTC canônico,
capital e endpoints reconciliados. Identidades de política/benchmark/custo/janela
ficam nas contas; agregados não contêm curvas. Não há migração silenciosa.

## 8. Importação e persistência

HTTP recebe bytes e identificadores opacos, nunca caminho local. Seletor é
explícito, SHA externo opcional. Prévia não grava e expira em 300 s; duas pendentes.
Persistência exige `--lab-dir` nova/vazia ou já pertencente ao app. Marcador,
nomes SHA e rejeição de junction/symlink/UNC delimitam a área. Até 32 packs.
Confirmação usa temporário exclusivo, flush/fsync e replace; sem sobrescrita
silenciosa. Reabrir revalida bytes e hashes. Origem escolhida não é modificada.
Não se promete durabilidade contra toda falha de hardware ou ataques de corrida
por usuário local com permissão de modificar simultaneamente os diretórios.

## 9. Biblioteca histórica

Tipos SYNTHETIC_DEMO / ARCHIVED_RESEARCH_RESULT / AGGREGATED_RESEARCH_SUMMARY,
natureza sintética ou histórica declarada e estados DATA_UNAVAILABLE/INVALID
distintos. O adaptador M1/M1.R anterior permanece opt-in e somente leitura,
com descritor e acesso às janelas existentes, sem conversão/cópia automática.
Nesta rodada, nenhum novo pack histórico privado foi admitido ou redistribuído.

## 10. Matemática e oráculos

`NAV=C+B×P`, BTCeq=NAV/P, retorno=NAVfinal/NAVinicial−1; divisões indefinidas
permanecem indisponíveis. Reservas não são patrimônio adicional. Saldos/preço
não negativos/positivo, ordem temporal e NAV são validados em Decimal/Fraction.
NAV zero é absorvente sob ausência declarada de fluxos externos. Custos em USDT
já estão nos saldos, sem segunda subtração. Ledger de taxas em outros ativos,
passivos e fluxos externos não são suportados nem inferidos no v1.

Oráculo quadrático de drawdown e oráculo vetorial de Pareto independentes,
60 exemplos Hypothesis cada, fronteiras exatamente/acima de 1/5, gaps, zeros,
recuperação, janela unitária, precisão além de 50 dígitos e contexto Decimal baixo.
Resultados usam racionais `exact`; apresentação usa até 50 dígitos e UI BigInt
half-even, inclusive centavos acima de 2^53. Float fica restrito a coordenadas.
Anualização indisponível: convenção de dias não definida no contrato v1.

## 11. Comparador

Grupo exige fonte, janela, cenário de custo, capital, timestamps e preços iguais.
Benchmark incompatível recusa o pack; benchmark não selecionado é indisponível.
Deltas absolutos/relativos não dividem por zero. Não se concatenam janelas nem
misturam grupos para declarar superioridade. Exposição média usa intervalos
observados e marca esquerda; gaps e denominadores nulos são explicitados.

## 12. Pareto

Objetivos selecionáveis: maximizar NAV/BTC e minimizar DD/fees. Dominância usa
Fraction, sem pesos; empates são não dominados. Contas com risco incompleto são
inelegíveis quando DD é objetivo. Não dominância é relativa ao grupo/seleção,
sem vencedor global ou recomendação. Custos/janelas diferentes permanecem separados.

## 13. Risco e robustez

Pico observado, primeira marca abaixo, vale mais antigo empatado, recuperação
maior/igual ao pico. Pico empatado renova sua referência temporal. Episódio final
aberto é censurado. Qualquer intervalo diferente da cadência encerra um segmento;
não há recuperação presumida através de gap. Máximo segmentado não certifica risco
da janela inteira. 20% exatos não excedem; valores maiores excedem. Marcas diárias
não observam perdas intradiárias. Tabela descritiva separa política/custo/duração/
capital, sinaliza sobreposição e não calcula CI, causalidade ou score de vencedor.

## 14. Rastreabilidade e PAPER

Pack → manifesto → results → série → conta → índice/horário/unidades. Manifesto
de análise inclui identidade do código normalizada LF/CRLF, capturada no início
do processo, seleção e hash canônico esperado. Reinício após alterar código é
necessário; não há relabeling de uma execução antiga com novos bytes do disco.
PAPER usa a demo nativa existente. BUY/SELL mostram fills e saldos reconstruídos
em Fraction; HTTP instalado e navegador verificaram antes/depois e determinismo.
Não se executa estratégia histórica através do replay analítico.

## 15. Exports e proveniência

PUBLIC permite pack e séries; AGGREGATES_ONLY exige revisão explícita e remove
raw, episódios e curvas; RESTRICTED bloqueia exports. HTML escapado/CSP sem scripts,
CSV neutraliza fórmulas; nomes fixos. Download real de ZIP teve checksums, NAV e CSV
reconciliados e replay EQUIVALENT; SVG baixado reteve identidade sintética e hash.
Adaptador histórico anterior agora nega JSON bruto, exige revisão no CSV resumido
e bloqueia SVG restrito. Permissões/proveniência são declarações, não verificação
jurídica/autoria. SHA não substitui assinatura confiável ou autenticação da origem.

## 16. Segurança e revisão adversarial

Upload ≤2 MiB, conteúdo total ≤6 MiB, 60 contas/10.000 marcas, JSON depth 32 e
250.000 itens, razão de compressão limitada. ZIP nunca é extraído. Rejeitados
traversal, links/tipos especiais, entradas duplicadas, encoding inválido, ZIP
incompleto, prefixos/sufixos/comentários/extras, NUL e estruturas inesperadas.
Metadados recusam controles Unicode/invisíveis e vetores HTML/fórmula.
80 mutações ZIP com seed fixo e testes adversariais limitados, não fuzzing infinito.

Loopback, cookie de sessão HttpOnly/SameSite, Host/Origin únicos, cabeçalho próprio
para POST, framing/conteúdo/tamanho estritos e erros redigidos. Casos inválidos,
CSRF, replay adulterado, permissões e cache adulterado têm regressões.
Processos instalados foram protegidos por audit hook: zero tentativa de acesso
protegido ou conexão não loopback. Instalação usa PyPI e inspeções usam GitHub/OSV;
isso não representa rede financeira do aplicativo. OSV consultou 33 pins, sem
advisories retornados, sem pretensão de prova completa de segurança.

Gitleaks sem exclusões de caminhos e sem comentários allow: árvore pública
delimitada e payloads decodificados, zero achados/erros/warnings. A entrada inicial
continha 364 arquivos e oito payloads gzip/ZIP decodificados, texto ~5,52 MB.
O fechamento inclui hooks e scan dos commits locais. Um filtro preliminar de
privacidade também recusou fixtures genéricos e menções antigas de bloqueio
corporativo; revisão local confirmou que eram placeholders/guardas preexistentes,
não caminhos pessoais ou acesso a arquivos corporativos. Nada foi removido para
forçar o scan de secrets, que manteve sua configuração sem exclusões de paths.

## 17. Testes e falhas preservadas

| Validação nova G4 | Resultado |
| --- | --- |
| Console completo, cobertura branch | 281 PASS + 1 skip Windows preexistente; 114,04 s |
| Arquitetura + verify runner | 303 PASS; 8,15 s |
| JavaScript, incluindo 19 anteriores | 26 PASS |
| Coleta global, sem executar toda a base | 3.567 nodeids; 145 novos, sem retirar anteriores |
| Mypy strict completo | 275 arquivos sem erros |
| Ruff / format / pre-commit / diff | fechamento local registrado nas evidências |
| Wheel / editable / launcher real Windows | PASS com biblioteca, import, restart, replay e PAPER |

São **584 testes Python distintos aprovados nesta seleção**, não 3.565 testes
executados. Reexecuções dirigidas não são somadas. A coleta não é execução.
O skip é falta de permissão Windows para criar symlink, preservado.

Falhas de desenvolvimento não foram reclassificadas: expectativa de razão
arredondada corrigida para oráculo exato; formatação/tipagem inicial corrigidas;
timeout HTTP de cliente 5 s sob coverage (PAPER levou 9,33 s) corrigido somente no
cliente de teste para 20 s, sem remover teste ou reduzir threshold; probe isolado
teve teste PASS mas gate de cobertura FAIL. Uma regressão nova chamou o validador
com argumentos invertidos; corrigido o teste e repetida a suíte completa.
Um ensaio de coverage falhou antes da coleta porque o harness recebeu ambiente
incompleto, causando WinError 10106; repetido com ambiente completo, sem mudar app.
Colisão de nomes de artefato/recibo por case-insensitivity Windows foi identificada;
JSON de cobertura foi regenerado do banco SQLite preservado e medições recuperadas
dos logs intactos em nomes distintos. Recibos/logs das tentativas foram mantidos.

## 18. Cobertura e identidade

Console: **95,98965071151359%**, 1.211/1.252 statements e 273/294 branches.
Somente `lab/*`: **97,24896836313617%**, 707/727 oportunidades statement+branch.
Packs 100%, exports 100%, fixtures 100%; analytics ~99%, library ~95%, HTTP ~89%.
Restam ramos de falha operacional/rotas defensivas/cache/quota e denominador nulo;
não se adicionaram testes espelho para preencher números. Código Python e testes
tiveram hashes idênticos antes/depois da medição válida, sem edição concorrente.
Threshold original 85%, config/source global `gridbot`, intactos.
**GLOBAL_COVERAGE_PENDING**: não foi feita nova execução global completa nem mistura
de bancos G3/G4. A evidência global histórica de 96,53% permanece histórica.

## 19. Performance

Fixtures de escala alternam observações fictícias, sem estratégia/backtest.
Relógio perf_counter_ns; três amostras de tempo, memória em ensaio separado.
Medição inicial com tracemalloc amplo excedeu cap 60 s e continua TIMEOUT.
Workload foi limitado a 300/1.500/3.000 marcas totais; não houve execução infinita.

No marco antes/depois comparável de 3.000 marcas e mesmos bytes, export caiu de
212,06 para 117,40 ms e adaptador aquecido de 225,73 para 84,83 ms. Perfil demonstrou
duas validações `read_pack` por chamada antes e uma depois; manifesto também
reanalisava resultado já disponível. Correção usa snapshot único e projeção de
resultado interno, mantendo revalidação de bytes e precisão. N=3 não é inferência
estatística ou garantia; melhorias posteriores acrescentaram trabalho de evidência.

Na medição **final**, 3.000 marcas: validação 63,95 ms, análise 134,50 ms, export
190,93 ms (uma amostra), adaptador aquecido 92,67 ms. Startup Library 5,85 ms,
catálogo 2,18 ms; pico separado de alocações Python 948.519 bytes, não RSS.
Instalações: processo→HTTP ~528 ms wheel/~523 ms editable; oito leituras/4 clientes
de fixture pequeno ~20,64/~20,65 ms no total, respostas determinísticas.
Servidor é sequencial: esse ensaio mede fila local moderada, não escalabilidade
multiusuário ou paralelismo de CPU. Não há SLA ou extrapolação para grandes corpora.
Construção DOM medida no navegador ~5,5–7,2 ms; não inclui paint/GPU ou rede.
Componentes isolados do mesmo fixture: SHA-256 0,0069 ms, parsing JSON limitado
15,48 ms, Pareto de três contas 0,0922 ms, serialização canônica 3,95 ms,
cache com revalidação 80,08 ms, três hits e uma entrada. Essas medidas separadas
não devem ser somadas como se fossem um trace único. Limites de tamanho/quota
continuam aplicados; o ensaio não prova desempenho na capacidade máxima permitida.

## 20. Navegador e capturas reais

Navegador integrado, instância própria em porta alternativa; sessão existente
na porta padrão preservada. Exercitados busca/fonte/ordem, prévia/confirmação,
arquivo inválido, reinclusão de conta, episódio censurado, fronteira 20%, evidências,
PAPER BUY/SELL, teclado e download ZIP/SVG/manifesto, replay por arquivo baixado.
Regressão com atraso artificial limitado de 1 s confirmou que navegar para
Patrimônio mantém essa página após a resposta atrasada.

Viewports CSS 1920×1080, 1366×768, 768×1024 e 390×844: scrollWidth=clientWidth,
tabelas com rolagem local intencional. Capturas full-page reais preservadas nas
evidências locais; [captura pública desktop](../images/g4-library-1920.jpg).
Primeiras capturas viewport-only do provider vieram cortadas: não são a prova
final. A captura full-page nativa funcionou nas quatro larguras, sem imagem gerada
ou redimensionamento posterior. Scatter foi corrigido após inspeção mobile para
manter rótulos legíveis. Não se declara teste com leitor de tela ou todos os browsers.
Aba própria fechada, override de viewport restaurado, processos de teste encerrados;
instância preexistente continuou com o mesmo PID. Console JS sem warnings/errors
consultados ao fim das jornadas bem-sucedidas.

## 21. Compatibilidade

Python ≥3.13, sem dependência nova, API local limitada, mesma versão de pacote
0.1.0.dev0. Normalização de identidade LF/CRLF evita replay divergente por checkout
Windows. Linux/macOS não foram executados; não se afirma validação multiplataforma.

## 22. Empacotamento e primeiro uso

Clone local limpo sem hardlinks, dois venvs novos, build isolado com constraints
originais, pip check aprovado. Wheel SHA-256
`199a6a61de87ea563c92d1b51ef40278112dfda78f558db0b99aec4d636d55d6`:
138 membros, 104 módulos nativos idênticos, assets G4 e três packs incluídos,
sem docs/tests/ferramentas privadas. Execução fora do checkout confirmou import
instalado, CLI e entry point. Biblioteca, importação sem gravação antes do consentimento,
persistência após restart, checksums/export/replay e oráculo de fills passaram em
wheel e editable. Launcher CMD também iniciou HTTP real em porta própria.

## 23. Documentação e ensino

[Guia G4](../G4_RESEARCH_LAB.md), [schema](../G4_EVIDENCE_PACK_V1.md), índice de
fixtures, README atualizado e [proposta local de PR](../G4_CHANGELOG_AND_PR.md).
Exemplos executáveis usam escrita exclusiva e não dependem de caminho pessoal,
dados privados, credenciais ou acesso financeiro. Guia distingue consulta local,
redistribuição, integridade, proveniência, autenticidade e reprodutibilidade.

## 24. Commits locais

- `5e20fca`: contratos, pacotes e análise racional.
- `3579eb2`: importação HTTP, persistência, segurança e direitos.
- `f47ffec`: biblioteca, comparação, risco e fixtures públicos.
- `2a3b306`: documentação, schema e captura real.
- Fechamento: esta auditoria, resumo sanitizado e proposta local, em commit separado.

## 25. Arquivos e preservação

Diff concentrado em `research_console`, `tests/console`, exemplos de packs,
README/guias e auditoria. Manifesto de arquivos/recibos no resumo de validação.
Diff vazio em `src/gridbot`, `pyproject.toml`, constraints/build-constraints,
exemplo PAPER e licença. Rehash de **1.665 arquivos** do original: zero diferenças;
HEAD original `528f8c40ce6f74f9440444b2e652c56fae222fb2`, status rastreado limpo,
sem remote e seis históricos não rastreados preservados. V2 FINAL SHA-256:
`44e9639554d01c13e2e0648613e7904a6f1649ca934b00b3821021aa28582249`.
Nenhum acesso corporativo, descarte de relatórios, reset/clean ou alteração de CORE.

## 26. Segunda revisão e correções comprovadas

| Achado no desenvolvimento | Evidência e correção | Impacto |
| --- | --- | --- |
| Conteúdo ZIP fora dos dois arquivos | quatro repros inicialmente FAIL; preflight EOCD e layout contíguo, nomes originais/centrais estritos; regressões PASS | P2, fronteira de integridade/importação |
| Host/Origin/Cookie duplicados aceitos | três repros HTTP retornavam 200; exigência de unicidade; regressões PASS | P2, falha de contrato; não se demonstrou exploração remota |
| Resposta atrasada podia sobrescrever outra página | invalidação de revisão/root conectado + ensaio real de navegação atrasada | P2, consistência da UI |
| Número da UI podia perder centavos >2^53 | formatação BigInt de racionais e regressões half-even | P2, apresentação; matemática backend preservada |
| Export histórico podia redistribuir séries restritas | política aplicada no servidor/GUI, regressões de direitos e projeção | P2, privacidade/contrato de redistribuição |
| Validação/análise duplicadas | perfil antes/depois, snapshot/projeção únicos | P3, desempenho |
| Scatter ilegível no celular | viewBox proporcional à largura, captura repetida | P3, usabilidade |

Revisão questionou duplicação, cálculo, direitos, fontes privadas, identidade,
cache, mistura de cenários, erro silencioso e offline. Nenhuma alteração financeira
nativa foi necessária. A segunda passagem foi crítica do executor, sem alegar
auditoria humana externa independente ou cobertura de todas as ameaças possíveis.

## 27. Limitações e riscos remanescentes

Proveniência e ausência de fluxos declaradas; fees não autenticadas por ledger;
sem assinaturas ou migração automática; limites deliberados de tamanho;
risco apenas nas marcas observadas; servidor sequencial e caches locais;
sem garantia de segurança contra usuário local privilegiado e corridas de diretório;
sem garantia absoluta de crash/power-loss. Banco de dados e infra multiusuário não
foram introduzidos. Sem teste Linux/macOS, leitor de tela, RSS ou carga máxima.
Cobertura global G4 pendente. Nenhuma conclusão econômica nova, operação real ou
garantia de drawdown. Resultado de scanner é evidência limitada, não prova universal.

## 28. Recomendação e encerramento

Candidata funcional pronta para revisão local de contrato, diff, UX e evidências.
Recomenda-se revisão humana e decisão explícita sobre o gate global restante antes
de publicar. Não foi aberta PR nem iniciada G5. Melhorias futuras a decidir:
validação em outros sistemas, corpus autorizado com direitos claros, assinatura
de packs e limites de carga medidos; não são autorização para novas estratégias.

Resumo público: [G4_VALIDATION_SUMMARY.json](G4_VALIDATION_SUMMARY.json).
Logs completos, tentativas, SQL de cobertura, quatro capturas e medições permanecem
na área de auditoria local, sem copiar caminhos pessoais/corpus para o público.

```text
G4_OFFLINE_RESEARCH_LAB_PASS
RESEARCH_PACK_INTEGRITY_VALIDATED
LOCAL_IMPORT_SECURITY_VALIDATED
ANALYTICAL_RESULTS_RECONCILED
PAPER_DEMO_DETERMINISTIC
PUBLIC_DEMO_SELF_CONTAINED
ORIGINAL_GRIDBOT_PRESERVED
FROZEN_V2_PRESERVED
REAL_TRADING_DISABLED
GITHUB_PUSH_NOT_PERFORMED
GLOBAL_COVERAGE_PENDING
```

PARADO para revisão do ChatGPT orquestrador. Publicação, merge, release e G5
exigem decisão separada.

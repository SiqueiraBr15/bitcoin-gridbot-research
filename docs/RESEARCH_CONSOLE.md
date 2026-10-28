# Research Console — instalação e uso

Consulta local de resultados arquivados e demonstração PAPER. Sem novas
estratégias, ordens reais, coleta de mercado ou ajustes econômicos.

## Instalar e abrir

No PowerShell, clone a main pública, que já contém o Research Lab G4:

```powershell
git clone https://github.com/SiqueiraBr15/bitcoin-gridbot-research.git
cd bitcoin-gridbot-research
```

G1–G3.2 foram integradas pelo PR #1 e G4 pelo PR #2, merge
`acaa6879877c8a081a127f3ea8a0cdbb840b88cd`. Dentro do checkout:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --index-url https://pypi.org/simple pip==26.2.1
.\.venv\Scripts\python.exe -m pip install --index-url https://pypi.org/simple -c constraints.txt --build-constraint build-constraints.txt .
.\start_console.cmd
```

Para começar, abra **http://127.0.0.1:8765/#lab** e escolha Analisar em um dos
três packs sintéticos. Não é necessário autorizar um arquivo histórico. Consulte [o guia do Offline Research Lab](G4_RESEARCH_LAB.md)
para biblioteca, importação confirmada, métricas e replay, e
[o contrato de packs](G4_EVIDENCE_PACK_V1.md) para produzir evidências compatíveis.
Exports históricos brutos JSON são bloqueados; CSV de resumo exige revisão
explícita e SVG de séries restritas fica indisponível. A demonstração sintética
continua permitindo JSON/CSV/SVG. Essa restrição evita redistribuição automática
de uma origem autorizada apenas para consulta local.

Abra **http://127.0.0.1:8765**. Mantenha o terminal aberto; Ctrl+C encerra.
Equivalente: `.\.venv\Scripts\python.exe -m research_console`.
Para outra porta, acrescente `--port 8766`. O bind é sempre 127.0.0.1.
Não há serviço, agendamento, telemetria ou inicialização automática.
Linux/macOS: crie o venv com `python3.13`, instale com os mesmos constraints
e execute `python -m research_console` no checkout. Essa plataforma não foi
executada nesta auditoria Windows.

Sem histórico interno, abra **Demonstração PAPER → Executar cenários sintéticos**.
Cada uma das duas contas existentes começa com 100 USDT fictícios. Os cenários
têm preços diferentes e não constituem comparação pareada de políticas.
Eventos, reservas, fills, fees, saldos e NAV vêm do runner nativo já existente,
com conservação em Fraction e replay. A primeira execução pode levar alguns
segundos; o processo reutiliza o resultado determinístico em memória.
Recarregar a página exige novamente o clique explícito para exibir a demo.

## Fonte histórica autorizada

A distribuição pública **não contém as matrizes ou curvas internas**. Sem fonte
autorizada, mostra `UNAVAILABLE`, sem gerar curvas para preencher lacunas.
O operador pode fornecer a pasta local de relatórios:

```powershell
.\start_console.cmd --archive-root "PASTA_ABSOLUTA_LOCAL_AUTORIZADA_DE_RELATORIOS"
```

Só se admite `m1_risk/M1_RISK_ARTIFACT_MANIFEST.json` com SHA-256 congelado
`405755ffd2c3de0abeab4751e59f428e0dd5c8f933c329d097842585df58b68d`.
Não há upload, caminho por HTTP, pin ajustável ou importador de corpus genérico.
Não aponte para dados corporativos ou financeiros pessoais.

Contrato: 4.266 resultados (237 janelas × seis políticas × três custos),
1.730.196 marcas e 143 chunks comprimidos. Nove matrizes e índice são admitidos
no início; curvas são lidas sob seleção. Checksum demonstra igualdade ao
artefato admitido, não autentica o mercado nem elimina defeitos da pesquisa.
Candles, ledgers brutos e relatórios completos não são servidos ou copiados.

Hashes/tamanhos, schema, unidades, contagens, timestamps, ordem, identidades e
invariantes são verificados. Cada seleção revalida metadados e conteúdo dos
chunks relevantes, inclusive com cache aquecido. Alterar tamanho/mtime não
esconde corrupção. Recusa não produz substituição sintética automática.
Erros mostram códigos sanitizados, sem caminhos ou tracebacks.

## Seleção e comparação

Fonte, data, horizonte 6/12/24 meses, custo CA/CB/CX2, política em foco,
referência e subconjunto acompanham navegação e reload na mesma aba/sessão.
`sessionStorage` guarda preferências, nunca séries ou caminhos. **Restaurar
seleção** retorna a combinação existente. Horizonte/custo normalizam datas
incompatíveis; não criam combinações. Carregamento remove números anteriores
até validar os novos filtros.

A página PAPER oculta filtros históricos e tem cenário próprio, sem alterar
a seleção histórica. Também é possível escolher `SYNTHETIC_DEMO` nas outras
páginas, sempre com identificação explícita.

O comparador exige período, custo, capital inicial e mark final iguais.
Referência sempre integra o subconjunto. Diferenças usam **USDT** para NAV,
**pontos percentuais** para retorno e **BTC** para quantidade física.
Mínimos/máximos e empates aparecem por métrica; maior fee ou drawdown não é
um resultado desejável. Não há score nem vencedora universal.

## Páginas e interpretação

- **Visão geral:** proveniência, integridade, contexto negativo da pesquisa e limites.
- **Patrimônio:** NAV, retorno, exposição e comparação. Eixo absoluto começa em
  zero; ajuste opcional identifica corte e domínio. Não é retorno normalizado.
- **BTC:** físico, equivalente e caixa separados. `NAV = caixa + BTC × mark`;
  `BTCeq = NAV / mark`. Explicação da divergência decompõe ΔBTC × mark + Δcaixa.
  Inventário simulado não é BTC CORE; reservas não são somadas novamente.
- **Risco:** DD assinado `NAV / máximo observado − 1`, incluindo capital inicial.
  Eixo superior zero e linha em −20%. MDD mostrado como magnitude, classificado
  exatamente por `MDD > 1/5` antes de arredondar; excesso em pp. Pico igual mais
  recente, primeiro vale em empate, recuperação por igualdade/superação e censura
  no endpoint. Episódio e tempo amostral abaixo do pico são distintos.
  Frequências separam horizonte/custo.
- **Janelas:** registros existentes do horizonte/custo/subconjunto. Digite data/ID
  e use **Pesquisar** ou Enter; ordene data, NAV, retorno, DD ou BTC. Paginação
  de 18 linhas; estado vazio explícito. Não soma janelas como execução contínua.
- **PAPER:** eventos, ordens/fills fictícios, disponível/reservado, BTC, NAV,
  conservação e replay dos dois cenários existentes.

**Limite de referência analítico, não mecanismo garantido de proteção.** Marcação
diária não prova ausência de extremos intradiários. Exposição média histórica é
ponderada por capital × tempo. Janelas sobrepostas não são independentes;
custos hipotéticos, ausência de liquidação/impostos e riscos USDT/custódia
limitam qualquer inferência prospectiva.

Novas distribuições de retorno/DD e sinais existem somente para **dois cenários
sintéticos**, sem inferência econômica. No corpus privado exibem
`PUBLIC_AUDITED_CORPUS_NOT_DISTRIBUTED`: seção 8 da autorização G2 exige artefatos
públicos auditados ou sintéticos para novas análises. Nada foi copiado para
habilitá-las; dispersão/heatmap não foram adicionados sem esse corpus.

## Gráficos e downloads

Todos os pontos da seleção, sem downsampling/reconstrução. Lacunas acima de um
dia quebram a linha. Cursor/toque/setas/Home/End consultam marcas observadas;
série ausente naquele instante é indicada. Legendas numeradas, traços e ênfase
complementam cores. BTC não negativo começa em zero; exposição usa 0–100%.

Backend mantém Decimal/Fraction e strings exatas. O formatador G4.6 usa BigInt
e half-even; Number é usado para coordenadas/eixos aproximados. Frontend não
recalcula NAV, DD ou fees.

Downloads iniciados pelo usuário, sem escrita automática na origem:

- **CSV:** resumos do subconjunto, valores exatos, unidades, fonte, período,
  custo, manifesto, referência e diferenças; não é export da página do explorador.
- **JSON:** demonstrações sintéticas e projeções permitidas; JSON bruto do
  adaptador histórico não é exportado. No Lab, vale o escopo autorizado do pack.
- **SVG:** gráfico com fonte/unidade/legenda e descrição da seleção; sem scripts
  ou recursos externos. Imagem de apresentação, não ledger exato.

Sem caminhos locais ou campos privados extras. Resultados autorizados continuam
locais: revise-os antes de compartilhar. Capturas do repositório são sintéticas.

## Arquitetura e segurança

HTTP stdlib e HTML/CSS/JS locais, sem dependência UI/CDN nova. Fluxo em
[ARCHITECTURE.md](../ARCHITECTURE.md). LRU de quatro seleções completas,
chave versão/origem/hashes/seleção, cópia por resposta. Hashes custam leitura
mesmo em hit. Servidor local de desenvolvimento, não produção/multiusuário.

Host/Origin validados. APIs exigem cookie efêmero HttpOnly/SameSite=Strict e
mesma origem; frames/APIs cross-site bloqueados. Somente GET da raiz em navegação
de documento pode entrar de outro site, permitindo abrir o console legitimamente.
CSP limita recursos/conexões à origem e impede framing. Sem CORS, rotas de
trading ou leitura arbitrária. POSTs do Lab são limitados a prévia, confirmação,
remoção, replay e autorização de export, com sessão/origem/header específico. Nomes fixos, limites de leitura e
descompressão, recusa de links/junctions/origens de rede. Não é sandbox contra
usuário local capaz de adulterar processo; não exponha via proxy público.
O wheel atual inclui núcleo, console, exemplos sintéticos, assets e dois guias G4. Nenhum corpus
privado é empacotado. Testes/tools continuam no checkout.

## Verificar

```powershell
.\.venv\Scripts\python.exe -m pytest tests/console -q --cov=research_console --cov-branch --cov-report=term-missing
node --test tests/console/chart_state.test.cjs
.\.venv\Scripts\python.exe -m pytest tests/architecture tests/backtest/test_metrics.py tests/test_repo_hygiene.py tests/test_public_demo.py -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
```

Node é ferramenta opcional para testes, não dependência de execução; sem npm
install para abrir. A evidência nativa G3.1 é **96,52624362001981%**, source
`gridbot`, branches, threshold 85%, Windows/Python 3.13.16, baseline d2cdf2f.
Ela é separada da cobertura dirigida do console; nenhuma média foi feita.
O console identifica essa evidência arquivada e informa CI remoto não executado.
Threshold 85% e Hypothesis CI 300 preservados. Consulte a
[auditoria G3.1](reviews/G3_1_GLOBAL_QUALITY_GATE_CLOSURE_AUDIT.md) para execuções, falhas
intermediárias, capturas reais e limitações ambientais.


## G3: operação, diagnóstico e exports reproduzíveis

A navegação registra páginas na URL (`#wealth`, `#risk`, `#demo`, etc.).
Voltar/avançar e reload preservam preferências válidas da sessão. A chave de
preferências G2 foi mantida por compatibilidade; não guarda séries ou caminhos.
Novas consultas cancelam fetches anteriores; leitura/API/export têm deadline
cliente de 15 s. Um cancelamento não interrompe uma validação já iniciada no
servidor, mas sua resposta não substitui a seleção mais recente.

A API usa cookie de sessão com nome por porta. Windows recebe bind exclusivo;
uma segunda instância na mesma porta falha explicitamente. Use `--port` diferente,
sem encerrar automaticamente outro processo. Ctrl+C encerra o processo manual.
Sem serviços, tarefas agendadas ou alteração de política global do Windows.

No checkout, o launcher opcional PowerShell valida o ambiente local:

```powershell
.\start_console.ps1
.\start_console.ps1 -Port 8766
```

`-Python` aceita o caminho de um interpretador já instalado; `-ArchiveRoot`
aceita somente uma fonte local autorizada do contrato descrito acima. Se a política
do PowerShell impedir scripts, use `start_console.cmd` ou `python -m research_console`;
não é necessário alterar a política de execução. O launcher CMD não fica esperando
tecla quando faltar o ambiente: retorna erro e aponta as instruções de instalação.

Após instalação do wheel em um venv, mesmo fora do clone:

```powershell
gridbot-research-console --port 8765
```

O modo público abre com `DATA_UNAVAILABLE` para pesquisa ausente. A demo só
aparece após escolha e execução explícitas. **Reexecutar cenários sintéticos**
executa novamente o caminho nativo determinístico; navegação e downloads comuns
reutilizam a projeção validada em memória. Não são preços de mercado.

Cada gráfico oferece **Consultar marcas exatas em tabela**, com 25 marcas por
página da política em foco. Valores permanecem strings exatas; ratios são
identificados como razões (por exemplo −0.2 = −20%). Há caption e cabeçalhos de
coluna; o gráfico continua consultável por setas/Home/End, com estado textual.
Não se afirma certificação WCAG ou equivalência a leitor de tela não testado.

API/JSON e CSV usam `GRIDBOT_RESEARCH_SELECTION_V3`. Campos novos são aditivos;
os campos anteriores continuam. A identidade inclui fonte, dataset, janela UTC,
horizonte, custo, políticas, foco, referência e manifesto aplicável. CSV inclui
também capital inicial, mark final e hash das marcas históricas. Pontos decimais
são a representação interna; vírgulas pt-BR são apenas formatação visual.
CSV UTF-8 BOM é separado por vírgula, com quoting padrão; importe explicitamente
essa opção em planilhas que usem ponto e vírgula por locale. Não se afirma que
Excel foi operado neste teste.

SVG é `GRIDBOT_CHART_EXPORT_V1` e contém `<metadata>` JSON com identidade e
resumos exatos/unidades, além de traços visuais. O manifesto histórico não é
atribuído à demo: nela é nulo/não aplicável. Round trip é equivalência de campos,
não reimportação como fonte oficial ou identidade binária da imagem em todo
viewport. CSV rejeita identificadores/valores incompatíveis com seu schema,
incluindo fórmulas, sem converter silenciosamente a identidade de política.
JSON exige UTF-8, constantes finitas, profundidade/estrutura e leitura limitadas.

O download é cancelado se a seleção mudar durante sua preparação. Mensagens de
timeout/fonte inválida não exibem caminhos nem stack traces; recarregue a página
para obter uma nova sessão após reiniciar o serviço. Confira primeiro a porta e
o ambiente se houver recusa HTTP; não desative controles de origem/sessão.

A auditoria financeira opcional exige autorização da pasta e não executa backtest:

```powershell
python -m tools.audit_console_archive --archive-root "PASTA_ABSOLUTA_LOCAL_AUTORIZADA_DE_RELATORIOS"
```

O comando imprime resumo limitado de 27 seleções predeterminadas, verificadas
com Fraction contra JSON/gzip e HTTP/exports. A distribuição pública não contém
o corpus necessário; sem ele, o comando não promete reprodução histórica.

Ver [auditoria G3](reviews/G3_QUALITY_ENGINEERING_AND_RELEASE_CANDIDATE_AUDIT.md)
para falhas intermediárias, resultados efetivos, profiling e limitações das
capturas. Os pendentes daquela fase foram fechados na G3.1, sem apagar o histórico.
Gitleaks não equivale a auditoria de CVEs
ou de toda a máquina. Nenhum push/Actions/release remoto foi autorizado na G3.

## Versão e primeiro uso público

O pacote permanece em **0.1.0.dev0**, coerente com pyproject, CLI e metadados
instalados. A G4 está na main; isso não é tag ou release formal. Qualquer
bump de versão ou release depende de decisão separada; esta revisão não
altera a versão e não anuncia pré-release.

Sem a pasta original, o modo público mostra DATA_UNAVAILABLE para pesquisa
histórica. A demo funciona por si. Os 4.266 resultados arquivados descrevem o
contrato de um acervo privado opcional, não simulações incluídas no download.
Exemplos públicos: `examples.paper_cycle` e `examples.offline_grid`, sintéticos.
O comparador histórico exige o contrato admitido e contas equivalentes; na demo,
os cenários têm trajetórias distintas e não recebem um benchmark pareado fictício.

## Uso atual e qualidade G4

O comando mínimo acima instala o pacote, sem ferramentas de desenvolvimento.
Para contribuir, substitua . por -e ".[dev]" na instalação. Não é preciso
ativar o venv nem mudar a política global do PowerShell.

O launcher CMD repassa --lab-dir ao console. O launcher PowerShell aceita
somente -Port, -ArchiveRoot e -Python: ele não possui parâmetro -LabDir.
Para persistência, use python -m research_console --lab-dir ou o CMD com
--lab-dir e uma pasta absoluta nova/vazia, com pai existente.

G4.8, 27/10/2026 UTC: 3.633 Python PASS/dois skips; coverage global histórica
96,46987628%, threshold de 85%. G4.10, 27–28/10/2026 UTC: 171 Python PASS/um skip,
46 JavaScript PASS e wheel independente aprovado. G4.12, 28/10/2026 UTC:
merge/397 blobs, instalação limpa e oito verificações HTTP aprovados. Não são
novas execuções deste guia. As seções G3 anteriores são históricas.

Servidor sequencial e CPU após cancelamento continuam limites. O P3
Windows10053 pode tentar enviar 422 redundantemente após desconexão, sem
entrega e com recuperação previamente verificada. Actions continua
desativado; nenhuma aprovação de CI ou Linux/macOS é afirmada.

O modo G5 proposto ainda não existe. Seu contrato e UX estão em revisão nos
documentos G5 do checkout. Replay/export disponíveis são os da G4, sem
novas rotas ou permissões introduzidas pela proposta.

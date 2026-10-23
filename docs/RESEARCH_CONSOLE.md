# Research Console G2

Consulta local de resultados arquivados e demonstração PAPER. Sem novas
estratégias, ordens reais, coleta de mercado ou ajustes econômicos.

## Instalar e abrir

No PowerShell, dentro do checkout:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install pip==26.2.1
.\.venv\Scripts\python.exe -m pip install -c constraints.txt --build-constraint build-constraints.txt -e ".[dev]"
.\start_console.cmd
```

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

Backend mantém Decimal/Fraction e strings exatas. Number somente desenha/formata;
BigInt ordena decimais sem perda. Frontend não recalcula NAV, DD ou fees.

Downloads iniciados pelo usuário, sem escrita automática na origem:

- **CSV:** resumos do subconjunto, valores exatos, unidades, fonte, período,
  custo, manifesto, referência e diferenças; não é export da página do explorador.
- **JSON:** projeção validada completa da seleção e metadados permitidos.
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
CSP limita recursos/conexões à origem e impede framing. Sem CORS/escrita HTTP,
rotas de trading ou leitura arbitrária. Nomes fixos, limites de leitura e
descompressão, recusa de links/junctions/origens de rede. Não é sandbox contra
usuário local capaz de adulterar processo; não exponha via proxy público.
Console e exemplos requerem checkout e não integram o wheel do núcleo.

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
install para abrir. Cobertura dirigida não substitui a global **PENDING**.
Threshold 85% e Hypothesis CI 300 preservados. Consulte a
[auditoria G2](reviews/G2_RESEARCH_CONSOLE_PRO_AUDIT.md) para execuções, falhas
intermediárias, capturas reais e limitações ambientais.

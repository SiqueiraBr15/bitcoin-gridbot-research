# Research Console G1

Interface local de consulta, comparação e demonstração. Sem nova estratégia,
ordem real, coleta de mercado, credencial financeira ou ajuste econômico.

## Instalar e abrir no Windows

No PowerShell, dentro do checkout do projeto:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install pip==26.2.1
.\.venv\Scripts\python.exe -m pip install -c constraints.txt --build-constraint build-constraints.txt -e ".[dev]"
.\start_console.cmd
```

Abra **http://127.0.0.1:8765** no navegador. Mantenha o terminal aberto e use
**Ctrl+C** nele para encerrar. A interface não abre conexões externas.
O comando equivalente é `.\.venv\Scripts\python.exe -m research_console`.
Se a porta estiver ocupada: acrescente `--port 8766` e abra essa porta.
Não há instalação de serviço ou inicialização automática. O bind é sempre
127.0.0.1; não existe opção para expor o console na rede.

Sem arquivo interno, abra **Demonstração PAPER → Executar cenários sintéticos**.
Dois cenários existentes começam com 100 USDT independentes, um termina em ganho
e outro em perda. Preços fictícios, estado `SYNTHETIC_DEMO`, fills legítimos do
runner nativo, conservação Fraction e replay conferidos. A primeira execução pode
levar alguns segundos; o resultado em memória é reutilizado até fechar o processo.

## Consultar resultados já arquivados

A distribuição pública **não contém as matrizes ou curvas internas**. Sem uma
origem autorizada, o painel histórico mostra `UNAVAILABLE` / dados indisponíveis.
Não são fabricadas curvas nem executados backtests para preencher o painel.

O operador pode autorizar uma pasta local de relatórios no comando:

```powershell
.\start_console.cmd --archive-root "PASTA_ABSOLUTA_LOCAL_AUTORIZADA_DE_RELATORIOS"
```

Essa pasta deve conter `m1_risk/M1_RISK_ARTIFACT_MANIFEST.json` e os artefatos
originais M1.R. Só é reconhecido o manifesto congelado SHA-256
`405755ffd2c3de0abeab4751e59f428e0dd5c8f933c329d097842585df58b68d`.
Não há opção HTTP de caminho, upload, alteração do pin ou seleção de outro arquivo.
Não aponte para documentos corporativos ou dados financeiros pessoais.

O console abre somente o manifesto, as nove matrizes de resumo, o índice e os
chunks das curvas da seleção atual. Verifica hashes e tamanhos antes de interpretar
os arquivos. Arquivos brutos de candles, ledgers e relatórios completos não são
servidos. Nada é copiado automaticamente para o checkout ou gravado na origem.
Checksum demonstra igualdade ao artefato admitido, não autenticidade econômica
externa ou ausência de defeitos no estudo original.

Selecione **data inicial, horizonte 6/12/24 meses e custo CA/CX2/CB**. Apenas datas
existentes naquela combinação aparecem. A seleção de política muda os indicadores,
a ênfase no gráfico e a leitura dos pontos; os benchmarks permanecem na comparação.
O ponteiro consulta marcas observadas. Não há otimização ou busca de vencedores.

O catálogo identifica matrizes verificadas e curvas verificadas **sob seleção**;
não anuncia que todas as trajetórias foram lidas ao iniciar. Erro de integridade
impede mostrar a seleção; não se reutiliza silenciosamente uma série anterior.
A versão G1 suporta o contrato M1.R específico. R1/M2 são contexto metodológico;
seus corpus não são importados nem suas pesquisas reexecutadas.

## Interpretar as páginas

- **Visão geral:** origem, integridade, data do relatório arquivado, limitações e
  conclusões negativas preservadas. Data da pesquisa não é mtime da pasta.
- **Patrimônio:** NAV, retorno sobre capital inicial, fees, exposição e diferenças
  pareadas contra comprar e manter e 50/50, no mesmo período/custo/preço final.
- **Acumulação de BTC:** moedas físicas, BTC equivalente e caixa. Reservas não
  são somadas novamente. `NAV = caixa + BTC × mark`; `BTCeq = NAV / mark`.
  Mais BTC físico pode coexistir com menos caixa e menos patrimônio.
- **Risco:** DD assinado `NAV / máximo observado − 1`, com capital inicial;
  máximo mostrado como magnitude positiva. Classificação exata `MDD > 1/5`, antes
  de arredondar. Pico igual mais recente; primeiro vale em empates de profundidade;
  recuperação por igualdade ou superação; censura no endpoint explícita. A duração
  pico→recuperação/fim e o tempo amostral abaixo do pico são medidas diferentes.
  Frequências usam todas as datas do horizonte/custo, sem afirmar amostras IID.
- **Janelas históricas:** mesma seleção arquivada e comparação de todos os saldos,
  custos, DD e benchmarks; não soma janelas como execução contínua.
- **Demonstração PAPER:** eventos, fills, saldos e NAV dos dois cenários sintéticos.

Gráficos usam todos os pontos da seleção, sem downsampling/interpolação de preços.
O eixo horizontal respeita os instantes originais; lacunas maiores que um dia
quebram a linha. O backend mantém Decimal/Fraction e strings exatas; conversão
para Number ocorre só para coordenadas/formatação no navegador. A classificação
de risco nunca depende do arredondamento visual.

**20% é preferência indicativa, não garantia nem stop-loss.** Observação diária
não mede extremos intradiários. Janelas sobrepostas, custos hipotéticos, ausência
de liquidação/impostos e riscos de USDT/custódia limitam os resultados. Não há
recomendação operacional nem evidência de rentabilidade futura.

O botão **Exportar esta janela** gera JSON na memória e oferece download local
somente da seleção exibida. Ação explícita do usuário; não escreve na origem,
não envia a terceiros, não inclui caminhos, tokens ou campos privados inesperados.
O operador é responsável por manter esse arquivo local e revisar antes de publicar.

## Arquitetura e segurança

Sem framework anterior de UI. G1 usa uma aplicação de consulta de pequena escala
com HTTP Python stdlib e HTML/CSS/JS locais, sem React/API de trading/dependências
adicionais/CDN/telemetria. O servidor é de desenvolvimento local, **não produção**.

`research_console/data.py` carrega/valida/projeta os dados; `risk.py` reutiliza o
prefixo puro do módulo M1.R arquivado (`Mark`, `profile`, classificação e auxiliares),
com a mesma semântica e testes diferenciais. Não duplica decisões financeiras no
frontend. `demo.py` adapta `examples.paper_cycle`; `server.py` serve apenas rotas
fixas; `static/` apresenta; export usa a mesma projeção validada.
Os módulos financeiros `src/gridbot` e a demonstração existente não são alterados.
O console e exemplos precisam do **checkout** e não integram o wheel do núcleo.

Host/Origin/Sec-Fetch-Site são validados; API exige cookie de sessão efêmero,
HttpOnly/SameSite=Strict. CSP restringe scripts/estilos/conexões ao próprio console,
sem framing; não há CORS, escrita HTTP ou acesso arbitrário a arquivos. Leituras
têm limites comprimido/descomprimido, nomes fixos, hashes e recusa de links/junctions,
origens de rede e caminhos corporativos identificados. Mensagens não expõem paths
ou tracebacks. O processo manual não é sandbox contra um usuário local malicioso
capaz de alterar seus arquivos/processo. Não o coloque atrás de proxy público.

## Verificar

```powershell
.\.venv\Scripts\python.exe -m pytest tests/console -q --cov=research_console --cov-report=term-missing
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
```

Cobertura dirigida mede `research_console`, não a cobertura global histórica.
O limiar 85% e o Hypothesis CI 300 permanecem. A pendência da suíte global não
é convertida em PASS por estes testes. Não execute indiscriminadamente novos
backtests ou a suíte monolítica pendente para abrir a interface.

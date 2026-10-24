# Offline Research Lab — G4

Biblioteca local para inspecionar resultados existentes, comparar patrimônio,
BTC físico, custos e risco e reproduzir análises. Não executa estratégias
históricas, otimiza parâmetros ou coleta preços. Os três exemplos incluídos são
observações matemáticas fictícias, sem significado de desempenho de mercado.

## Abrir

Instale conforme [o guia do console](RESEARCH_CONSOLE.md). Nesta candidata local,
use a branch `feat/g4-offline-research-lab`; a G4 ainda não foi publicada.

```powershell
.\.venv\Scripts\python.exe -m research_console --port 8769
```

Abra `http://127.0.0.1:8769/#lab`. Sem argumentos de origem, a biblioteca tem três
packs em memória e não procura arquivos no computador. Use outra porta se houver
uma instância aberta. Ctrl+C encerra somente o processo iniciado nesse terminal.

Para habilitar a persistência de importações, escolha uma pasta absoluta nova ou
vazia, cujo diretório pai já exista:

```powershell
.\.venv\Scripts\python.exe -m research_console --port 8769 --lab-dir "$env:LOCALAPPDATA\GridBotResearchLab"
```

O launcher Windows encaminha os mesmos argumentos:
`start_console.cmd --port 8769 --lab-dir "<pasta absoluta nova ou pertencente ao lab>"`.
Não escolha pastas de outros projetos, documentos ou dados originais. A aplicação
recusa pastas não vazias sem seu marcador de propriedade, UNC, symlinks e junctions.
Sem `--lab-dir`, é possível validar uma prévia; confirmar sua persistência é recusado.

## Biblioteca e importação

1. Abra **Research Lab · biblioteca**. Busque nome, estudo ou política, filtre a
   fonte e ordene por nome, data ou tipo. Expanda os detalhes de identidades.
2. Escolha **Analisar** em um exemplo, ou selecione um `.gbpack` autorizado.
   Os arquivos públicos ficam em [`examples/lab_packs`](../examples/lab_packs/).
3. Opcionalmente informe um SHA-256 obtido por canal independente. **Validar prévia**
   verifica estrutura, unidades, hashes e conservação, sem persistir o arquivo.
4. Leia fonte, período e restrições. Marque a confirmação e clique **Confirmar
   importação local**. A cópia é nomeada pelo SHA-256, nunca pelo nome recebido.
5. Remover exige outra confirmação e remove somente essa cópia na pasta do lab.
   Não há lixeira para essa cópia; o arquivo de origem escolhido não é alterado.

Prévia expira em 300 segundos; são mantidas no máximo duas. A biblioteca aceita
32 cópias locais, cada pack com até 2 MiB compactados. Nenhum caminho de origem
é enviado por HTTP ou incluído nos metadados da análise.

`SYNTHETIC_DEMO` é demonstração; `ARCHIVED_RESEARCH_RESULT` é resultado declarado
arquivado; `AGGREGATED_RESEARCH_SUMMARY` contém apenas contagens, sem curvas.
`DATA_UNAVAILABLE` e `DATA_INVALID` são estados de diagnóstico, não tipos de pack.
`data_nature` mantém explícita a distinção SYNTHETIC/HISTORICAL_DECLARED.
O adaptador M1/M1.R preexistente exige `--archive-root` explícito, permanece somente
leitura e aparece como descritor e acesso às janelas. Ele não converte nem copia
seus arquivos automaticamente para packs. Nenhum histórico privado integra esta entrega.

## Análise e comparação

Selecione contas e objetivos e aplique. As tabelas mostram valores financeiros
exatos na origem; a apresentação arredonda em half-even usando inteiros BigInt.
Gráficos usam números de ponto flutuante apenas para coordenadas; consulte a
tabela de marcas exatas e a trilha de evidências para auditoria numérica.

Para cada marca, com P em USDT/BTC, B em BTC e C em USDT:

```text
NAV = C + B × P
BTC equivalente = NAV / P
retorno absoluto = NAV final − NAV inicial
retorno razão = NAV final / NAV inicial − 1, se NAV inicial > 0
exposição na marca = B × P / NAV, se NAV > 0
```

Não existem outros ativos, passivos ou fluxos externos suportados no schema v1.
Caixa e BTC são totais líquidos, incluindo eventuais subconjuntos reservados
uma única vez. Fees são o custo acumulado declarado em USDT, já refletido nos
saldos; não são subtraídas novamente. O pack não contém ledger de execução que
permita autenticar esse custo ou verificar fees em outro ativo. Converta e audite
externamente um ledger autorizado antes de produzir um pack compatível.

A exposição média pondera o valor da marca esquerda pelo tempo até a próxima
marca na cadência declarada. Intervalos irregulares são excluídos e explicitados.
NAV zero torna razões indisponíveis e não pode voltar a ser positivo sob o
contrato de ausência de fluxos. Um ponto ou uma série sempre nula não comprova risco.
Retorno anualizado permanece indisponível: v1 não define convenção de dias.

Benchmark e dominância exigem mesmo grupo: fonte, janela, custo, capital inicial,
endpoints e toda a sequência de horários/preços. A tabela apresenta o identificador
do grupo. Benchmarks incompatíveis são recusados no carregamento. Referências
não selecionadas têm comparação indisponível; denominador zero não vira zero artificial.

Pareto maximiza NAV/BTC e minimiza drawdown/fees apenas nos objetivos escolhidos.
Uma conta domina outra quando não é pior em nenhum objetivo e é estritamente
melhor em pelo menos um, dentro do mesmo grupo. Empates permanecem não dominados.
Risco incompleto exclui a conta quando drawdown é objetivo. Não há pesos, score
ou vencedor global. Eficiência histórica não demonstra desempenho futuro.

Robustez é descritiva por política, custo, duração e capital: perdas, violações,
retornos mínimo/máximo e sobreposição. Janelas independentes não são concatenadas;
janelas sobrepostas são dependentes. Não há intervalos de confiança, causalidade
ou inferência de superioridade. Cenários de custo distintos continuam separados.

## Risco e evidências

O drawdown em cada segmento é `1 − NAV / pico observado`. Um pico empatado renova
o horário do pico. O episódio começa na primeira marca abaixo dele, mantém o vale
mais antigo em caso de empate e recupera na primeira marca maior ou igual ao pico.
A duração observada vai do pico à recuperação ou ao último ponto disponível.
No final sem recuperação, o episódio é censurado; qualquer intervalo diferente
da cadência declarada encerra o segmento anterior e inicia outro pico de referência.
Não se presume recuperação através de lacuna. O máximo por segmentos não comprova
o máximo da janela completa, e a interface informa risco incompleto.

**20% é referência indicativa, sem stop-loss ou garantia operacional.** Exatamente
`1/5` não excede o limite; um valor maior excede. Marcas diárias não revelam perdas
intradiárias. Tempo abaixo do pico usa marcas esquerdas em intervalos observados,
não uma estimativa de horário intrabar.

Escolha conta e episódio para ver índices, pico, vale, recuperação/censura e duração.
Expanda evidências: hash do pack, manifesto, arquivo de resultados, série, conta,
marca final e unidades permitem localizar a origem. O gráfico aceita teclado e
consulta de marcas exatas. Tabelas largas têm rolagem horizontal local em telas pequenas.

**Investigar fills da demonstração PAPER** usa o motor sintético já existente,
separado dos packs. Cada BUY/SELL mostra ordem, horário, taxa e caixa/BTC antes e
depois, reconciliados em Fraction. Não cria ordens de mercado ou nova estratégia.

## Replay e exports

Baixe o manifesto da análise e confira a reprodução na mesma seleção. Para outra
sessão, carregue primeiro o mesmo pack e escolha o manifesto baixado. Replay
recalcula análises dos dados existentes; nunca reexecuta estratégias históricas.
Mudar dados, código, objetivos, contas ou hash esperado impede equivalência.
A identidade do código normaliza LF/CRLF e é capturada no início do processo;
reinicie o servidor após mudar código. Uma nova versão pode exigir novo manifesto,
sem prometer replay entre versões incompatíveis.

O pacote de análise contém manifesto, métricas JSON/CSV, relatório HTML estático
escapado, checksums e, apenas quando PUBLIC, o pack fonte. Nomes de saída são fixos.
CSV neutraliza células com prefixos de fórmula; por isso uma célula numérica negativa
pode começar com apóstrofo. Consuma JSON/exact para reconciliação programática.

| Restrição declarada | Exportação |
| --- | --- |
| PUBLIC | Pack bruto, análise e SVG das séries permitidos |
| AGGREGATES_ONLY | Exige revisão explícita; resumo sem curvas/episódios/raw pack; SVG negado |
| RESTRICTED | Export de análise/raw/SVG bloqueado |

O adaptador histórico anterior agora bloqueia JSON bruto de `/api/export`; CSV
resumido exige revisão explícita. JSON/CSV da demonstração sintética continuam
disponíveis. A consulta local de dados autorizados é diferente de redistribuição.
Permissões são declaradas pelo produtor: a aplicação não verifica direitos legais
nem consegue impedir que um usuário local com acesso ao disco copie seus arquivos.

SHA-256 verifica integridade relativa aos bytes/identidade esperados, não autoria.
Proveniência é declarada; autenticidade criptográfica exigiria assinatura e chave
confiável, ausentes no v1. Reprodutibilidade demonstra a mesma análise dos mesmos
bytes/código, não a veracidade econômica da origem.

## Exemplos e limites

Cada conta começa com NAV 100: BTC_HOLD tem BTC 10; CASH tem USDT 100; MIX tem BTC 5
e USDT 50. Taxas zero são propriedade do fixture matemático, não hipótese de execução.

| Pack fictício | NAV final BTC_HOLD / MIX / CASH | DD BTC_HOLD / MIX / CASH |
| --- | --- | --- |
| favorable | 130 / 115 / 100 | 0 / 0 / 0 |
| unfavorable | 85 / 92,5 / 100 | 15% / 7,5% / 0 |
| risk_violation | 60 / 80 / 100 | 40% / 20% / 0 |

Datas fixas de 2020 são parte da ficção determinística; não são candles históricos
nem horários reais de arquivamento. O [índice](../examples/lab_packs/INDEX.json)
registra bytes, SHA-256 e expectativas derivadas à mão, verificadas nos testes.

O parser limita 60 contas, 10.000 marcas totais, 6 MiB descompactados, JSON com
profundidade 32 e razão de compressão controlada. ZIP não é extraído. Cache LRU
de quatro análises inclui dados, seleção, versão e código; os bytes locais são
revalidados mesmo no cache hit. O servidor atende sequencialmente: uma análise ou
demo longa pode bloquear temporariamente outras requisições locais. Não há SLA,
autenticação multiusuário ou isolamento contra um usuário local malicioso com
permissão de modificar simultaneamente o sistema de arquivos. Não exponha a porta
por proxy. Publicação de packs históricos exige revisão de proveniência/licença.

## Arquitetura e verificações

`lab/packs.py` valida; `fixtures.py` gera os três fixtures; `library.py` controla
propriedade/persistência/cache; `analytics.py` analisa em Fraction; `exports.py`
aplica direitos e identidades; `http.py` traduz rotas. O servidor e os gráficos
existentes são reutilizados; `static/lab.js` acrescenta a biblioteca e a investigação.
Não há framework ou dependência de runtime nova. O motor financeiro nativo não mudou.

```powershell
python -m pytest tests/console --cov=research_console --cov-branch --cov-fail-under=85
node --test tests/console/chart_state.test.cjs tests/console/lab_state.test.cjs
python -m ruff check .
python -m ruff format --check .
python -m mypy
```

O primeiro comando mede somente o console, não toda a base. Consulte a
[auditoria G4](reviews/G4_OFFLINE_RESEARCH_LAB_IMPLEMENTATION_AUDIT.md) para evidências,
falhas encontradas e limites. Windows foi exercitado; Linux/macOS não foram testados.
Não há prontidão para produção ou vantagem econômica comprovada por estes exemplos.

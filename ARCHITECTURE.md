# Arquitetura

O núcleo usa funções puras, objetos imutáveis e coordenação explícita. Não lê
saldo de exchange para criar inventário de GRID nem vende BTC CORE.

| Pacote | Responsabilidade |
| --- | --- |
| domain | Decimal, ativos, preços, quantidades, regras e contratos |
| strategy | Geometria, células, sizing, intenções e identidade de ciclo |
| portfolio | Fills BUY, inventário adquirido e avaliação de venda |
| application | BUY/SELL coordenados, reservas e projeções econômicas |
| paper | Ledger e liquidação virtual; simulação e gerações |
| storage | Journal, verificações e recuperação local |
| backtest | Dados, hipóteses de execução, benchmark e métricas |
| marketdata | Contratos e suporte à admissão de arquivo público |
| config / cli / infra / observability | Configuração explícita, diagnóstico e redação de logs |

Os testes de arquitetura verificam dependências, ausência de relógio/aleatoriedade
no núcleo e restrições financeiras. O suporte de dados públicos não fornece
autoridade para baixar uma janela prospectiva ou operar.

## Identidades e autoridade

Uma intenção não é ordem na exchange. Um fill observado não é prova suficiente
de completude externa. A reconciliação distingue consistência estrutural da
autenticidade da fonte. Apenas a autoridade PAPER aplica os efeitos virtuais
autorizados; reservas e evidências não duplicam fundos.

O journal implementa contratos locais de persistência e recuperação, sem
prometer resistência a toda falha de energia ou concorrência hostil.
Não existe adaptador de trading real habilitado nesta distribuição.

## Demonstração e ferramentas públicas

`examples/paper_cycle.py` constrói datasets sintéticos, chama o runner nativo e
confere saldos/NAV em Fraction a partir dos fills. O replay PAPER é verificado
separadamente. Não há persistência em disco ou uso de dados financeiros privados
nesse caminho. `tools/verify.py` controla apenas processos de teste e limites;
`tools/test_catalog.py` coleta e classifica casos. Esses auxiliares não fazem
parte do wheel e não modificam a autoridade financeira.

O pacote preserva um coletor opt-in de arquivos públicos em
`marketdata.public_archives`, com allowlist e quotas. Sua existência não significa
que todo comando do pacote seja incapaz de rede. As demos e o CLI de diagnóstico
não o acionam; ele não foi executado nesta missão. Dados prospectivos e ordens
reais continuam sujeitos a contratos/autorização separados.

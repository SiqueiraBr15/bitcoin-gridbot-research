# Demonstrações offline

Execute a partir do checkout instalado com `pip install -c constraints.txt
--build-constraint build-constraints.txt -e ".[dev]"` (pip 26.2.1).

`python -m examples.paper_cycle` executa dois cenários independentes em memória.
Cada um começa com 100 USDT, zero BTC e três candles de um minuto fictícios.
Os preços 69–111 são didáticos: não são um dataset histórico de Bitcoin.
A grade 90–110 de dois intervalos e os custos explícitos pertencem só ao exemplo;
não substituem parâmetros das políticas de pesquisa congeladas.

O JSON contém os tipos de comandos, revisões, fills, fees, reservas e marcação
final. NAV é caixa total mais BTC físico ao preço final. Caixa reservado não é
somado duas vezes. Um oráculo separado em Fraction aplica compras/vendas e fees
USDT a cada marcação e exige resíduo zero. O replay das fontes PAPER deve resultar
no mesmo estado final. Os testes detectam fee adulterada e recusam tentativas de
conexão de rede durante a demonstração. Não se testa todo contrato financeiro
por meio desta pequena simulação.

`round_trip` e `falling_mark` não são uma execução contínua. O segundo termina
com NAV inferior aos 100 USDT iniciais; o primeiro não demonstra lucratividade
histórica. O exemplo não grava journal em disco, não consulta relógio, não usa
credenciais e não calcula novas evidências econômicas de mercado.

`python -m examples.offline_grid` mostra apenas geometria de quatro intervalos.
Ambos os comandos são exemplos do checkout; o wheel contém somente `gridbot`.

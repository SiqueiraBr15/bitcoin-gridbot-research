# Proposta local de Pull Request — G2 Research Console Pro

Nenhum PR remoto criado, push ou merge realizado. Branch local
`feat/g2-research-console-pro`, baseada na G1 `5b7244f`.

## Objetivo

Tornar a consulta de resultados existentes mais clara: separar patrimônio,
quantidade física de BTC e risco, comparar contas equivalentes e explicar
proveniência/indisponibilidade, mantendo o núcleo financeiro congelado.

## Mudanças

- Layout responsivo, contraste, legendas numeradas, traços e tooltip por teclado.
- DD com zero no topo e referência −20%; BTC não negativo começa em zero;
  domínio NAV absoluto ou corte explicitamente identificado.
- Seleção persistida na sessão, subconjunto e referência configurável.
- Comparação exata em Fraction com diferenças USDT/pp/BTC, extrema por métrica
  e decomposição de mais BTC com menor NAV, sem score geral.
- Busca, ordenação exata e paginação dos registros existentes. Novas
  distribuições apenas sintéticas enquanto corpus público auditado não existir.
- Demo PAPER existente com eventos, fills, reservas, saldos e conservação.
- Proveniência e erros sanitizados; CSV/JSON/SVG iniciados pelo usuário.
- LRU de quatro seleções com revalidação de hashes em todo acesso.

## Capturas reais

Todas usam exclusivamente dados fictícios `SYNTHETIC_DEMO`.

![PAPER G2](images/g2-synthetic-paper.png)
![Drawdown G2](images/g2-synthetic-risk.png)
![Distribuição sintética](images/g2-synthetic-distributions.png)

## Validação

50 casos novos (35 Python, 15 JavaScript). 91 casos do console, 322 regressões
pertinentes e 15 testes JavaScript aprovados: 428 casos distintos. Cobertura
dirigida de linhas+ramos do console: 96,14%; **global PENDING**. Ruff, formatação,
Mypy, pip check, pre-commit e Gitleaks conferidos conforme auditoria.
Tentativa intermediária de CSV sintético falhou e foi corrigida; não foi
contabilizada como PASS. UI operada em três resoluções, exports reais conferidos.

## Segurança e limites

Somente loopback e consulta; APIs com sessão/origem, CSP e caminhos fixos.
GET de navegação de documento na raiz pode abrir o console a partir de outro
site; essa exceção não autoriza API, iframe ou export cross-site.
Sem novas dependências de execução, Binance, credenciais, LIVE, coleta ou backtest.
104 módulos nativos, exemplos, CORE, V2 e original preservados. Nenhum corpus
privado incluído; apenas projeções autorizadas são servidas localmente.
Servidor de desenvolvimento, sem prontidão operacional para investimento.

Brave permitiu testes DOM/viewport mas a captura expirou; screenshots reais
foram obtidas no navegador integrado, sem simular resoluções por redimensionamento.
Distribuições M1 privadas indisponíveis por limite de autorização, não por ausência
inventada de registros. Consulte a auditoria para detalhes e roteiro reproduzível.

## Checklist de revisão antes de eventual publicação

- [ ] Revisar o diff e as capturas, distinguindo demo de pesquisa histórica.
- [ ] Reproduzir os comandos de instalação e testes dirigidos documentados.
- [ ] Manter explícitos cobertura global PENDING e limites econômicos.
- [ ] Confirmar ausência de datasets/caminhos pessoais e preservação do núcleo.
- [ ] Obter autorização separada antes de push/publicação; manter Actions desativado.

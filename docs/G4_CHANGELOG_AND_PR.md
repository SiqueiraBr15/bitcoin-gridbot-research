# Proposta local de PR — G4 Offline Research Lab

Título: **Add an offline research lab with validated evidence packs and exact analysis**

Base: main `88390ac0b3726c50b548e5087acfa39982d76342`.
Branch: `feat/g4-offline-research-lab`. Proposta local; nenhum PR/push G4 criado.

O console consultava um arquivo histórico específico e a demo PAPER, sem um
contrato portátil para organizar e analisar outros resultados autorizados.
Esta mudança acrescenta Evidence Pack v1, biblioteca pesquisável, prévia sem
persistência e importação mediante confirmação em pasta exclusiva.

A análise usa Fraction para conservar NAV/BTC/USDT, comparar benchmarks e
identificar dominância somente em condições equivalentes. A interface apresenta
trade-offs, episódios de drawdown com censura em gaps, evidências por marca e
saldos antes/depois dos fills PAPER existentes. Replay verifica identidade dos
dados, código, seleção e resultado, sem executar backtests.

Exports aplicam direitos declarados. O adaptador histórico anterior passa a
negar JSON bruto e SVG de séries restritas; CSV de resumo exige revisão explícita.
Três fixtures públicos fictícios incluem ganho, perda e violação de risco.
Não há estratégia nova, dependência de runtime nova ou mudança nos 104 módulos
financeiros nativos, parâmetros congelados, CORE ou manifesto V2.

Validação local: 281 testes do console aprovados + um skip Windows preexistente,
95,99% de cobertura do console e 97,25% de seus módulos G4; 303 regressões de
arquitetura/ferramentas e 26 testes JavaScript aprovados. Oráculos racionais,
Hypothesis, fuzzing limitado, rejeição de ZIPs inválidos, CSRF e cabeçalhos
duplicados. Navegador real em quatro resoluções, import/export/replay e teclado;
wheel/editable/launcher validados em instalações separadas no Windows.

Ruff, Mypy strict, formatação, pre-commit e scans de secrets fazem parte do
fechamento descrito na [auditoria](reviews/G4_OFFLINE_RESEARCH_LAB_IMPLEMENTATION_AUDIT.md).
**GLOBAL_COVERAGE_PENDING**: a medição G4 cobre o console, não toda a suíte.
Os 96,53% da G3.1 continuam evidência histórica, sem reclassificação como G4.

Limitações para revisão: proveniência declarada sem assinatura; fees agregadas
sem ledger no pack; servidor sequencial; risco amostrado sem proteção automática;
sem teste Linux/macOS ou corpus histórico novo. Não se demonstrou vantagem
econômica. Revisar diff, contratos, direitos de exportação e pendência global
antes de autorizar publicação. Não há autorização implícita para merge/release/G5.

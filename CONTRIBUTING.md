# Contribuição

Antes de alterar comportamento financeiro, descreva a necessidade e o contrato
afetado em uma issue técnica. Não crie atividade artificial. Correções pequenas
de documentação podem ir direto para uma branch.

Fluxo: branch → mudança concreta → verificações pertinentes → revisão →
commit → PR. Preserve Decimal, conservação, identidade de ciclos, CORE e
bloqueios de execução real. Não altere regras econômicas congeladas para melhorar
resultados históricos. Registre limitações e falhas sem rotulá-las como PASS.

Verificações locais: Ruff, Mypy e a seleção explícita em `ci/smoke-suite.txt`.
Outros testes permanecem no pacote; a seleção não transforma a pendência de
cobertura global em aprovação. Testes financeiros usam somente fixtures sintéticas.

O projeto ainda não escolheu licença de distribuição. Propostas de contribuição
devem aguardar a decisão do titular sobre licença e condições de participação.

# Contribuição e manutenção

Descreva um problema reproduzível e o contrato afetado antes de mudar comportamento
financeiro. Preserve Decimal, conservação, ciclos, CORE e bloqueios de execução real.
Não altere políticas congeladas para melhorar resultados históricos.

Fluxo: issue concreta → branch → mudança → verificações pertinentes → revisão →
commit → PR. Não crie atividade para preencher calendário. Um bug deve registrar
entrada mínima, resultado esperado/observado e um teste que falhe antes da correção.

Instalação: siga o README. Execute Ruff, Mypy e `python -m tools.verify --profile
smoke`. Escolha grupos adicionais conforme o impacto; `--profile all` mantém todos
os módulos disponíveis. [TESTING_AND_PERFORMANCE.md](TESTING_AND_PERFORMANCE.md)
distingue testes aprovados, coleta e cobertura pendente. Timeout não é PASS.
Mudanças no núcleo exigem propriedades e verificação de invariantes além do smoke.

Revise dependências em uma branch: release notes, constraints, build, ambiente
limpo, testes e segurança. Registre descobertas e limitações nas notas de versão.
Releases devem corresponder a melhorias verificadas e levar proveniência e estado
real dos gates. Não publique corpus de mercado sem revisão de redistribuição.

Antes de publicar, repita scan de árvore e histórico com Gitleaks, verificando
erros de leitura e a lista exata de arquivos. Não coloque secrets em exemplos,
logs, issues ou capturas. Relatos sensíveis seguem [SECURITY.md](SECURITY.md).

O projeto usa [MIT](LICENSE). Contribua apenas com material que você tenha direito
de disponibilizar sob essa licença e preserve atribuições de terceiros.
CI remoto permanece desativado. A documentação não concede autorização de operação financeira.

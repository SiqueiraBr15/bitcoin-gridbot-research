# G3.1 — Fechamento local e proposta de PR

Proposta documental após validação. Nenhum PR remoto, push, merge, release ou
ativação de Actions. Branch: `fix/g3-global-quality-gate`, derivada de 183efd7.

## Título proposto

Research Console: concluir validação global com partições e cobertura auditáveis

## Descrição proposta

A candidata G3 tinha 1.425 casos Python sem execução concluída e cobertura nativa
parcial de 70,04%, abaixo de 85%. A infraestrutura nova inventaria os nodeids,
executa partições finitas e retomáveis, certifica somente fases completas e
consolida bancos compatíveis pelo coverage.py. A validação do source efetivamente
medido recusa bancos estrangeiros, incompletos ou sem branches.

O fechamento contabilizou **3.420 Python PASS, dois SKIP preexistentes e
19 JavaScript PASS**, zero pendentes. Cobertura nativa **96,52624362001981%**,
104 módulos, 264 bancos completos, threshold original de 85%, exit 0.
Não se somaram reruns, percentuais ou chamadas Hypothesis. As tentativas que
atingiram timeout continuam registradas, com retomadas identificáveis.

Os perfis mostraram custo de reconstrução/revalidação financeira e instrumentação.
O prazo ampliado permitiu concluir os casos caros sem reduzir assertions,
exemplos ou steps. Nenhum código financeiro, console, estratégia, taxa,
parâmetro, CORE, V2 ou dataset foi alterado na G3.1. O original foi revalidado
por 1.665 hashes, HEAD, seis não rastreados e SHA-256 do V2 FINAL.

## Validação e limites para o revisor

- Oito regressões novas de infraestrutura passaram na campanha certificada.
- Console/segurança/isolamento financeiro: 14 casos dirigidos passaram;
  JS: 19 passaram novamente. A fonte do console continua igual à G3.
- Ruff, formatação, Mypy strict, pip check, pre-commit, Gitleaks e diff-check
  registrados na auditoria e nos recibos locais.
- Dois skips: chmod POSIX e criação real de symlink sem privilégio no Windows.
- Linux, CI remoto e todas as ordens de sessão monolítica não foram demonstrados.
- A certificação G3 reutilizada é retrospectiva, verificada por Git/logs/config.
- Cobertura global refere-se ao source original `gridbot`; console Python tem
  95,45% dirigido separado. Lacunas por módulo continuam no manifesto.
- O snapshot da interface G3 ainda informa PENDING; revisar esse metadata antes
  de uma publicação futura. Ele não acompanha dinamicamente os gates locais.
- Nenhuma conclusão de vantagem econômica ou prontidão para trading real.

Um futuro PR contra main inclui também G1/G2/G3 ainda não publicados. Este
documento descreve apenas o delta G3.1; consultar as propostas anteriores para
o conjunto da interface e distribuição. A revisão de publicação continua sendo
uma decisão do orquestrador, sem autorização implícita para push.

## Evidências e reprodução

- [Auditoria de 25 itens](reviews/G3_1_GLOBAL_QUALITY_GATE_CLOSURE_AUDIT.md).
- [Inventário, segmentos e checksums](reviews/G3_1_EXECUTION_MANIFEST.json.gz).
- [Índice do manifesto](reviews/G3_1_EXECUTION_EVIDENCE_INDEX.json).
- [Procedimento manual](G3_1_VALIDATION_PROTOCOL.md).
- [Contexto G3 e proposta anterior](G3_CHANGELOG_AND_PR.md).

## Delta exato G3.1

```text
README.md
TESTING_AND_PERFORMANCE.md
docs/G3_1_CHANGELOG_AND_PR.md
docs/G3_1_VALIDATION_PROTOCOL.md
docs/reviews/G3_1_EXECUTION_EVIDENCE_INDEX.json
docs/reviews/G3_1_EXECUTION_MANIFEST.json.gz
docs/reviews/G3_1_GLOBAL_QUALITY_GATE_CLOSURE_AUDIT.md
tests/test_quality_coverage.py
tests/test_quality_gate.py
tools/quality_coverage.py
tools/quality_gate.py
```

Commits locais: c14aa50, 5cd2e66 e fechamento documental identificável por
`git log`, sem autorreferência circular no relatório. Nenhum arquivo histórico
foi removido. Não iniciar G4 automaticamente.

# G4.6 — Contrato numérico e cadência PAPER

Proposta local para revisão. **Nenhuma atualização do PR #2 foi enviada.**

Base publicada: `bff062beea10bd0ccc614e852797b643aa887497`.
Branch: `fix/g4-numeric-contract-and-paper-cadence`.
HEAD executável validado: `e0ba226f31ff5aae2d253ebf0bafe20e2ae3c437`.
Versão do pacote: `0.1.0.dev0`.

Os packs válidos de 100 e 1.200 marcações falhavam em camadas distintas:
limite de 300 dígitos do formatter e conversão direta de inteiros com mais de
4.300 dígitos no Python. O reparo conserva Fraction e as strings racionais,
usa serialização exata com orçamento derivado do schema, soma balanceada e
formatter BigInt compartilhado. Erros internos são HTTP 500/ANALYSIS_FAILED;
dados inválidos continuam recusados. Valores não nulos pequenos usam aproximação
explícita em vez de zero enganoso. PAPER informa cadência observada de 60 s.

A campanha global também comprovou uma corrida preexistente do lock Windows.
A inicialização do byte agora ocorre somente após adquirir o lock e o unlock
reposiciona o descritor. Duas regressões novas falharam antes e passaram depois.
As campanhas do primeiro HEAD foram retidas e excluídas da cobertura final.

Validação final: **3.631 testes Python PASS, dois skips preexistentes,
33 testes Node PASS, 189 verificações equivalentes G4.5 PASS, quatro holdouts
PASS e cobertura global 96.469876%**, threshold 85% preservado.
Ruff, Mypy, Prettier, pre-commit, Gitleaks, instalação limpa do wheel,
instalação editável, launcher Windows e navegador em quatro dimensões passaram.
Wheel SHA-256: `3f55247c96ff0975bb573ac62f94c46428467ce19c527cec62f0ab589c6f3383`.

JSON completo mantém valores exatos; CSV e export derivado conservam a precisão
decimal documentada. Replay exige identidade analítica. Direitos de exportação,
ZIP integral e quota entre processos permanecem protegidos. CORE, estratégias,
V2 FINAL e o projeto original foram preservados. Nenhuma operação financeira.

Limites: validação local no Windows, sem SLA de pior caso, revisão externa humana
ou prontidão para trading. A auditoria completa e o manifesto identificam as
tentativas incompletas, incidentes de harness, recursos e evidências certificadas.

`G4_6_NUMERIC_CONTRACT_REPAIR_PASS`

`G4_6_PR_UPDATE_READY_FOR_REVIEW`

Aguardar decisão do orquestrador e autorização explícita para qualquer escrita
remota. Não houve push, edição do PR, merge, tag, release ou ativação de Actions.
Não iniciar G5 automaticamente.

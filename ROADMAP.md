# Roadmap técnico

## Base entregue

G4 está integrada à main pelo PR #2, merge
`acaa6879877c8a081a127f3ea8a0cdbb840b88cd`, versão 0.1.0.dev0. A campanha
global histórica G4.8 terminou; não é pendência reaberta pelo planejamento.
Não há release formal ou CI remoto aprovado; Actions permanece desativado.

## Direção G5 escolhida, contrato pendente

1. Alinhar documentação atual e revisar o
   [contrato de Revisão Guiada](docs/G5_GUIDED_EVIDENCE_REVIEW_CONTRACT.md).
2. Após aprovação do orquestrador, implementar o percurso de interpretação
   reutilizando dados, cálculos, APIs e controles de export G4.
3. Validar comportamento, acessibilidade, precisão e empacotamento conforme
   [matriz proposta](docs/G5_IMPLEMENTATION_ACCEPTANCE_MATRIX.md).
4. Submeter candidata à revisão e a checkpoint separado de publicação.

A interface guiada não está implementada. O modo detalhado G4 permanece
disponível. Não criar outra engine financeira, score ou recomendação automática.

## Oportunidades separadas

Jobs/cancelamento CPU, receitas offline, HTML interpretável, Linux/macOS e
assinatura de autoria exigem justificativa e missão próprias. O P3 diagnóstico
Windows10053 pode receber manutenção dirigida, sem virar gate automático.
Otimizações de validação/cache precisam de medição e provas de invariantes;
não retirar revalidação de bytes para acelerar. Manter threshold de 85% e os
300 exemplos do perfil CI Hypothesis; nome CI não significa Actions ativo.

Preservar CORE, políticas e protocolo prospectivo congelados. Não reabrir
otimização retrospectiva de pesos/bandas. Coleta e avaliação econômica
prospectivas dependem de gates e autorizações separados. Nada neste roadmap
autoriza aquisição, Testnet, LIVE, ordens ou ativação de CI.

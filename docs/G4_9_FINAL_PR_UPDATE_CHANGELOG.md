# G4.9 — Changelog local e proposta de atualização futura do PR #2

Status: candidata local final para revisão independente. Nenhuma publicação executada.

G48-P3-004 permitia que IDs válidos longos, títulos contínuos e o readout acionado por teclado ultrapassassem o layout em320/375 px. Uma regra CSS restrita ao Research Lab faz os textos quebrarem dentro dos controles, legendas, headings e ações de estudo; conserva fonte, identidade completa, hashes, schema e rolagem local das tabelas.

Foram adicionados dois guards Node. Não houve alteração de Python, JavaScript produtivo, contratos, dependências, estratégias ou configuração de coverage. Commit executável: `cf1e9c9aba3072bbef80956852bc115e4b1b34b9`. O commit documental final e a identidade do wheel estão nos recibos de entrega G4.9.

Validação fresca:650 Python PASS + um skip Windows preexistente em console/arquitetura;46 Node PASS;446 vetores independentes;189 verificações G4.5;16 cenários Windows; oráculos Fraction; navegador em320/375/390/768/1366/1920; holdout pós-congelamento com dois IDs80 semelhantes e título Unicode240; replay, export real com checksums/source byte a byte e persistência após reinício. Ruff, formatação, Mypy strict, pre-commit, Gitleaks, diff e instalação limpa são fechados nos recibos finais.

Coverage global **histórica G4.8**:96,46987627756859%,3.633 PASS/dois skips; não foi repetida nem mesclada nesta fase. Git prova identidade de Python/testes/configurações e a coleta continua com3.635 nodeids. O wheel muda somente CSS e RECORD em relação ao anterior.

PAPER frio via UI real: HTTP3,344731 s normal e4,148664 s com carga própria moderada. Transporte permanece15 s. Atraso negativo de16,25 s produziu erro explícito em15,111 s; retry recuperou resultado e resposta tardia não sobrescreveu o Lab. Não se confunde o orçamento de60 s de integração com o transporte produtivo. Arquitetura sequencial e trabalho CPU após cancelamento continuam limitações; os tempos são amostras controladas, sem SLA.

Wheel testado: SHA-256 `46c1988aa2d02b9e58b89da14c7f2e1758a4c752972af32539b3fa9d2d73d1ea`. O build de HEAD documental final é comparado byte a byte em `FINAL_WHEEL_IDENTITY.json`. Manifesto V2 FINAL, original, CORE, históricos e resultados preservados.

Leitura GitHub final de27/10/2026 17:45:57 UTC: PR #2 aberto, head `bff062beea10bd0ccc614e852797b643aa887497`, main `88390ac0b3726c50b548e5087acfa39982d76342`; nenhuma mudança remota; Actions desativado. Zero checks não equivale a CI aprovada.

Para uma atualização futura, revisar o intervalo completo bff062 → HEAD final, incluindo reparos G4.6/G4.8 ainda locais. Patch integral e inventário estão na área externa G4.9; o pequeno delta G4.9 contém apenas CSS, teste Node e dois documentos. Relatório: [auditoria final G4.9](reviews/G4_9_FINAL_UX_AND_RELEASE_FREEZE_AUDIT.md).

Recomendação: revisão independente e decisão do orquestrador. Sem push, edição do PR, merge, Actions, release ou G5 nesta missão.

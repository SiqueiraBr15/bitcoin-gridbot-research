# G4.8 — Changelog e proposta local para o PR #2

O teste de menus usava o mesmo prazo de socket para transporte e para geração fria do motor PAPER, cujo replay/validações consomem CPU e ficam mais caros sob tracing. O contrato de menus agora prepara dados reais numa fixture própria; duas integrações HTTP frias conservam geração e oráculos independentes com orçamento finito medido. O prazo padrão de 15 s foi preservado e o orçamento específico de 60 s está explicitamente justificado no relatório.

O Lab preserva capacidades do catálogo ao navegar e selecionar estudos, apresenta erros atuais após importação com estados separados e formata/quebra o aviso de risco móvel mantendo origem e exportações exatas. Navegação interrompida informa incerteza da confirmação; cancelar o cliente não é desfazer persistência no servidor.

Validação nova no executável `f75bef168f9f7dba077f91870460a55f27a6b972`:

- 3633 Python PASS + 2 skips preexistentes; zero falhas/omissões/incompletos, 3.635 nodeids reconciliados.
- Cobertura global de linhas+ramos 96.46987628%, limiar original 85%, dados novos sem medições históricas.
- 44 testes Node; 189 regressões G4.5; 446 vetores numéricos em campanha separada; oráculos Fraction e Windows lock/quota PASS.
- Wheel limpo SHA-256 `206887c7deb4872afefce5e4f4d840adb15fdf5ab5da78ffa48501ffcc969107`; UI real, replay, ZIP/JSON/SVG, reinício e holdouts novos conferidos.
- Ruff, Mypy strict, formatação, hooks, Gitleaks e Git checks PASS; sem alteração de dependências, CORE, estratégias, parâmetros ou V2 FINAL.

Limitações para revisão: geração nativa fria ainda pode ocupar o servidor sequencial; isso não é otimização de runtime. Novo P3 de layout com identificador muito longo permanece em 320/375 px (página 370 px; parágrafo de risco corrigido sem overflow). A aceitação/priorização deve constar da decisão do orquestrador. Histórico G4.7 continua BLOCKED; esta é evidência nova G4.8.

Relatório completo: [G4.8](reviews/G4_8_FINAL_QUALITY_GATE_AND_UX_REPAIR_AUDIT.md). Evidências locais em `C:/dev/github-portfolio-2026/audit/g4_8/`, com hashes, comandos e logs. Este texto é apenas proposta local: não foi enviado ao GitHub. HEAD de entrega posterior contém somente estes dois documentos adicionais e é reconciliado com o executável certificado no receipt final.

Nenhum push, atualização de PR, merge, Actions, tag, release ou G5 nesta fase. Aguardar revisão do ChatGPT orquestrador.

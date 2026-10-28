# G4.2 — Checklist de publicação controlada

Branch local: `release/g4-offline-research-lab`.
Base remota verificada anonimamente: `88390ac0b3726c50b548e5087acfa39982d76342`.
Código instalado: `548aaa8fa0761ce57a36e47950b7dd3f55b0026f`.
HEAD de entrega: resolver `git rev-parse HEAD` no commit que contém este checklist;
identificador completo também consta na entrega/checkpoint externo da auditoria.

## Gates locais concluídos

- [x] Ancestralidade G4/G4.1 preservada; candidata local, sem reescrita de main.
- [x] 3.612 nodeids reconciliados; 3.610 PASS + 2 skips explicados, 273 segmentos.
- [x] Equivalência dos295 arquivos; cobertura96,47583040777748%, 120 módulos;
  threshold85% preservado; exemplos separados87,36842105263158% históricos.
- [x] 190 testes Python novos na execução, sem falhas/skips; 26 testes Node.
- [x] Revisão independente ZIP/consentimento/quota real32 e limites por byte.
- [x] Oráculo Fraction, benchmark, Pareto, episódios, export e replay conferidos.
- [x] Wheel/editable novos, launcher Windows e recursos completos; nenhum acesso
  runtime ao original/checkout privado/caches G4.1.
- [x] Navegador real no wheel em1920/1366/768/390, captura nativa, persistência,
  cancelamento/resposta atrasada, autorização por sessão e PAPER.
- [x] Ruff, formato Python/JS, Mypy strict, pre-commit e diff check.
- [x] Gitleaks árvore, histórico inteiro candidato, novos blobs e arquivos
  compactados decodificados; nenhum scanner com erro aceito como PASS.
- [x] 39 versões consultadas no OSV, zero achados conhecidos nessa consulta.
- [x] Inventário A/M/D e hashes preparados; nenhum arquivo candidato >500KiB.
- [x] Original1665 arquivos, seis históricos e V2 FINAL preservados; dois
  relatórios públicos antigos não rastreados preservados fora do stage/PR.
- [x] README diferencia candidata local e main publicada; versão real dev0.
- [x] Nenhuma ordem, credencial, coleta prospectiva ou novo estudo econômico.

## Checkpoint obrigatório antes de qualquer escrita remota

- [ ] ChatGPT/usuário revisar auditoria, diff e HEAD completo final.
- [ ] Autorizar expressamente push da branch/HEAD e abertura do PR, sem merge.
- [ ] Conferir novamente main remota e ausência de mudança inesperada.
- [ ] Proprietário conferir **Actions administrativo OFF**. Último registro
  autenticado é histórico; consulta anônima nesta fase recebeu401 nessa rota.
  Zero workflows/runs públicos não substitui essa verificação. Não ativar Actions.
- [ ] Se o HEAD/código/config/dependências mudarem, definir e concluir nova
  validação proporcional; não atribuir os resultados a código diferente.

## Sequência futura, somente depois da autorização

1. Conferir Git, inventário e os dois não rastreados; publicar somente a candidata.
2. Abrir PR para main com corpo revisado, links corretos e número dado pelo GitHub.
3. Conferir diff remoto, identidade do HEAD, arquivos e evidências sem dados privados.
4. Parar para revisão e autorização separada de merge.
5. Avaliar depois versão0.1.0rc1/rebuild e eventual release. Nenhuma tag agora.

Estado atual: **PUBLICATION_CANDIDATE_READY**, publicação **não autorizada**.
Sem push, PR remoto, merge, tag/release ou Actions nesta missão. Sem G5.

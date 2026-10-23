# Checkpoint de publicação — Research Console

Este documento não executa comandos nem concede autorização remota.

## Preparação local verificada

- [x] Reconciliar 2.006 PASS mistos e 3.420 PASS Python por nodeids.
- [x] Confirmar os dois skips, zero omissões e fonte da cobertura de 96,53%.
- [x] Preservar cadeia main → G1 → G2 → G3 → G3.1 → G3.2, sem rebase/reset.
- [x] Validar console, regressões, instalação limpa, wheel e exports sintéticos.
- [x] Manter runtime financeiro, CORE, V2, original e seis históricos.
- [x] Corrigir pin dev filelock 4.2.1, mantendo o achado anterior registrado.
- [x] Rever documentação, screenshots reais e manifesto de arquivos.
- [x] Manter CI inativo e proposta fora de `.github/workflows/`.

Os resultados específicos, scans e limites estão na auditoria; caixas marcadas
não substituem evidências ou autorização do usuário.

## Ações remotas — nenhuma realizada

| Etapa | Destino | Exige aprovação explícita |
| --- | --- | --- |
| 1. Publicar branch candidata | SiqueiraBr15/bitcoin-gridbot-research, `release/g3-research-console` | Sim, após revisar HEAD/diff/manifesto |
| 2. Abrir PR | Mesmo repositório, base main | Sim; descrição consolidada preparada |
| 3. Integrar à main | PR revisado, sem force-push | Aprovação nova em etapa separada |
| 4. Publicar tag/release | Versão/artefato/notas exatos | Aprovação nova após preparar/testar versão |

Autorização das etapas 1–2 não autoriza 3–4 nem Actions. Não criar cron, secrets,
adaptação de trading ou coleta. Confirmar novamente a main remota antes de push;
se divergir de a28e6f3, revisar a integração em vez de substituir o histórico.

## Antes de eventual release

- [ ] Aprovar a proposta 0.1.0rc1 ou outra versão coerente.
- [ ] Atualizar/testar metadados e regressão de versão; gerar novo wheel.
- [ ] Conferir checksum/conteúdo do artefato exato a publicar.
- [ ] Repetir consulta de advisories e Gitleaks no HEAD aprovado.
- [ ] Manter as limitações econômicas e de plataforma nas notas.
- [ ] Obter autorização específica para tag e release; não renomear dev0 como rc1.

Linux e CI remoto continuam não validados; eventual ativação de Actions exige
aprovação própria e revisão do YAML. Nenhum gate de engenharia autoriza operar
com dinheiro real ou promete vantagem econômica.

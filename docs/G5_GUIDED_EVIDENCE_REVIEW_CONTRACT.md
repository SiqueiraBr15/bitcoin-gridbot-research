# G5 — Contrato de Revisão Guiada de Evidências

**Contrato G5.1 inspecionado e implementação G5.2 autorizada pelo orquestrador.**
Contrato de 28/10/2026, baseado na G4 integrada por PR #2, main
`acaa6879877c8a081a127f3ea8a0cdbb840b88cd`. Os requisitos abaixo são preservados;
o estado anterior de proposta está no histórico Git G5.1. Consulte o
[guia implementado](G5_GUIDED_REVIEW.md) e a auditoria G5.2 para resultados e
limitações de validação. Não autoriza operações remotas ou avaliação econômica nova.

## Objetivo e alcance

Organizar a leitura de uma análise existente em sete etapas, reutilizando o
Lab, suas métricas, gráficos, evidências e controles. Não criar outro dashboard,
engine, schema financeiro, endpoint ou sistema de exportação. O modo detalhado
permanece disponível. Etapas podem ser visitadas diretamente; avançar não
significa aprovar um investimento ou certificar a pesquisa.

O MVP proposto atende Evidence Packs v1 admitidos pela biblioteca. O adaptador
histórico M1/M1.R e a demo PAPER conservam suas páginas atuais; não serão
convertidos automaticamente em packs ou misturados à revisão. Entrar no
percurso não executa a demo, estratégias, coleta, otimização ou replay.

### Decisões críticas frente ao planejamento G5.0

- Adotar as sete etapas desta missão, com acesso direto e atalho ao modo
  detalhado, em vez de obrigar um usuário experiente a atravessar sete telas.
- Selecionar contas existentes, não criar políticas/janelas/custos. Esses
  campos são filtros de contas do pack, traduzidos para account_id.
- Benchmark é a referência declarada da conta, somente leitura. Incluir sua
  conta na seleção quando disponível usa accounts; substituir benchmark
  exigiria outro escopo. Não enviar parâmetro benchmark inventado.
- Não duplicar comparable_key, NAV, DD ou Pareto no JS. Motivos não enviados
  pelo backend só podem ser explicados genericamente, sem atribuir causa falsa.
- Concluir significa resumo local de leitura, sem persistência nova, relatório
  exportado novo ou recomendação. Download continua nas funções G4.

## Jornada e ligação aos dados existentes

| Etapa | Conteúdo e origem | Ausências e limites |
| --- | --- | --- |
| 1 Escolher evidência | Biblioteca: título, fonte/tipo, natureza, integridade, proveniência, período, políticas, custos, restrição. Escolher pack e contas; janela/custo/benchmark são contexto das contas selecionadas | Sem pack ou fonte válida: nenhum número. Um resumo agregado não vira curva. Fonte autodeclarada não comprova autoria |
| 2 Patrimônio | metrics.exact.nav_initial/nav_final/return_usdt/return_ratio/fees_usdt; benchmark_comparison.delta_nav/relative_nav e status | Razão com denominador zero é null. Delta de benchmark disponível apenas quando COMPARABLE; valores existentes de comparação têm precisão decimal declarada, não inventar exact ausente |
| 3 BTC | exact.btc_physical/btc_equivalent/cash_usdt/btc_change, ponto final de accounts.points e preço/unidades | BTC equivalente não é custódia. Mais BTC não implica maior NAV universalmente. Fees já refletidas; v1 não prova CORE ou fees em terceiro ativo |
| 4 Risco | metrics.risk: max_drawdown_fraction, risk_complete, status, gaps, episodes, índices/horários, recovery_at, censored, observed_seconds e flags existentes | Não tratar risco incompleto como zero, recuperação ausente como concluída ou 20% como proteção. Separar máximo por segmentos de máximo completo |
| 5 Comparar | group_id, benchmark/status, objetivos escolhidos, pareto.non_dominated, métricas e descritivos já calculados | Comparar somente dentro de grupos admitidos. Fora do Pareto por exact null é distinto de dominância. Não concatenar contas ou ranquear grupos |
| 6 Verificar | Hash pack/manifesto/results/série, account_id/policy/window, seleção, evidence.final_point_index/timestamp/units, versões e analysis_manifest; replay mediante clique | Integridade não prova origem. Replay de análise não reexecuta políticas; somente EQUIVALENT vigente comprova igualdade de análise |
| 7 Concluir | Recapitular valores examinados, fonte/seleção, completude, comparabilidade e limitações; ligar à evidência e aos controles atuais de export | Resumo por projeção dos campos presentes, sem texto econômico livre/inferência/score. Restrições não desaparecem na etapa final |

Filtros de política/janela/custo não são parâmetros livres da API do Lab. A
interface deve mostrar combinações realmente presentes e identificar grupos
distintos, sem sintetizar novas observações. Quando a referência não estiver
selecionada, oferecer incluir a conta declarada ou manter comparação
indisponível; nenhuma inclusão silenciosa.

## APIs existentes e permissões

GETs usam Host/origem e cookie local efêmero já existentes. POSTs exigem também
`X-GridBot-Lab: 1`, Content-Type exato e Content-Length único dentro da quota.
Não introduzir CORS, chamadas externas ou paths por HTTP.

| Endpoint existente | Parâmetros/corpo | Uso proposto e resultado |
| --- | --- | --- |
| GET /api/lab/library | Sem query | Etapa1; studies, metadados, persistence_enabled e archive_adapter. O adaptador indisponível não impede os três estudos embutidos |
| GET /api/lab/analysis | id obrigatório; accounts e objectives opcionais, listas CSV em parâmetro único | Etapas2–7; rows/metrics/risk/benchmark, accounts/points, pareto, evidências e analysis_manifest. Não enviar policy/window/cost/benchmark como parâmetros novos |
| POST /api/lab/replay | JSON exatamente id, manifest | Etapa6 sob ação explícita; retorna EQUIVALENT/result_sha256/strategies_executed=false ou erro. Não chamar ao voltar/avançar |
| GET /api/lab/export | id; accounts/objectives; reviewed=0 ou1 | Etapa7 via controle existente; ZIP autorizado. AGGREGATES_ONLY exige revisão explícita, e todos os grants continuam verificados no servidor |
| GET /api/lab/source | Somente id | Fonte bruta apenas RAW_AND_DERIVED; não criar nova forma de baixar dados |
| POST /api/lab/authorize-export | JSON id, scope, basis, confirmed | Reutilizar formulário G4; escopos DERIVED_ONLY/RAW_AND_DERIVED e bases atuais. confirmed deve ser true; metadados não concedem grant |
| POST /api/lab/preview | Bytes application/zip, até2 MiB | Importador existente antes da revisão; prévia não é cópia persistida |
| POST /api/lab/confirm | JSON preview_token, confirmed | Confirmação existente, prazo300 s e pasta própria. Não repetir em navegação ou inferir rollback de conexão interrompida |
| POST /api/lab/remove | JSON id, confirmed | Controle existente da biblioteca; invalida revisão daquele pack após remoção confirmada |

O guide não usa GET /api/lab/paper, /api/demo, /api/selection ou /api/export
legados para preencher etapas. Esses fluxos continuam disponíveis em seus
contextos atuais. POST JSON tem teto16384 bytes; o seletor atual de manifesto
de replay limita arquivo a16000 bytes. Não ampliar esses limites nesta G5.

### Versões e matemática

Pack: schema_version=1. Análise: analytics_version=G4_ANALYTICS_V1,
numeric_contract=EXACT_RATIONAL_DECIMAL_V2. Manifesto:
GRIDBOT_ANALYSIS_V1, implementation_sha256 e expected_result_sha256.
GRIDBOT_RESEARCH_SELECTION_V3 pertence ao console legado, não ao pack.

NAV=caixa+BTC×preço e BTCeq=NAV/preço já são calculados/validados em Python.
Frontend formata strings com numbers.js/BigInt/half-even; Number fica restrito
às coordenadas aproximadas dos gráficos. Não calcular métricas por diferença
de números arredondados. DD de gráfico assinado e magnitude positiva do máximo
devem ser rotulados. Exatamente1/5 não excede a referência; ausência de dado
permanece null. Não adicionar anualização, indicadores, score ou regras de venda.

## Estado e identidade propostos

Contrato interno de apresentação: GRIDBOT_GUIDED_REVIEW_STATE_V1. Não é arquivo
importável, schema de pack ou manifesto de resultado. Estrutura conceitual:

| Campo | Regra |
| --- | --- |
| mode, step | detailed/guided; etapa1–7, preferência validada |
| generation, requestTicket | Contadores locais efêmeros; cada nova seleção invalida tickets anteriores |
| draftSelection | pack_id opaco e accounts/objectives destinados à API atual; sem métricas |
| committedIdentity | pack_sha256, manifest_sha256, implementation_sha256, accounts/objectives e expected_result_sha256 recebidos do resultado aceito |
| focusedAccount | account_id presente nas rows atuais; policy, window, custo e benchmark são lidos dessa conta |
| evidenceContext | Fonte/natureza/redistribution, evidence e versões da resposta; nenhum path |
| comparableGroups | group_id das rows atuais; não computar novamente no JS |
| availability | IDLE/LOADING/READY/AGGREGATE_ONLY/UNAVAILABLE/INVALID/ERROR; qualificadores de risco ficam separados |
| error | Código/status sanitizados do request vigente; sem path/stack ou interpretação jurídica |
| replay | NOT_RUN/RUNNING/EQUIVALENT/FAILED, sempre vinculado à committedIdentity e ticket |
| export | Estado informativo do escopo atual e request IDLE/RUNNING/FAILED; não armazena autoridade própria |

Antes da resposta não existe expected_result_sha256 conhecido: draft/ticket e
identidade confirmada são distintos. Preservar ordem/semântica das seleções
atuais nos manifestos; não reordenar objetivos de manifestos antigos para forçar
equivalência. Comparar identidade completa, nunca só título/policy ou prefixo
do SHA. Mudar foco/etapa sem alterar subconjunto não executa nova análise.

### Transições e concorrência

| Evento | Transição/efeito obrigatório |
| --- | --- |
| Entrada no modo | Biblioteca atual; sem análise fictícia ou execução PAPER automática |
| Seleção aplicada | generation++; abortar fetch anterior; LOADING; retirar resultado/replay/export dependentes da tela até aceitar resposta |
| Resposta válida vigente | Ticket e pack/seleção compatíveis: vincular committedIdentity, READY ou AGGREGATE_ONLY; replay NOT_RUN |
| Resposta tardia | Ignorar inclusive erro/sucesso, sem sobrescrever status ou liberar botões |
| Fonte/seleção alterada ou removida | Invalidar dados/replay/export dependentes; voltar ao contexto seguro da etapa1 sem reutilizar valores como atuais |
| Anterior/próxima/etapa direta | Somente apresentação; não duplicar requests, confirmação, replay ou download |
| Timeout/erro vigente | Falha visível, dados atuais indisponíveis; retry explícito da seleção. Nunca usar sucesso antigo como fallback |
| Replay clicado | Vincular ticket e identidade; EQUIVALENT somente após resposta atual; trocar seleção invalida o selo |
| Export clicado | Reutilizar controle/validação G4; mudança de seleção cancela download e impede publicação tardia |
| Reinício do servidor | Recarregar sessão e revalidar biblioteca; grants e replay local são perdidos. Pack persistido não herda autorização |

Duas abas têm navegação/preferências isoladas por aba; o cookie e os grants
do servidor podem ser compartilhados no mesmo processo/porta, como já ocorre.
Não prometer isolamento de grants entre abas ou identificar cada aba como
usuário. Alteração de pack/remove exige nova leitura; bytes são revalidados
mesmo em cache hit no backend.

Somente preferência enumerada de modo/etapa pode ir para sessionStorage.
Não usar localStorage nem persistir séries, packs, tokens, grants, paths,
notas ou cópias financeiras adicionais. Erro de leitura de preferência volta
ao padrão. Reload pode restaurar uma etapa, mas exige biblioteca/análise
vigentes antes de exibir números ou estado EQUIVALENT.

### Erros reais e linguagem de disponibilidade

HTTP403: sessão/origem/header recusado; HTTP405: rota/método não admitido;
HTTP422: dados/seleção/restrição recusados; HTTP500 ANALYSIS_FAILED: falha
interna, não prova de pack inválido. HTTP400 cobre target malformado;404 rota
inexistente;503 asset indisponível. Falha de rede/timeout cliente não prova
rollback ou corrupção. POST pode ter concluído antes de perder a conexão;
consultar biblioteca, não confirmar novamente automaticamente.

Razões atuais do Lab incluem DATA_UNAVAILABLE, LIBRARY_BUSY,
INTEGRITY_MISMATCH, SIZE_LIMIT, UNSUPPORTED_VERSION, INCOMPATIBLE_BENCHMARK,
NAV_CONSERVATION_FAILED, INVALID_TIMESTAMPS, PERSISTENCE_DISABLED,
PREVIEW_EXPIRED, CONFIRMATION_REQUIRED, EXPORT_RESTRICTED e
INVALID_SCHEMA_OR_DATA. Um422 com source_kind=DATA_INVALID pode significar
restrição de export: usar reason/contexto, não afirmar corrupção pelo rótulo.
Falha de replay não tem código específico garantido; não inventar um endpoint
ou classificador para ocultar essa limitação. Erros desconhecidos recebem
mensagem neutra, com retry quando apropriado, sem exibir exception original.

## Arquitetura e limites de confiança

Proposta: projeção pura review_model.js e renderizador review_view.js, integrados
ao lifecycle de lab.js e aos componentes existentes. Esses módulos ainda não
existem. Novos JS requereriam nomes fixos no mapa de assets de server.py e
carregamento em index.html; não autorizar servidor genérico de arquivos.

Nenhuma fórmula/API analítica nova. Preservar src/gridbot, analytics, numeric,
packs, exports, permissions, library, data, risk e demo. A identidade carregada
por exports inclui __init__, analytics, numeric, packs, exports, data e risk;
alterar HTML/JS/allowlist não deve alterar os hashes analíticos para a mesma
seleção. Versão da UI é separada. Uma eventual edição de exports.py requer
outra revisão de identidade/replay, fora deste MVP.

Texto de pack é entrada não confiável: textContent/DOM seguro, sem código,
innerHTML ou templates executáveis. UI não concede grants e não cria Blob,
CSV, HTML, manifesto ou SVG novo para contornar a política. RESTRICTED nunca
é superado; DERIVED_ONLY não ganha séries/raw/exact/episódios no export.
Não copiar dados privados ao wheel/Git, não fazer upload externo, telemetria,
chamadas Binance, aquisição ou agendamento. Leitura local autorizada não é DRM
nem autorização automática para redistribuir. Nenhuma mudança de segurança G4
está aprovada por este contrato ainda pendente.

## Revisão crítica e decisões para aprovação

O ganho esperado é compreensão e rastreabilidade, não mais métricas. Evitar
duplicar as sete páginas do console: um único painel no Lab, com cartões e
detalhes existentes. Mostrar todos os passos como mapa de leitura e permitir
saltar; a conclusão não exige marcar sete confirmações. Estudo com agregados
pode pular explicações sem suporte, mantendo “não disponível” explícito.

Riscos principais: modo guiado parecer certificação; group_id confundido com
autoria; null parecer zero; uma aba receber resposta antiga; etapa final criar
export paralelo. As regras acima e a matriz tornam esses riscos verificáveis.
Não há necessidade demonstrada de endpoint novo, framework, worker, persistência
de revisões ou assinaturas. Jobs, relatório narrativo exportado, prospectivo,
novos indicadores e portabilidade são trilhas separadas.

ChatGPT deve aprovar: sete etapas com salto livre; MVP restrito a packs;
benchmark declarado somente leitura; modelo/estados; limites de arquivos
propostos; matriz e UX. G5.2 só começa depois dessa decisão. Não escolher
implementação maior se essas etapas puderem ser atendidas pelos controles atuais.

[UX](G5_GUIDED_EVIDENCE_REVIEW_UX.md) ·
[Matriz verificável](G5_IMPLEMENTATION_ACCEPTANCE_MATRIX.md) ·
[Contrato Pack v1](G4_EVIDENCE_PACK_V1.md)

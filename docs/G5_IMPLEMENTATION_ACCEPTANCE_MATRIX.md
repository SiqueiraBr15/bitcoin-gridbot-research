# G5 — Matriz de aceitação futura

**G5_CONTRACT_AWAITING_ORCHESTRATOR_APPROVAL.** Critérios G5.1,28/10/2026.
Todos os casos abaixo estão **PLANNED / NÃO EXECUTADOS PARA G5**. Testes G4
preexistentes ajudam a definir oráculos, mas não aprovam componentes ainda
inexistentes. [Contrato](G5_GUIDED_EVIDENCE_REVIEW_CONTRACT.md) ·
[UX](G5_GUIDED_EVIDENCE_REVIEW_UX.md)

G5.2 proposta: modelo/render e integração do percurso após aprovação do
contrato. G5.3 proposta: validação independente da candidata e fechamento das
pendências. A numeração anterior do planejamento G5.0 era sugestiva; este
recorte não autoriza desenvolvimento ou publicação.

| ID / requisito | Entrada/ação de reprodução futura | Oráculo e resultado verificável | Camada / fase |
| --- | --- | --- | --- |
| A01 Percurso completo | Abrir favorable, selecionar três contas e percorrer1–7 | NAV inicial100; finais BTC_HOLD130/MIX115/CASH100 conforme fixture; fonte sintética, sem execução de estratégia ou requests financeiros extras | Browser + recibos HTTP; G5.2/3 |
| A02 Navegação | Anterior/próxima, salto direto, detalhado/guiado, sair/voltar | Mesma seleção/valores; zero replay/import/export duplicado; foco no título por ação, sem roubo assíncrono | Modelo + browser; G5.2/3 |
| A03 Mudança de seleção | Pack A em voo; aplicar B ou outro subconjunto/objetivos | A invalida; somente ticket/identidade B pode preencher resumo; conta/benchmark/risco do A não aparecem | Modelo e HTTP controlado; G5.2/3 |
| A04 Fonte inválida | Corromper checksum/schema em cópia sintética ou injetar422 existente | Diagnóstico sanitizado; sem substituição sintética automática, valores antigos ou rótulo de sucesso | HTTP + browser; G5.2/3 |
| A05 Fonte indisponível | Biblioteca/fonte recusada ou id removido | Ausência explícita e volta à seleção; biblioteca de exemplos não depende de corpus histórico | HTTP + browser; G5.2/3 |
| A06 Dados incompletos | Pack válido com gap; série unitária; agregado sem curva | risk_complete=false/null preservados; segmentos/censura não viram risco completo ou gráfico inventado | Fixture/oráculo independente + browser; G5.2/3 |
| A07 Estudos incompatíveis | Selecionar contas de grupos distintos; benchmark ausente; benchmark inválido no pack | Sem Pareto global; status benchmark ausente permanece; declaração incompatível é recusada pelo leitor atual, não “corrigida” pela UI | Python existente + modelo/browser; G5.2/3 |
| A08 Valores exatos | Racionais longos, expoentes extremos e arredondamento half-even | Formatação pelo numbers.js atual; exact não passa por Number; valores não nulos pequenos não parecem zero exato | Vetores independentes Node + browser; G5.2/3 |
| A09 NAV | Marca do fixture risk_violation; conferir caixa/BTC/preço/NAV | Fraction independente da fixture confere NAV; UI mostra valores canônicos, não soma strings arredondadas ou reservas novamente | Oráculo Python/harness + browser; G5.3 |
| A10 BTC físico | BTC_HOLD10, MIX5, CASH0 nos fixtures matemáticos | Quantidade física mostrada como BTC; não somar equivalente nem atribuir CORE sem evidência no schema | Fixture manual + browser; G5.2/3 |
| A11 BTC equivalente | favorable final a preço13 | BTC_HOLD=10; MIX=115/13; CASH=100/13. Racionais existentes preservados; caixa/quantidade física distintos | Fraction independente + formatter/browser; G5.3 |
| A12 Drawdown | risk_violation: BTC_HOLD40%, MIX20%, CASH0%; adicionar gap/censura | >1/5 excede; =1/5 não excede; zero válido distinto de insuficiente; recuperação somente observada | Oráculo e episódios G4 + browser; G5.2/3 |
| A13 Pareto | Empates/permutação; objetivos com/sem DD e DD null | Lista canônica vem do backend; não recomputar. Inelegível por null é distinto de dominada; nenhum vencedor entre grupos | Propriedades existentes + modelo; G5.2/3 |
| A14 Rastreabilidade | Trocar conta e inspecionar origem de cada cartão | Hash completo, account_id, índice/hora/unidades e manifestação pertencem ao snapshot atual; prefixos iguais não confundem identidades | Modelo + browser; G5.2/3 |
| A15 Replay | Clique explícito; manifesto alterado/outro código; troca de seleção em voo | EQUIVALENT só com resposta atual idêntica; incompatibilidade mantém falha; navegar não executa replay | HTTP/replay atual + browser; G5.2/3 |
| A16 Export | Matriz fixture interno/PUBLIC externo sem grant/DERIVED_ONLY/RAW_AND_DERIVED/AGGREGATES_ONLY/RESTRICTED | Servidor decide. Sem rota/Blob novo; derivados não contêm raw/séries/exact/episódios; RESTRICTED bloqueado; grant não nasce do pack | HTTP/ZIP por conteúdo + browser; G5.3 |
| A17 Respostas atrasadas | Atrasar sucesso/erro/replay/export A, aceitar B, liberar A | A não altera foco/status/selo/download. Abort cliente não é prova de CPU parada ou rollback | Tickets/modelo + browser; G5.2/3 |
| A18 Erros HTTP |403/400/404/405/422/500/503 e timeout/rede nos contextos apropriados |500 não é dado inválido;422 restrição não é corrupção só por source_kind; mensagem sem path/stack; retry explícito | Harness HTTP + browser; G5.2/3 |
| A19 Duas abas | Mesma porta, seleções distintas; grant numa aba | Resultados/navegação isolados; grants/cookie compartilhados conforme servidor atual, sem alegar isolamento inexistente | Browser com duas abas; G5.3 |
| A20 Reinício | Pack persistido, grant e replay; reiniciar processo próprio | Pack íntegro persiste; sessão/grant/replay não são restaurados de storage. Recarregar/revalidar antes de números atuais | Processo/browser; G5.3 |
| A21 Responsividade |320/390/768/1366/1920, IDs80/título240 e zoom200% | Sem clipping/readout truncado ou overflow global; tabelas têm rolagem local identificada; controles acessíveis | Capturas e medidas DOM reais; G5.2/3 |
| A22 Acessibilidade | Teclado inteiro, foco, labels/legendas, erros, contraste e leitor disponível | Ordem e foco observáveis, erros anunciados sem roubo de foco; contraste medido conforme UX; limitações registradas | Browser/ferramenta/AT real; G5.3 |
| A23 Wheel público | Build novo e instalação limpa fora do checkout | Assets/guias presentes; versão correta; nenhum corpus/secret/path privado; conteúdo inspecionado e comparado por hash | ZIP/METADATA/payload + Gitleaks; G5.3 |
| A24 Preservação financeira | Comparar candidata com baseline e repetir mesma seleção | src/gridbot, módulos de identidade analítica, políticas e V2 intactos; mesmo analysis_manifest/result hash; sem API nova ou efeitos de negociação | Git/hash/replay + isolamento de rede; G5.2/3 |

## Regras para os oráculos e evidências

Os números dos três packs vêm de `examples/lab_packs/INDEX.json` e da construção
matemática de `lab/fixtures.py`, não de copiar a saída do renderer novo. A09/11/12
devem usar Fraction independente no harness, com exemplos pequenos deriváveis
à mão; não executar novos backtests para criar expectativas. Não substituir
comparações exatas por tolerância de float ou screenshot apenas visual.

Separar modelo sem efeitos, integração de requests e browser real. Fixtures de
resposta controlada podem exercitar corrida/erro, mas os caminhos completos
de análise/replay/export devem usar o servidor e wheel reais também. Conteúdo
hostil em títulos deve ser texto, sem execução. Estado financeiro não pode ser
persistido em localStorage/sessionStorage pela revisão.

Cada execução futura registra HEAD, hash/fixture, seleção, oráculo, comando,
ambiente, duração/limite e resultado PASS/FAIL/SKIP/INCOMPLETE. Guardar falhas
intermediárias; contar nodeids únicos sem somar reexecuções. Um componente
existir ou screenshot carregar não basta para aprovar um requisito.

## Critérios de saída propostos

G5.2: contrato aprovado antes de código, implementação dentro do escopo,
regressões dirigidas concluídas e evidências observáveis. G5.3: auditoria
independente dos riscos materiais, matriz resolvida ou pendências explicitamente
bloqueantes. Sem aprovar ausência de teste de leitor/OS por inferência.

Preservar todos os testes atuais, threshold85%, perfil Hypothesis CI300 e
limites de precisão/dados. Módulos financeiros inalterados permitem reconciliar
evidência histórica; isso não é uma nova suíte global. Ampliar verificações se
o diff real ultrapassar UI/allowlist. Nenhuma aprovação autoriza push/merge,
release, Actions, coleta ou evolução econômica automaticamente.

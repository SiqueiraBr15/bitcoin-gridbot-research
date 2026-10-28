# G5 — Proposta visual da Revisão Guiada

**G5_CONTRACT_AWAITING_ORCHESTRATOR_APPROVAL.** Desenho G5.1,28/10/2026.
Nenhum componente, rota ou tela G5 foi implementado. Ver
[contrato](G5_GUIDED_EVIDENCE_REVIEW_CONTRACT.md) e
[aceitação](G5_IMPLEMENTATION_ACCEPTANCE_MATRIX.md).

## Uma experiência dentro do Lab

Propor dois modos de leitura no painel atual: Detalhado e Guiado. Não criar
outro dashboard ou duplicar gráficos, biblioteca, importação e permissões.
O usuário experiente pode entrar diretamente em qualquer etapa ou voltar ao
detalhado, preservando a mesma seleção vigente. A preferência de modo não
executa análise, PAPER, replay, importação ou exportação.

Mapa: **1 Evidência → 2 Patrimônio → 3 BTC → 4 Risco → 5 Comparação →
6 Verificação → 7 Resumo**. É um mapa de leitura, não barra percentual de
processamento ou checklist de aprovação financeira. Passos podem estar sem
dados; isso não bloqueia ler suas limitações ou navegar ao resumo.

Wireframe conceitual; não representa interface implementada:

```text
Research Lab                         [Detalhado | Guiado]
Estudo · fonte/natureza · janela · custo · seleção vigente
[1 Evidência] [2 Patrimônio] ... [7 Resumo]

Título da etapa
Explicação curta, com unidade e alcance
[Valor existente] [Estado/limitação] [Inspecionar origem]
Detalhes/IDs completos e gráfico existente quando pertinente

[Anterior]                  [Próxima]   [Abrir modo detalhado]
```

## Conteúdo e interações por etapa

| Etapa | Blocos propostos | Ações e linguagem |
| --- | --- | --- |
| Evidência | Seleção da biblioteca; contexto de contas/políticas/janelas/custo; fonte, natureza, integridade e restrição separados | “Escolher evidência” e aplicar contas pelos controles atuais. Benchmark declarado não é lista de políticas substituíveis. Importar abre o formulário existente |
| Patrimônio | NAV inicial/final e retorno; fees declaradas; delta benchmark com estado; unidade USDT | “Inspecionar marca final”. Fees já refletidas no caixa. Mostrar “Indisponível: referência não selecionada ou não declarada” em vez de0 |
| BTC | BTC físico, BTC equivalente, caixa e variação; preço/hora final consultáveis | Texto curto: equivalente é poder de compra; não são moedas adicionais. Não usar “melhor carteira” por quantidade física isolada |
| Risco | Magnitude máxima com status; referência20%; lacunas, episódios e recuperação/censura | Usar gráfico e seletor de episódio já existentes. Sem selo verde “seguro”. Data ausente de recuperação aparece “não observada” |
| Comparação | Grupo, benchmark, objetivos e Pareto existentes; tabela de trade-offs | Seleção explícita das contas/objetivos atuais. “Não dominada neste grupo” não significa vencedora global; explicar inelegibilidade por dado ausente |
| Verificação | Trilha de pack → conta → série → marca; versões, seleção e manifesto | “Conferir reprodução” somente por clique e API atual; selo EQUIVALENT vinculado à seleção vigente. IDs completos em detalhes, sem cortar informação |
| Resumo | Contexto, métricas examinadas, limitações/ausências e referências atuais | “Voltar à evidência”, modo detalhado e controles de export existentes. Texto por templates factuais, sem recomendação ou conclusão causal |

O resumo apresenta todos os valores selecionados disponíveis com seus
qualificadores; não declara que uma métrica foi examinada pelo usuário apenas
porque o componente renderizou. Se houver indicação de etapa visitada, deve
ser explicitamente navegação local, não atestado de revisão independente.

## Seleção e carregamento

Manter um resumo compacto sempre visível: estudo, natureza, conta em foco,
janela e custo. Em seleções heterogêneas, mostrar “múltiplos grupos” e oferecer
detalhes; não exibir um período/custo único como se valesse para todas as contas.

Ao aplicar seleção, retirar valores dependentes até validar a resposta. Usar
estado textual “Carregando análise desta seleção”, aria-busy e região de status.
Não conservar um cartão de sucesso antigo sob novo título. Esqueleto pode
indicar estrutura, nunca valores financeiros fictícios. Retry é explícito.

Mudar somente etapa ou conta em foco, dentro do subconjunto já carregado,
não faz request novo. Mudar contas/objetivos usa os controles e lifecycle G4.
Após trocar pack/remover a origem, invalidar resumo/replay/export e voltar à
etapa1. Resposta tardia não altera foco, status, seleção ou botões atuais.

## Navegação, foco e histórico

Anterior/próxima e índice permitem navegar por teclado; na primeira/última
etapa o botão correspondente tem estado indisponível claro. Ao mudar etapa
por ação do usuário, mover foco para seu título com tabindex gerenciado;
não roubar foco quando um request termina em segundo plano. Manter foco
visível e ordem DOM correspondente à leitura visual.

Usar o `#lab` e a navegação de páginas existentes. Não inventar rota backend
ou formato de URL persistente para dados privados. Botões anterior/próxima
são do percurso; voltar/avançar do navegador continuam navegação de páginas.
Uma integração futura com history.state só poderá guardar modo/etapa e precisa
de teste próprio; não é requisito do MVP. Ao sair da página, aplicar teardown,
cancelamento e descarte de observadores existentes. Voltar ao Lab requer estado
vigente, não recuperação de selo de replay de outra sessão.

## Estados visuais e erros

| Estado | Mensagem/ação esperada |
| --- | --- |
| Sem seleção | Escolha um estudo; três exemplos disponíveis, sem histórico privado obrigatório |
| Agregado | Somente contagens declaradas; etapas sem série explicam a ausência |
| Risco incompleto | Limitação em texto junto da métrica, sem substituir null por zero |
| Grupos diferentes | Comparação não admitida; mostrar grupos/contextos, sem eleger vencedor |
| Restrição de export | Explicar estado e encaminhar à revisão de direitos existente; etapa7 não libera dados |
| Erro de dados | Código sanitizado e retorno à escolha da evidência; sem paths/stack |
| Erro interno500 | Análise não concluída; não declarar pack inválido |
| Sessão403/reinício | Recarregar e obter sessão; informar que autorizações anteriores expiraram |
| Timeout/rede | Nenhum resultado atual concluído; retry explícito; não presumir rollback de POST |

Usar ícone/texto/estrutura além de cor. Um status “integridade validada” deve
ficar separado de “autoria não autenticada” e “export não autorizado”; não
combinar os três em uma medalha genérica de confiança.

## Responsividade e acessibilidade a comprovar futuramente

| Largura | Comportamento proposto |
| --- | --- |
| 320 px | Cards em coluna; etapa atual e índice expansível; rótulos inteiros; IDs quebram linha; tabelas com rolagem local identificada |
| 390 px | Mesmo percurso móvel; ações em linhas próprias, sem clipping ou fonte encolhida para caber |
| 768 px | Cards reorganizados conforme espaço real; índice pode ocupar duas linhas sem alterar ordem de teclado |
| 1366 px | Resumo/etapas legíveis, gráfico/tabela existentes; evitar painel paralelo redundante |
| 1920 px | Limitar largura de leitura, usar espaço para detalhes sem esticar linhas de texto indefinidamente |

Não permitir rolagem horizontal da página para resolver IDs longos; a exceção
é a tabela/gráfico com área local navegável já identificada. Preservar o reparo
G4.9 de título e readout, inclusive IDs80 semelhantes e título240 Unicode.

Exigir hierarquia h1/h2/h3 coerente, labels associados, fieldset/legend para
seleções, caption/th nas tabelas, foco visível, botão com nome compreensível,
estado atual das etapas exposto semanticamente e mensagens de erro em região
acessível. Interações não podem depender só de hover, cor ou mouse.

Metas propostas de contraste para os testes: texto normal≥4,5:1; texto grande
e componentes/foco relevantes≥3:1. Medir nas cores realmente renderizadas e
registrar a ferramenta/método; estes critérios não certificam conformidade
integral da aplicação. Testar zoom200%, teclado e pelo menos um leitor de tela
disponível, registrando ambiente/limites. Falta de execução é pendência, não PASS.

## Simplificações recomendadas

Reutilizar cartões, formatter, gráficos, tabela exata, disclosures e formulários.
Não criar tutoriais modais obrigatórios, novos consentimentos para leitura,
histórico persistido de revisões, geração automática de recomendações, PDF,
assinatura ou botão “aprovar estratégia”. O resumo final não é artefato novo
de export. A melhoria deve poder ser avaliada por compreensão e rastreabilidade,
sem tornar sete cliques obrigatórios para alcançar dados que já existem.

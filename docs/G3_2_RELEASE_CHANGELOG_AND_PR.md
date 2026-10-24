# Research Console — changelog consolidado e proposta de PR

Documento local. Nenhuma branch, PR, merge, tag ou release desta atualização foi
publicada. Candidata: `release/g3-research-console`, descendente linear de main.

## Título proposto

Adicionar Research Console offline com demo PAPER, exports e validação auditável

## Descrição preparada para revisão

A versão pública a28e6f3 oferece núcleo e exemplos por CLI. A atualização reúne
G1–G3.2 numa interface local para consultar patrimônio, BTC físico/equivalente,
drawdown, comparação de contas equivalentes e resultados arquivados autorizados.
Sem corpus privado, o modo público informa indisponibilidade e oferece execução
explícita de duas contas sintéticas existentes. Nenhum dos 4.266 registros do
acervo interno acompanha o clone ou o wheel.

O console utiliza HTTP stdlib em 127.0.0.1 e assets locais. Seleção persistente,
referência/subconjunto, navegação voltar/avançar, gráficos por teclado e tabelas
exatas acompanham exports CSV/JSON/SVG com proveniência. DD tem zero no topo e
linha analítica −20%; BTC físico e equivalente são grandezas distintas. Não há
score geral, seleção automática de estratégia, promessa de retorno ou stop-loss.

G3 reforça sessão por porta, bind exclusivo Windows, validação HTTP/JSON, limites
de leitura, cancelamento cliente e identidade de exports. Wheel inclui console,
assets e exemplos; launchers são manuais. G3.1 fecha os 1.425 testes pendentes
por partições com nodeids/hashes e consolidação estrita de branches.

G3.2 identifica corretamente a evidência local na interface e mantém a versão
do catálogo coerente com o pacote instalado. O pin de desenvolvimento filelock
passa a 4.2.1 após advisory verificado; dependências de runtime não mudam.
Os 104 módulos financeiros, regras, CORE, V2 e resultados econômicos permanecem
preservados. Não foram executados estudos históricos novos.

## Validação que acompanha o PR

- Inventário: **3.422 Python = 3.420 PASS + dois skips preexistentes**, zero
  pendentes; **19 JS PASS**, separados. Nodeids G3/G3.1/G3.2 reconciliados.
- G3.2: 474 Python PASS distintos + um skip no recorte reexecutado, 19 JS PASS;
  nenhuma remoção de testes. Os dois skips globais continuam identificados.
- Nativa: evidência local G3.1 de **96,52624362001981%**, source `gridbot`,
  branches, threshold 85%, Windows/Python 3.13.16. Fontes/configuração/runtime
  financeiro iguais; não é medição nova de todo o checkout ou CI remoto.
- Console atual: **95,46079779917468%**, fonte própria e bancos separados.
- Ruff, format, Mypy strict, pre-commit, Gitleaks, pip check e verificações Git.
- Clone local novo, instalação pelo PyPI com constraints, wheel instalado fora
  do checkout, entrypoint, HTTP/assets e demo sem pasta original.
- Oráculo Fraction instalado reconcilia fills/fees, saldos, reservas, NAV,
  BTC equivalente e DD nas oito marcas sintéticas; JSON/CSV fazem round trip.
- Capturas novas são JPEG reais de 611×863, sem edição/resize, somente sintéticas.

Os resultados econômicos anteriores continuam negativos quanto à demonstração
de vantagem ativa robusta sobre benchmarks. O software é experimental, sem
autorização para trading real. Referência de DD de 20% não garante perdas futuras.

## Versão proposta

Atual/candidata técnica: **0.1.0.dev0**, consistente entre pyproject, wheel e CLI.
Proposta para eventual pré-release: **0.1.0rc1**. Não há tag/release remota com
esse nome. O bump não foi aplicado para não reetiquetar o pacote medido.
Antes de uma release, atualizar metadados/teste de versão, validar novo wheel e
aprovar separadamente tag, artefato e notas. Não publicar o wheel dev0 como rc1.

## Limitações para aceitação

Windows testado; Linux/macOS, CI remoto, leitor de tela e todas as ordens de uma
sessão monolítica não demonstrados. Skips: chmod POSIX e symlink real sem
privilégio. Servidor serial de desenvolvimento, sem sandbox contra usuário local
ou prontidão de produção. Corpus privado não distribuído; comparação histórica
depende de origem compatível autorizada. Capturas antigas preservadas têm seus
próprios limites de viewport documentados.

O teste de clone utilizou a candidata **local**, pois a main GitHub ainda contém
a versão anterior. Hook de auditoria nos smokes instalados recusaria acesso ao
original/corporativo e conexão não loopback; nenhuma tentativa foi observada.
Isso cobre aqueles processos, não é uma sandbox geral do sistema.

## Evidências e escopo

- [Auditoria final](reviews/G3_2_RELEASE_INTEGRATION_AND_PUBLICATION_AUDIT.md).
- [Resumo verificável de testes e identidades](reviews/G3_2_VALIDATION_SUMMARY.json).
- [Manifesto integral de arquivos](reviews/G3_2_PUBLICATION_FILE_MANIFEST.json).
- [Instalação e uso](RESEARCH_CONSOLE.md).
- [Checklist de publicação](G3_2_PUBLICATION_CHECKLIST.md).
- [Segurança](../SECURITY.md).

O manifesto separa código, testes, documentação, exemplos, configuração e
evidências. A lista integral é o delta cumulativo contra a28e6f3, incluindo os
commits G1–G3.1; não deve ser reduzida somente ao patch G3.2. Não há YAML
executável em `.github/workflows/`; proposta de CI permanece em `ci/`.

Recomendação: revisão do diff e publicação experimental via branch/PR, somente
após o checkpoint humano. Merge, release e Actions são decisões separadas.

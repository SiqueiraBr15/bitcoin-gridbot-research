# Proposta local de PR — G4.1

Título: **Harden research evidence imports, export authorization and global quality evidence**

Base de desenvolvimento G4: cc7f140. Branch local fix/g4-research-lab-hardening.
Não foi criado PR remoto, push, merge, tag ou release.

A G4 podia aceitar um DEFLATE com conteúdo além do tamanho declarado e liberava
exports de packs externos com base em uma declaração PUBLIC do próprio arquivo.
Instâncias concorrentes também podiam ultrapassar a quota da biblioteca.

A G4.1 confere saída efetiva/EOF/CRC, exige autorização independente do operador
para exports externos e serializa gravações com lock liberado pelo OS após crash.
A interface invalida ações antigas e separa derivados de dados brutos/SVG;
grants expiram com o processo. Há regressões de corrupção, aliases Windows,
junction/hardlink, disk-full, escrita parcial, crash real e concorrência.

O gate de coverage passa a incluir console e nativos e exige todos os arquivos
medidos. Nenhum parâmetro financeiro, estratégia, CORE ou módulo nativo muda.
Guias essenciais são incluídos no wheel, sem nova dependência de runtime.

Validação nova: **3.610 Python PASS + dois skips preexistentes**, 3.612 nodeids,
273 segmentos, zero falhas/incompletos. Cobertura global de núcleo+console:
**96,48%**, linhas+branches, limiar 85%; exemplos empacotados: 87,37% em medição
separada. **26 JS PASS**, Ruff, Mypy strict, format e pre-commit aprovados.
Wheel/instalação limpa/editável/launcher Windows e navegador em quatro larguras
aprovados; contexto de 9.999 marcas também exercitado. Consulta aquecida de
3.000 marcas: mediana 86,76 ms em sete repetições, sem SLA ou promessa de ganho.
Antes/depois tiveram inputs e resultados matemáticos iguais.

Três defeitos P2 foram reproduzidos na G4: inflação ZIP não manifestada,
autorização de export baseada no próprio pack e corrida de quota. A candidata
local está pronta para revisão técnica, com os limites detalhados no relatório.
Consulte a [auditoria G4.1](reviews/G4_1_RESEARCH_LAB_HARDENING_AND_GLOBAL_QUALITY_AUDIT.md).
A consulta local autorizada continua contendo as marcas necessárias aos gráficos;
a política de export não é DRM contra o operador. Não há autenticação de autoria,
garantia de limite de perdas, teste Linux/macOS ou prontidão para dinheiro real.
Esta proposta é local; a publicação requer autorização posterior.

# G1 — changelog e descrição de PR preparada

## Mudança

O projeto podia ser consultado por módulos/relatórios, mas não tinha interface
local. G1 adiciona um console de pesquisa com navegação entre patrimônio, BTC,
risco, janelas e a demonstração PAPER existente. O usuário seleciona período/custo
e consulta resultados arquivados; ausência/corrupção de dados impede sua exibição.

Usa HTTP stdlib em 127.0.0.1, assets locais, projeção explícita e verificação
SHA-256 dos artefatos M1.R autorizados na inicialização. Nenhum dataset interno é
incluído. O motor financeiro, CORE, V2 e parâmetros econômicos permanecem intactos.

## Revisão

Conferir isolamento de origem/sessão, leitura delimitada, export local e cálculos
Fraction/Decimal. Risco reaproveita o método M1.R; benchmarks são pareados, sem
seleção retrospectiva de política. A demo conserva a distinção sintético/histórico.

Validações e limites estão em
[G1_RESEARCH_CONSOLE_IMPLEMENTATION_AUDIT.md](reviews/G1_RESEARCH_CONSOLE_IMPLEMENTATION_AUDIT.md).
Cobertura global permanece PENDING; Linux/CI remoto não validados.

Branch local: `feat/g1-research-console`. **Descrição preparada; nenhum PR remoto
criado e nenhum push autorizado nesta fase.** Actions continua desativado.

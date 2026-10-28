# GridBot — Offline Research Lab

Laboratório local de engenharia de software e pesquisa quantitativa para
investigar patrimônio, BTC e risco com evidências verificáveis.
**PAPER/OFFLINE, sem operações reais.**

**English.** Exact Bitcoin spot accounting and an offline research console.
Inspect evidence, compare portfolio value and physical BTC, and reproduce
analyses. The active strategies studied did not demonstrate a robust advantage
over simple benchmarks. Experimental research/engineering software.

## Disponível na main

A **G4 Offline Research Lab está integrada à main**, pelo
[PR #2](https://github.com/SiqueiraBr15/bitcoin-gridbot-research/pull/2), merge
`acaa6879877c8a081a127f3ea8a0cdbb840b88cd`. Não é necessário trocar para uma
branch candidata para usar o laboratório. A versão permanece **0.1.0.dev0**.
Código integrado e pacote instalado localmente não constituem uma release
formal do GitHub; nenhuma tag/release foi criada nesse checkpoint.

- Biblioteca com três Evidence Packs sintéticos e importação local confirmada.
- Validação de ZIP/JSON, hashes, unidades e conservação de patrimônio.
- NAV em USDT, BTC físico/equivalente, caixa, custos e exposição.
- Comparações e Pareto dentro de grupos compatíveis, sem vencedor universal.
- Drawdown observado, episódios, lacunas e limitações de risco explícitas.
- Replay analítico e exports condicionados aos direitos de cada evidência.
- Demonstração PAPER determinística com fills e reconciliação racional.

[Instalação e uso](docs/RESEARCH_CONSOLE.md) · [Guia do Lab](docs/G4_RESEARCH_LAB.md) ·
[Evidence Pack v1](docs/G4_EVIDENCE_PACK_V1.md)

## Instalar e abrir no Windows

Pré-requisitos: Git e Python 3.13 com o launcher `py`. No PowerShell:

```powershell
git clone https://github.com/SiqueiraBr15/bitcoin-gridbot-research.git
cd bitcoin-gridbot-research
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --index-url https://pypi.org/simple pip==26.2.1
.\.venv\Scripts\python.exe -m pip install --index-url https://pypi.org/simple -c constraints.txt --build-constraint build-constraints.txt .
.\.venv\Scripts\python.exe -m research_console --port 8765
```

A instalação usa o PyPI; os exemplos públicos não requerem conexão,
credenciais ou dados históricos. Abra **http://127.0.0.1:8765/#lab** e escolha
**Analisar** em um estudo fictício. Ctrl+C no terminal encerra o servidor.
Outra porta livre pode ser usada com `--port`. No checkout,
`start_console.cmd --port 8765` usa esse mesmo ambiente `.venv`.

Os packs `favorable`, `unfavorable` e `risk_violation` mostram cenários
matemáticos, incluindo perda e violação de risco. Não são candles históricos
ou evidência de retorno de mercado. A página **PAPER** executa os dois cenários
sintéticos do motor somente após clique explícito.

Para persistir importações, acrescente `--lab-dir "<pasta absoluta nova/vazia>"`,
com pai local existente. Sem esse argumento, a biblioteca embutida e a análise
funcionam; confirmar persistência é recusado. A origem não é sobrescrita.
Desenvolvimento: substitua `.` por `-e ".[dev]"` no comando de instalação.
Node é ferramenta de testes JavaScript, não dependência do produto.
Linux/macOS têm orientações no guia, ainda sem validação demonstrada.

![Console G3 sintético; captura histórica, não interface G5](docs/images/g3-paper-1280.jpg)

## Interpretação e limites

```text
NAV = caixa USDT líquido + BTC físico líquido × preço de marcação
BTC equivalente = NAV / preço de marcação
```

BTC equivalente não são moedas adicionais. Reservas são subconjuntos dos
fundos, nunca patrimônio extra. Fees declaradas já estão refletidas nos
saldos. Pack v1 não é ledger: não comprova custos em terceiro ativo, passivos,
fluxos externos ou separação CORE. O núcleo preserva a regra
**GRID CANNOT SELL CORE BTC** e não habilita trading real.

A análise usa Fraction/Decimal e transporte exato. Pareto respeita grupos e
objetivos selecionados. Janelas sobrepostas são dependentes; contas separadas
não formam execução contínua. **20% é referência indicativa, sem stop-loss
ou garantia de drawdown futuro.**

SHA-256 comprova igualdade de bytes, não autoria. Proveniência é declarada.
PUBLIC no pack não concede direitos: arquivos externos exigem autorização
independente de export, por bytes/sessão; RESTRICTED continua bloqueado.
O histórico privado R1/M1 não é distribuído nem convertido automaticamente.

## Engenharia e evidências

Python 3.13 · Decimal/Fraction · Pydantic · pytest/Hypothesis · Ruff/Mypy.
104 módulos nativos preservados e console separado.
[Arquitetura](ARCHITECTURE.md) · [Testes e performance](TESTING_AND_PERFORMANCE.md)

| Evidência histórica | Escopo e resultado |
| --- | --- |
| G4.8, 27/10/2026 UTC | 3.633 Python PASS, dois skips; cobertura global 96,46987628%, linhas/branches, threshold 85% |
| G4.10, 27–28/10/2026 UTC | Auditoria independente local aprovada: 171 Python PASS, um skip Windows preexistente, 46 JavaScript PASS; wheel/regressões verificados |
| G4.12, 28/10/2026 UTC | Merge e 397 blobs conferidos; wheel reconstruído, instalação limpa, pip check e oito verificações HTTP locais aprovados |

Esses resultados são arquivados, não uma suíte nova nesta revisão documental.
[G4.8](docs/reviews/G4_8_FINAL_QUALITY_GATE_AND_UX_REPAIR_AUDIT.md) e
[G4.9](docs/reviews/G4_9_FINAL_UX_AND_RELEASE_FREEZE_AUDIT.md) preservam evidências
públicas; recibos locais G4.10/G4.12 não integram o wheel.
Actions está desativado, sem CI remoto aprovado. Windows foi exercitado;
Linux/macOS não foram validados.

O servidor é sequencial. Cancelamento HTTP pode deixar CPU ocupada até concluir.
Permanece o P3 diagnóstico Windows10053: tentativa redundante de HTTP422 após
desconexão, sem entrega e com recuperação anteriormente verificada. Tempos
amostrais não são SLA. Não exponha o servidor por proxy público.

## Pesquisa e continuidade

GRID e rebalanceamentos ativos estudados **não demonstraram vantagem robusta**
sobre benchmarks simples. Nenhuma política com BTC respeitou 20% em todas as
janelas examinadas. Capital dos estudos é hipotético.
[Síntese e limitações](RESEARCH.md).

O protocolo prospectivo permanece congelado; coleta e avaliação precisam de
autorizações separadas. O coletor histórico opt-in do núcleo não é usado pelos
exemplos. Não há nova pesquisa econômica nesta entrega documental.

A direção G5 é **Revisão Guiada de Evidências**:
[contrato](docs/G5_GUIDED_EVIDENCE_REVIEW_CONTRACT.md),
[UX](docs/G5_GUIDED_EVIDENCE_REVIEW_UX.md) e
[aceitação](docs/G5_IMPLEMENTATION_ACCEPTANCE_MATRIX.md).
**Contrato aguardando aprovação do orquestrador; interface não implementada.**
[Roadmap](ROADMAP.md) · [Contribuição](CONTRIBUTING.md) · [Segurança](SECURITY.md)

Projeto de **Leonardo Siqueira Ribeiro dos Santos / SiqueiraBr15**, com assistência
de IA em implementação, testes e revisão; não é auditoria externa certificada.
[Proveniência pública](docs/PUBLIC_SOURCE_MANIFEST.json).
Licença [MIT](LICENSE); [atribuições de terceiros](THIRD_PARTY_NOTICES.md).

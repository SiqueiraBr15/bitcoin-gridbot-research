# Research Evidence Pack v1

Contrato normativo implementado em `research_console/lab/packs.py`. Extensão
`.gbpack`; ZIP sem extração com exatamente `manifest.json` e `results.json`.
Sem diretórios, duplicatas, links, ZIP64, criptografia, descritores, extras,
comentários, prefixos ou bytes finais não manifestados. Apenas STORED/DEFLATED.
Writer determinístico usa ordem fixa e datas ZIP fictícias de 2020.

G4.1 verifica também os bytes efetivamente descomprimidos: limite aplicado ao
decoder, EOF, ausência de unused/unconsumed data, tamanho real e CRC. Tamanhos
plausíveis nos cabeçalhos não autorizam um fluxo que produza conteúdo adicional.
Essa verificação não muda os hashes dos três exemplos válidos.

JSON UTF-8, objeto estrito, sem chaves duplicadas, NaN/Infinity, campos adicionais
ou conteúdo executável. Limites de bytes e estrutura são aplicados antes dos
cálculos. Não há migração silenciosa entre versões. Use `write_pack(manifest,
results)` para preencher `files` e validar antes de gerar bytes.

## Manifesto — todos os campos obrigatórios

| Campo | Contrato |
| --- | --- |
| schema_version | inteiro 1, não booleano |
| pack_id, dataset_identity, producer_version, study_identity, license | identificador ASCII `[A-Za-z0-9][A-Za-z0-9_.-]{0,79}` |
| title | texto portátil não vazio de até 240 caracteres |
| source_kind | SYNTHETIC_DEMO, ARCHIVED_RESEARCH_RESULT ou AGGREGATED_RESEARCH_SUMMARY |
| data_nature | SYNTHETIC ou HISTORICAL_DECLARED; demonstração exige SYNTHETIC |
| flow_convention | NO_EXTERNAL_FLOWS_DECLARED |
| created_at, start, end | ISO UTC canônico com `+00:00`, resolução de segundos; start ≤ end |
| timezone, currency | UTC e USDT |
| units | exatamente `["UTC","USDT_PER_BTC","USDT","BTC","USDT"]` |
| sampling_seconds | inteiro entre 1 e 2678400 |
| redistribution | PUBLIC, AGGREGATES_ONLY ou RESTRICTED |
| limitations | 1 a 12 textos portáteis obrigatórios |
| files | somente `results.json: {bytes: inteiro positivo, sha256: 64 hex minúsculos}` |

Texto portátil recusa controles Unicode, caracteres invisíveis de categoria C,
separadores de linha/parágrafo, barras de caminho, `<`, `>` e prefixos de fórmula.
Identidades de estratégia, benchmark, cenário e janela pertencem às contas, evitando
redundância de campos no manifesto. O SHA do próprio manifesto e do contêiner é
calculado externamente, sem autorreferência. Um SHA externo confiável pode ser
conferido na interface; SHA autodeclarado não autentica a fonte.

## Resultados — exatamente accounts e aggregates

Para séries, `aggregates=[]` e `accounts` tem de 1 a 60 objetos. Cada conta contém
exatamente:

```text
account_id, policy, benchmark, window_id, cost_scenario,
start, end, initial_nav, fees_usdt, points
```

Identificadores seguem a regra ASCII; account_id é único. `benchmark` é null ou
account_id existente e comparável. Endpoints são canônicos, estão dentro do estudo
e correspondem à primeira/última marca. `initial_nav` e `fees_usdt` são strings
decimais finitas não negativas; não se aceitam números JSON de ponto flutuante.
Valores seguem os limites de precisão/magnitude do leitor decimal do console.

`points` é uma lista não vazia, com até 10.000 marcas no total do pack. Cada marca:

```json
["2020-01-01T00:00:00+00:00", "10", "50", "5", "100"]
```

Ordem das colunas: UTC, preço USDT/BTC, caixa USDT, BTC físico, NAV USDT. Timestamps
estritamente crescentes e únicos. Preço positivo, saldos não negativos;
`NAV = cash + BTC × price` em Fraction exata. Primeira NAV = capital inicial.
NAV zero é absorvente, pois não há fluxos externos. A cadência irregular não é
preenchida: análise sinaliza lacunas e risco incompleto. Não se aceitam outros
ativos/passivos; reservas não são somadas novamente. Não é um ledger de fills.

Para resumos, `accounts=[]`, source_kind=AGGREGATED_RESEARCH_SUMMARY e `aggregates`
tem de 1 a 60 linhas estritas: policy, cost_scenario, observations, losses,
violations. Contagens inteiras até um milhão, observations>0 e perdas/violações
entre zero e observations; combinação política/custo única. Sem curva inventada.
O campo data_nature identifica se o resumo é sintético ou declarado histórico.

## Construir um exemplo local válido

Em um diretório temporário do próprio laboratório, fora de dados originais:

```python
from pathlib import Path
from research_console.lab.fixtures import bundled
from research_console.lab.packs import read_pack

raw = bundled()["risk_violation"]
pack = read_pack(raw)
print(pack.sha256, pack.manifest["source_kind"])
with Path("risk-demo.gbpack").open("xb") as output:
    output.write(raw)
```

`xb` recusa sobrescrita. Para resultados reais autorizados, o produtor deve
preencher o mesmo contrato, reconciliar saldos/custos e revisar direitos antes
de transportar o pack. A G4 não fornece conversor de arquivos privados arbitrários.

## Manifesto de análise

`GRIDBOT_ANALYSIS_V1` contém analytics_version, implementation_sha256,
pack_sha256, manifest_sha256, accounts, objectives, expected_result_sha256,
provenance e redistribution. Todos obrigatórios, sem campos adicionais.
Código analítico v1 inclui hashes normalizados de packs, analytics, exports,
data, risk e a versão de lab. Replay exige igualdade da projeção completa e
recalcula resultado canônico. Os resultados carregam valores racionais em `exact`;
strings decimais de apresentação não determinam dominância ou violação de risco.

Veja [o guia](G4_RESEARCH_LAB.md) para fórmulas, direitos de exportação e limitações.

Na G4.1, `redistribution` e `license` continuam declarações do produtor. Não são
autorizações executáveis. Grants de exportação pertencem ao estado do operador,
por SHA e sessão do servidor, fora do pack e do resultado matemático. Somente os
bytes dos três fixtures do projeto recebem permissão automática. Alterar título,
identidade ou dados cria outro pack e exige revisão independente; alegar natureza
sintética ou licença pública não contorna esse requisito.

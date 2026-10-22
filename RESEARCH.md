# Pesquisa e limites das evidências

Esta síntese descreve resultados arquivados do desenvolvimento local. Não é
uma nova campanha, promessa de retorno ou auditoria independente de mercado.
Capital de 10.000 USDT nos estudos é **hipotético**, não patrimônio do autor.

## Perguntas estudadas

Foram investigados GRID clássico, protótipo persistente, recentralização,
preservação de inventário legado, acumulação e estratégias passivas. A campanha
M1 comparou BH, 50/50 inicial, DCA do orçamento original, caixa, bandas e mensal.
M1.R examinou uma tolerância de 20% informada depois dos resultados M1; M2
consolidou o conflito entre patrimônio, BTC e risco sem nova otimização.

São 237 janelas independentes como contas: 87 de 6m, 81 de 12m e 69 de 24m,
com entradas mensais sobrepostas e três hipóteses de custo. Não são observações
estatisticamente independentes. A história já era conhecida no projeto.

## Resumo do cenário principal M1, 12 meses

NAV e BTC são medianas das 81 contas; as colunas não formam uma carteira única.

| Política | NAV mediano USDT | BTC físico mediano | Pior DD diário | Violações de 20% |
| --- | --- | --- | --- | --- |
| BH | 15.896,26 | 0,33485 | 72,66% | 78/81 |
| 50/50 inicial | 12.948,07 | 0,16758 | 48,18% | 50/81 |
| DCA | 12.683,96 | 0,30310 | 63,41% | 57/81 |
| Caixa | 10.000,00 | 0 | 0% | 0/81 |
| Bandas | 13.197,69 | 0,16453 | 45,73% | 48/81 |
| Mensal | 13.041,15 | 0,15877 | 45,01% | 48/81 |

Nem bandas nem mensal passaram em todas as entradas de 24 meses: ambas
violaram 20% em 50/69 casos. Menor risco relativo não demonstrou compatibilidade
integral com a tolerância. Caixa passou nominalmente, sem crescer ou adquirir BTC.

## O que os resultados não demonstram

- Vantagem robusta das estratégias ativas sobre benchmarks simples.
- Teto futuro de drawdown ou disponibilidade de execução em gaps/suspensões.
- BTC físico maior significando necessariamente NAV maior.
- Retornos prospectivos, custódia segura ou prontidão operacional.
- Independência estatística de milhares de linhas derivadas de janelas comuns.

Fees, spread, slippage, volume e latência são hipóteses. A marcação diária
não captura todos os movimentos intradiários. USDT é numerário nominal:
depeg, impostos, custódia e uma liquidação final não estão integralmente modelados.

## Reprodutibilidade disponível e ausente

O pacote permite inspecionar o núcleo nativo, executar testes e trabalhar com
fixtures sintéticas. Não inclui o acervo de dados oficiais, decisões internas,
scripts de campanha R1/M1 nem exports necessários para repetir toda a tabela.
Portanto não afirma reprodução integral pública dos resultados econômicos.
Os números acima são uma síntese documental da M2, cuja identidade original
está registrada no manifesto de proveniência, sem copiar materiais pessoais.

Dados externos não foram redistribuídos: publicação de arquivos de mercado exige
revisão própria de direitos e condições de uso. O pacote não concede direitos
sobre materiais de terceiros.

## Prospectivo

O protocolo original está congelado para observação de 01/11/2026 a 01/05/2027,
fim exclusivo. A inspeção A25 de 22/10/2026 encontrou intervalo futuro e 404
nos 12 objetos; coleta e avaliação não foram iniciadas. Aquisição manual está
restrita contratualmente a [01/06/2027, 08/06/2027), com autorização separada.
Os mecanismos e manifestos privados não são distribuídos aqui; nada neste
snapshot ativa uma coleta. A hipótese congelada não é evidência de rentabilidade.

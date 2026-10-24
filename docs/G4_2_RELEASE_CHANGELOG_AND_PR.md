# G4.2 — Changelog e Pull Request local

**Somente preparação local. Não houve push nem criação de PR remoto.**
Base pública: `88390ac0b3726c50b548e5087acfa39982d76342`.
Branch candidata: `release/g4-offline-research-lab`.
Código instalado auditado: `548aaa8fa0761ce57a36e47950b7dd3f55b0026f`;
o HEAD final acrescenta apenas documentação, inventário e captura.
Pacote efetivo `0.1.0.dev0`; `0.1.0rc1` é proposta ainda não aplicada.

## Changelog desta integração

- Corrige orientação de instalação para a branch candidata local. A main remota
  ainda distribui o Console G1–G3; o clone da G4 depende de publicação autorizada.
- Esclarece que os dois guias incluídos no wheel podem remeter a relatórios do
  repositório, sem depender desses relatórios para executar o produto.
- Reconfere os 273 segmentos G4.1 e cobertura a partir dos recibos originais,
  acrescenta adversários independentes e jornada real de primeira instalação.
- Acrescenta auditoria de release, inventário publicável, checklist e captura real.

Nenhuma mudança G4.2 em Python/JS, estratégia, CORE, testes, parâmetros,
dependências ou configuração. Os três P2 G4.1 foram revisados novamente.

## Título sugerido

`feat: add hardened offline research lab with portable evidence packs`

## Corpo sugerido do PR

O Console publicado permitia inspecionar pesquisas explicitamente autorizadas e
demonstrar o motor PAPER. Este PR acrescenta uma biblioteca offline de Evidence
Packs: importar e validar observações, comparar NAV/BTC/custos/risco, investigar
Pareto e episódios, reproduzir análises e exportar segundo autorização explícita.
Três exemplos matemáticos inteiramente sintéticos tornam a instalação utilizável
sem dados privados ou acesso a uma exchange.

O leitor ZIP verifica todo o conteúdo manifestado, inclusive bytes compactados,
CRC/EOF e limites. A declaração PUBLIC do próprio pack não autoriza exportação;
o backend exige uma base independente confirmada pelo operador e restringe cada
escopo. Gravação local usa lock entre processos, quota rechecada e persistência
atômica. Cancelamento e respostas antigas da interface respeitam o contexto ativo.
O núcleo financeiro e os parâmetros congelados permanecem idênticos à main.

Validação local Windows/Python3.13:

- Global G4.1 **reconciliado**, não reexecutado integralmente: 3.610 PASS + 2 skips
  Windows, 273 segmentos, 295 arquivos congelados iguais; 120 módulos e 96,48%
  de cobertura combinada; threshold85%. Exemplos separados87,37%.
- Nova rodada: 190 testes Python dirigidos, 26 Node, Ruff/format/Mypy strict,
  pre-commit, diff check, Gitleaks árvore/histórico/blobs descompactados.
- Wheel/editable novos, PyPI e caches limpos, launcher Windows, navegador real em
  quatro larguras, reinício/persistência/replay/exports e PAPER determinístico.
- Adversários independentes confirmam ZIP, autorização, corrida real31→32 e
  aritmética Fraction com caso literal de compra/venda. Nenhum backtest novo.
- Wheel dev0: SHA-256
  `e016580179032cf179f43691e7b1cf286e6ef19d16d712b8228cb64615221c8a`.

![Métricas fictícias verificadas no wheel instalado](images/g4_2-wheel-analysis-1366.jpg)

Limitações: pesquisa local experimental, sem trading, sem garantia de drawdown,
sem corpus histórico distribuído, autoria externa não autenticada, direitos a
verificar fora do pack, sem validação Linux/macOS ou CI remoto. Servidor
sequencial e limites explícitos de tamanho/contas/marcas; PAPER pode ocupar
segundos. Autorizações de exportação expiram no reinício. Não é DRM.

Detalhes: [auditoria G4.2](reviews/G4_2_RELEASE_INTEGRATION_AND_PUBLICATION_AUDIT.md),
[guia do Lab](G4_RESEARCH_LAB.md) e [contrato v1](G4_EVIDENCE_PACK_V1.md).

## Antes de usar este texto no GitHub

O corpo acima só será enviado após autorização. Converter os links relativos
para caminhos `docs/...` no corpo remoto e conferir a captura no diff. O GitHub
atribuirá o número real; #2 não está reservado. Conferir main, HEAD e configuração
administrativa de Actions OFF antes de push. Consulta pública atual mostrou zero
workflows/runs; endpoint administrativo exige autenticação e não foi revalidado.
Não alterar essa limitação para afirmar CI aprovado. Merge exige autorização
separada; nenhuma tag/release está autorizada.

# G3 — Changelog e proposta de PR local

Documento preparado para revisão; nenhum PR, push, merge ou release foi criado.
Branch: `feat/g3-quality-release-candidate`. Baseline G3: `2171548`.
Um futuro PR contra `main` incluirá também G1/G2 ainda não publicadas;
esta lista descreve exclusivamente o delta G3.

## Título proposto

Research Console: transporte local robusto, exports reproduzíveis e instalação offline

## Descrição proposta

O console podia aceitar parâmetros vazios inesperados, compartilhar cookies entre
portas e mostrar o manifesto histórico numa demonstração sintética. No Windows,
um segundo listener podia ocupar a mesma porta. Esta atualização corrige esses
comportamentos, limita JSON inválido/excessivo e preserva a identidade completa
da seleção nos exports CSV/JSON/SVG.

A navegação agora participa do histórico do navegador. Requests têm deadline e
cancelamento de respostas obsoletas; gráficos oferecem marcas exatas paginadas
e liberam seus observers. A demo continua explicitamente sintética e pode ser
reexecutada pelo caminho nativo. A filtragem anterior à cópia do cache reduz o
custo da seleção de uma política; a validação estrutural acrescenta custo de
inicialização e não se anuncia melhoria universal de performance.

Wheel e instalação editable incluem console, assets e exemplos sintéticos.
Entrypoint e launcher PowerShell manual funcionaram fora do checkout, inclusive
com espaços/acentos no caminho. Não há autostart, serviço, trading ou coleta.

O motor financeiro, políticas, parâmetros, dados originais e V2 permanecem
preservados. O corpus histórico privado não acompanha a distribuição: sua ausência
produz DATA_UNAVAILABLE e a demo exige seleção explícita.

## Validação e limitações que devem acompanhar o PR

- Console: **136 PASS + um SKIP**, cobertura dirigida **95,45%** (linhas+ramos).
- JavaScript: **19 PASS**. Novos casos G3: 46 Python + quatro JS,
  com **49 PASS e um SKIP ambiental**.
- União comprovada: **1.987 Python PASS + 19 JS PASS**, dois SKIP;
  **1.425 Python pendentes** de 3.414 coletados. Reexecuções não foram somadas.
- Global **PENDING**. Campanha de 600 s: nove segmentos concluídos e sete
  TIMEOUT. Decomposição posterior aprovou 1.308 casos; não equivale a suíte global.
- Cobertura nativa **parcial 70,04%**; `coverage json` **FAIL/exit 2**, abaixo
  do limiar preservado de 85%. Não apresentar como gate global aprovado.
- Oráculo independente Fraction: **27 seleções, 162 carteiras, 69.174 marcas**,
  com ganhos/perdas/empates, via origem autorizada → HTTP → CSV/JSON.
- UI: seis páginas × cinco viewports, navegação/filtros/risco/PAPER/exports
  reais. Três seleções financeiras confrontadas com a origem em Decimal.
- CSV/JSON/SVG baixados, reimportados e reconciliados; demo reexecutada com
  JSON idêntico. SVG aberto no navegador e inspecionado por parser XML.
- Ruff, Mypy strict, pip check, formatação e pre-commit aprovados;
  Gitleaks no histórico de implementação sem achados, com fechamento final
  documentado na entrega e nos recibos locais.
- Wheel instalado e exercitado fora do checkout; 104 módulos nativos idênticos
  aos bytes do source público. SHA-256 do candidato:
  `aa9884966cfc92052f61c10049a1d32bb8741fac3cb1049756de85493be422ef`.
- Original: 1.665 hashes preservados. Os 104 blobs Git nativos coincidem com
  o original; sete diferenças brutas entre worktrees eram somente EOL preexistente.

SKIPs: chmod POSIX preexistente no Windows e criação real de symlink sem
permissão. Guardas simulados não substituem o segundo teste. Linux/macOS,
leitor de tela, paint/GPU/heap prolongado e interatividade PowerShell 5.1 não
foram demonstrados. Ctrl+C liberou a porta; o host PTY retornou 1 por interrupção.
O serviço continua serial e local, sem certificação de segurança ou produção.

## Evidências para revisão

- [Auditoria completa](reviews/G3_QUALITY_ENGINEERING_AND_RELEASE_CANDIDATE_AUDIT.md).
- [Resumo sanitizado](reviews/G3_VALIDATION_SUMMARY.json).
- [Índice de testes e cobertura por módulo](reviews/G3_GLOBAL_TEST_DECOMPOSITION_INDEX.json).
- [Nodeids aprovados, pulados e pendentes](reviews/G3_GLOBAL_TEST_DECOMPOSITION.json.gz).
- [Antes G2](images/g3-before-g2-paper.jpg), [depois G3](images/g3-paper-1280.jpg),
  [documento integral no viewport 1920](images/g3-paper-full-1920.jpg),
  [marcas acessíveis](images/g3-accessible-marks.jpg),
  [risco por teclado](images/g3-risk-keyboard.jpg) e
  [SVG aberto no browser](images/g3-svg-export.jpg).

Screenshots reais, sintéticos e sem edição. As capturas visíveis largas são
limitadas pelo painel físico; não são arquivos de 1920×1080. A auditoria descreve
as dimensões e distingue viewport CSS, captura visível e fullPage.
Logs completos ficam fora do repositório; não são publicados dados históricos.

## Como executar

Após a instalação descrita em [RESEARCH_CONSOLE.md](RESEARCH_CONSOLE.md):

```powershell
.\start_console.cmd
```

Abra `http://127.0.0.1:8765`, escolha Demonstração PAPER e execute os cenários
sintéticos. Ctrl+C encerra. Outra porta:
`.\start_console.cmd --port 8766`.
PowerShell opcional: `.\start_console.ps1 -Port 8766`.
Python direto: `.\.venv\Scripts\python.exe -m research_console`.
Sem fonte local autorizada não há resultados históricos disponíveis.

## Commits locais

1. `8d36b59` — hardening, proveniência, exports, regressões e oráculo QA.
2. `9db8af1` — distribuição offline, entrypoint, launcher e documentação.
3. Commit documental de fechamento — este arquivo, auditoria, imagens e
   manifestos; consultar `git log` e a entrega para o hash, sem autorreferência.

## Lista exata de arquivos G3

35 caminhos, relativos à raiz do repositório. Nenhum arquivo preexistente foi
excluído. Conferir com `git diff --name-only 2171548..HEAD` após o fechamento.

### Código e interface (oito)

```text
research_console/analysis.py
research_console/data.py
research_console/server.py
research_console/static/app.js
research_console/static/charts.js
research_console/static/index.html
research_console/static/state.js
research_console/static/style.css
```

### Build e execução (quatro)

```text
build-constraints.txt
pyproject.toml
start_console.cmd
start_console.ps1
```

### Testes e ferramenta QA (três)

```text
tests/console/chart_state.test.cjs
tests/console/test_quality.py
tools/audit_console_archive.py
```

### Documentação e evidências (20)

```text
ARCHITECTURE.md
README.md
TESTING_AND_PERFORMANCE.md
docs/G3_CHANGELOG_AND_PR.md
docs/RESEARCH_CONSOLE.md
docs/images/g3-accessible-marks.jpg
docs/images/g3-before-g2-paper.jpg
docs/images/g3-paper-1280.jpg
docs/images/g3-paper-1366.jpg
docs/images/g3-paper-1920.jpg
docs/images/g3-paper-390.jpg
docs/images/g3-paper-768.jpg
docs/images/g3-paper-full-1920.jpg
docs/images/g3-risk-full.jpg
docs/images/g3-risk-keyboard.jpg
docs/images/g3-svg-export.jpg
docs/reviews/G3_GLOBAL_TEST_DECOMPOSITION.json.gz
docs/reviews/G3_GLOBAL_TEST_DECOMPOSITION_INDEX.json
docs/reviews/G3_QUALITY_ENGINEERING_AND_RELEASE_CANDIDATE_AUDIT.md
docs/reviews/G3_VALIDATION_SUMMARY.json
```

## Checklist para o orquestrador

- [ ] Revisar os defeitos demonstrados e os limites do hardening local.
- [ ] Conferir as identidades financeiras e a separação de proveniência.
- [ ] Aceitar explicitamente o global PENDING e a falha de limiar parcial;
      não anunciar toda a suíte aprovada.
- [ ] Avaliar os SKIPs e a necessidade de outro ambiente para symlink/portabilidade.
- [ ] Conferir o delta cumulativo G1/G2/G3 se o destino for main.
- [ ] Revisar screenshots, docs de instalação e ausência de corpus privado.
- [ ] Decidir se autoriza publicação experimental após revisão.

Pronto para **revisão**, sem autorização para publicar automaticamente.
Não iniciar G4, novas estratégias ou avaliação econômica.

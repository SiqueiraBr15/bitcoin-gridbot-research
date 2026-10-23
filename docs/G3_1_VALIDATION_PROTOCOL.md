# G3.1 — Validação segmentada e cobertura reproduzível

Ferramentas de desenvolvimento; não fazem parte do wheel nem alteram o motor.
Windows/Python 3.13.16, constraints do projeto, perfil Hypothesis `ci` preservado.
Não há validação Linux ou execução de Actions nesta fase. A consolidação só
aprova os testes quando todos os nodeids do inventário estão contabilizados.

## Nova execução integral

Após instalar o ambiente de desenvolvimento conforme README, na raiz do checkout:

```powershell
$env:HYPOTHESIS_PROFILE = 'ci'
$env:PYTHONDONTWRITEBYTECODE = '1'
$gateEvidence = Join-Path $PWD 'runs\quality-g3-1'
.\.venv\Scripts\python.exe -m tools.quality_gate inventory --out "$gateEvidence\inventory"
.\.venv\Scripts\python.exe -m tools.quality_gate run --inventory "$gateEvidence\inventory\inventory.json" --out "$gateEvidence\campaign" --segment-seconds 300 --budget-seconds 5400
```

Use diretórios novos: tentativas anteriores não são sobrescritas. `runs/` é
ignorado pelo Git. O orçamento é finito e não promete conclusão em 90 minutos.
Cada propriedade/máquina reconhecida fica isolada; demais casos formam lotes de
até 20 por módulo. Nenhum exemplo Hypothesis, assertion ou threshold é reduzido.
O runner não usa `-x`/`--lf`; segue para segmentos independentes após falha/timeout.

O inventário inclui nodeids parametrizados, perfil, versões e hashes dos fontes/
configuração/suporte dos testes. O plano registra a partição, hashes do runner e
dos módulos. Cada worker registra coleção, setup/call/teardown, JUnit, CPU/parede,
log e cobertura de branches em arquivo separado. Um timeout termina somente a
árvore do processo de teste criado pelo runner no Windows. Não há agendamento,
serviço ou execução residente; mantenha o terminal aberto.

## Exportar evidências concluídas e retomar

```powershell
.\.venv\Scripts\python.exe -m tools.quality_coverage bundle --inventory "$gateEvidence\inventory\inventory.json" --campaign "$gateEvidence\campaign" --out "$gateEvidence\bundle-1"
```

O bundle revalida hashes, coleção esperada e fases. Segmentos FAIL/TIMEOUT não
entram na cobertura certificada, mesmo que existam calls verdes antes do corte.
`pending.json.gz` lista os nodeids restantes; arquivos de cobertura concluídos
são copiados e preservados. Para retomar uma execução incompleta:

```powershell
.\.venv\Scripts\python.exe -m tools.quality_gate run --inventory "$gateEvidence\inventory\inventory.json" --pending "$gateEvidence\bundle-1\pending.json.gz" --out "$gateEvidence\campaign-2" --segment-seconds 600 --budget-seconds 5400
.\.venv\Scripts\python.exe -m tools.quality_coverage bundle --inventory "$gateEvidence\inventory\inventory.json" --campaign "$gateEvidence\campaign-2" --bundle "$gateEvidence\bundle-1\bundle.json" --out "$gateEvidence\bundle-2"
```

Aumentar prazo só depois de investigar o caso; não repetir orçamento sem hipótese.
Para subdividir lotes interrompidos, acrescente `--max-cases 1` à retomada;
o novo plano preserva a união e exclusividade dos nodeids. Não interprete silêncio como
deadlock. Uma falha financeira não autoriza corrigir regras para obter aprovação.

Alteração de identidade invalida a reutilização automática: recoloque os segmentos
afetados no plano e gere evidências compatíveis. Não misture configurações, versões
ou fontes. O tool compara hashes atuais; não é assinatura criptográfica externa.

## Consolidar sobre os dados, não sobre porcentagens

```powershell
.\.venv\Scripts\python.exe -m tools.quality_coverage combine --inventory "$gateEvidence\inventory\inventory.json" --bundle "$gateEvidence\bundle-1\bundle.json" --bundle "$gateEvidence\bundle-2\bundle.json" --out "$gateEvidence\combined"
.\.venv\Scripts\python.exe -m coverage report --rcfile=pyproject.toml --data-file="$gateEvidence\combined\global.coverage"
```

Se a primeira campanha concluir tudo, omita bundle-2. O `combine` verifica
identidades, hashes, disjunção, ausência de resultados incompletos, dados de
branches e os arquivos efetivamente medidos. Recusa fontes externas e exige a
união completa dos módulos nativos; declarar source não basta para filtrar um
banco importado. Usa `Coverage.combine(..., keep=True, strict=True)`; mantém inputs,
gera JSON/HTML e compara com o threshold original, sem overrides.

Escopo original: **`source=["gridbot"]`, branches, fail_under=85**. UI Python
`research_console` tem cobertura dirigida separada; JS tem testes Node próprios.
Não somar nem tirar média de percentuais. Uma cobertura parcial acima de 85%
não demonstra que todos os testes terminaram. Skips devem permanecer identificados
com motivo. Processos filhos dos testes não ganham instrumentação implicitamente.

## Reutilização auditada da G3

Nesta missão, a G3 foi reconstruída a partir de JUnit/logs e Git: 1.987 Python
PASS, dois SKIP e 1.425 pendentes, além de 19 JS PASS. Onze bancos nativos completos
foram preservados para consolidação; cobertura do console com source diferente,
consolidação parcial duplicada e TIMEOUTs ficaram fora. A certificação antiga é
retrospectiva por logs/Git, não um hash contemporâneo de cada execução antiga.
Um clone sem esses arquivos deve executar a campanha integral acima, sem inventar
uma evidência de reaproveitamento. Ver relatório G3.1 para o resultado efetivo.

Logs e bancos podem conter caminhos locais e mensagens de fixtures. Revise antes
de compartilhar; não adicione a pasta de execução ao Git. O relatório e manifesto
publicáveis usam caminhos relativos, checksums e conteúdo sanitizado.

# Segurança

Este projeto é offline/PAPER e não deve receber credenciais de exchange,
seeds, chaves privadas ou informações financeiras pessoais.

Não publique segredos em issues, pull requests, exemplos ou logs. Se houver
um canal privado de relato disponível na aba Security do repositório, use-o;
sua ativação ainda depende da configuração aprovada no GitHub. Na ausência
dele, use o contato profissional do perfil para combinar um canal seguro,
sem enviar o segredo ou seu valor.

Uma varredura sem achados não garante ausência de todo dado sensível. Revise
arquivos e histórico antes de publicar. Dados e dependências externos exigem
revisão própria. Não há suporte nem garantia para operação financeira real.

## Dependências e distribuição

Use o HEAD revisado e as constraints atuais. A revisão de 22/10/2026 atualizou
virtualenv de 21.14.5 para 21.14.13 por avisos de segurança da ferramenta de
criação de ambientes. Isso é uma dependência de desenvolvimento, não autoridade
financeira. Commits antigos conservam pins históricos; não são recomendações
atuais. A ausência de avisos conhecidos em uma consulta não garante segurança.
Repita a verificação de dependências antes de instalar ou publicar uma release.

O runtime não é vendorizado. Pydantic, pydantic-settings e pydantic-core declaram
MIT; python-dotenv declara BSD-3-Clause nos metadados examinados. Ferramentas
possuem condições próprias, incluindo MPL-2.0 em Hypothesis/pathspec e PSF-2.0
em typing_extensions. A licença MIT do GridBot não substitui essas condições.
Não se afirma aqui uma revisão jurídica completa das dependências transitivas.

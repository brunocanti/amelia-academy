# Amelia, de 2019 à Academy

Amelia é o primeiro projeto histórico da Amelia Academy, iniciado em 2019. Essa
data pertence ao projeto, não à plataforma. A fixture de referência preserva
somente fatos e exemplos já publicados nos documentos Amelia4: calor brasileiro,
curiosidade, presença sem exigência e limites contra dependência, posse,
submissão ou alegações de sentimentos e consciência.

## Como a referência é construída

`personas/amelia/charter.json` é identidade canônica versionada. O manifest em
`fixtures/projects/amelia` expressa fontes, temas, fichas e samples usando as
mesmas entidades públicas da API que qualquer projeto. Ele é uma curadoria
manual da documentação deste repositório. Não é dump, sincronização nem import
automático do banco privado da Amelia3; não contém conversas, memória, sessões,
assets privados ou pesos.

`scripts/reference-import.py` lê os manifests Amelia e Atlas. Sem opções, gera
um plano de requisições HTTP para inspeção. Com `--apply`, envia essas mesmas
requisições à API escolhida. A ferramenta não possui driver de banco, DSN da
Amelia3 nem operação para copiar modelos.

## Por que isso prova generalidade

Atlas Atendimento percorre exatamente `Project → Source → Theme → Behavior →
Sample`, sem tipo, endpoint ou branch específico para Amelia. Voz, relação,
limites e conteúdo variam nos dados; revisão, scoping, hashes e estados
continuam na plataforma. O teste do importador carrega somente Atlas e confirma
que seu plano completo não referencia Amelia. O serviço também já testa Atlas
diretamente no repositório genérico.

Excluir ou não semear a fixture Amelia apenas remove um conjunto opcional de
dados. Não remove schema, rota, contrato nem capacidade do Atlas. Isso é o
critério operacional para Amelia validar a Academy sem se tornar seu domínio.

## Limites atuais

As fixtures são pequenas e deliberadamente não representam uma migração. Samples
continuam `proposed` e exigem revisão humana. Direitos declarados ainda exigem
revisão do operador. Releases e pesos históricos não são importados. Qualquer
migração futura da Amelia3 deve partir de export explícito, redigido e
selecionado, nunca de conexão automática ao banco privado.

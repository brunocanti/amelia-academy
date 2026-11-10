# ADR 007 — Estrutura multi-project desde v1; um operador local inicialmente

**Status:** Accepted  
**Data:** 24 out. 2026

## Contexto

A marca define Amelia Academy como plataforma geral; Amelia é o primeiro projeto histórico e Atlas demonstra um projeto corporativo. Se o schema nascer singleton, persona, políticas e paths da Amelia contaminarão o produto e a correção futura será cara. Em contrapartida, autenticação multiusuário e colaboração não são necessárias para a primeira implantação numa máquina pessoal.

## Decisão

Projetos são fronteira estrutural desde a v1. Toda entidade de domínio, fila, auditoria, artifact ref, endpoint e caminho carrega `project_id`; unicidade e foreign keys respeitam essa fronteira. Catálogos realmente globais — versões de runtime e templates públicos — são explicitamente marcados e somente leitura para projetos.

A implantação inicial possui um ator `local-operator`, sem cadastro, organizações, convites ou papéis remotos. A API faz bind em loopback. O modelo de autorização recebe `Actor` e `ProjectScope` desde já, permitindo adicionar identidade real sem alterar casos de uso.

## Alternativas consideradas

- **Singleton Amelia:** entrega ligeiramente mais rápida, mas contradiz o produto e cria migração transversal.
- **Multi-tenant SaaS completo:** resolve futuro hipotético, amplia muito segurança, UX e operação.
- **Um banco/schema por projeto:** isolamento forte, porém migrations, consultas globais e backups se multiplicam.
- **Prefixo de caminho apenas:** não protege relações nem consultas SQL.

## Consequências

- Queries e testes são mais explícitos e compostos.
- Erro de escopo pode vazar dados; RLS e testes de isolamento são defesa adicional.
- A UI pode mostrar atividade entre projetos sem misturar conteúdo.
- Não se promete segurança contra outros usuários do mesmo sistema operacional na v1.
- Adicionar autenticação futura não exige adicionar `project_id` retroativamente.

## Validação

- Suite cria Amelia e Atlas e tenta cruzar cada tipo de FK, API e artifact; todas as operações falham.
- Fitness test rejeita migration com tabela de domínio sem `project_id`.
- RLS impede leitura com contexto de projeto errado.
- Nenhum texto operacional assume nome, gênero ou charter da Amelia.
- Os dois projetos completam fonte→release usando os mesmos componentes e um único operador.

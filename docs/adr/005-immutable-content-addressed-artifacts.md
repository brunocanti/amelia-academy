# ADR 005 — Artifacts imutáveis e endereçados por conteúdo

**Status:** Accepted  
**Data:** 24 out. 2026

## Contexto

Fontes, exports, adapters, checkpoints e relatórios são maiores que registros relacionais e precisam de integridade, deduplicação e rollback. Caminhos mutáveis como `latest/adapter` não provam qual conteúdo foi avaliado ou publicado. Amelia 3 registra caminhos de arquivo, mas a Academy promete linhagem e reversibilidade verificáveis.

## Decisão

Todo artifact é um blob imutável identificado por SHA-256. Escrita ocorre em staging por tentativa; depois de `fsync`, tamanho e hash são verificados e o blob é movido atomicamente para o CAS. O PostgreSQL guarda tipo, hash, tamanho, media type, projeto, origem, estado de retenção e referências. Manifests também são conteúdo endereçado e usam serialização canônica.

Nomes amigáveis e estados são ponteiros mutáveis no banco; nunca alteram o blob. Remoção é mark-and-sweep: tombstone, janela de recuperação, análise de referências e coleta. Artefato adulterado entra em quarentena.

## Alternativas consideradas

- **Arquivos por nome/versão:** legíveis, mas sujeitos a sobrescrita e colisão.
- **BLOBs no PostgreSQL:** transações simples, porém aumenta backup, WAL e custo de grandes checkpoints.
- **Object storage S3 desde v1:** boa evolução futura, mas adiciona serviço remoto ao fluxo local.
- **Git/LFS:** bom para texto versionado, inadequado como store operacional de jobs e retenção.

## Consequências

- Hash liga avaliação, release e bytes exatos.
- Conteúdo igual é deduplicado, inclusive entre tentativas autorizadas.
- Diretório pode ser movido ou espelhado sem mudar identidade.
- Garbage collection precisa entender manifests e referências.
- Confidencialidade não vem do hash; permissões continuam por projeto e criptografia de backup.

## Validação

- Alterar um byte faz a verificação falhar antes de treino ou publicação.
- Duas gravações idênticas resultam em um blob e duas referências auditáveis.
- Crash antes/depois do rename não produz artifact final parcial.
- GC nunca remove blob alcançável por release, dataset ou janela de retenção.
- Restore em diretório limpo reconstrói catálogo e verifica todos os hashes publicados.

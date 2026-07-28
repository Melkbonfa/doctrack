# PLANO — Arquivos anexados na plataforma

> Objetivo: cada documento pode ter **seu próprio arquivo** enviado para dentro do
> DocTrack e **visualizado na plataforma**, sem depender do caminho de rede.
> O arquivo na plataforma é uma **cópia de conveniência** — o mestre continua no
> servidor da engenharia e a Qualidade mantém o sistema dela.

---

## 0. Contexto e decisões (ler antes de codar)

### O que já existe e será reaproveitado
- `Documento` (models.py:214) — já modela o ciclo de vida inteiro (`status`, `responsavel`,
  `codigo_doc`, `DocumentoHistorico`, `AuditLog`). Falta só o arquivo.
- `@require_role("admin", "gestor")` — padrão já usado em `delete_documento`
  (documentos.py:504) e `update_aplicabilidade` (documentos.py:519). **É a hierarquia
  que já existe; não criar coluna de permissão nova.**
- `log_action(caller, ACAO, entidade=, campo=, antigo=, novo=, documento_id=, ip=get_client_ip())`
  (auth.py) — trilha de auditoria pronta.
- **O visualizador já existe**: modal `#modal-docview` (dashboard.html:334-348) com
  `#docview-body`, `#docview-title`, `#docview-download`; `visualizarDocx()`
  (app.js:1059) renderiza `.docx` no navegador via `docx.renderAsync`; PDF/imagem
  abrem inline por `abrirArquivo()` (app.js:1046).
- `app.config["JWT_TOKEN_LOCATION"] = ["headers", "query_string"]` (servidor.py:85) —
  então `<iframe src="...&token=...">` autentica sem gambiarra.
- `db.create_all()` (servidor.py:2962) cria **tabelas novas** sozinho. `_sync_schema()`
  só é necessário para **colunas novas em tabelas existentes** — este plano não precisa dele.
  Os `migrations/NNN_*.py` são espelhos SQLite opcionais, não o caminho de produção.

### Decisões tomadas (e por quê)

| Decisão | Escolha | Motivo |
|---|---|---|
| Quem envia/substitui/remove | `admin` + `gestor` | É a hierarquia que o sistema já tem. Zero schema novo. |
| Quem lê / baixa | qualquer autenticado com acesso à área | Quem acessa o DocTrack já acessa as pastas — restringir download seria teatro. |
| Nome no disco | SHA-256 do conteúdo | Elimina path traversal por construção, mata colisão de nome e deduplica. Já há duplicata real no share (`IT - Extracta 16 V1.0.docx`, 56 MB, em dois lugares). |
| Substituir arquivo | nova linha `versao+1`, antiga vira inativa | Nunca sobrescrever: "quando esta cópia foi atualizada" é a defesa contra ler versão velha. |
| Formatos aceitos | pdf, docx, doc, xlsx, xls, pptx, png, jpg, jpeg | É exatamente o que existe no share hoje (486 arquivos medidos). |
| Teto de tamanho | 80 MB (`DOCTRACK_UPLOAD_MAX_MB`) | O maior documento real medido tem 56 MB. Hoje **não há `MAX_CONTENT_LENGTH` nenhum** — sem teto, upload é enchimento de disco trivial. |

### O que a medição do share diz sobre o escopo
- 53.875 arquivos / 12,52 GB nas 33 árvores, mas **só 486 são documentos** (0,9% dos
  arquivos, 7% dos bytes). O resto é árvore de firmware, saída de compilação e vídeo.
- O DocTrack rastreia **1347 documentos ativos/aplicáveis**. Ou seja: a maioria ainda
  **não tem arquivo** — são trabalho a fazer.
- **Consequência de produto:** o anexo é a *evidência de conclusão*. Vale expor depois
  "documento concluído sem arquivo anexado" como indicador (Fase 6, opcional).

### Fora de escopo (decidido explicitamente)
- Rasterizar página / marca d'água / bloquear download — descartado: quem lê já tem o share.
- Fluxo de aprovação, assinatura eletrônica, validação CSV — o DocTrack **não** é o mestre.
- Migração em massa dos 486 arquivos existentes — enche por uso, um upload por vez.

---

## 1. Modelo — `DocumentoArquivo` (models.py)

Criar depois de `DocumentoHistorico` (models.py:479):

```python
class DocumentoArquivo(db.Model):
    """Cópia do documento hospedada na plataforma (o mestre segue no servidor).

    Versionado: substituir cria uma linha nova com versao+1 e marca a anterior
    ativo=False. Nunca sobrescrever — saber QUANDO a cópia foi atualizada é o
    que impede alguém ler uma versão velha achando que é a atual.

    `sha256` é o nome do arquivo no disco (endereçado por conteúdo): nenhum
    caminho vem da requisição, então path traversal não existe aqui.
    """
    __tablename__ = "documento_arquivos"

    id            = db.Column(db.Integer, db.ForeignKey(...), primary_key=True)
    documento_id  = db.Column(db.Integer, db.ForeignKey("documentos.id"),
                              nullable=False, index=True)
    versao        = db.Column(db.Integer, default=1, nullable=False)
    sha256        = db.Column(db.String(64), nullable=False, index=True)
    nome_original = db.Column(db.String(300), nullable=False, default="")
    ext           = db.Column(db.String(10), default="")
    mime          = db.Column(db.String(120), default="")
    tamanho       = db.Column(db.Integer, default=0)
    observacao    = db.Column(db.String(300), default="")
    enviado_por   = db.Column(db.String(120), default="")
    enviado_em    = db.Column(db.DateTime, default=datetime.now)
    ativo         = db.Column(db.Boolean, default=True, nullable=False, index=True)

    documento_rel = db.relationship("Documento",
                                    backref=db.backref("arquivos", lazy="select"))

    def to_dict(self): ...   # + `pode_visualizar` (ext em PDF/DOCX/imagem)
```

Em `Documento.to_dict()` (models.py) adicionar, sem consulta extra pesada:
- `"tem_arquivo": bool` e `"arquivo_versao"` / `"arquivo_enviado_em"` da versão ativa.

---

## 2. Armazenamento — módulo `arquivos_store.py` (novo)

Um módulo pequeno, na linha do `caminhos.py`: responsabilidade única, testável isolado.

```python
RAIZ = os.environ.get("DOCTRACK_ARQUIVOS") or <raiz do projeto>/arquivos
MAX_BYTES = int(os.environ.get("DOCTRACK_UPLOAD_MAX_MB", "80")) * 1024 * 1024
EXT_PERMITIDAS = {".pdf",".docx",".doc",".xlsx",".xls",".pptx",".png",".jpg",".jpeg"}

def caminho_de(sha):   # RAIZ/ab/cd/abcd...  (2 níveis de fan-out)
def guardar(stream) -> (sha256, tamanho)   # escreve em .tmp, calcula hash, move
def remover(sha)                            # só se nenhuma linha ativa usar o hash
```

Regras:
- Escrever primeiro num `.tmp` e só então `os.replace` para o destino final —
  upload interrompido nunca deixa arquivo meio gravado com nome válido.
- Se o SHA já existir no disco, **não regravar** (dedup).
- `remover()` só apaga o blob se **nenhuma outra linha** referenciar aquele SHA.

### Armadilhas de deploy (as duas importam)
1. **A pasta NÃO pode ficar dentro de `_internal\`.** O `docs/DEPLOY_SERVIDOR.md:69`
   manda substituir `_internal\` na atualização — os arquivos sumiriam na primeira
   atualização. Fica ao lado do `.env`, como o banco.
2. **`scripts/gerar_backup.ps1` só faz `pg_dump`.** Banco sem os blobs é inútil e
   vice-versa: o script precisa copiar a pasta de arquivos na mesma execução, ou o
   backup passa a ser falso.

---

## 3. API (documentos.py, no fim do bloco de arquivos, após `servir_arquivo` :1159)

| Rota | Método | Papel | Auditoria |
|---|---|---|---|
| `/api/documentos/<doc_id>/arquivos` | GET | autenticado | — |
| `/api/documentos/<doc_id>/arquivos` | POST | **admin, gestor** | `UPLOAD` |
| `/api/documentos/arquivos/<arq_id>/conteudo` | GET | autenticado | — |
| `/api/documentos/arquivos/<arq_id>` | DELETE | **admin, gestor** | `DELETE` |

**POST** — `multipart/form-data`, campo `arquivo` (+ `observacao` opcional):
1. 400 se não veio arquivo; 415 se a extensão não está na allowlist.
2. `arquivos_store.guardar()` → `(sha, tamanho)`; 413 se estourar o teto.
3. Se já existe versão ativa: marca `ativo=False` e a nova entra com `versao+1`.
4. `log_action(..., "UPLOAD", entidade=doc.documento, campo="arquivo",
   antigo=<nome anterior>, novo=<nome novo>, documento_id=doc.id, ip=get_client_ip())`.
5. Devolve o documento atualizado (mesmo formato do PATCH) para o front repintar.

**GET conteudo** — `send_file(arquivos_store.caminho_de(arq.sha256),
as_attachment = ext not in _EXT_INLINE or request.args.get("download")=="1",
download_name=arq.nome_original, conditional=True, mimetype=arq.mime)`.
O caminho **sempre** sai da linha do banco, nunca da querystring.

**DELETE** — soft delete (`ativo=False`) + `arquivos_store.remover(sha)` se órfão.

### Teto de upload (servidor.py)
- `app.config["MAX_CONTENT_LENGTH"] = arquivos_store.MAX_BYTES`
- Handler `@app.errorhandler(413)` devolvendo **JSON** (`{"erro": "Arquivo maior que
  80 MB"}`), senão o front recebe HTML e quebra o `res.json()`.

---

## 4. Frontend

### 4.1 Painel "Arquivos" do documento (app.js, bloco `doc-sec` de Arquivos, ~:1846)
Acima do campo de caminho de rede, uma faixa nova:

- **Sem arquivo:** texto `Nenhum arquivo na plataforma` + botão `⬆ Enviar arquivo`
  (só renderiza o botão se `_isGestor()` — checagem de UI; o servidor é quem decide).
- **Com arquivo:** linha no estilo `.arquivo-row` já existente (app.js:1023) com
  ícone da extensão, nome, `v3 · 2,4 MB · enviado por Fulano em 12/03/2026`, e ações
  `Visualizar` · `Baixar` · `Substituir`/`Remover` (as duas últimas só para gestor).

O selo de versão/autor é obrigatório: é o que impede alguém ler cópia velha sem perceber.

### 4.2 Envio
`<input type="file" hidden>` + `FormData` via `apiFetch` **sem** `Content-Type` manual
(o browser precisa definir o boundary). Barra de progresso não é necessária no v1;
um estado "enviando…" no botão basta.

### 4.3 Visualização dentro da plataforma
Reaproveitar `#modal-docview`:
- **`.docx`** → já funciona: `docx.renderAsync` sobre o blob do novo endpoint.
- **`.pdf`/imagem** → hoje `abrirArquivo()` faz `window.open` em aba nova (app.js:1051).
  Para "dentro da plataforma", renderizar `<iframe src="<endpoint>?token=...">` dentro
  de `#docview-body`. Sem biblioteca nova — o visualizador nativo do navegador resolve.
- Botão `#docview-download` apontando para o mesmo endpoint com `&download=1`.

---

## 5. Testes (`tests/test_documento_arquivos.py`, novo)

Seguir `tests/test_pastas_equipamento.py`. `DOCTRACK_ARQUIVOS` apontando para `tmp_path`.

1. `tecnico` recebe **403** no POST; `gestor` recebe 201.
2. Upload grava o blob, cria `versao=1` e `Documento.to_dict()["tem_arquivo"]` vira True.
3. Segundo upload → `versao=2`, versão 1 fica `ativo=False`, GET lista as duas.
4. Extensão fora da allowlist (`.exe`) → **415** e nada é gravado no disco.
5. GET conteudo: qualquer papel autenticado (inclusive `leitura`) recebe 200.
6. DELETE por `tecnico` → 403; por `gestor` → 200 e o blob some.
7. Dois documentos com o **mesmo conteúdo** → um único blob no disco (dedup), e
   apagar um **não** deixa o outro sem arquivo.
8. Upload registra `AuditLog` com ação `UPLOAD` e `documento_id` correto.

---

## 6. Fases (ordem de execução)

| # | Fase | Entrega |
|---|---|---|
| 1 | `arquivos_store.py` + testes do módulo | isolado, sem tocar em rota |
| 2 | Modelo `DocumentoArquivo` + `to_dict` do documento | `create_all` cria a tabela |
| 3 | Rotas (POST/GET/GET conteudo/DELETE) + `MAX_CONTENT_LENGTH` + handler 413 | API completa |
| 4 | Frontend: faixa de arquivo, envio, visor no `#modal-docview` | fluxo ponta a ponta |
| 5 | `gerar_backup.ps1` + `DEPLOY_SERVIDOR.md` + `.env.example` + `CHANGELOG.md` | operável |
| 6 | *(opcional, depois)* indicador "concluído sem arquivo anexado" | usa o dado novo |

Fases 1–3 são backend puro e verificáveis por `pytest`. A 4 é a única que exige o
navegador. A 5 não é opcional para ir a produção — sem ela o backup mente.

---

## 7. Riscos aceitos

- **A cópia pode ficar desatualizada em relação ao mestre.** Mitigação: versão + autor +
  data sempre visíveis. Não há sincronização automática, e isso é intencional.
- **Sem antivírus no upload.** O arquivo vem de rede interna e de usuário com papel de
  gestor; o servido é sempre `Content-Disposition` coerente com a extensão da allowlist.
- **`send_file` com `conditional=True` mantém o arquivo aberto durante o stream** — em
  Windows, remover um blob enquanto alguém baixa pode falhar. Por isso o DELETE é soft
  primeiro; a remoção física falhando não quebra a operação.

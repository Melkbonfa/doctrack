"""
cadernos/models.py — Modelos do módulo Cadernos (cadernos de laboratório).

Reutiliza o `db` da plataforma mestre. Tabelas prefixadas `caderno_`.

Domínio: Caderno → CadernoNo (grupo de seções ou seção, em árvore) → CadernoPagina
(lista plana por seção, com `nivel` 1–3), mais as versões da página e o espaço de
arquivos. O desenho completo e o porquê de cada escolha estão em
docs/planos/PLANO_cadernos.md; aqui ficam só as três decisões que mudam como se
lê o código.

**1. Subpágina não tem `parent_id`.** É o modelo do OneNote ([MS-ONE] PageLevel):
as páginas de uma seção são UMA lista ordenada, e a subpágina é deduzida de
`ordem` + `nivel`. Mover uma página com suas subpáginas é reescrever `ordem`, sem
recursão. As invariantes (primeira página no nível 1, sem pular nível, nível ≤ 3)
moram em `core.normalizar_niveis` e valem em toda escrita.

**2. O conteúdo é HTML saneado, não blocos.** O editor é o CKEditor 5 e o servidor
guarda o que ele produz depois de passar por `core.sanear_html` — nunca o que
chegou. Imagem é guardada como `<img data-arquivo="<uuid>">`, sem `src`: o `src`
é montado no front com o token da sessão, e assim nenhum token vai para o banco
nem para o histórico de versões.

**3. Uma pessoa edita a página por vez.** `editando_por`/`editando_ate` são a trava
(ver `core.pode_editar`). A trava expira sozinha — aba fechada ou máquina que
dormiu não deixam a página presa — e é por ela que a versão por sessão de edição
fica bem definida.
"""
import uuid as _uuid
from datetime import datetime

from models import db


def _novo_uuid():
    return str(_uuid.uuid4())


# ── CONSTANTES DE DOMÍNIO ─────────────────────────────────────────────────────

# Papel de um membro no caderno. A ordem importa: core.PESO_PAPEL compara.
PAPEIS = ["leitor", "editor", "dono"]

# O que a área inteira recebe sem ser membro. 'editor' é o padrão porque o
# caderno de laboratório é da equipe: exigir cadastro um a um para escrever seria
# burocracia que ninguém pediu. 'nenhum' é o caderno privado.
ACESSOS_AREA = ["nenhum", "leitor", "editor"]

TIPOS_NO = ["grupo", "secao"]
TIPOS_PAGINA = ["nota", "registro_teste"]
ESCOPOS_ARQUIVO = ["caderno", "secao", "pagina"]
RESULTADOS_TESTE = ["", "em_andamento", "aprovado", "reprovado", "inconclusivo"]
MOTIVOS_VERSAO = ["sessao", "antes_excluir", "antes_restaurar", "importacao", "reimportacao"]


# ── CADERNO ───────────────────────────────────────────────────────────────────
class Caderno(db.Model):
    __tablename__ = "caderno_cadernos"

    id            = db.Column(db.Integer, primary_key=True)
    uuid          = db.Column(db.String(36), unique=True, nullable=False, default=_novo_uuid)
    nome          = db.Column(db.String(200), nullable=False)
    cor           = db.Column(db.String(9), default="#a855f7")
    descricao     = db.Column(db.Text, default="")
    # Área de P&D dona do caderno (slug de areas.py). É o recorte de visibilidade.
    area          = db.Column(db.String(20), nullable=False, index=True)
    acesso_area   = db.Column(db.String(10), nullable=False, default="editor")
    # Modelo usado na criação (ex.: 'projeto_pdr'). Só registro: o modelo não
    # amarra nada depois que as seções nascem.
    modelo        = db.Column(db.String(40), default="")
    dono_id       = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    criado_em     = db.Column(db.DateTime, default=datetime.now)
    atualizado_em = db.Column(db.DateTime, default=datetime.now)
    arquivado     = db.Column(db.Boolean, default=False, nullable=False)
    excluido_em   = db.Column(db.DateTime, nullable=True, index=True)
    excluido_por  = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    # ID do OneNote, quando o caderno veio de uma importação.
    origem_ref    = db.Column(db.String(120), default="", index=True)

    def to_dict(self, papel=None):
        return {
            "uuid":          self.uuid,
            "nome":          self.nome,
            "cor":           self.cor or "",
            "descricao":     self.descricao or "",
            "area":          self.area,
            "acesso_area":   self.acesso_area,
            "modelo":        self.modelo or "",
            "dono_id":       self.dono_id,
            "arquivado":     bool(self.arquivado),
            "excluido_em":   self.excluido_em.isoformat() if self.excluido_em else None,
            "criado_em":     self.criado_em.isoformat() if self.criado_em else None,
            "atualizado_em": self.atualizado_em.isoformat() if self.atualizado_em else None,
            "papel":         papel,
        }


class CadernoMembro(db.Model):
    """Papel explícito de uma pessoa num caderno. Vence o `acesso_area`."""
    __tablename__ = "caderno_membros"
    __table_args__ = (db.UniqueConstraint("caderno_id", "user_id", name="uq_caderno_membro"),)

    id         = db.Column(db.Integer, primary_key=True)
    caderno_id = db.Column(db.Integer, db.ForeignKey("caderno_cadernos.id"), nullable=False, index=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    papel      = db.Column(db.String(10), nullable=False, default="editor")


# ── GRUPO DE SEÇÕES / SEÇÃO ───────────────────────────────────────────────────
class CadernoNo(db.Model):
    """Grupo de seções ou seção. Uma tabela para os dois: são nós da mesma árvore
    (o grupo do OneNote contém seções E outros grupos). Só `secao` tem páginas —
    quem garante é o core, não o banco."""
    __tablename__ = "caderno_nos"

    id               = db.Column(db.Integer, primary_key=True)
    uuid             = db.Column(db.String(36), unique=True, nullable=False, default=_novo_uuid)
    caderno_id       = db.Column(db.Integer, db.ForeignKey("caderno_cadernos.id"), nullable=False, index=True)
    parent_id        = db.Column(db.Integer, db.ForeignKey("caderno_nos.id"), nullable=True, index=True)
    tipo             = db.Column(db.String(10), nullable=False, default="secao")
    nome             = db.Column(db.String(200), nullable=False)
    cor              = db.Column(db.String(9), default="")
    ordem            = db.Column(db.Integer, default=0)
    # Tipo de página que "+ Página" cria por padrão nesta seção.
    tipo_pagina_padrao = db.Column(db.String(20), default="nota")
    criado_em        = db.Column(db.DateTime, default=datetime.now)
    excluido_em      = db.Column(db.DateTime, nullable=True, index=True)
    excluido_por     = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    origem_ref       = db.Column(db.String(120), default="", index=True)

    def to_dict(self):
        return {
            "uuid":      self.uuid,
            "tipo":      self.tipo,
            "nome":      self.nome,
            "cor":       self.cor or "",
            "ordem":     self.ordem or 0,
            "parent_id": self.parent_id,
            "id":        self.id,
            "tipo_pagina_padrao": self.tipo_pagina_padrao or "nota",
            "excluido_em": self.excluido_em.isoformat() if self.excluido_em else None,
        }


# ── PÁGINA ────────────────────────────────────────────────────────────────────
class CadernoPagina(db.Model):
    __tablename__ = "caderno_paginas"

    id              = db.Column(db.Integer, primary_key=True)
    uuid            = db.Column(db.String(36), unique=True, nullable=False, default=_novo_uuid)
    secao_id        = db.Column(db.Integer, db.ForeignKey("caderno_nos.id"), nullable=False, index=True)
    # Desnormalizado: permissão e busca filtram por caderno sem subir a árvore.
    caderno_id      = db.Column(db.Integer, db.ForeignKey("caderno_cadernos.id"), nullable=False, index=True)
    tipo            = db.Column(db.String(20), nullable=False, default="nota")
    titulo          = db.Column(db.String(300), nullable=False, default="")
    # A data/hora sob o título. Num caderno de bancada ela É o registro, por isso
    # é editável e separada de criado_em.
    data_pagina     = db.Column(db.DateTime, default=datetime.now)
    nivel           = db.Column(db.Integer, nullable=False, default=1)
    recolhida       = db.Column(db.Boolean, default=False, nullable=False)
    ordem           = db.Column(db.Integer, nullable=False, default=0)
    conteudo_html   = db.Column(db.Text, default="")
    # Ficha do "Registro de teste" (ver core.CAMPOS_FICHA). JSON em texto.
    ficha_json      = db.Column(db.Text, default="")
    texto_busca     = db.Column(db.Text, default="")
    versao          = db.Column(db.Integer, nullable=False, default=1)
    criado_por      = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    criado_em       = db.Column(db.DateTime, default=datetime.now)
    atualizado_por  = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    atualizado_em   = db.Column(db.DateTime, default=datetime.now)
    # Trava de edição. Ver core.pode_editar.
    editando_por    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    editando_ate    = db.Column(db.DateTime, nullable=True)
    # Versão em que a sessão de edição atual começou: decide se há o que guardar
    # como versão quando a sessão termina.
    sessao_versao   = db.Column(db.Integer, nullable=True)
    excluido_em     = db.Column(db.DateTime, nullable=True, index=True)
    excluido_por    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    origem_ref      = db.Column(db.String(120), default="", index=True)
    origem_autores  = db.Column(db.Text, default="")


class CadernoPaginaVersao(db.Model):
    """Foto completa da página. Uma por sessão de edição, mais as de segurança
    (antes de excluir/restaurar). Completa e não delta: páginas são pequenas e
    restaurar não pode depender de uma corrente de diffs íntegra."""
    __tablename__ = "caderno_pagina_versoes"

    id            = db.Column(db.Integer, primary_key=True)
    pagina_id     = db.Column(db.Integer, db.ForeignKey("caderno_paginas.id"), nullable=False, index=True)
    versao        = db.Column(db.Integer, nullable=False)
    titulo        = db.Column(db.String(300), default="")
    conteudo_html = db.Column(db.Text, default="")
    ficha_json    = db.Column(db.Text, default="")
    autor_id      = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    criado_em     = db.Column(db.DateTime, default=datetime.now)
    motivo        = db.Column(db.String(20), default="sessao")


# ── ARQUIVOS ──────────────────────────────────────────────────────────────────
class CadernoArquivo(db.Model):
    """Arquivo de QUALQUER extensão preso ao caderno, a uma seção ou a uma página.

    É também onde moram as imagens coladas no editor (`embutido=True`): elas não
    aparecem no painel de arquivos, mas são arquivos como os outros — mesmo blob
    endereçado por conteúdo (ADR-0009), mesma rota de download.

    Versionado: substituir cria uma linha nova com `versao+1` no mesmo `grupo` e
    marca a anterior `ativo=False`. Diferente de `DocumentoArquivo`, a versão
    anterior CONTINUA baixável — a versão do programa usada num teste precisa
    ser recuperável. Por isso o blob é segurado por qualquer linha não excluída
    (`excluido_em IS NULL`), ativa ou não; ver `documentos._sha_orfao`.
    """
    __tablename__ = "caderno_arquivos"

    id                 = db.Column(db.Integer, primary_key=True)
    uuid               = db.Column(db.String(36), unique=True, nullable=False, default=_novo_uuid)
    # Identifica a família de versões do mesmo arquivo (uuid da primeira versão).
    grupo              = db.Column(db.String(36), nullable=False, index=True)
    caderno_id         = db.Column(db.Integer, db.ForeignKey("caderno_cadernos.id"), nullable=False, index=True)
    escopo             = db.Column(db.String(10), nullable=False, default="pagina")
    escopo_id          = db.Column(db.Integer, nullable=False, index=True)
    pasta              = db.Column(db.String(120), default="")
    descricao          = db.Column(db.Text, default="")
    nome_original      = db.Column(db.String(300), nullable=False, default="")
    ext                = db.Column(db.String(20), default="")
    mime               = db.Column(db.String(120), default="")
    sha256             = db.Column(db.String(64), nullable=False, index=True)
    tamanho            = db.Column(db.BigInteger, default=0)
    versao             = db.Column(db.Integer, nullable=False, default=1)
    ativo              = db.Column(db.Boolean, default=True, nullable=False)
    embutido           = db.Column(db.Boolean, default=False, nullable=False)
    incluir_exportacao = db.Column(db.Boolean, default=True, nullable=False)
    ocr_texto          = db.Column(db.Text, default="")
    origem             = db.Column(db.String(20), default="upload")
    origem_url         = db.Column(db.Text, default="")
    enviado_por        = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    enviado_em         = db.Column(db.DateTime, default=datetime.now)
    excluido_em        = db.Column(db.DateTime, nullable=True, index=True)
    excluido_por       = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    def to_dict(self):
        return {
            "uuid":               self.uuid,
            "grupo":              self.grupo,
            "escopo":             self.escopo,
            "pasta":              self.pasta or "",
            "descricao":          self.descricao or "",
            "nome":               self.nome_original,
            "ext":                self.ext or "",
            "tamanho":            int(self.tamanho or 0),
            "versao":             self.versao,
            "ativo":              bool(self.ativo),
            "embutido":           bool(self.embutido),
            "incluir_exportacao": bool(self.incluir_exportacao),
            "origem":             self.origem or "upload",
            "enviado_por":        self.enviado_por,
            "enviado_em":         self.enviado_em.isoformat() if self.enviado_em else None,
        }


# ── EXPORTAÇÃO ────────────────────────────────────────────────────────────────
class CadernoExportacao(db.Model):
    """Registro de cada pacote .zip gerado para a liderança: quem gerou, quando,
    quais páginas (e em que versão) e o manifesto com o SHA-256 de cada arquivo.

    O zip em si não é guardado (pode ter centenas de MB de programas): fica numa
    pasta temporária por um dia para o download. O que vale como rastro é este
    registro — com ele dá para saber exatamente o que a liderança recebeu.
    """
    __tablename__ = "caderno_exportacoes"

    id             = db.Column(db.Integer, primary_key=True)
    uuid           = db.Column(db.String(36), unique=True, nullable=False, default=_novo_uuid)
    caderno_id     = db.Column(db.Integer, db.ForeignKey("caderno_cadernos.id"), nullable=False, index=True)
    criado_por     = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    criado_em      = db.Column(db.DateTime, default=datetime.now)
    escopo         = db.Column(db.String(200), default="")
    nome_zip       = db.Column(db.String(300), default="")
    tamanho        = db.Column(db.BigInteger, default=0)
    # [{uuid, titulo, versao}] e [{caminho, tamanho, sha256}]
    paginas_json   = db.Column(db.Text, default="[]")
    manifesto_json = db.Column(db.Text, default="[]")

    def to_dict(self):
        import json
        return {
            "uuid":      self.uuid,
            "escopo":    self.escopo or "",
            "nome_zip":  self.nome_zip or "",
            "tamanho":   int(self.tamanho or 0),
            "criado_por": self.criado_por,
            "criado_em": self.criado_em.isoformat() if self.criado_em else None,
            "paginas":   len(json.loads(self.paginas_json or "[]")),
            "arquivos":  len(json.loads(self.manifesto_json or "[]")),
        }

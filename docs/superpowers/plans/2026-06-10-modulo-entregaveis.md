# Módulo de Entregáveis por Projeto — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir a planilha "Entregáveis - Engenharia (rev fev).xlsm" por um módulo `/entregaveis` no DocTrack: cards de projeto + drill-down de entregáveis com status/percentual/responsáveis, edição auditada em tempo real e export Excel limpo.

**Architecture:** Mesma aplicação Flask e mesmo `doctrack.db` (abordagem integrada). Duas tabelas novas (`Projeto`, `Entregavel`) em `models.py`; blueprint novo `entregaveis.py` com a API; página própria `templates/entregaveis.html` + `static/entregaveis.js`; importação única via script `importar_entregaveis.py`. Avanço do projeto é sempre calculado (média dos entregáveis aplicáveis), nunca armazenado.

**Tech Stack:** Flask, SQLAlchemy, Flask-JWT-Extended (roles: admin/gestor/tecnico/leitura), Flask-SocketIO + event_bus, openpyxl, pytest. Frontend vanilla JS com o tema escuro/ciano existente.

**⚠️ RESTRIÇÃO GLOBAL:** **NÃO commitar nada no git.** Todos os passos de "commit" do fluxo padrão foram substituídos por checkpoints locais (rodar testes). O trabalho fica apenas no working tree até o usuário validar.

**Spec:** `docs/superpowers/specs/2026-06-10-modulo-entregaveis-design.md`

---

## Contexto do código (leia antes de começar)

- `models.py` — modelos SQLAlchemy; padrão: `to_dict()`, datas via `datetime.now`, `db = SQLAlchemy()` global.
- `auth.py` — `require_role(*roles)` (decorator JWT), `log_action(...)` (audit log), `get_client_ip()`.
- `servidor.py` — app principal; registra `auth_bp` (linha ~66); `socketio` global; `publish_event(EventType.X, payload, user_id, user_email, db=db, AuditLog=AuditLog, socketio=socketio)` para tempo real; rota `/` serve `dashboard.html` com `asset_v=_static_version()`.
- `event_bus.py` — classe `EventType` (constantes) e `publish_event(...)`.
- `tests/conftest.py` — fixtures `app`, `client`, `admin_token`, `gestor_token`, `tecnico_token`, `leitura_token`, `auth_headers`. DB SQLite temporário com `db.create_all()` (tabelas novas entram automaticamente).
- Planilha: `files/Entregáveis - Engenharia (rev fev).xlsm`, aba **"Controle Projetos 2026"**:
  - Linha 1 = categorias (Produto, Sistema, Documentação, Capacitação, Marketing) em células esparsas (forward-fill); depois vêm colunas de "% janeiro" etc. que devem ser IGNORADAS.
  - Linha 2 = cabeçalhos: `Ordem | MoSCoW | Prioridade | Entregáveis | (vazio) | Descrição | Consumível? | Cronograma Mapeado | SKU | Lançamentos | <tipos de entregáveis...>`
  - Linha 3 = responsáveis padrão por coluna de entregável (ex.: "Guilherme/Melk").
  - Linhas 4+ = projetos; células de entregável contêm 0–1, "NA", "na", "N/A" ou vazio.
  - Células `#REF!`/`#VALUE!`/`#DIV/0!` aparecem em colunas de fórmula — ignorar.
- Rodar servidor/testes: `./venv/Scripts/python.exe` (Windows). Pytest: `./venv/Scripts/python.exe -m pytest`.

### Estrutura de arquivos do módulo

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `models.py` | Modificar | + `Projeto`, `Entregavel`, constantes, conversão célula→status |
| `entregaveis.py` | Criar | Blueprint com toda a API + export Excel |
| `importar_entregaveis.py` | Criar | Script CLI de importação única da planilha |
| `servidor.py` | Modificar | Registrar blueprint + rota da página `/entregaveis` |
| `templates/entregaveis.html` | Criar | Página (cards + drill-down + popover de edição) |
| `static/entregaveis.js` | Criar | Lógica da página |
| `static/entregaveis.css` | Criar | Estilos próprios do módulo (complementa style.css) |
| `templates/dashboard.html` | Modificar | Link "Entregáveis" no header |
| `tests/test_entregaveis.py` | Criar | Testes de modelo, conversão, API, permissões, export |

---

### Task 1: Modelos `Projeto` e `Entregavel` + conversão de célula

**Files:**
- Modify: `models.py` (adicionar ao final, antes de `RevokedToken` ou após — ordem irrelevante)
- Test: `tests/test_entregaveis.py` (novo)

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/test_entregaveis.py`:

```python
"""Testes do módulo de Entregáveis (Projeto, Entregavel, API, export)."""


# ── Conversão célula → status ────────────────────────────────────────────────

def test_converter_celula():
    from models import converter_celula
    assert converter_celula(1) == ("concluido", 100)
    assert converter_celula(1.0) == ("concluido", 100)
    assert converter_celula(0) == ("pendente", 0)
    assert converter_celula(0.85) == ("em_progresso", 85)
    assert converter_celula(0.5) == ("em_progresso", 50)
    assert converter_celula("NA") == ("na", None)
    assert converter_celula("na") == ("na", None)
    assert converter_celula("N/A") == ("na", None)
    assert converter_celula(None) == ("na", None)
    assert converter_celula("") == ("na", None)
    # Lixo de fórmula → na
    assert converter_celula("#REF!") == ("na", None)


# ── Avanço calculado ─────────────────────────────────────────────────────────

def test_avanco_projeto(app):
    from models import db, Projeto, Entregavel
    with app.app_context():
        p = Projeto(nome="Teste X", ano=2026)
        db.session.add(p)
        db.session.flush()
        db.session.add_all([
            Entregavel(projeto_id=p.id, tipo="A", categoria="Produto", status="concluido"),
            Entregavel(projeto_id=p.id, tipo="B", categoria="Produto", status="pendente"),
            Entregavel(projeto_id=p.id, tipo="C", categoria="Sistema",
                       status="em_progresso", percentual=50),
            Entregavel(projeto_id=p.id, tipo="D", categoria="Sistema", status="na"),
        ])
        db.session.commit()
        # (100 + 0 + 50) / 3 aplicáveis = 50
        assert p.avanco == 50


def test_avanco_projeto_sem_entregaveis(app):
    from models import db, Projeto
    with app.app_context():
        p = Projeto(nome="Vazio", ano=2026)
        db.session.add(p)
        db.session.commit()
        assert p.avanco == 0


def test_avanco_projeto_todos_na(app):
    from models import db, Projeto, Entregavel
    with app.app_context():
        p = Projeto(nome="Só NA", ano=2026)
        db.session.add(p)
        db.session.flush()
        db.session.add(Entregavel(projeto_id=p.id, tipo="A", categoria="Produto", status="na"))
        db.session.commit()
        assert p.avanco == 0
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `./venv/Scripts/python.exe -m pytest tests/test_entregaveis.py -v`
Expected: FAIL — `ImportError: cannot import name 'converter_celula'`

- [ ] **Step 3: Implementar em `models.py`**

Adicionar ao final de `models.py`:

```python
# ── ENTREGÁVEIS DE PROJETO ───────────────────────────────────────────────────

CATEGORIAS_ENTREGAVEL = ["Produto", "Sistema", "Documentação", "Capacitação", "Marketing"]
STATUS_ENTREGAVEL = ["na", "pendente", "em_progresso", "concluido"]
MOSCOW = ["Must", "Should", "Could", "Wont"]


def converter_celula(valor):
    """Converte valor de célula da planilha para (status, percentual).

    1 → concluido/100 · 0 → pendente/0 · 0<x<1 → em_progresso/round(x*100)
    NA/vazio/lixo de fórmula → na/None
    """
    if valor is None:
        return ("na", None)
    if isinstance(valor, str):
        v = valor.strip().lower()
        if v in ("", "na", "n/a") or v.startswith("#"):
            return ("na", None)
        try:
            valor = float(v.replace(",", "."))
        except ValueError:
            return ("na", None)
    try:
        x = float(valor)
    except (TypeError, ValueError):
        return ("na", None)
    if x >= 1:
        return ("concluido", 100)
    if x <= 0:
        return ("pendente", 0)
    return ("em_progresso", round(x * 100))


class Projeto(db.Model):
    __tablename__ = "projetos"

    id          = db.Column(db.Integer, primary_key=True)
    nome        = db.Column(db.String(200), nullable=False)
    descricao   = db.Column(db.String(400), default="")
    sku         = db.Column(db.String(50), default="")
    moscow      = db.Column(db.String(10), default="")
    prioridade  = db.Column(db.Integer, default=0)
    consumivel  = db.Column(db.Boolean, default=False)
    lancamento  = db.Column(db.String(40), default="")   # data ou ano em texto livre
    ano         = db.Column(db.Integer, default=2026, index=True)
    ativo       = db.Column(db.Boolean, default=True, nullable=False, index=True)
    criado_em   = db.Column(db.DateTime, default=datetime.now)

    entregaveis = db.relationship("Entregavel", back_populates="projeto",
                                  cascade="all, delete-orphan")

    @property
    def avanco(self):
        """Avanço 0-100: média dos entregáveis aplicáveis (status != na)."""
        valores = []
        for e in self.entregaveis:
            if e.status == "na":
                continue
            if e.status == "concluido":
                valores.append(100)
            elif e.status == "em_progresso":
                valores.append(e.percentual or 0)
            else:
                valores.append(0)
        return round(sum(valores) / len(valores)) if valores else 0

    @property
    def pendentes(self):
        return sum(1 for e in self.entregaveis if e.status == "pendente")

    def to_dict(self, com_entregaveis=False):
        d = {
            "id":         self.id,
            "nome":       (self.nome or "").strip(),
            "descricao":  self.descricao or "",
            "sku":        self.sku or "",
            "moscow":     self.moscow or "",
            "prioridade": self.prioridade or 0,
            "consumivel": bool(self.consumivel),
            "lancamento": self.lancamento or "",
            "ano":        self.ano,
            "ativo":      bool(self.ativo),
            "avanco":     self.avanco,
            "pendentes":  self.pendentes,
            "total_entregaveis": sum(1 for e in self.entregaveis if e.status != "na"),
        }
        if com_entregaveis:
            d["entregaveis"] = [e.to_dict() for e in self.entregaveis]
        return d


class Entregavel(db.Model):
    __tablename__ = "entregaveis"

    id             = db.Column(db.Integer, primary_key=True)
    projeto_id     = db.Column(db.Integer, db.ForeignKey("projetos.id"),
                               nullable=False, index=True)
    tipo           = db.Column(db.String(120), nullable=False)
    categoria      = db.Column(db.String(40), default="Produto")
    status         = db.Column(db.String(20), default="pendente", index=True)
    percentual     = db.Column(db.Integer, nullable=True)
    responsaveis   = db.Column(db.String(200), default="")
    atualizado_por = db.Column(db.String(120), default="")
    atualizado_em  = db.Column(db.DateTime, default=datetime.now,
                               onupdate=datetime.now)

    projeto = db.relationship("Projeto", back_populates="entregaveis")

    def to_dict(self):
        return {
            "id":             self.id,
            "projeto_id":     self.projeto_id,
            "tipo":           (self.tipo or "").strip(),
            "categoria":      self.categoria or "",
            "status":         self.status or "pendente",
            "percentual":     self.percentual,
            "responsaveis":   self.responsaveis or "",
            "atualizado_por": self.atualizado_por or "",
            "atualizado_em":  self.atualizado_em.strftime("%d/%m/%Y %H:%M") if self.atualizado_em else "",
        }
```

- [ ] **Step 4: Rodar e confirmar que passam**

Run: `./venv/Scripts/python.exe -m pytest tests/test_entregaveis.py -v`
Expected: 4 PASS

- [ ] **Step 5: Checkpoint local (SEM commit)**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: suíte inteira verde (nada quebrou). **Não commitar.**

---

### Task 2: Script de importação `importar_entregaveis.py`

**Files:**
- Create: `importar_entregaveis.py`
- Test: manual (script CLI com resumo) + função de parse coberta por teste

- [ ] **Step 1: Teste da função de parse (falha primeiro)**

Adicionar a `tests/test_entregaveis.py`:

```python
# ── Parser da planilha ───────────────────────────────────────────────────────

def test_extrair_colunas_entregaveis():
    """Forward-fill de categorias e corte nas colunas de % mensal."""
    from importar_entregaveis import extrair_colunas
    # Simula linhas 1-3 da aba (listas alinhadas por índice de coluna, 0-based)
    linha1 = [None]*10 + ["Produto", None, "Sistema", None, "% janeiro", None]
    linha2 = ["Ordem", "MoSCoW", "Prioridade", "Entregáveis", None, "Descrição",
              "Consumível?", "Cronograma Mapeado", "SKU", "Lançamentos",
              "Validação Técnica", "Protótipo", "Software Neutro", "Embalagem",
              "% janeiro", "%fevereiro"]
    linha3 = [None]*10 + ["Paulo/Giullia", "Julio/ Diego", "Paulo", "Paulo/Giullia", None, None]
    cols = extrair_colunas(linha1, linha2, linha3)
    assert cols == [
        (10, "Validação Técnica", "Produto", "Paulo/Giullia"),
        (11, "Protótipo", "Produto", "Julio/ Diego"),
        (12, "Software Neutro", "Sistema", "Paulo"),
        (13, "Embalagem", "Sistema", "Paulo/Giullia"),
    ]
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `./venv/Scripts/python.exe -m pytest tests/test_entregaveis.py::test_extrair_colunas_entregaveis -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'importar_entregaveis'`

- [ ] **Step 3: Criar `importar_entregaveis.py`**

```python
"""
importar_entregaveis.py — Importação única da aba "Controle Projetos 2026"
da planilha files/Entregáveis - Engenharia (rev fev).xlsm para o doctrack.db.

Uso:
  ./venv/Scripts/python.exe importar_entregaveis.py            # importa (aborta se já houver dados)
  ./venv/Scripts/python.exe importar_entregaveis.py --substituir  # apaga projetos do ano e reimporta
  ./venv/Scripts/python.exe importar_entregaveis.py --dry-run     # só mostra o resumo, não grava
"""
import os
import sys
import argparse

XLSM = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "files", "Entregáveis - Engenharia (rev fev).xlsm")
ABA = "Controle Projetos 2026"
ANO = 2026
CATEGORIAS_VALIDAS = ["Produto", "Sistema", "Documentação", "Capacitação", "Marketing"]
# Cabeçalhos (linha 2) das colunas de metadados, em lower
META = {"ordem", "moscow", "prioridade", "entregáveis", "descrição", "consumível?",
        "cronograma mapeado", "sku", "lançamentos"}


def extrair_colunas(linha1, linha2, linha3):
    """Retorna [(idx0, tipo, categoria, responsaveis)] das colunas de entregável.

    Categoria vem da linha 1 com forward-fill; corta quando a categoria
    deixa de ser uma das válidas (ex.: '% janeiro') ou o tipo começa com '%'.
    """
    cols, categoria = [], None
    for i, tipo in enumerate(linha2):
        cab1 = linha1[i] if i < len(linha1) else None
        if isinstance(cab1, str) and cab1.strip():
            categoria = cab1.strip()
        nome = (tipo or "").strip() if isinstance(tipo, str) else ""
        if not nome or nome.lower() in META:
            continue
        if nome.startswith("%") or categoria not in CATEGORIAS_VALIDAS:
            # primeira coluna de % mensal encerra a região de entregáveis
            if categoria is not None and categoria not in CATEGORIAS_VALIDAS:
                break
            continue
        resp = linha3[i] if i < len(linha3) else None
        resp = (resp or "").strip() if isinstance(resp, str) else ""
        # normaliza quebras de linha em nomes tipo "Software\nNeutro"
        nome = " ".join(nome.split())
        cols.append((i, nome, categoria, resp))
    return cols


def carregar_planilha():
    from openpyxl import load_workbook
    wb = load_workbook(XLSM, read_only=True, data_only=True)
    ws = wb[ABA]
    linhas = list(ws.iter_rows(values_only=True))
    return linhas


def indices_metadados(linha2):
    """Mapeia cabeçalho de metadado → índice de coluna (0-based)."""
    idx = {}
    for i, v in enumerate(linha2):
        if isinstance(v, str) and v.strip().lower() in META:
            idx[v.strip().lower()] = i
    return idx


def importar(substituir=False, dry_run=False):
    os.environ.setdefault("JWT_SECRET", "import-local-secret-32-chars-xxxxxxxx")
    from servidor import app
    from models import db, Projeto, Entregavel, converter_celula

    linhas = carregar_planilha()
    l1, l2, l3 = linhas[0], linhas[1], linhas[2]
    cols = extrair_colunas(l1, l2, l3)
    meta = indices_metadados(l2)
    ignoradas = 0
    projetos = []

    for row in linhas[3:]:
        nome = row[meta["entregáveis"]] if meta.get("entregáveis") is not None else None
        if not (isinstance(nome, str) and nome.strip()):
            continue
        def mv(chave, default=""):
            i = meta.get(chave)
            v = row[i] if i is not None and i < len(row) else None
            return v if v is not None else default
        lanc = mv("lançamentos")
        if hasattr(lanc, "strftime"):
            lanc = lanc.strftime("%d/%m/%Y")
        p = dict(
            nome=" ".join(str(nome).split()),
            descricao=str(mv("descrição") or "").strip(),
            sku=str(mv("sku") or "").strip(),
            moscow=str(mv("moscow") or "").strip(),
            prioridade=int(mv("prioridade") or 0) if str(mv("prioridade") or "").strip().isdigit() else 0,
            consumivel=str(mv("consumível?") or "").strip().lower() == "sim",
            lancamento=str(lanc or "").strip(),
            entregaveis=[],
        )
        for (i, tipo, categoria, resp) in cols:
            valor = row[i] if i < len(row) else None
            status, pct = converter_celula(valor)
            if isinstance(valor, str) and valor.strip().startswith("#"):
                ignoradas += 1
            p["entregaveis"].append(dict(tipo=tipo, categoria=categoria,
                                         responsaveis=resp, status=status,
                                         percentual=pct))
        projetos.append(p)

    total_e = sum(len(p["entregaveis"]) for p in projetos)
    print(f"Planilha lida: {len(projetos)} projetos, {total_e} entregáveis, "
          f"{len(cols)} tipos de entregável, {ignoradas} células com lixo de fórmula.")
    for p in projetos:
        aplic = sum(1 for e in p["entregaveis"] if e["status"] != "na")
        print(f"  - {p['nome']}  [{p['moscow'] or '—'}]  {aplic} entregáveis aplicáveis")

    if dry_run:
        print("\n--dry-run: nada gravado.")
        return

    with app.app_context():
        db.create_all()
        existentes = Projeto.query.filter_by(ano=ANO).count()
        if existentes and not substituir:
            print(f"\nABORTADO: já existem {existentes} projetos de {ANO} no banco. "
                  f"Use --substituir para apagar e reimportar.")
            sys.exit(1)
        if existentes and substituir:
            Projeto.query.filter_by(ano=ANO).delete()
            db.session.commit()
            print(f"Projetos de {ANO} anteriores removidos.")
        for p in projetos:
            proj = Projeto(nome=p["nome"], descricao=p["descricao"], sku=p["sku"],
                           moscow=p["moscow"], prioridade=p["prioridade"],
                           consumivel=p["consumivel"], lancamento=p["lancamento"],
                           ano=ANO)
            db.session.add(proj)
            db.session.flush()
            for e in p["entregaveis"]:
                db.session.add(Entregavel(projeto_id=proj.id, **e,
                                          atualizado_por="importacao"))
        db.session.commit()
        print(f"\nOK: {len(projetos)} projetos e {total_e} entregáveis gravados no banco.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--substituir", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    importar(substituir=args.substituir, dry_run=args.dry_run)
```

- [ ] **Step 4: Rodar o teste do parser**

Run: `./venv/Scripts/python.exe -m pytest tests/test_entregaveis.py::test_extrair_colunas_entregaveis -v`
Expected: PASS

- [ ] **Step 5: Dry-run contra a planilha real**

Run: `./venv/Scripts/python.exe importar_entregaveis.py --dry-run`
Expected: resumo com ~20-40 projetos e tipos de entregável plausíveis (Validação Técnica, Protótipo, Manual do Usuário...). **Conferir visualmente os nomes e contagens.** Se categorias/colunas vierem erradas, ajustar `extrair_colunas` antes de seguir.

- [ ] **Step 6: Checkpoint local (SEM commit)**

Run: `./venv/Scripts/python.exe -m pytest -q` → tudo verde. **Não commitar.**

---

### Task 3: API — blueprint `entregaveis.py`

**Files:**
- Create: `entregaveis.py`
- Modify: `servidor.py` (registrar blueprint — ver Task 4)
- Test: `tests/test_entregaveis.py`

- [ ] **Step 1: Escrever testes de API que falham**

Adicionar a `tests/test_entregaveis.py`:

```python
# ── Fixtures locais ──────────────────────────────────────────────────────────

import pytest


@pytest.fixture
def projeto_seed(app):
    """Projeto com 3 entregáveis para testes de API."""
    from models import db, Projeto, Entregavel
    with app.app_context():
        p = Projeto(nome="Amplio Teste", sku="01.000001", moscow="Must",
                    prioridade=1, lancamento="2026", ano=2026)
        db.session.add(p)
        db.session.flush()
        db.session.add_all([
            Entregavel(projeto_id=p.id, tipo="Protótipo", categoria="Produto",
                       status="concluido", responsaveis="Julio/Diego"),
            Entregavel(projeto_id=p.id, tipo="Manual do Usuário PT", categoria="Documentação",
                       status="pendente", responsaveis="Guilherme/Melk"),
            Entregavel(projeto_id=p.id, tipo="Software Neutro", categoria="Sistema",
                       status="em_progresso", percentual=90, responsaveis="Paulo"),
        ])
        db.session.commit()
        return p.id


# ── GET /api/projetos ────────────────────────────────────────────────────────

def test_listar_projetos(client, leitura_token, auth_headers, projeto_seed):
    res = client.get("/api/projetos", headers=auth_headers(leitura_token))
    assert res.status_code == 200
    projetos = res.get_json()["projetos"]
    assert len(projetos) == 1
    p = projetos[0]
    assert p["nome"] == "Amplio Teste"
    assert p["avanco"] == 63           # (100+0+90)/3 = 63.33 → 63
    assert p["pendentes"] == 1


def test_listar_projetos_sem_token(client, projeto_seed):
    res = client.get("/api/projetos")
    assert res.status_code == 401


def test_detalhe_projeto_agrupado(client, leitura_token, auth_headers, projeto_seed):
    res = client.get(f"/api/projetos/{projeto_seed}", headers=auth_headers(leitura_token))
    assert res.status_code == 200
    body = res.get_json()
    assert body["nome"] == "Amplio Teste"
    cats = body["categorias"]
    assert [c["categoria"] for c in cats] == ["Produto", "Sistema", "Documentação"]
    assert cats[2]["entregaveis"][0]["tipo"] == "Manual do Usuário PT"


# ── PUT /api/entregaveis/<id> ────────────────────────────────────────────────

def _primeiro_entregavel_id(client, token, auth_headers, projeto_id):
    res = client.get(f"/api/projetos/{projeto_id}", headers=auth_headers(token))
    return res.get_json()["categorias"][0]["entregaveis"][0]["id"]


def test_tecnico_atualiza_entregavel(client, tecnico_token, auth_headers, projeto_seed):
    eid = _primeiro_entregavel_id(client, tecnico_token, auth_headers, projeto_seed)
    res = client.put(f"/api/entregaveis/{eid}", headers=auth_headers(tecnico_token),
                     json={"status": "em_progresso", "percentual": 40})
    assert res.status_code == 200
    body = res.get_json()
    assert body["entregavel"]["status"] == "em_progresso"
    assert body["entregavel"]["percentual"] == 40
    assert body["entregavel"]["atualizado_por"] == "tecnico@test.com"
    assert "avanco_projeto" in body


def test_leitura_nao_edita(client, leitura_token, auth_headers, projeto_seed):
    eid = _primeiro_entregavel_id(client, leitura_token, auth_headers, projeto_seed)
    res = client.put(f"/api/entregaveis/{eid}", headers=auth_headers(leitura_token),
                     json={"status": "concluido"})
    assert res.status_code == 403


def test_percentual_invalido(client, tecnico_token, auth_headers, projeto_seed):
    eid = _primeiro_entregavel_id(client, tecnico_token, auth_headers, projeto_seed)
    res = client.put(f"/api/entregaveis/{eid}", headers=auth_headers(tecnico_token),
                     json={"status": "em_progresso", "percentual": 150})
    assert res.status_code == 400


def test_status_invalido(client, tecnico_token, auth_headers, projeto_seed):
    eid = _primeiro_entregavel_id(client, tecnico_token, auth_headers, projeto_seed)
    res = client.put(f"/api/entregaveis/{eid}", headers=auth_headers(tecnico_token),
                     json={"status": "fazendo"})
    assert res.status_code == 400


def test_concluido_forca_percentual_100(client, tecnico_token, auth_headers, projeto_seed):
    eid = _primeiro_entregavel_id(client, tecnico_token, auth_headers, projeto_seed)
    res = client.put(f"/api/entregaveis/{eid}", headers=auth_headers(tecnico_token),
                     json={"status": "concluido", "percentual": 37})
    assert res.status_code == 200
    assert res.get_json()["entregavel"]["percentual"] == 100


def test_edicao_gera_audit_log(client, tecnico_token, admin_token, auth_headers, projeto_seed):
    eid = _primeiro_entregavel_id(client, tecnico_token, auth_headers, projeto_seed)
    client.put(f"/api/entregaveis/{eid}", headers=auth_headers(tecnico_token),
               json={"status": "pendente"})
    res = client.get("/api/audit?limit=10", headers=auth_headers(admin_token))
    assert res.status_code == 200
    acoes = [e.get("acao") for e in res.get_json().get("logs", res.get_json().get("entries", []))]
    assert "ENTREGAVEL_UPDATED" in acoes


# ── CRUD de projetos (admin/gestor) ──────────────────────────────────────────

def test_criar_projeto_gestor(client, gestor_token, auth_headers):
    res = client.post("/api/projetos", headers=auth_headers(gestor_token),
                      json={"nome": "Novo Produto", "moscow": "Should", "ano": 2026})
    assert res.status_code == 201
    assert res.get_json()["projeto"]["nome"] == "Novo Produto"


def test_criar_projeto_tecnico_negado(client, tecnico_token, auth_headers):
    res = client.post("/api/projetos", headers=auth_headers(tecnico_token),
                      json={"nome": "X"})
    assert res.status_code == 403


def test_arquivar_projeto(client, admin_token, auth_headers, projeto_seed):
    res = client.delete(f"/api/projetos/{projeto_seed}", headers=auth_headers(admin_token))
    assert res.status_code == 200
    # some da listagem padrão
    res = client.get("/api/projetos", headers=auth_headers(admin_token))
    assert res.get_json()["projetos"] == []


# ── Resumo e export ──────────────────────────────────────────────────────────

def test_resumo(client, leitura_token, auth_headers, projeto_seed):
    res = client.get("/api/entregaveis/resumo", headers=auth_headers(leitura_token))
    assert res.status_code == 200
    body = res.get_json()
    assert body["projetos"] == 1
    assert body["pendentes"] == 1
    assert body["concluidos"] == 1
    assert "Guilherme/Melk" in body["por_responsavel"]


def test_export_excel(client, leitura_token, auth_headers, projeto_seed):
    res = client.get("/api/entregaveis/export", headers=auth_headers(leitura_token))
    assert res.status_code == 200
    assert res.content_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    # arquivo xlsx começa com assinatura PK (zip)
    assert res.data[:2] == b"PK"
```

> Nota sobre `test_edicao_gera_audit_log`: confira no `servidor.py` (rota `/api/audit`, linha ~853) qual é a chave do JSON de resposta (`logs` ou `entries`) e simplifique o assert para a chave correta.

- [ ] **Step 2: Rodar e confirmar falha (404 em tudo)**

Run: `./venv/Scripts/python.exe -m pytest tests/test_entregaveis.py -v`
Expected: testes novos FAIL com 404 (rotas não existem)

- [ ] **Step 3: Criar `entregaveis.py`**

```python
"""
entregaveis.py — Módulo de Entregáveis por Projeto
Rotas:
  GET    /api/projetos                — lista com avanço calculado + filtros
  POST   /api/projetos                — criar (admin/gestor)
  GET    /api/projetos/<id>           — detalhe agrupado por categoria
  PUT    /api/projetos/<id>           — editar metadados (admin/gestor)
  DELETE /api/projetos/<id>           — arquivar (admin/gestor)
  PUT    /api/entregaveis/<id>        — atualizar status/percentual/responsáveis (tecnico+)
  POST   /api/projetos/<id>/entregaveis — adicionar entregável (admin/gestor)
  GET    /api/entregaveis/resumo      — KPIs e visão por responsável
  GET    /api/entregaveis/export      — Excel limpo
"""
import io
from datetime import datetime

from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import get_jwt_identity

from models import (db, Projeto, Entregavel, CATEGORIAS_ENTREGAVEL,
                    STATUS_ENTREGAVEL, MOSCOW)
from auth import require_role, log_action, get_client_ip

entregaveis_bp = Blueprint("entregaveis", __name__)

# preenchido por servidor.py para emitir tempo real sem import circular
_rt = {"socketio": None, "publish_event": None, "AuditLog": None, "EventType": None}


def init_realtime(socketio, publish_event, AuditLog, EventType):
    _rt.update(socketio=socketio, publish_event=publish_event,
               AuditLog=AuditLog, EventType=EventType)


def _emit(event_type, payload, email):
    if _rt["socketio"] and _rt["publish_event"]:
        try:
            _rt["publish_event"](event_type, payload, user_email=email,
                                 db=db, AuditLog=_rt["AuditLog"],
                                 socketio=_rt["socketio"])
        except Exception:
            pass  # tempo real é best-effort; a gravação já foi feita


# ── PROJETOS ─────────────────────────────────────────────────────────────────

@entregaveis_bp.route("/api/projetos", methods=["GET"])
@require_role("admin", "gestor", "tecnico", "leitura")
def listar_projetos():
    q = Projeto.query.filter_by(ativo=True)
    ano = request.args.get("ano", type=int)
    if ano:
        q = q.filter_by(ano=ano)
    moscow = request.args.get("moscow", "").strip()
    if moscow:
        q = q.filter(Projeto.moscow.ilike(moscow))
    busca = request.args.get("busca", "").strip()
    if busca:
        q = q.filter(Projeto.nome.ilike(f"%{busca}%"))
    projetos = q.all()
    resp = request.args.get("responsavel", "").strip().lower()
    out = []
    for p in projetos:
        d = p.to_dict()
        if resp:
            tipos = [e.to_dict() for e in p.entregaveis
                     if resp in (e.responsaveis or "").lower() and e.status != "na"]
            if not tipos:
                continue
            d["entregaveis_do_responsavel"] = tipos
        out.append(d)
    out.sort(key=lambda d: (d["prioridade"] or 999, d["nome"]))
    return jsonify({"projetos": out})


@entregaveis_bp.route("/api/projetos", methods=["POST"])
@require_role("admin", "gestor")
def criar_projeto():
    data = request.get_json(silent=True) or {}
    nome = (data.get("nome") or "").strip()
    if not nome:
        return jsonify({"erro": "nome é obrigatório"}), 400
    moscow = (data.get("moscow") or "").strip()
    if moscow and moscow not in MOSCOW:
        return jsonify({"erro": f"moscow inválido. Use: {', '.join(MOSCOW)}"}), 400
    p = Projeto(
        nome=nome,
        descricao=(data.get("descricao") or "").strip(),
        sku=(data.get("sku") or "").strip(),
        moscow=moscow,
        prioridade=int(data.get("prioridade") or 0),
        consumivel=bool(data.get("consumivel")),
        lancamento=(data.get("lancamento") or "").strip(),
        ano=int(data.get("ano") or datetime.now().year),
    )
    db.session.add(p)
    db.session.commit()
    email = get_jwt_identity()
    log_action(email, "CREATE", entidade=f"Projeto:{p.nome}", ip=get_client_ip())
    _emit("PROJETO_CREATED", {"projeto": p.to_dict()}, email)
    return jsonify({"projeto": p.to_dict()}), 201


@entregaveis_bp.route("/api/projetos/<int:pid>", methods=["GET"])
@require_role("admin", "gestor", "tecnico", "leitura")
def detalhe_projeto(pid):
    p = Projeto.query.get_or_404(pid)
    grupos = {c: [] for c in CATEGORIAS_ENTREGAVEL}
    extras = {}
    for e in p.entregaveis:
        (grupos if e.categoria in grupos else extras).setdefault(e.categoria, [])
        (grupos.get(e.categoria) if e.categoria in grupos
         else extras[e.categoria]).append(e.to_dict())
    categorias = [{"categoria": c, "entregaveis": grupos[c]}
                  for c in CATEGORIAS_ENTREGAVEL if grupos[c]]
    categorias += [{"categoria": c, "entregaveis": v} for c, v in extras.items()]
    d = p.to_dict()
    d["categorias"] = categorias
    return jsonify(d)


@entregaveis_bp.route("/api/projetos/<int:pid>", methods=["PUT"])
@require_role("admin", "gestor")
def editar_projeto(pid):
    p = Projeto.query.get_or_404(pid)
    data = request.get_json(silent=True) or {}
    email = get_jwt_identity()
    for campo in ("nome", "descricao", "sku", "moscow", "lancamento"):
        if campo in data:
            novo = (data.get(campo) or "").strip()
            antigo = getattr(p, campo) or ""
            if campo == "moscow" and novo and novo not in MOSCOW:
                return jsonify({"erro": "moscow inválido"}), 400
            if campo == "nome" and not novo:
                return jsonify({"erro": "nome não pode ficar vazio"}), 400
            if novo != antigo:
                setattr(p, campo, novo)
                log_action(email, "UPDATE", entidade=f"Projeto:{p.nome}",
                           campo=campo, antigo=antigo, novo=novo, ip=get_client_ip())
    if "prioridade" in data:
        p.prioridade = int(data.get("prioridade") or 0)
    if "consumivel" in data:
        p.consumivel = bool(data.get("consumivel"))
    db.session.commit()
    _emit("PROJETO_UPDATED", {"projeto": p.to_dict()}, email)
    return jsonify({"projeto": p.to_dict()})


@entregaveis_bp.route("/api/projetos/<int:pid>", methods=["DELETE"])
@require_role("admin", "gestor")
def arquivar_projeto(pid):
    p = Projeto.query.get_or_404(pid)
    p.ativo = False
    db.session.commit()
    email = get_jwt_identity()
    log_action(email, "DELETE", entidade=f"Projeto:{p.nome}", ip=get_client_ip())
    _emit("PROJETO_UPDATED", {"projeto": p.to_dict()}, email)
    return jsonify({"ok": True})


# ── ENTREGÁVEIS ──────────────────────────────────────────────────────────────

@entregaveis_bp.route("/api/entregaveis/<int:eid>", methods=["PUT"])
@require_role("admin", "gestor", "tecnico")
def atualizar_entregavel(eid):
    e = Entregavel.query.get_or_404(eid)
    data = request.get_json(silent=True) or {}
    email = get_jwt_identity()
    mudancas = []

    if "status" in data:
        novo = (data.get("status") or "").strip()
        if novo not in STATUS_ENTREGAVEL:
            return jsonify({"erro": f"status inválido. Use: {', '.join(STATUS_ENTREGAVEL)}"}), 400
        if novo != e.status:
            mudancas.append(("status", e.status, novo))
            e.status = novo
        if novo == "concluido":
            e.percentual = 100
        elif novo in ("pendente", "na"):
            e.percentual = 0 if novo == "pendente" else None

    if "percentual" in data and e.status == "em_progresso":
        try:
            pct = int(data.get("percentual"))
        except (TypeError, ValueError):
            return jsonify({"erro": "percentual deve ser número"}), 400
        if not (0 <= pct <= 100):
            return jsonify({"erro": "percentual deve estar entre 0 e 100"}), 400
        if pct != e.percentual:
            mudancas.append(("percentual", e.percentual, pct))
            e.percentual = pct

    if "responsaveis" in data:
        novo = (data.get("responsaveis") or "").strip()
        if novo != (e.responsaveis or ""):
            mudancas.append(("responsaveis", e.responsaveis, novo))
            e.responsaveis = novo

    e.atualizado_por = email
    e.atualizado_em = datetime.now()
    db.session.commit()

    for campo, antigo, novo in mudancas:
        log_action(email, "ENTREGAVEL_UPDATED",
                   entidade=f"{e.projeto.nome} · {e.tipo}",
                   campo=campo, antigo=antigo, novo=novo, ip=get_client_ip())
    _emit("ENTREGAVEL_UPDATED",
          {"entregavel": e.to_dict(), "projeto_id": e.projeto_id,
           "avanco_projeto": e.projeto.avanco}, email)
    return jsonify({"entregavel": e.to_dict(), "avanco_projeto": e.projeto.avanco})


@entregaveis_bp.route("/api/projetos/<int:pid>/entregaveis", methods=["POST"])
@require_role("admin", "gestor")
def adicionar_entregavel(pid):
    p = Projeto.query.get_or_404(pid)
    data = request.get_json(silent=True) or {}
    tipo = (data.get("tipo") or "").strip()
    if not tipo:
        return jsonify({"erro": "tipo é obrigatório"}), 400
    categoria = (data.get("categoria") or "Produto").strip()
    e = Entregavel(projeto_id=p.id, tipo=tipo, categoria=categoria,
                   status=(data.get("status") or "pendente"),
                   responsaveis=(data.get("responsaveis") or "").strip(),
                   atualizado_por=get_jwt_identity())
    db.session.add(e)
    db.session.commit()
    return jsonify({"entregavel": e.to_dict()}), 201


# ── RESUMO ───────────────────────────────────────────────────────────────────

@entregaveis_bp.route("/api/entregaveis/resumo", methods=["GET"])
@require_role("admin", "gestor", "tecnico", "leitura")
def resumo():
    projetos = Projeto.query.filter_by(ativo=True).all()
    pend = conc = prog = 0
    por_resp = {}
    for p in projetos:
        for e in p.entregaveis:
            if e.status == "pendente":
                pend += 1
            elif e.status == "concluido":
                conc += 1
            elif e.status == "em_progresso":
                prog += 1
            if e.status in ("pendente", "em_progresso") and e.responsaveis:
                por_resp.setdefault(e.responsaveis, []).append(
                    {"projeto": p.nome, "tipo": e.tipo, "status": e.status,
                     "percentual": e.percentual, "id": e.id})
    avancos = [p.avanco for p in projetos]
    return jsonify({
        "projetos": len(projetos),
        "avanco_medio": round(sum(avancos) / len(avancos)) if avancos else 0,
        "pendentes": pend, "em_progresso": prog, "concluidos": conc,
        "por_responsavel": por_resp,
    })


# ── EXPORT EXCEL ─────────────────────────────────────────────────────────────

@entregaveis_bp.route("/api/entregaveis/export", methods=["GET"])
@require_role("admin", "gestor", "tecnico", "leitura")
def exportar_excel():
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    projetos = (Projeto.query.filter_by(ativo=True)
                .order_by(Projeto.prioridade, Projeto.nome).all())
    # união ordenada de tipos (categoria, tipo) preservando ordem de aparição
    tipos = []
    for p in projetos:
        for e in p.entregaveis:
            chave = (e.categoria, e.tipo)
            if chave not in tipos:
                tipos.append(chave)

    wb = Workbook()
    ws = wb.active
    ws.title = "Entregáveis 2026"
    CORES = {"concluido": "C6EFCE", "em_progresso": "FFEB9C",
             "pendente": "FFC7CE", "na": "D9D9D9"}
    cab = Font(bold=True, color="FFFFFF")
    azul = PatternFill("solid", fgColor="1F4E5F")

    headers = ["Projeto", "MoSCoW", "SKU", "Lançamento", "Avanço %"] + \
              [f"{t}\n({c})" for c, t in tipos]
    for j, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=j, value=h)
        cell.font = cab
        cell.fill = azul
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for i, p in enumerate(projetos, 2):
        ws.cell(row=i, column=1, value=p.nome).font = Font(bold=True)
        ws.cell(row=i, column=2, value=p.moscow)
        ws.cell(row=i, column=3, value=p.sku)
        ws.cell(row=i, column=4, value=p.lancamento)
        ws.cell(row=i, column=5, value=p.avanco)
        mapa = {(e.categoria, e.tipo): e for e in p.entregaveis}
        for j, chave in enumerate(tipos, 6):
            e = mapa.get(chave)
            if e is None:
                continue
            if e.status == "concluido":
                v = "OK"
            elif e.status == "em_progresso":
                v = f"{e.percentual or 0}%"
            elif e.status == "pendente":
                v = "Pendente"
            else:
                v = "NA"
            cell = ws.cell(row=i, column=j, value=v)
            cell.fill = PatternFill("solid", fgColor=CORES[e.status])
            cell.alignment = Alignment(horizontal="center")
    ws.column_dimensions["A"].width = 24
    for j in range(2, len(headers) + 1):
        ws.column_dimensions[get_column_letter(j)].width = 13
    ws.freeze_panes = "B2"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    nome = f"Entregaveis_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return send_file(
        buf, as_attachment=True, download_name=nome,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
```

- [ ] **Step 4: Registrar o blueprint (mínimo para os testes passarem)**

Em `servidor.py`, logo após `app.register_blueprint(auth_bp)` (linha ~66):

```python
from entregaveis import entregaveis_bp, init_realtime as entregaveis_init_realtime
app.register_blueprint(entregaveis_bp)
```

E logo APÓS a criação do `socketio` (depois do bloco `socketio = SocketIO(...)`):

```python
entregaveis_init_realtime(socketio, publish_event, AuditLog, EventType)
```

> `EventType` é uma classe de constantes string; passar nomes novos ("ENTREGAVEL_UPDATED") como string literal funciona porque `publish_event` recebe `event_type: str`. Opcionalmente adicione em `event_bus.py` dentro de `class EventType`: `ENTREGAVEL_UPDATED = "ENTREGAVEL_UPDATED"` e `PROJETO_CREATED = "PROJETO_CREATED"` e `PROJETO_UPDATED = "PROJETO_UPDATED"` — preferível para manter o padrão "use SEMPRE estas constantes".

- [ ] **Step 5: Rodar os testes**

Run: `./venv/Scripts/python.exe -m pytest tests/test_entregaveis.py -v`
Expected: todos PASS. Se `test_edicao_gera_audit_log` falhar na chave do JSON, ajustar o assert à resposta real de `/api/audit`.

- [ ] **Step 6: Suíte inteira + checkpoint local (SEM commit)**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: tudo verde. **Não commitar.**

---

### Task 4: Rota da página `/entregaveis` em `servidor.py`

**Files:**
- Modify: `servidor.py` (perto da rota `/`, linha ~315)
- Test: `tests/test_entregaveis.py`

- [ ] **Step 1: Teste que falha**

Adicionar a `tests/test_entregaveis.py`:

```python
def test_pagina_entregaveis(client):
    res = client.get("/entregaveis")
    assert res.status_code == 200
    assert b"Entreg" in res.data
```

Run: `./venv/Scripts/python.exe -m pytest tests/test_entregaveis.py::test_pagina_entregaveis -v` → FAIL (404)

- [ ] **Step 2: Adicionar a rota**

Em `servidor.py`, logo após a rota `/` (linha ~317):

```python
@app.route("/entregaveis")
def entregaveis_page():
    return render_template("entregaveis.html", asset_v=_static_version())
```

- [ ] **Step 3: Criar `templates/entregaveis.html` mínimo provisório** (será completado na Task 5)

```html
<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="UTF-8"><title>Entregáveis — DocTrack</title></head>
<body>Entregáveis</body>
</html>
```

- [ ] **Step 4: Rodar o teste**

Run: `./venv/Scripts/python.exe -m pytest tests/test_entregaveis.py::test_pagina_entregaveis -v`
Expected: PASS

---

### Task 5: Frontend — página completa (cards + drill-down + edição)

**Files:**
- Rewrite: `templates/entregaveis.html`
- Create: `static/entregaveis.css`
- Create: `static/entregaveis.js`
- Modify: `templates/dashboard.html` (link no header)

Sem testes automatizados de UI; verificação via preview (Step 4). O JS reusa o padrão de auth do `static/app.js`: token em `localStorage.doctrack_token`, fetch com header `Authorization: Bearer`.

- [ ] **Step 1: `templates/entregaveis.html` (versão completa)**

```html
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Entregáveis — DocTrack</title>
  <link rel="stylesheet" href="/static/style.css?v={{ asset_v }}">
  <link rel="stylesheet" href="/static/entregaveis.css?v={{ asset_v }}">
</head>
<body>
  <div class="app-shell" style="display:block">
    <main class="main" style="margin:0;max-width:1280px;padding:24px;margin-inline:auto">

      <div class="page-header" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px">
        <div>
          <h1 style="margin:0">Entregáveis por Projeto</h1>
          <p class="muted" style="margin:4px 0 0">Engenharia · 2026</p>
        </div>
        <div class="page-actions" style="display:flex;gap:10px;align-items:center">
          <a class="btn btn-ghost btn-sm" href="/">← Dashboard</a>
          <button class="btn btn-primary btn-sm" id="btn-export" onclick="exportarExcel()">Exportar Excel</button>
        </div>
      </div>

      <div class="kpi-grid" id="ent-kpis" style="margin-top:18px">
        <div class="loading-state" style="grid-column:1/-1"><div class="spinner"></div>Carregando…</div>
      </div>

      <div class="card" style="margin-top:14px">
        <div class="filter-bar" style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
          <input class="input" id="f-busca" placeholder="Buscar projeto…" oninput="aplicarFiltros()" style="max-width:220px">
          <select class="input" id="f-moscow" onchange="aplicarFiltros()" style="max-width:140px">
            <option value="">MoSCoW: todos</option>
            <option>Must</option><option>Should</option><option>Could</option>
          </select>
          <select class="input" id="f-resp" onchange="aplicarFiltros()" style="max-width:200px">
            <option value="">Responsável: todos</option>
          </select>
          <select class="input" id="f-ordem" onchange="aplicarFiltros()" style="max-width:180px">
            <option value="prioridade">Ordenar: prioridade</option>
            <option value="avanco">Ordenar: avanço</option>
            <option value="nome">Ordenar: nome</option>
          </select>
          <span class="filter-count" id="proj-badge" style="margin-left:auto">—</span>
        </div>
      </div>

      <div id="cards-grid" class="ent-grid"></div>

      <!-- Drill-down -->
      <div id="detalhe" class="ent-detalhe" style="display:none">
        <button class="btn btn-ghost btn-sm" onclick="fecharDetalhe()">← Voltar aos projetos</button>
        <div class="card" style="margin-top:12px">
          <div id="detalhe-header"></div>
          <div id="detalhe-grupos"></div>
        </div>
      </div>

    </main>
  </div>

  <!-- Popover de edição -->
  <div id="edit-pop" class="ent-pop" style="display:none">
    <div class="ent-pop-card">
      <h3 id="pop-titulo" style="margin:0 0 10px"></h3>
      <label class="muted">Status</label>
      <select class="input" id="pop-status" onchange="popStatusChange()">
        <option value="na">N/A</option>
        <option value="pendente">Pendente</option>
        <option value="em_progresso">Em progresso</option>
        <option value="concluido">Concluído</option>
      </select>
      <div id="pop-pct-wrap" style="margin-top:8px">
        <label class="muted">Percentual: <b id="pop-pct-val">0%</b></label>
        <input type="range" id="pop-pct" min="0" max="100" step="5" style="width:100%"
               oninput="document.getElementById('pop-pct-val').textContent=this.value+'%'">
      </div>
      <label class="muted" style="margin-top:8px;display:block">Responsáveis</label>
      <input class="input" id="pop-resp" placeholder="Ex.: Guilherme/Melk" style="width:100%">
      <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:14px">
        <button class="btn btn-ghost btn-sm" onclick="fecharPop()">Cancelar</button>
        <button class="btn btn-primary btn-sm" onclick="salvarPop()">Salvar</button>
      </div>
    </div>
  </div>

  <div id="toast" class="toast" style="display:none"></div>
  <script src="/static/entregaveis.js?v={{ asset_v }}"></script>
</body>
</html>
```

> Conferir os nomes de classe (`btn`, `input`, `card`, `kpi-grid`, `filter-count`, `toast`, `muted`) contra `static/style.css` — se algum não existir, definir o equivalente em `entregaveis.css`.

- [ ] **Step 2: `static/entregaveis.css`**

```css
/* ═══ MÓDULO ENTREGÁVEIS ═══ */
.ent-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:14px;margin-top:16px}
.ent-card{background:var(--card,#0f1822);border:1px solid var(--border,#1d2a38);border-radius:12px;
  padding:16px;cursor:pointer;transition:transform .15s,border-color .15s}
.ent-card:hover{transform:translateY(-2px);border-color:#22d3ee66}
.ent-card h3{margin:0 0 4px;font-size:15px}
.ent-card .meta{font-size:12px;color:#7d8da0;display:flex;gap:10px;flex-wrap:wrap}
.ent-badge{font-size:10px;font-weight:700;border-radius:5px;padding:2px 7px;letter-spacing:.4px}
.ent-badge.must{background:#ef444422;color:#f87171}
.ent-badge.should{background:#f59e0b22;color:#fbbf24}
.ent-badge.could{background:#3b82f622;color:#60a5fa}
.ent-bar{background:#1d2a38;border-radius:6px;height:8px;margin:10px 0 6px;overflow:hidden}
.ent-bar>i{display:block;height:100%;border-radius:6px;background:linear-gradient(90deg,#0891b2,#22d3ee)}
.ent-bar.warn>i{background:linear-gradient(90deg,#b45309,#fbbf24)}
.ent-bar.low>i{background:linear-gradient(90deg,#b91c1c,#f87171)}
.ent-row{display:flex;justify-content:space-between;align-items:center;gap:10px;
  padding:8px 10px;border-bottom:1px solid #1d2a3866;border-radius:6px;cursor:pointer}
.ent-row:hover{background:#22d3ee0d}
.ent-row .quem{font-size:12px;color:#7d8da0}
.ent-status{font-size:11px;font-weight:700;border-radius:5px;padding:2px 8px;white-space:nowrap}
.ent-status.na{background:#64748b22;color:#94a3b8}
.ent-status.pendente{background:#ef444422;color:#f87171}
.ent-status.em_progresso{background:#f59e0b22;color:#fbbf24}
.ent-status.concluido{background:#22c55e22;color:#4ade80}
.ent-cat-title{font-size:11px;font-weight:700;letter-spacing:1.2px;color:#22d3ee;
  text-transform:uppercase;margin:18px 0 6px}
.ent-pop{position:fixed;inset:0;background:#0009;display:flex;align-items:center;
  justify-content:center;z-index:60}
.ent-pop-card{background:#0f1822;border:1px solid #22d3ee44;border-radius:14px;
  padding:20px;width:min(380px,92vw)}
.ent-detalhe .donut-mini{width:84px;height:84px}
@media (max-width:640px){.ent-grid{grid-template-columns:1fr}}
```

- [ ] **Step 3: `static/entregaveis.js`**

```javascript
/* Entregáveis por Projeto — lógica da página */
const TOKEN_KEY = "doctrack_token";
let _projetos = [], _detalheId = null, _popEntregavel = null;

function token(){ return localStorage.getItem(TOKEN_KEY) || ""; }

async function api(url, opts={}){
  const res = await fetch(url, {...opts, headers: {
    "Content-Type": "application/json",
    "Authorization": "Bearer " + token(),
    ...(opts.headers||{})
  }});
  if (res.status === 401){ window.location.href = "/"; throw new Error("401"); }
  if (!res.ok){
    const body = await res.json().catch(()=>({}));
    throw new Error(body.erro || ("HTTP " + res.status));
  }
  return res.json();
}

function toast(msg, erro=false){
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.style.display = "block";
  t.style.borderColor = erro ? "#ef4444" : "#22d3ee";
  clearTimeout(t._h); t._h = setTimeout(()=> t.style.display="none", 3000);
}

function esc(s){ const d=document.createElement("div"); d.textContent=s??""; return d.innerHTML; }

/* ── KPIs ── */
async function loadKpis(){
  const r = await api("/api/entregaveis/resumo");
  const box = document.getElementById("ent-kpis");
  box.innerHTML = [
    ["Projetos ativos", r.projetos],
    ["Avanço médio", r.avanco_medio + "%"],
    ["Em progresso", r.em_progresso],
    ["Pendentes", r.pendentes],
    ["Concluídos", r.concluidos],
  ].map(([l,v]) => `<div class="card kpi"><div class="kpi-val">${v}</div><div class="kpi-lbl">${l}</div></div>`).join("");
  // popular filtro de responsáveis a partir do resumo
  const sel = document.getElementById("f-resp");
  const atual = sel.value;
  const nomes = new Set();
  Object.keys(r.por_responsavel||{}).forEach(grupo =>
    grupo.split("/").forEach(n => nomes.add(n.trim())));
  sel.innerHTML = '<option value="">Responsável: todos</option>' +
    [...nomes].sort().map(n=>`<option ${n===atual?"selected":""}>${esc(n)}</option>`).join("");
}

/* ── Cards ── */
async function loadProjetos(){
  const busca  = document.getElementById("f-busca").value.trim();
  const moscow = document.getElementById("f-moscow").value;
  const resp   = document.getElementById("f-resp").value;
  const qs = new URLSearchParams();
  if (busca)  qs.set("busca", busca);
  if (moscow) qs.set("moscow", moscow);
  if (resp)   qs.set("responsavel", resp);
  const data = await api("/api/projetos?" + qs.toString());
  _projetos = data.projetos;
  renderCards();
}

function renderCards(){
  const ordem = document.getElementById("f-ordem").value;
  const lista = [..._projetos];
  if (ordem === "avanco") lista.sort((a,b)=> a.avanco - b.avanco);
  if (ordem === "nome")   lista.sort((a,b)=> a.nome.localeCompare(b.nome));
  document.getElementById("proj-badge").textContent = lista.length + " projetos";
  const grid = document.getElementById("cards-grid");
  grid.innerHTML = lista.map(p => {
    const cls = p.avanco >= 70 ? "" : p.avanco >= 35 ? "warn" : "low";
    const badge = p.moscow ? `<span class="ent-badge ${p.moscow.toLowerCase()}">${esc(p.moscow.toUpperCase())}</span>` : "";
    return `<div class="ent-card" onclick="abrirDetalhe(${p.id})">
      <h3>${esc(p.nome)} ${badge}</h3>
      <div class="meta">
        ${p.sku ? "SKU " + esc(p.sku) : ""}
        ${p.lancamento ? "· Lançamento " + esc(p.lancamento) : ""}
      </div>
      <div class="ent-bar ${cls}"><i style="width:${p.avanco}%"></i></div>
      <div class="meta" style="justify-content:space-between">
        <span><b style="color:#e2e8f0">${p.avanco}%</b> concluído</span>
        <span>${p.pendentes} pendente${p.pendentes===1?"":"s"}</span>
      </div>
    </div>`;
  }).join("") || '<p class="muted" style="grid-column:1/-1">Nenhum projeto encontrado.</p>';
}

function aplicarFiltros(){ loadProjetos().catch(e=>toast(e.message,true)); }

/* ── Drill-down ── */
async function abrirDetalhe(id){
  _detalheId = id;
  const p = await api("/api/projetos/" + id);
  document.getElementById("cards-grid").style.display = "none";
  document.querySelector(".filter-bar").parentElement.style.display = "none";
  document.getElementById("detalhe").style.display = "block";
  document.getElementById("detalhe-header").innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
      <div>
        <h2 style="margin:0">${esc(p.nome)}</h2>
        <p class="muted" style="margin:4px 0 0">${esc(p.descricao||"")}
          ${p.sku ? " · SKU " + esc(p.sku) : ""} ${p.lancamento ? " · Lançamento " + esc(p.lancamento) : ""}</p>
      </div>
      <div style="text-align:right">
        <div style="font-size:28px;font-weight:800;color:#22d3ee" id="det-avanco">${p.avanco}%</div>
        <div class="muted" style="font-size:12px">avanço geral</div>
      </div>
    </div>`;
  document.getElementById("detalhe-grupos").innerHTML = p.categorias.map(c => `
    <div class="ent-cat-title">${esc(c.categoria)}</div>
    ${c.entregaveis.map(e => entRowHtml(e)).join("")}
  `).join("");
}

function entRowHtml(e){
  const stTxt = {na:"N/A", pendente:"Pendente",
    em_progresso:(e.percentual??0)+"%", concluido:"Concluído"}[e.status];
  return `<div class="ent-row" id="ent-${e.id}" onclick='abrirPop(${JSON.stringify(e).replace(/'/g,"&#39;")})'>
    <span>${esc(e.tipo)}</span>
    <span class="quem">${esc(e.responsaveis||"—")}
      <span class="ent-status ${e.status}">${stTxt}</span></span>
  </div>`;
}

function fecharDetalhe(){
  _detalheId = null;
  document.getElementById("detalhe").style.display = "none";
  document.getElementById("cards-grid").style.display = "";
  document.querySelector(".filter-bar").parentElement.style.display = "";
  loadProjetos().catch(()=>{});
  loadKpis().catch(()=>{});
}

/* ── Popover de edição ── */
function abrirPop(e){
  _popEntregavel = e;
  document.getElementById("pop-titulo").textContent = e.tipo;
  document.getElementById("pop-status").value = e.status;
  document.getElementById("pop-pct").value = e.percentual ?? 0;
  document.getElementById("pop-pct-val").textContent = (e.percentual ?? 0) + "%";
  document.getElementById("pop-resp").value = e.responsaveis || "";
  popStatusChange();
  document.getElementById("edit-pop").style.display = "flex";
}
function popStatusChange(){
  const st = document.getElementById("pop-status").value;
  document.getElementById("pop-pct-wrap").style.display =
    st === "em_progresso" ? "block" : "none";
}
function fecharPop(){ document.getElementById("edit-pop").style.display = "none"; _popEntregavel = null; }

async function salvarPop(){
  if (!_popEntregavel) return;
  const payload = {
    status: document.getElementById("pop-status").value,
    responsaveis: document.getElementById("pop-resp").value.trim(),
  };
  if (payload.status === "em_progresso")
    payload.percentual = parseInt(document.getElementById("pop-pct").value, 10);
  try{
    const r = await api("/api/entregaveis/" + _popEntregavel.id, {
      method: "PUT", body: JSON.stringify(payload)});
    toast("Entregável atualizado");
    fecharPop();
    if (_detalheId) abrirDetalhe(_detalheId);
  }catch(err){ toast(err.message, true); }
}

/* ── Export ── */
async function exportarExcel(){
  try{
    const res = await fetch("/api/entregaveis/export", {
      headers: {"Authorization": "Bearer " + token()}});
    if (!res.ok) throw new Error("Falha no export (HTTP " + res.status + ")");
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "Entregaveis.xlsx";
    a.click();
    URL.revokeObjectURL(a.href);
  }catch(err){ toast(err.message, true); }
}

/* ── Init ── */
(async function init(){
  if (!token()){ window.location.href = "/"; return; }
  try{
    await Promise.all([loadKpis(), loadProjetos()]);
  }catch(e){ toast(e.message, true); }
})();
```

> Validar com `node --check static/entregaveis.js` (atenção ao template literal dentro de `onclick` com `JSON.stringify` — já escapado com `&#39;`).

- [ ] **Step 4: Link no dashboard**

Em `templates/dashboard.html`, na `page-actions` do header principal (linha ~102), adicionar antes do badge:

```html
<a class="btn btn-ghost btn-sm" href="/entregaveis">📋 Entregáveis</a>
```

- [ ] **Step 5: Verificação no preview**

1. Garantir dados: rodar `./venv/Scripts/python.exe importar_entregaveis.py` (sem `--dry-run`; se o banco já tiver dados de teste anteriores, usar `--substituir`).
2. Iniciar preview (`preview_start` no servidor Flask) e navegar para `/entregaveis`.
3. Logar antes em `/` (admin@pde.com / admin123) para ter token no localStorage; depois abrir `/entregaveis`.
4. Conferir: KPIs preenchidos, cards com barras, clique → drill-down agrupado, popover salva e a barra atualiza, filtro por responsável funciona, "Exportar Excel" baixa arquivo.
5. `preview_console_logs` sem erros.

- [ ] **Step 6: Checkpoint local (SEM commit)**

Run: `./venv/Scripts/python.exe -m pytest -q` → tudo verde. `node --check static/entregaveis.js` → OK. **Não commitar.**

---

### Task 6: Importação real + verificação final

**Files:** nenhum novo — execução e conferência.

- [ ] **Step 1: Backup do banco**

```powershell
Copy-Item doctrack.db ("doctrack.db.backup-entregaveis-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
```

- [ ] **Step 2: Importar de verdade**

Run: `./venv/Scripts/python.exe importar_entregaveis.py` (ou `--substituir` se a Task 5 já importou)
Expected: "OK: N projetos e M entregáveis gravados no banco."

- [ ] **Step 3: Conferência cruzada com a planilha**

Escolher 2 projetos (ex.: "Librarian 340" e "Amplio® Station 64") e comparar célula a célula alguns entregáveis no drill-down contra a planilha aberta. Status e percentuais devem bater com a conversão (1→Concluído, 0.5→50%, NA→N/A).

- [ ] **Step 4: Suíte completa final**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: tudo verde.

- [ ] **Step 5: Relatar ao usuário**

Resumo do que foi construído + URL `http://192.168.0.75:5000/entregaveis` + lembrete: **nada foi commitado**; quando validar, fazemos um commit único do módulo.

---

## Self-review (feito na escrita do plano)

- **Cobertura do spec:** modelo ✔ (Task 1) · importação ✔ (Task 2/6) · API+permissões+auditoria+tempo real ✔ (Task 3) · página/rota ✔ (Task 4) · UI cards+drill-down+popover+filtros+export ✔ (Task 5) · testes ✔ (1–4) · restrição "sem git" ✔ (todos os checkpoints).
- **Sem placeholders:** todo step com código completo.
- **Consistência de tipos:** `converter_celula` retorna tupla `(status, pct)`; `Projeto.avanco`/`pendentes` usados na API e nos testes; `init_realtime` chamado no servidor com a mesma assinatura definida no blueprint.
- **Fora de escopo respeitado:** sem sync contínuo, sem vínculo usuário↔responsável, sem outras abas.

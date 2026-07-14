# Escopo de documentos por equipamento (N/A) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir marcar, por equipamento, quais tipos de documento se aplicam ou não (N/A reversível), e fazer toda a completude (card, chips, KPIs, IDP) contar apenas os aplicáveis.

**Architecture:** Duas colunas novas em `documentos` (`aplicavel`, `motivo_na`). Todo equipamento passa a nascer com os 12 tipos — os 9 de hoje aplicáveis, os 3 opcionais em N/A. Uma rota dedicada (`PUT /api/documentos/<id>/aplicabilidade`, admin/gestor) vira o bit; todo cálculo de completude passa a filtrar por `aplicavel`. No front, a aba "+ Adicionar" do modal do equipamento vira a aba **Escopo**.

**Tech Stack:** Flask + SQLAlchemy (SQLite local / Postgres em produção), JS vanilla, pytest.

**Spec:** `docs/superpowers/specs/2026-07-14-escopo-documentos-por-equipamento-design.md`

---

## Estrutura de arquivos

| Arquivo | Responsabilidade nesta mudança |
| --- | --- |
| `models.py` | Colunas `aplicavel`/`motivo_na`, `to_dict()`, renomear `TIPOS_DOC_AUTO` → `TIPOS_DOC_PADRAO_APLICAVEL` |
| `servidor.py` | Migração de schema, `_ensure_docs_for_equip` (12 tipos), `_migrar_taxonomia_docs` (reativar opcionais ocultados como N/A), `compute_kpis` |
| `documentos.py` | Criação dos 12 tipos + rota `PUT /api/documentos/<id>/aplicabilidade` |
| `static/app.js` | Aba Escopo, cor do card, chips, abas do modal |
| `static/style.css` | Estilos da lista de escopo |
| `static/equipamentos.js` | IDP respeita o N/A dos documentos |
| `tests/test_taxonomia_docs.py` | Escopo padrão dos 12 tipos, migração |
| `tests/test_documentos.py` | Rota de aplicabilidade (permissão, reversibilidade), KPIs |

---

### Task 1: Colunas `aplicavel` / `motivo_na` no modelo

**Files:**
- Modify: `models.py:188-276` (classe `Documento`)
- Modify: `servidor.py:1503-1505` (`novas_colunas["documentos"]`)
- Test: `tests/test_documentos.py`

- [ ] **Step 1: Escrever o teste que falha**

Adicione ao final de `tests/test_documentos.py`:

```python
def test_documento_nasce_aplicavel(client, admin_token, auth_headers):
    """Todo documento nasce aplicável; o dict expõe aplicavel/motivo_na."""
    h = auth_headers(admin_token)
    res = client.post("/api/documentos",
                      json={"setor": "PRE", "equipamento": "MAQ-APL", "sku": "SKU-APL"},
                      headers=h)
    assert res.status_code == 201
    doc = res.get_json()["documento"]
    assert doc["aplicavel"] is True
    assert doc["motivo_na"] == ""
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `venv\Scripts\python -m pytest tests/test_documentos.py::test_documento_nasce_aplicavel -v`
Expected: FAIL com `KeyError: 'aplicavel'`

- [ ] **Step 3: Adicionar as colunas ao modelo**

Em `models.py`, na classe `Documento`, logo depois de `version` (linha 214):

```python
    version         = db.Column(db.Integer, default=0, nullable=False)
    # Escopo de documentos do equipamento: aplicavel=False → "não se aplica" (N/A).
    # O documento continua existindo (status, código, histórico preservados), mas
    # sai do denominador da completude (card, chips, KPIs, IDP). Reversível.
    aplicavel       = db.Column(db.Boolean, default=True, nullable=False, index=True)
    motivo_na       = db.Column(db.String(300), default="")
```

E em `to_dict()`, depois de `"version"`:

```python
            "version":          self.version or 0,
            "aplicavel":        bool(self.aplicavel),
            "motivo_na":        self.motivo_na or "",
```

- [ ] **Step 4: Adicionar as colunas ao migrador de schema**

Em `servidor.py`, dentro de `_sync_schema`, a chave `"documentos"` do dicionário `novas_colunas` (linha 1503). O default booleano precisa da forma verdadeira do dialeto — declare-a junto do `_bool_false` já existente (linha 1479):

```python
    _bool_false = "FALSE" if db.engine.dialect.name == "postgresql" else "0"
    _bool_true  = "TRUE"  if db.engine.dialect.name == "postgresql" else "1"
```

```python
        "documentos": [
            ("equipamento_id", "INTEGER"),
            ("aplicavel",      f"BOOLEAN DEFAULT {_bool_true} NOT NULL"),
            ("motivo_na",      "VARCHAR(300) DEFAULT ''"),
        ],
```

Documentos que já existem no banco nascem `aplicavel = TRUE` pelo DEFAULT da coluna — é exatamente o backfill que queremos (inclusive para os opcionais já criados: existirem significa que se aplicam).

- [ ] **Step 5: Rodar o teste e ver passar**

Run: `venv\Scripts\python -m pytest tests/test_documentos.py::test_documento_nasce_aplicavel -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add models.py servidor.py tests/test_documentos.py
git commit -m "feat(documentos): coluna aplicavel/motivo_na (escopo N/A por equipamento)"
```

---

### Task 2: Todo equipamento nasce com os 12 tipos (opcionais em N/A)

`TIPOS_DOC_AUTO` significava "os tipos que são criados automaticamente". Agora **todos** os 12 são criados; o que a lista distingue é quais nascem aplicáveis. O nome passa a mentir — renomeie para `TIPOS_DOC_PADRAO_APLICAVEL`.

**Files:**
- Modify: `models.py:44-45`
- Modify: `servidor.py:93-94` (import), `servidor.py:465-482` (`_ensure_docs_for_equip`)
- Modify: `documentos.py:25-30` (import), `documentos.py:164-198` (criação)
- Test: `tests/test_taxonomia_docs.py`

- [ ] **Step 1: Escrever os testes que falham**

Substitua os testes `test_constantes_taxonomia`, `test_post_nao_cria_opcionais` e `test_post_cria_opcional_quando_selecionado` de `tests/test_taxonomia_docs.py` por:

```python
def test_constantes_taxonomia():
    from models import (TIPOS_DOC_PRE, TIPOS_DOC_PADRAO_APLICAVEL, TIPOS_DOC_OPCIONAIS,
                        TIPOS_DOC_TODOS, SETOR_DO_TIPO)
    # PRE = IT + 4 checklists, todos no pipeline de 4 etapas
    assert TIPOS_DOC_PRE == ["IT", "Checklist_Conferencia", "Checklist_BurnIn",
                             "Checklist_Limpeza_Embalagem", "Checklist_Produto"]
    for t in TIPOS_DOC_PRE:
        assert SETOR_DO_TIPO[t] == "PRE"
    # opcionais nascem fora do conjunto aplicável por padrão
    assert set(TIPOS_DOC_OPCIONAIS) == {"Spare_Parts", "Dossie", "QIQOQD"}
    assert not set(TIPOS_DOC_OPCIONAIS) & set(TIPOS_DOC_PADRAO_APLICAVEL)
    assert set(TIPOS_DOC_PADRAO_APLICAVEL) | set(TIPOS_DOC_OPCIONAIS) == set(TIPOS_DOC_TODOS)


def test_post_cria_12_tipos_com_opcionais_em_na(client, admin_token, auth_headers):
    """Equipamento novo nasce com os 12 documentos: 9 aplicáveis + 3 opcionais N/A."""
    from models import TIPOS_DOC_TODOS, TIPOS_DOC_OPCIONAIS
    h = auth_headers(admin_token)
    res = client.post("/api/documentos",
                      json={"setor": "PRE", "equipamento": "MAQ-OPT", "sku": "SKU-OPT"},
                      headers=h)
    assert res.status_code == 201
    docs = [d for d in client.get("/api/documentos", headers=h).get_json()
            if d["equipamento"] == "MAQ-OPT"]
    por_tipo = {d["tipo_doc"]: d for d in docs}
    assert set(por_tipo) == set(TIPOS_DOC_TODOS)          # os 12 existem
    for t in TIPOS_DOC_OPCIONAIS:
        assert por_tipo[t]["aplicavel"] is False          # opcionais em N/A
    for t in set(TIPOS_DOC_TODOS) - set(TIPOS_DOC_OPCIONAIS):
        assert por_tipo[t]["aplicavel"] is True


def test_post_com_opcional_selecionado_nasce_aplicavel(client, admin_token, auth_headers):
    """Criar explicitamente um opcional (botão do modal) já o marca como aplicável."""
    h = auth_headers(admin_token)
    res = client.post("/api/documentos",
                      json={"setor": "Manuais", "equipamento": "MAQ-OPT2",
                            "tipo_doc": "Dossie", "codigo_doc": "DOS-1"},
                      headers=h)
    assert res.status_code == 201
    doc = res.get_json()["documento"]
    assert doc["tipo_doc"] == "Dossie"
    assert doc["aplicavel"] is True
    docs = [d for d in client.get("/api/documentos", headers=h).get_json()
            if d["equipamento"] == "MAQ-OPT2"]
    por_tipo = {d["tipo_doc"]: d for d in docs}
    assert por_tipo["Spare_Parts"]["aplicavel"] is False   # os outros opcionais nascem N/A
    assert por_tipo["QIQOQD"]["aplicavel"] is False
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `venv\Scripts\python -m pytest tests/test_taxonomia_docs.py -v`
Expected: FAIL — `ImportError: cannot import name 'TIPOS_DOC_PADRAO_APLICAVEL'`

- [ ] **Step 3: Renomear a constante em `models.py`**

Substitua as linhas 43-45 de `models.py`:

```python
# Opcionais: nascem marcados como "não se aplica" (aplicavel=False). O documento
# existe (a aba Escopo do modal liga/desliga), mas fica fora da completude.
TIPOS_DOC_OPCIONAIS = ["Spare_Parts", "Dossie", "QIQOQD"]
TIPOS_DOC_PADRAO_APLICAVEL = [t for t in TIPOS_DOC_TODOS if t not in TIPOS_DOC_OPCIONAIS]
```

- [ ] **Step 4: Atualizar `_ensure_docs_for_equip` (servidor.py)**

No import de `models` (servidor.py:93-94), troque `TIPOS_DOC_AUTO` por `TIPOS_DOC_PADRAO_APLICAVEL`. Depois substitua o corpo de `_ensure_docs_for_equip` (linhas 465-482):

```python
def _ensure_docs_for_equip(equip):
    """Garante os 12 tipos de documento do equipamento (paridade com o módulo
    Documentos). Os opcionais nascem em N/A (aplicavel=False) — existem, mas fora
    da completude, até alguém ligá-los na aba Escopo. Cria só o que falta.
    Retorna quantos criou. Idempotente."""
    existentes = {d.tipo_doc for d in Documento.query.filter(
        Documento.ativo == True, Documento.equipamento_id == equip.id).all() if d.tipo_doc}
    n = 0
    for t in TIPOS_DOC_TODOS:
        if t in existentes:
            continue
        label = TIPOS_DOC_LABELS.get(t, t)
        db.session.add(Documento(
            setor=SETOR_DO_TIPO[t], equipamento=equip.nome, equipamento_id=equip.id,
            sku=equip.sku, fabricante=equip.fabricante, codigo_doc="",
            documento=f"{label} - {equip.nome}", tipo_doc=t, status="Elaborar",
            aplicavel=(t not in TIPOS_DOC_OPCIONAIS),
            armazenamento=equip.armazenamento_base))
        n += 1
    return n
```

- [ ] **Step 5: Atualizar a criação em `documentos.py`**

O import atual (documentos.py:25-30) traz `TIPOS_DOC_AUTO` e **não** traz `TIPOS_DOC_OPCIONAIS`, que o código novo usa. Ajuste-o:

```python
from models import (
    db, Documento, Equipamento, AuditLog,
    SETORES, STATUS_MAP,
    TIPOS_DOC_PRE, TIPOS_DOC_FABRICANTE, TIPOS_DOC_TODOS, TIPOS_DOC_OPCIONAIS,
    SETOR_DO_TIPO, TIPOS_DOC_LABELS,
)
```

(`TIPOS_DOC_PADRAO_APLICAVEL` não é usado em `documentos.py` — a criação decide pelo `TIPOS_DOC_OPCIONAIS`.) Substitua o bloco de criação (linhas 164-198) — os 12 tipos passam a nascer sempre, e o `aplicavel` sai do tipo (opcional → N/A), exceto quando o opcional é justamente o selecionado:

```python
    # Todos os 12 tipos nascem com o equipamento. Os opcionais nascem em N/A
    # (fora da completude); ligá-los é um toggle na aba Escopo. Se o opcional for
    # o tipo explicitamente selecionado neste POST, ele já nasce aplicável.
    for t in TIPOS_DOC_TODOS:
        if t in existentes:
            continue
        is_sel = (t == selected_tipo)
        label = TIPOS_DOC_LABELS.get(t, t)
        novo = Documento(
            setor=SETOR_DO_TIPO[t],
            equipamento=equip,
            equipamento_id=equip_id,
            sku=sku,
            codigo_doc=data.get("codigo_doc", "") if is_sel else "",
            documento=(data.get("documento") or f"{label} - {equip}") if is_sel else f"{label} - {equip}",
            responsavel=data.get("responsavel", "") if is_sel else "",
            status=data.get("status", "Elaborar") if is_sel else "Elaborar",
            tipo_doc=t,
            fabricante=fab,
            aplicavel=(is_sel or t not in TIPOS_DOC_OPCIONAIS),
            obs_treinamento=data.get("obs_treinamento", "") if is_sel else "",
            obs_homologacao=data.get("obs_homologacao", "") if is_sel else "",
            armazenamento=data.get("armazenamento", "") if is_sel else (equip_obj.armazenamento_base if equip_obj else ""),
        )
        if is_sel:
            if data.get("data_treinamento"):
                try: novo.data_treinamento = datetime.strptime(data["data_treinamento"], "%Y-%m-%d")
                except: pass
            if data.get("data_homologacao"):
                try: novo.data_homologacao = datetime.strptime(data["data_homologacao"], "%Y-%m-%d")
                except: pass
        db.session.add(novo)
        if is_sel:
            doc = novo
```

Remova a linha `tipos_criar = [...]` que ficou órfã (documentos.py:167-168).

- [ ] **Step 6: Rodar os testes e ver passar**

Run: `venv\Scripts\python -m pytest tests/test_taxonomia_docs.py -v`
Expected: PASS (o teste `test_migracao_renomeia_checklist_e_oculta_opcionais_em_branco` ainda falha — é a Task 3)

- [ ] **Step 7: Commit**

```bash
git add models.py servidor.py documentos.py tests/test_taxonomia_docs.py
git commit -m "feat(documentos): equipamento nasce com os 12 tipos; opcionais em N/A"
```

---

### Task 3: Migração — opcionais ocultados voltam como N/A

`_migrar_taxonomia_docs` (servidor.py:1623) hoje faz soft delete (`ativo=False`) dos opcionais em branco. Com o novo modelo isso vira duplicata: `_ensure_docs_for_equip` só enxerga os ativos e criaria um segundo `Dossie`. A regra passa a ser: opcional em branco **volta a existir** (ativo) com `aplicavel=False`.

**Files:**
- Modify: `servidor.py:1623-1669` (`_migrar_taxonomia_docs`)
- Test: `tests/test_taxonomia_docs.py`

- [ ] **Step 1: Escrever o teste que falha**

Substitua `test_migracao_renomeia_checklist_e_oculta_opcionais_em_branco` em `tests/test_taxonomia_docs.py` por:

```python
def test_migracao_renomeia_checklist_e_marca_opcionais_em_branco_como_na(app):
    from models import db, Documento, Equipamento
    from servidor import _migrar_taxonomia_docs
    from datetime import datetime

    with app.app_context():
        equip = Equipamento(nome="MAQ-MIG", sku="SKU-MIG", armazenamento_base="P:/Base")
        db.session.add(equip)
        db.session.flush()
        db.session.add_all([
            # Checklist genérico com dados → vira Checklist_Conferencia
            Documento(setor="PRE", equipamento="MAQ-MIG", equipamento_id=equip.id,
                      documento="Checklist - MAQ-MIG", tipo_doc="Checklist",
                      codigo_doc="CHK-1", status="Homologado"),
            # opcional em branco (armazenamento = base do equip) → N/A, mas ativo
            Documento(setor="Manuais", equipamento="MAQ-MIG", equipamento_id=equip.id,
                      documento="Dossiê - MAQ-MIG", tipo_doc="Dossie",
                      status="Elaborar", armazenamento="P:/Base"),
            # opcional com dado (codigo_doc) → aplicável
            Documento(setor="Manuais", equipamento="MAQ-MIG", equipamento_id=equip.id,
                      documento="QI/QO/QD - MAQ-MIG", tipo_doc="QIQOQD",
                      codigo_doc="QQ-9", status="Elaborar"),
            # opcional já ocultado por uma migração anterior → volta ativo, em N/A
            Documento(setor="Manuais", equipamento="MAQ-MIG", equipamento_id=equip.id,
                      documento="Spare Parts - MAQ-MIG", tipo_doc="Spare_Parts",
                      status="Elaborar", ativo=False, deleted_at=datetime.now()),
        ])
        db.session.commit()

        _migrar_taxonomia_docs()

        docs = {d.tipo_doc: d for d in Documento.query.filter(
            Documento.equipamento == "MAQ-MIG").all()}
        assert "Checklist" not in docs
        chk = docs["Checklist_Conferencia"]
        assert chk.codigo_doc == "CHK-1" and chk.status == "Homologado"
        assert chk.documento == "Checklist de Conferência - MAQ-MIG"
        assert chk.aplicavel is True

        dossie = docs["Dossie"]
        assert dossie.ativo is True and dossie.aplicavel is False   # em branco → N/A
        assert docs["QIQOQD"].aplicavel is True                     # tinha dado → aplica

        spare = docs["Spare_Parts"]
        assert spare.ativo is True and spare.aplicavel is False     # ressuscitado em N/A
        assert spare.deleted_at is None

        # idempotência: rodar de novo não muda nada
        _migrar_taxonomia_docs()
        assert Documento.query.filter_by(tipo_doc="Checklist").count() == 0
        assert Documento.query.filter_by(tipo_doc="Dossie").count() == 1
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `venv\Scripts\python -m pytest tests/test_taxonomia_docs.py::test_migracao_renomeia_checklist_e_marca_opcionais_em_branco_como_na -v`
Expected: FAIL — `assert False is True` (o Dossiê em branco ainda é soft-deletado)

- [ ] **Step 3: Reescrever o passo 2 da migração**

Substitua as linhas 1642-1669 de `servidor.py` (o bloco "oculta opcionais em branco" e o print final):

```python
    # 2) Opcionais (Spare Parts / Dossiê / QIQOQD) em branco passam a existir como
    #    N/A: ficam ativos, mas fora da completude. Os que têm qualquer dado
    #    preenchido são considerados aplicáveis. Também ressuscita os que a versão
    #    anterior desta migração ocultou (ativo=False) — senão _ensure_docs_for_equip
    #    criaria uma segunda linha do mesmo tipo.
    marcados = 0
    base_por_equip = {e.id: (e.armazenamento_base or "").strip()
                      for e in Equipamento.query.all()}
    candidatos = Documento.query.filter(
        Documento.tipo_doc.in_(TIPOS_DOC_OPCIONAIS)).all()
    for d in candidatos:
        arm = (d.armazenamento or "").strip()
        arm_base = base_por_equip.get(d.equipamento_id, "")
        em_branco = (
            not (d.codigo_doc or "").strip()
            and not (d.responsavel or "").strip()
            and (d.status or "Elaborar") == "Elaborar"
            and d.data_treinamento is None and d.data_homologacao is None
            and not (d.obs_treinamento or "").strip()
            and not (d.obs_homologacao or "").strip()
            and (not arm or arm == arm_base)
        )
        # opcional ocultado pela migração antiga: volta ativo, em N/A
        ressuscitar = (not d.ativo) and em_branco
        if ressuscitar:
            d.ativo = True
            d.deleted_at = None
        if em_branco and d.aplicavel:
            d.aplicavel = False
            marcados += 1
        elif ressuscitar:
            marcados += 1

    if renomeados or marcados:
        db.session.commit()
        print(f"[INFO] Taxonomia de documentos: {renomeados} 'Checklist' renomeados; "
              f"{marcados} opcionais em branco marcados como N/A.")
```

Atualize também o docstring da função (linhas 1623-1631) para descrever o passo 2 novo.

- [ ] **Step 4: Rodar e ver passar**

Run: `venv\Scripts\python -m pytest tests/test_taxonomia_docs.py -v`
Expected: PASS (3 testes)

- [ ] **Step 5: Commit**

```bash
git add servidor.py tests/test_taxonomia_docs.py
git commit -m "fix(documentos): migracao converte opcionais ocultados em N/A ativos"
```

---

### Task 4: Rota `PUT /api/documentos/<id>/aplicabilidade`

**Files:**
- Modify: `documentos.py` (nova rota, no fim da seção CRUD — depois de `delete_documento`)
- Test: `tests/test_documentos.py`

- [ ] **Step 1: Escrever os testes que falham**

Adicione a `tests/test_documentos.py`:

```python
def _doc_de_tipo(client, headers, equipamento, tipo):
    docs = client.get("/api/documentos", headers=headers).get_json()
    return next(d for d in docs if d["equipamento"] == equipamento and d["tipo_doc"] == tipo)


def test_aplicabilidade_gestor_marca_na(client, admin_token, gestor_token, auth_headers):
    ha, hg = auth_headers(admin_token), auth_headers(gestor_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-NA"}, headers=ha)
    doc = _doc_de_tipo(client, ha, "MAQ-NA", "Manual_ES")

    res = client.put(f"/api/documentos/{doc['id']}/aplicabilidade",
                     json={"aplicavel": False, "motivo_na": "produto sem versão ES"},
                     headers=hg)
    assert res.status_code == 200
    d = res.get_json()["documento"]
    assert d["aplicavel"] is False
    assert d["motivo_na"] == "produto sem versão ES"
    assert d["status"] == "Elaborar"        # marcar N/A não mexe no status


def test_aplicabilidade_tecnico_negado(client, admin_token, tecnico_token, auth_headers):
    ha, ht = auth_headers(admin_token), auth_headers(tecnico_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-NA2"}, headers=ha)
    doc = _doc_de_tipo(client, ha, "MAQ-NA2", "Manual_ES")

    res = client.put(f"/api/documentos/{doc['id']}/aplicabilidade",
                     json={"aplicavel": False}, headers=ht)
    assert res.status_code == 403


def test_religar_na_preserva_dados(client, admin_token, auth_headers):
    """Religar um documento N/A devolve status, código e responsável intactos."""
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-NA3"}, headers=h)
    doc = _doc_de_tipo(client, h, "MAQ-NA3", "Manual_Servico")

    client.patch(f"/api/documentos/{doc['id']}",
                 json={"codigo_doc": "MS-77", "responsavel": "Ana", "status": "Em andamento"},
                 headers=h)
    client.put(f"/api/documentos/{doc['id']}/aplicabilidade",
               json={"aplicavel": False, "motivo_na": "sem serviço em campo"}, headers=h)
    res = client.put(f"/api/documentos/{doc['id']}/aplicabilidade",
                     json={"aplicavel": True}, headers=h)

    assert res.status_code == 200
    d = res.get_json()["documento"]
    assert d["aplicavel"] is True
    assert d["motivo_na"] == ""              # religar limpa o motivo
    assert d["codigo_doc"] == "MS-77"
    assert d["responsavel"] == "Ana"
    assert d["status"] == "Em andamento"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `venv\Scripts\python -m pytest tests/test_documentos.py -k aplicabilidade -v`
Expected: FAIL — 405/404 (rota não existe)

- [ ] **Step 3: Implementar a rota**

Em `documentos.py`, logo depois de `delete_documento` (linha 281):

```python
@documentos_bp.route("/api/documentos/<int:doc_id>/aplicabilidade", methods=["PUT"])
@require_role("admin", "gestor")
def update_aplicabilidade(doc_id):
    """Liga/desliga um tipo de documento no escopo do equipamento (N/A).

    Fora do PATCH genérico de propósito: o PATCH é tecnico+ (edita status e campos
    do documento); mexer no escopo muda o denominador da completude de todo mundo,
    então fica restrito a admin/gestor. Marcar N/A NÃO altera o status nem toca nos
    cartões de missão vinculados — o documento só sai da conta.
    """
    caller = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    if "aplicavel" not in data:
        return jsonify({"erro": "Informe 'aplicavel' (true/false)"}), 400

    doc = Documento.query.filter(Documento.ativo == True, Documento.id == doc_id).first()
    if not doc:
        return jsonify({"erro": "Não encontrado"}), 404

    novo = bool(data.get("aplicavel"))
    antigo = bool(doc.aplicavel)
    # motivo só existe enquanto o documento está em N/A; religar limpa
    motivo = (data.get("motivo_na") or "").strip()[:300] if not novo else ""

    if novo == antigo and motivo == (doc.motivo_na or ""):
        return jsonify({"mensagem": "Nada a alterar", "documento": doc.to_dict()}), 200

    doc.aplicavel = novo
    doc.motivo_na = motivo
    doc.updated_em = datetime.now()
    doc.version = (doc.version or 0) + 1
    db.session.commit()

    log_action(caller, "UPDATE", entidade=doc.documento, campo="aplicavel",
               antigo="Aplica" if antigo else "N/A",
               novo=("Aplica" if novo else f"N/A{(' — ' + motivo) if motivo else ''}"),
               documento_id=doc.id, ip=get_client_ip())
    _emit(EventType.DOCUMENT_UPDATED,
          {"documento_id": doc.id, "documento": doc.to_dict(),
           "setor": doc.setor, "equipamento": doc.equipamento},
          caller)
    return jsonify({"mensagem": "Escopo atualizado", "documento": doc.to_dict()}), 200
```

- [ ] **Step 4: Rodar e ver passar**

Run: `venv\Scripts\python -m pytest tests/test_documentos.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add documentos.py tests/test_documentos.py
git commit -m "feat(documentos): rota PUT /aplicabilidade (admin/gestor) para marcar N/A"
```

---

### Task 5: KPIs contam só os aplicáveis

**Files:**
- Modify: `servidor.py:174-202` (`compute_kpis`)
- Test: `tests/test_documentos.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
def test_kpis_ignoram_documentos_na(client, admin_token, auth_headers):
    """Documento em N/A sai do total, do backlog e do pct_concluidos."""
    h = auth_headers(admin_token)
    client.post("/api/documentos", json={"setor": "PRE", "equipamento": "MAQ-KPI"}, headers=h)

    antes = client.get("/api/kpis", headers=h).get_json()
    doc = _doc_de_tipo(client, h, "MAQ-KPI", "Manual_Servico")
    client.put(f"/api/documentos/{doc['id']}/aplicabilidade",
               json={"aplicavel": False}, headers=h)
    depois = client.get("/api/kpis", headers=h).get_json()

    assert depois["total"] == antes["total"] - 1
    assert depois["pendentes"] == antes["pendentes"] - 1
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `venv\Scripts\python -m pytest tests/test_documentos.py::test_kpis_ignoram_documentos_na -v`
Expected: FAIL — `assert 12 == 11`

- [ ] **Step 3: Filtrar os N/A em `compute_kpis`**

Em `servidor.py`, no topo de `compute_kpis` (linha 174):

```python
def compute_kpis(docs):
    # Documentos em N/A ("não se aplica a este equipamento") ficam fora de TODA a
    # contagem: eles não são backlog, não são pendência e não podem puxar o
    # pct_concluidos para baixo. Ver aba Escopo do modal do equipamento.
    docs = [d for d in docs if d.get("aplicavel", True)]
    total = len(docs)
```

O resto da função fica igual — todas as contagens já derivam de `docs`.

- [ ] **Step 4: Rodar a suíte inteira**

Run: `venv\Scripts\python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add servidor.py tests/test_documentos.py
git commit -m "feat(dashboard): KPIs contam so os documentos aplicaveis"
```

---

### Task 6: Front — completude do card e chips contam só os aplicáveis

**Files:**
- Modify: `static/app.js:990-1019` (`_equipDocs`, `equipStatusColor`, `equipManuaisOk`, `equipMatchesChip`)

- [ ] **Step 1: Filtrar os aplicáveis na base do cálculo**

Substitua as linhas 990-1019 de `static/app.js`:

```javascript
// Documentos de equipamento (PRE + Manuais) do grupo. `_equipDocs` devolve só os
// APLICÁVEIS: documentos em N/A ("não se aplica a este equipamento") estão fora da
// completude — não pintam o card, não entram nos chips, não contam nos KPIs.
function _equipDocs(g){ return g.docs.filter(d=>(d.setor==='PRE'||d.setor==='Manuais') && d.aplicavel!==false); }
function _equipDocsNA(g){ return g.docs.filter(d=>d.aplicavel===false); }
function _docFinalizado(d){
  return (d.setor==='PRE' && d.status==='Homologado') || (d.setor==='Manuais' && d.status==='Concluído');
}
function equipManuaisOk(g){ return g.manuais.filter(d=>d.aplicavel!==false && d.status==='Concluído').length; }
function equipManuaisAplicaveis(g){ return g.manuais.filter(d=>d.aplicavel!==false).length; }

// Cor do card = PIOR status entre os documentos APLICÁVEIS do equipamento.
// Equipamento sem nenhum aplicável (tudo N/A) fica neutro — como o idp() que
// devolve null quando todos os itens são N/A.
function equipStatusColor(g){
  const docs = _equipDocs(g);
  if(!docs.length) return 'neutro';
  if(docs.some(d=>d.status==='Elaborar')) return 'red';   // algum não iniciado
  if(docs.every(_docFinalizado)) return 'green';          // tudo finalizado
  return 'amber';
}

// Completude do equipamento: finalizados / aplicáveis (+ quantos estão em N/A)
function equipCompletude(g){
  const docs = _equipDocs(g);
  return { ok: docs.filter(_docFinalizado).length, total: docs.length, na: _equipDocsNA(g).length };
}

function equipMatchesChip(g, chip){
  const docs = _equipDocs(g);
  const color = equipStatusColor(g);
  const ok = equipManuaisOk(g), cnt = equipManuaisAplicaveis(g);
  switch(chip){
    case 'todos': return true;
    case 'pendente': return color==='red';
    case 'progresso': return color==='amber';
    case 'finalizado': return color==='green';
    case 'pre-pendente': return docs.some(d=>d.setor==='PRE' && d.status==='Elaborar');
    case 'manuais-incompletos': return cnt>0 && ok<cnt;
    default: return true;
  }
}
```

- [ ] **Step 2: Tratar a cor `neutro` no card e no cabeçalho do modal**

Em `renderEquipHeader` (app.js:1172), o mapa de cores ganha o caso neutro:

```javascript
  const dot = color==='green'?'var(--green)':color==='red'?'var(--red)':color==='neutro'?'var(--t4)':'var(--amber)';
```

Em `static/style.css`, junto das classes `.equip-card.st-*` já existentes, acrescente:

```css
.equip-card.st-neutro { border-left-color: var(--t4); }
```

Confira o nome exato da propriedade usada pelas classes `st-red`/`st-green`/`st-amber` no arquivo e espelhe-a (o ponto é só dar ao neutro o mesmo tratamento visual, em cinza).

- [ ] **Step 3: Mostrar a completude no card**

Em `renderGrid` (app.js:1060), o card ganha a linha de completude:

```javascript
  grid.innerHTML = filtered.map(g => {
    const color = equipStatusColor(g);
    const c = equipCompletude(g);
    const resumo = c.total
      ? `${c.ok}/${c.total} concluídos${c.na?` · ${c.na} N/A`:''}`
      : 'nenhum documento aplicável';
    return `<div class="equip-card st-${color}" data-equip="${esc(g.key)}" onclick="openEquipModal('${esc(g.key).replace(/'/g,"\\'")}')">
      <div class="equip-card-name">${esc(g.equipamento)}</div>
      <div class="equip-card-sku">${g.sku?esc(g.sku):'<span class="muted">sem SKU</span>'}</div>
      <div class="equip-card-compl">${esc(resumo)}</div>
    </div>`;
  }).join('');
```

E o estilo em `static/style.css`:

```css
.equip-card-compl { font-size: 11px; color: var(--t3); margin-top: 4px; }
```

- [ ] **Step 4: Verificar no navegador**

Run: `venv\Scripts\python servidor.py` e abra `http://localhost:5000` → módulo Documentos.
Expected: os cards mostram "x/y concluídos"; nenhum erro no console.

- [ ] **Step 5: Commit**

```bash
git add static/app.js static/style.css
git commit -m "feat(documentos): card e chips contam so os documentos aplicaveis"
```

---

### Task 7: Front — aba Escopo no modal do equipamento

Substitui a aba "+ Adicionar" (`renderAddOpcionaisPanel`) e a criação sob demanda (`createTipo`), que perdem a razão de existir: os 12 documentos já existem, o que muda é o bit.

**Files:**
- Modify: `static/app.js:1193-1237` (`_visibleTabs`, `renderEquipModal`), `1264-1270` (`renderAddOpcionaisPanel` → `renderEscopoPanel`), `1316-1325` (`renderTipoPanel`), `1426-1444` (`createTipo` → `setAplicabilidade`)
- Modify: `static/style.css` (lista de escopo)

- [ ] **Step 1: Abas — esconder os tipos em N/A e sempre mostrar a aba Escopo**

Substitua `_visibleTabs` e `renderEquipModal` (app.js:1197-1237):

```javascript
// Um tipo está no escopo quando o documento existe e está marcado como aplicável.
function _aplicavel(tipo){ const d=_equipCtx.byTipo[tipo]; return !!d && d.aplicavel!==false; }

// Abas visíveis: só os tipos APLICÁVEIS. IT, Checklists (os 4 numa aba só), Manual
// do Usuário (PT/ES numa aba só), Manual de Serviço, Guia de Instalação e os
// opcionais que estiverem ligados. A aba Escopo (sempre última) liga/desliga tudo.
function _visibleTabs(){
  const grupos = [
    ['IT','Instrução de Trabalho', ['IT']],
    ['Checklist_Conferencia','Checklists', _CHK_TIPOS.map(x=>x[0])],
    ['Manual_Usuario','Manual do Usuário', ['Manual_Usuario','Manual_ES']],
    ['Manual_Servico','Manual de Serviço', ['Manual_Servico']],
    ['Guia_Instalacao','Guia de Instalação', ['Guia_Instalacao']],
  ];
  const tabs = grupos
    .filter(([,,tipos]) => tipos.some(_aplicavel))   // aba some se todo o grupo é N/A
    .map(([id,label]) => [id,label]);
  _TIPOS_OPCIONAIS.forEach(t=>{ if(_aplicavel(t)) tabs.push([t,_tipoLabel(t)]); });
  return tabs;
}

function _tabDotColor(tipo){
  // abas agregadas (checklists / manuais PT+ES): pior status do grupo, só aplicáveis
  const grupo = (tipo==='Checklist_Conferencia') ? _CHK_TIPOS.map(x=>x[0])
              : (tipo==='Manual_Usuario') ? ['Manual_Usuario','Manual_ES']
              : [tipo];
  const docs = grupo.filter(_aplicavel).map(t=>_equipCtx.byTipo[t]);
  if(!docs.length) return 'var(--t4)';
  if(docs.some(d=>d.status==='Elaborar')) return 'var(--red)';
  if(docs.every(_docFinalizado)) return 'var(--green)';
  return 'var(--amber)';
}

// Abas + painéis
function renderEquipModal(){
  const tabsEl = document.getElementById('equip-tabs');
  const panelsEl = document.getElementById('equip-panels');
  const tabs = _visibleTabs();
  tabsEl.innerHTML = tabs.map(([tipo,label])=>
    `<button type="button" class="equip-modal-tab" data-tab="${tipo}" onclick="switchEquipTab('${tipo}')"><span class="tab-dot" style="background:${_tabDotColor(tipo)}"></span>${esc(label)}</button>`
  ).join('') +
    `<button type="button" class="equip-modal-tab tab-add" data-tab="__escopo" onclick="switchEquipTab('__escopo')" title="Escolher quais documentos se aplicam a este equipamento">⚙ Escopo</button>`;
  panelsEl.innerHTML = tabs.map(([tipo])=>
    `<div class="equip-tab-panel" data-panel="${tipo}">${
      tipo==='Checklist_Conferencia'?renderChecklistPanel()
      : tipo==='Manual_Usuario'?renderManualPanel()
      : renderTipoPanel(tipo)}</div>`
  ).join('') +
    `<div class="equip-tab-panel" data-panel="__escopo">${renderEscopoPanel()}</div>`;
}
```

Nas abas agregadas, o seletor interno também precisa esconder os N/A. Em `renderChecklistPanel` (app.js:1241) e `renderManualPanel` (1253), filtre os botões:

```javascript
function renderChecklistPanel(){
  const disp = _CHK_TIPOS.filter(([t])=>_aplicavel(t));
  if(!disp.some(([t])=>t===_chkSel)) _chkSel = disp.length ? disp[0][0] : 'Checklist_Conferencia';
  const btn=(t,txt)=>`<button type="button" class="btn btn-sm ${_chkSel===t?'btn-primary':'btn-ghost'}" onclick="setChkSel('${t}')">${txt}</button>`;
  return `<div class="man-lang-toggle">${disp.map(([t,l])=>btn(t,l)).join('')}</div>` + renderTipoPanel(_chkSel);
}
```

```javascript
function renderManualPanel(){
  const temPT = _aplicavel('Manual_Usuario'), temES = _aplicavel('Manual_ES');
  if(_manLang==='ES' && !temES) _manLang='PT';
  if(_manLang==='PT' && !temPT) _manLang='ES';
  const tipo = _manLang==='ES' ? 'Manual_ES' : 'Manual_Usuario';
  const btn = (l,txt)=>`<button type="button" class="btn btn-sm ${_manLang===l?'btn-primary':'btn-ghost'}" onclick="setManLang('${l}')">${txt}</button>`;
  const toggles = `${temPT?btn('PT','Português'):''}${temES?btn('ES','Español'):''}`;
  return `<div class="man-lang-toggle">${toggles}</div>` + renderTipoPanel(tipo);
}
```

- [ ] **Step 2: Escrever o painel Escopo**

Substitua `renderAddOpcionaisPanel` (app.js:1264-1270) por:

```javascript
// Painel "Escopo": liga/desliga cada um dos 12 tipos para este equipamento.
// Desligado = N/A: o documento continua existindo (status, código e histórico
// intactos), mas sai da conta de completude. Só admin/gestor edita.
function _podeEditarEscopo(){ return currentUser.role==='admin' || currentUser.role==='gestor'; }

function renderEscopoPanel(){
  const c = _equipCtx.g ? equipCompletude(_equipCtx.g) : {ok:0,total:0,na:0};
  const editavel = _podeEditarEscopo();
  const linha = ([tipo,label])=>{
    const d = _equipCtx.byTipo[tipo];
    if(!d) return '';                              // documento ainda não existe (equip. legado)
    const apl = d.aplicavel!==false;
    const dot = apl ? _statusDotColor(d) : 'var(--t4)';
    const status = apl ? esc(d.status) : 'Não se aplica';
    const motivo = (!apl && d.motivo_na) ? `<div class="escopo-motivo">${esc(d.motivo_na)}</div>` : '';
    return `<div class="escopo-row${apl?'':' off'}">
      <label class="escopo-toggle">
        <input type="checkbox" ${apl?'checked':''} ${editavel?'':'disabled'}
               onchange="toggleEscopo('${tipo}', this.checked)">
        <span class="escopo-dot" style="background:${dot}"></span>
        <span class="escopo-label">${esc(label)}</span>
      </label>
      <span class="escopo-status">${status}</span>
      ${motivo}
    </div>`;
  };
  const bloco = (titulo, tipos)=>`
    <div class="doc-sec">
      <div class="doc-sec-title">${titulo}</div>
      ${tipos.map(linha).join('')}
    </div>`;
  const resumo = c.total
    ? `${c.ok} de ${c.total} aplicáveis concluídos${c.na?` · ${c.na} N/A`:''}`
    : 'Nenhum documento aplicável a este equipamento';
  const aviso = editavel ? '' :
    '<p class="muted" style="font-size:12px">Só admin e gestor podem alterar o escopo — mexer nele muda a completude de todo mundo.</p>';
  return `
    <div class="equip-panel-head">
      <span class="equip-panel-title">Escopo de documentos</span>
      <span class="equip-tag">${esc(resumo)}</span>
    </div>
    <p class="muted" style="font-size:12px;margin-bottom:8px">Desmarque o que não se aplica a este equipamento. O documento continua salvo (status, código, arquivos) — só sai da conta de completude.</p>
    ${aviso}
    ${bloco('PRE', _PRE_TIPOS)}
    ${bloco('Manuais', _MAN_TIPOS)}`;
}
```

- [ ] **Step 3: Trocar `createTipo` pelo toggle de escopo**

Substitua `createTipo` (app.js:1426-1444) por:

```javascript
// Liga/desliga um tipo no escopo do equipamento aberto. Ao desligar, pede o motivo
// (opcional — dá pra deixar em branco). Reabre o modal na mesma aba.
async function toggleEscopo(tipo, aplicavel){
  const d = _equipCtx.byTipo[tipo];
  if(!d) return;
  let motivo = '';
  if(!aplicavel){
    motivo = (window.prompt(`Por que "${_tipoLabel(tipo)}" não se aplica a ${_equipCtx.equipamento}? (opcional)`) || '').trim();
  }
  const reopenKey = (_equipCtx.g && _equipCtx.g.key) || _equipCtx.equipamento;
  try{
    const res = await apiFetch(`/documentos/${d.id}/aplicabilidade`,
      {method:'PUT', body:JSON.stringify({aplicavel, motivo_na: motivo})});
    if(res && res.ok){
      showToast(`${_tipoLabel(tipo)} ${aplicavel?'incluído no escopo':'marcado como N/A'}`,'success');
      await refreshAll();
      openEquipModal(reopenKey);
      switchEquipTab('__escopo');
    } else {
      const e = res ? await res.json().catch(()=>({})) : {};
      showToast(e.erro||'Erro ao atualizar o escopo','error');
      renderEquipModal();            // desfaz o checkbox otimista
      switchEquipTab('__escopo');
    }
  }catch(e){
    showToast('Erro de rede','error');
    renderEquipModal(); switchEquipTab('__escopo');
  }
}
```

`renderTipoPanel` (app.js:1316-1325) tem um ramo "documento não existe → botão Criar" que chamava `createTipo`. Como as abas agora só mostram tipos aplicáveis e existentes, esse ramo vira uma mensagem sem botão:

```javascript
  if(!d){
    return `<div style="text-align:center;padding:24px;color:var(--t3)">
      <p>Este equipamento ainda não tem o documento "${esc(label)}". Ele será criado na próxima sincronização; use a aba <b>Escopo</b> para definir o que se aplica.</p>
    </div>`;
  }
```

- [ ] **Step 4: Estilos da lista de escopo**

Acrescente ao fim de `static/style.css`:

```css
/* ── Aba Escopo (quais documentos se aplicam ao equipamento) ── */
.escopo-row { display:flex; align-items:center; gap:10px; padding:7px 0; border-bottom:1px solid var(--bd); }
.escopo-row:last-child { border-bottom:0; }
.escopo-row.off .escopo-label { color: var(--t4); text-decoration: line-through; }
.escopo-toggle { display:flex; align-items:center; gap:8px; cursor:pointer; flex:1; }
.escopo-toggle input[disabled] { cursor:not-allowed; }
.escopo-dot { width:8px; height:8px; border-radius:50%; flex:none; }
.escopo-label { font-size:13px; }
.escopo-status { font-size:12px; color:var(--t3); white-space:nowrap; }
.escopo-motivo { flex-basis:100%; font-size:11px; color:var(--t4); padding-left:26px; }
```

- [ ] **Step 5: Verificar no navegador**

Run: `venv\Scripts\python servidor.py` → módulo Documentos → abra um equipamento.
Expected: a aba "⚙ Escopo" existe no lugar de "+ Adicionar"; desmarcar "Manual do Usuário ES" tira a aba ES, muda o resumo para "x de y aplicáveis" e recolore o card; remarcar traz tudo de volta com o status intacto. Logado como técnico, os checkboxes ficam desabilitados.

- [ ] **Step 6: Commit**

```bash
git add static/app.js static/style.css
git commit -m "feat(documentos): aba Escopo (liga/desliga tipos de documento por equipamento)"
```

---

### Task 8: IDP respeita o N/A dos documentos

**Files:**
- Modify: `static/equipamentos.js:196-213` (`_docsDoTipo`, `revState`)

- [ ] **Step 1: Derivar N/A do documento**

Substitua as linhas 196-213 de `static/equipamentos.js`:

```javascript
function _docsDoTipo(eqId,tipos){ return (DOCS_BY_EQ[eqId]||[]).filter(d=>tipos.includes(d.tipo_doc)); }
// Documento marcado como "não se aplica" no módulo Documentos → item N/A no IDP
// (sai do denominador, como o N/A das revisões manuais).
function _aplicaveis(ds){ return ds.filter(d=>d.aplicavel!==false); }
// estado de cada um dos 6 itens de revisão
function revState(e,item){
  if(item==="cadastro")   return e.rev_cadastro||"Pendente";
  if(item==="estrutura")  return e.rev_estrutura||"Pendente";
  if(item==="descritivo") return e.rev_descritivo||"Pendente";
  if(item==="it"){
    const ds=_docsDoTipo(e.id,["IT"]);
    if(ds.length && !_aplicaveis(ds).length) return "N/A";
    return _estPRE(_aplicaveis(ds)[0] && _aplicaveis(ds)[0].status);
  }
  if(item==="manual_usuario"){
    const ds=_docsDoTipo(e.id,["Manual_Usuario"]);
    if(ds.length && !_aplicaveis(ds).length) return "N/A";
    return _estManuais(_aplicaveis(ds)[0] && _aplicaveis(ds)[0].status);
  }
  if(item==="checklists"){
    const todos=_docsDoTipo(e.id,["Checklist_Conferencia","Checklist_BurnIn","Checklist_Limpeza_Embalagem","Checklist_Produto"]);
    const ds=_aplicaveis(todos);
    if(todos.length && !ds.length) return "N/A";     // os 4 checklists em N/A
    if(!ds.length) return "Pendente";
    const est=ds.map(d=>_estPRE(d.status));
    if(est.every(x=>x==="Revisado")) return "Revisado";
    if(est.every(x=>x==="Pendente")) return "Pendente";
    return "Em revisão";
  }
  return "Pendente";
}
```

`idp()` (linha 215) já ignora os itens `N/A` — nada a mudar lá.

- [ ] **Step 2: Verificar no navegador**

Run: `venv\Scripts\python servidor.py` → módulo Equipamentos → aba Desenvolvimento.
Expected: um equipamento com a IT marcada como N/A mostra o item IT em cinza (N/A) e o IDP sobe, porque o denominador caiu de 6 para 5.

- [ ] **Step 3: Commit**

```bash
git add static/equipamentos.js
git commit -m "feat(equipamentos): IDP trata documento N/A como item fora do denominador"
```

---

### Task 9: Verificação de ponta a ponta

- [ ] **Step 1: Suíte completa**

Run: `venv\Scripts\python -m pytest tests/ -v`
Expected: todos passam.

- [ ] **Step 2: Boot contra o banco real (migração)**

Run: `venv\Scripts\python servidor.py`
Expected: no log, `[INFO] Schema: coluna documentos.aplicavel adicionada`, `documentos.motivo_na adicionada` e `[INFO] Taxonomia de documentos: … opcionais em branco marcados como N/A.` Sem traceback. Rodar de novo não repete as mensagens (idempotente).

- [ ] **Step 3: Fluxo real no navegador**

Abrir Documentos → escolher um equipamento → aba Escopo → desmarcar dois tipos com motivo → conferir que o card mudou o resumo/cor, que o dashboard baixou o total de documentos e que o IDP do equipamento subiu. Remarcar um deles e conferir que status e código voltaram intactos.

- [ ] **Step 4: Commit final e PR**

```bash
git push -u origin feat/escopo-documentos
gh pr create --title "feat(documentos): escopo de documentos por equipamento (N/A)" --body "..."
```

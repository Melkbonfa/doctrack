"""Migration 021: itens de modelo conhecidos por projeto + ligação pelo nome.

A primeira prévia de "Aplicar aos projetos" na produção propunha criar ~1.760
entregáveis que ninguém tinha pedido, por dois motivos:

  * a ligação dos entregáveis antigos (020) exigia nome E categoria iguais, e
    os modelos do PDR tinham mudado vários itens de categoria depois que os
    projetos nasceram — eles ficaram avulsos;
  * item do modelo que o projeto não tinha parecia novo, mesmo que o projeto
    nunca o tivesse tido ou o tivesse tirado de propósito.

Esta migration:

  1. adiciona `projetos.modelo_conhecidos` (JSON com as chaves dos itens do
     modelo que o projeto já conhece; NULL = projeto ainda não avaliado);
  2. para cada projeto NULL, liga os avulsos a itens ainda livres do modelo do
     projeto pelo NOME — sem categoria, acento, maiúscula, hífen ou espaço
     sobrando —, gravando os valores atuais do modelo como origem;
  3. grava no projeto a lista de todos os itens do modelo de agora.

Espelha `servidor._sync_schema()` + `servidor._vincular_entregaveis_ao_modelo()`
(modelo_sync.vincular_legado). Idempotente. Pressupõe a 020.

Uso: python migrations/021_itens_conhecidos.py [db_path]
"""
import json
import sqlite3
import sys
import unicodedata
from pathlib import Path


def _chave_nome(texto):
    s = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return " ".join(s.replace("-", " ").replace("_", " ").split())


def _peso(v):
    try:
        return round(float(v if v is not None else 1.0), 4)
    except (TypeError, ValueError):
        return 1.0


def upgrade(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(projetos)")
        if "modelo_conhecidos" in {r[1] for r in cur.fetchall()}:
            print("  = projetos.modelo_conhecidos ja existia")
        else:
            cur.execute("ALTER TABLE projetos ADD COLUMN modelo_conhecidos TEXT")
            print("  + projetos.modelo_conhecidos adicionada")

        cur.execute("SELECT tipo_projeto, categoria, tipo, peso, responsavel_padrao, chave "
                    "FROM modelos_entregavel ORDER BY tipo_projeto, ordem, id")
        modelos = {}
        for tp, cat, nome, peso, resp, chave in cur.fetchall():
            modelos.setdefault(tp, []).append({
                "chave": chave, "tipo": (nome or "").strip(), "categoria": cat or "",
                "peso": _peso(peso), "responsavel": (resp or "").strip()})

        cur.execute("SELECT id, tipo FROM projetos WHERE modelo_conhecidos IS NULL")
        projetos = cur.fetchall()
        ligados = 0
        for pid, tipo in projetos:
            itens = modelos.get(tipo or "", [])
            cur.execute("SELECT id, tipo, modelo_chave FROM entregaveis WHERE projeto_id = ? "
                        "ORDER BY ordem, id", (pid,))
            ents = cur.fetchall()
            ja = {mc for _, _, mc in ents if mc}
            livres = {}
            for m in itens:
                if m["chave"] not in ja:
                    livres.setdefault(_chave_nome(m["tipo"]), m)
            for eid, nome, mc in ents:
                if mc:
                    continue
                m = livres.pop(_chave_nome(nome), None)
                if m:
                    origem = {k: m[k] for k in ("tipo", "categoria", "peso", "responsavel")}
                    cur.execute("UPDATE entregaveis SET modelo_chave = ?, modelo_origem = ? "
                                "WHERE id = ?", (m["chave"], json.dumps(origem, ensure_ascii=False), eid))
                    ligados += 1
            cur.execute("UPDATE projetos SET modelo_conhecidos = ? WHERE id = ?",
                        (json.dumps(sorted(m["chave"] for m in itens if m["chave"])), pid))
        print(f"  ~ {ligados} entregavel(is) ligado(s) pelo nome; "
              f"{len(projetos)} projeto(s) com a lista de itens conhecidos")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "doctrack.db"
    if not Path(db).exists():
        print(f"DB nao encontrado: {db}")
        sys.exit(1)
    print(f"Aplicando migration 021 em {db}...")
    upgrade(db)
    print("OK")

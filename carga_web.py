"""carga_web.py — a carga por planilha pela tela (Configurações → Carga por planilha).

Antes, a carga só existia como script no servidor: quem fosse usar precisava
de login no Windows do servidor, Área de Trabalho Remota (que derruba quem
estiver conectado) e PowerShell. Aqui é a mesma carga (carga_massa.py), só que
por três rotas, todas exclusivas de admin:

  GET  /api/carga/planilha  baixa a planilha com o que está no banco agora
  POST /api/carga/previa    recebe a planilha editada, executa tudo e desfaz:
                            devolve o relatório e um `token` que guarda ESTA
                            planilha no servidor por uma hora
  POST /api/carga/aplicar   {token, motivo}: faz o backup do banco e grava a
                            mesma planilha da prévia. Se o backup falhar, não
                            grava nada

Aplicar por token, e não reenviando o arquivo, é o que garante que o que grava
é exatamente o que a pessoa viu na prévia. A prévia guardada é de quem a fez:
outro admin não aplica a prévia alheia.
"""
import glob
import os
import secrets
import sqlite3
import subprocess
import threading
import time
from datetime import datetime
from io import BytesIO

from flask import Blueprint, current_app, jsonify, request, send_file
from flask_jwt_extended import get_jwt_identity

from auth import require_role
from carga_massa import ErroCarga, exportar, ler_planilha, processar
from models import db, User

carga_bp = Blueprint("carga", __name__)

ROOT = os.path.dirname(os.path.abspath(__file__))
MAX_BYTES = 10 * 1024 * 1024          # a planilha real tem poucas centenas de KB
VALIDADE_S = 60 * 60                  # a prévia guardada vale uma hora
MOTIVO_MIN, MOTIVO_MAX = 5, 500

_previas = {}                         # token -> {email, nome, conteudo, criada}
_previas_lock = threading.Lock()
_aplicando = threading.Lock()         # uma carga por vez (waitress usa threads)


class ErroBackup(Exception):
    pass


def _admin_atual():
    u = User.query.filter_by(email=get_jwt_identity(), ativo=True).first()
    return u if u is not None and u.role == "admin" else None


def _limpar_vencidas(agora):
    for t in [t for t, p in _previas.items() if agora - p["criada"] > VALIDADE_S]:
        del _previas[t]


# ── backup antes de aplicar ──────────────────────────────────────────────────

def _pasta_backup():
    return current_app.config.get("CARGA_BACKUP_DIR") or os.path.join(ROOT, "backups")


def fazer_backup():
    """Backup completo do banco antes de gravar. Devolve o nome do arquivo.
    PostgreSQL: o mesmo scripts/gerar_backup.ps1 do deploy (pg_dump + espelho
    dos arquivos). SQLite (homologação): cópia consistente do arquivo."""
    pasta = _pasta_backup()
    os.makedirs(pasta, exist_ok=True)
    if db.engine.dialect.name == "sqlite":
        origem = db.engine.url.database
        if not origem or origem == ":memory:":
            raise ErroBackup("banco em memória não tem backup")
        destino = os.path.join(pasta, f"doctrack_carga_{datetime.now():%Y-%m-%d_%H%M%S}.db")
        src, dst = sqlite3.connect(origem), sqlite3.connect(destino)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        return os.path.basename(destino)

    script = os.path.join(ROOT, "scripts", "gerar_backup.ps1")
    inicio = time.time() - 1
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive",
                            "-ExecutionPolicy", "Bypass", "-File", script],
                           capture_output=True, text=True, timeout=600,
                           encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ErroBackup(f"não consegui rodar o backup ({e})")
    novos = [f for f in glob.glob(os.path.join(pasta, "doctrack_*.sql"))
             if os.path.getmtime(f) >= inicio]
    if r.returncode != 0 or not novos:
        saida = ((r.stderr or "") + "\n" + (r.stdout or "")).strip().splitlines()
        raise ErroBackup(" / ".join(saida[-3:]) or f"o backup terminou com código {r.returncode}")
    return os.path.basename(max(novos, key=os.path.getmtime))


# ── rotas ────────────────────────────────────────────────────────────────────

@carga_bp.route("/api/carga/planilha", methods=["GET"])
@require_role("admin")
def baixar_planilha():
    buf = BytesIO()
    exportar(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True,
                     download_name=f"DocTrack_carga_{datetime.now():%Y-%m-%d_%H%M}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@carga_bp.route("/api/carga/previa", methods=["POST"])
@require_role("admin")
def previa():
    u = _admin_atual()
    if u is None:
        return jsonify({"erro": "Só um admin ativo pode usar a carga por planilha"}), 403
    arq = request.files.get("arquivo")
    if arq is None or not arq.filename:
        return jsonify({"erro": "Escolha a planilha (.xlsx) para enviar"}), 400
    if not arq.filename.lower().endswith(".xlsx"):
        return jsonify({"erro": "Envie a planilha no formato .xlsx"}), 400
    conteudo = arq.read(MAX_BYTES + 1)
    if len(conteudo) > MAX_BYTES:
        return jsonify({"erro": "A planilha passa de 10 MB"}), 400

    try:
        rel = processar(ler_planilha(BytesIO(conteudo)), u.email, "Prévia da carga por planilha")
    except ErroCarga as err:
        db.session.rollback()
        return jsonify({"erro": "A planilha tem problemas. Nada foi gravado.",
                        "erros": err.erros}), 422
    finally:
        # A prévia nunca grava: o rollback desfaz modelos, entregáveis,
        # histórico e auditoria que o processamento acabou de escrever.
        db.session.rollback()

    resposta = {"arquivo": arq.filename, "relatorio": rel.como_dict(), "token": None}
    if not rel.como_dict()["vazio"]:
        agora = time.time()
        token = secrets.token_urlsafe(18)
        with _previas_lock:
            _limpar_vencidas(agora)
            # Uma prévia viva por pessoa: a nova substitui a anterior.
            for t in [t for t, p in _previas.items() if p["email"] == u.email]:
                del _previas[t]
            _previas[token] = {"email": u.email, "nome": arq.filename,
                               "conteudo": conteudo, "criada": agora}
        resposta.update(token=token, valida_min=VALIDADE_S // 60)
    return jsonify(resposta), 200


@carga_bp.route("/api/carga/aplicar", methods=["POST"])
@require_role("admin")
def aplicar():
    u = _admin_atual()
    if u is None:
        return jsonify({"erro": "Só um admin ativo pode usar a carga por planilha"}), 403
    data = request.get_json(silent=True) or {}
    token = str(data.get("token") or "")
    motivo = " ".join(str(data.get("motivo") or "").split())
    if not MOTIVO_MIN <= len(motivo) <= MOTIVO_MAX:
        return jsonify({"erro": f"Escreva o motivo da carga ({MOTIVO_MIN} a "
                                f"{MOTIVO_MAX} caracteres). Ele fica no histórico."}), 400

    with _previas_lock:
        _limpar_vencidas(time.time())
        pend = _previas.get(token)
    if pend is None or pend["email"] != u.email:
        return jsonify({"erro": "Esta prévia venceu ou não é sua. Envie a planilha de "
                                "novo para ver a prévia antes de aplicar."}), 409

    if not _aplicando.acquire(blocking=False):
        return jsonify({"erro": "Outra carga está sendo aplicada agora. Espere terminar "
                                "e envie a planilha de novo."}), 409
    try:
        try:
            backup = fazer_backup()
        except ErroBackup as e:
            current_app.logger.error("Carga por planilha: backup falhou: %s", e)
            return jsonify({"erro": f"O backup do banco falhou, então nada foi aplicado. "
                                    f"Avise o administrador do servidor. Detalhe: {e}"}), 503
        try:
            rel = processar(ler_planilha(BytesIO(pend["conteudo"])), u.email, motivo)
            db.session.commit()
        except ErroCarga as err:
            # O banco mudou entre a prévia e o aplicar (outra pessoa mexeu).
            db.session.rollback()
            return jsonify({"erro": "Os dados mudaram depois da prévia e a planilha não "
                                    "passa mais. Nada foi gravado.", "erros": err.erros}), 422
        except Exception:
            db.session.rollback()
            raise
    finally:
        _aplicando.release()

    with _previas_lock:
        _previas.pop(token, None)
    return jsonify({"arquivo": pend["nome"], "relatorio": rel.como_dict(), "backup": backup,
                    "aplicado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
                    "motivo": motivo}), 200

r"""carga_planilha.py — a carga por planilha pela linha de comando, no servidor.

O caminho normal é a tela Configurações → Carga por planilha. Este script
continua para quem está no servidor (ou se a tela estiver fora do ar) e faz a
mesma coisa, com as funções de carga_massa.py:

    .\venv\Scripts\python.exe scripts\carga_planilha.py exportar carga.xlsx
    .\venv\Scripts\python.exe scripts\carga_planilha.py previa carga.xlsx
    .\venv\Scripts\python.exe scripts\carga_planilha.py aplicar carga.xlsx ^
        --motivo "Novos modelos PDR 2027" --por andre@empresa.com

As regras da planilha estão em carga_massa.py e na aba LEIA-ME.
"""
import argparse
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from carga_massa import ErroCarga, exportar, ler_planilha, processar  # noqa: E402


# ── linha de comando ─────────────────────────────────────────────────────────

def _salvar_relatorio(planilha, texto, sufixo):
    base = os.path.splitext(os.path.abspath(planilha))[0]
    caminho = f"{base}_{sufixo}_{datetime.now():%Y%m%d_%H%M%S}.txt"
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(texto)
    return caminho


def main(argv=None):
    ap = argparse.ArgumentParser(description="Edição em massa de modelos e projetos por planilha.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("exportar", help="grava a planilha com o estado atual")
    e.add_argument("planilha")
    pv = sub.add_parser("previa", help="mostra o que mudaria, sem gravar nada")
    pv.add_argument("planilha")
    pv.add_argument("--por", default="", help="e-mail de quem está fazendo (opcional na prévia)")
    a = sub.add_parser("aplicar", help="grava as mudanças da planilha")
    a.add_argument("planilha")
    a.add_argument("--motivo", required=True, help="por que a mudança (fica no histórico)")
    a.add_argument("--por", required=True, help="e-mail de um admin do DocTrack")
    args = ap.parse_args(argv)

    from servidor import app
    from models import db, User
    import killswitch

    with app.app_context():
        if args.cmd == "exportar":
            if os.path.exists(args.planilha):
                print(f"'{args.planilha}' já existe; escolha outro nome para não sobrescrever.")
                return 2
            n = exportar(args.planilha)
            print(f"Planilha gravada em {os.path.abspath(args.planilha)}: {n['modelos']} modelo(s), "
                  f"{n['itens']} item(ns) de modelo, {n['projetos']} projeto(s).")
            return 0

        if args.cmd == "aplicar":
            if killswitch.travado():
                print("O sistema está TRAVADO (kill switch). Destrave antes de aplicar.")
                return 2
            u = User.query.filter_by(email=args.por.strip()).first()
            if u is None or not u.ativo or u.role != "admin":
                print(f"--por '{args.por}' precisa ser o e-mail de um usuário admin ativo.")
                return 2
            motivo = " ".join(args.motivo.split())
            if not 5 <= len(motivo) <= 500:
                print("--motivo deve ter entre 5 e 500 caracteres.")
                return 2
        else:
            motivo = "Prévia da carga por planilha"

        try:
            dados = ler_planilha(args.planilha)
            rel = processar(dados, args.por.strip(), motivo)
        except ErroCarga as err:
            db.session.rollback()
            print("A planilha tem problemas; NADA foi gravado. Corrija e rode de novo:\n")
            for linha in err.erros:
                print(f"  x {linha}")
            return 1
        except Exception:
            db.session.rollback()
            raise

        if args.cmd == "previa":
            db.session.rollback()
            titulo = "PRÉVIA — nada foi gravado"
        else:
            db.session.commit()
            titulo = f"APLICADO por {args.por} em {datetime.now():%d/%m/%Y %H:%M} — {motivo}"
        texto = rel.texto(titulo)
        print(texto)
        print(f"Relatório salvo em {_salvar_relatorio(args.planilha, texto, args.cmd)}")
        return 0


if __name__ == "__main__":
    sys.exit(main())

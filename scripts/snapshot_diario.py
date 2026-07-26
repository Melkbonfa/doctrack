"""snapshot_diario.py — grava as fotos do dia e sai.

Alternativa à thread embutida (scheduler.py) para quem prefere o Agendador de
Tarefas do Windows: mesma lista de tarefas, execução única, código de saída 0
quando tudo passou. Rodar com DOCTRACK_AGENDADOR=0 no serviço evita as duas
coisas concorrendo — não que isso corrompa algo (as tarefas são idempotentes no
dia), mas dobra trabalho por nada.

Uso (a partir da raiz do projeto):

    .\\venv\\Scripts\\python.exe scripts\\snapshot_diario.py

Registrado no deploy por scripts/deploy_windows.ps1 (-ComAgendador).
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from servidor import app, rodar_tarefas_diarias  # noqa: E402


def main():
    inicio = datetime.now()
    print(f"[{inicio.strftime('%d/%m/%Y %H:%M:%S')}] DocTrack — tarefas diárias")
    with app.app_context():
        resultado = rodar_tarefas_diarias()
    for nome, valor in resultado.items():
        print(f"  {nome}: {valor}")
    falhas = [n for n, v in resultado.items() if isinstance(v, str) and v.startswith("erro:")]
    dur = (datetime.now() - inicio).total_seconds()
    print(f"Concluído em {dur:.1f}s" + (f" — {len(falhas)} falha(s)" if falhas else ""))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())

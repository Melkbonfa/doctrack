"""scheduler.py — agendador interno das tarefas diárias do DocTrack.

Por que existir: as séries temporais do sistema (ICE/IDP dos equipamentos,
fotos das missões e dos projetos) precisam de uma medição por dia, e o único
gancho que existia era a subida do servidor. Em produção o serviço fica semanas
no ar, então as tabelas `*_snapshot` tinham exatamente UMA data — os gráficos de
evolução desenhavam um ponto só. Cron externo resolveria, mas não havia nenhum
configurado e depender de um passo manual de deploy é como se chegou aqui.

Desenho deliberadamente simples: uma thread daemon que acorda a cada
`intervalo` segundos e pergunta "as tarefas de hoje já rodaram?". Sem
dependência nova (APScheduler não está no requirements e a rede fabril pode não
ter saída para instalar), sem estado em disco, e tolerante a restart — se o
serviço cair e voltar no mesmo dia, a checagem por data evita rodar de novo, e
as tarefas em si são idempotentes de qualquer forma.

Também é usado por `scripts/snapshot_diario.py`, que roda a mesma lista de
tarefas uma vez e sai (para quem preferir Agendador de Tarefas do Windows em
vez da thread embutida).

Desligue com DOCTRACK_AGENDADOR=0.
"""
import os
import threading
from datetime import date, datetime

# Intervalo entre checagens. Não é a frequência das tarefas (que é diária): é só
# de quanto em quanto tempo a thread verifica se o dia virou.
INTERVALO_PADRAO = int(os.environ.get("DOCTRACK_AGENDADOR_INTERVALO", "900"))

_thread = None
_ultimo_dia = None
_lock = threading.Lock()


def agendador_habilitado():
    return os.environ.get("DOCTRACK_AGENDADOR", "1").lower() not in ("0", "false", "no")


def rodar_uma_vez(app, tarefa, *, forcar=False):
    """Roda a tarefa diária se ela ainda não rodou hoje. Devolve True se rodou.

    `forcar=True` ignora a checagem por data (usado pelo script de linha de
    comando e por um disparo manual).
    """
    global _ultimo_dia
    hoje = date.today()
    with _lock:
        if not forcar and _ultimo_dia == hoje:
            return False
        _ultimo_dia = hoje
    with app.app_context():
        try:
            tarefa()
            return True
        except Exception as e:
            # Uma tarefa que explode não pode derrubar a thread: no próximo dia
            # ela tenta de novo. O erro fica no log do serviço.
            print(f"[WARN] Agendador: tarefa diária falhou — {e}")
            return False


def iniciar_agendador(app, tarefa, intervalo=None):
    """Sobe a thread daemon que executa `tarefa` uma vez por dia.

    Idempotente: chamar duas vezes (o reloader do Flask em debug faz isso) não
    cria uma segunda thread. Daemon de propósito — não deve segurar o shutdown
    do serviço.
    """
    global _thread
    if not agendador_habilitado():
        print("[INFO] Agendador interno desligado (DOCTRACK_AGENDADOR=0)")
        return None
    if _thread is not None and _thread.is_alive():
        return _thread

    espera = intervalo or INTERVALO_PADRAO
    parar = threading.Event()

    def _loop():
        # A primeira execução acontece na subida (junto do init_app), então aqui
        # só marcamos o dia como feito e esperamos a virada.
        while not parar.wait(espera):
            if rodar_uma_vez(app, tarefa):
                print(f"[INFO] Agendador: tarefas diárias de "
                      f"{date.today().isoformat()} executadas "
                      f"({datetime.now().strftime('%H:%M')})")

    _thread = threading.Thread(target=_loop, name="doctrack-agendador", daemon=True)
    _thread.start()
    print(f"[INFO] Agendador interno ativo (checagem a cada {espera}s)")
    return _thread

"""
cadernos/tarefas.py — Trabalho demorado (exportação, importação) fora da requisição.

Gerar o pacote de uma seção grande leva dezenas de segundos e importar um
caderno inteiro leva minutos: segurar a requisição esse tempo todo deixaria a
pessoa olhando para um botão travado. A rota inicia a tarefa, devolve o id, e o
front consulta `GET /cadernos/api/tarefas/<id>` para mostrar o progresso.

O estado fica em memória: o DocTrack roda num processo só (waitress + threads).
Se o serviço reiniciar no meio, a tarefa some e a pessoa refaz — e nada fica
pela metade, porque exportação e importação só gravam o resultado no fim.

A função da tarefa recebe IDs e recarrega tudo do banco: objeto do ORM carregado
na requisição pertence à sessão da requisição e não atravessa a thread.

Com `app.config["TESTING"]`, a tarefa roda na hora, na mesma thread — os testes
ficam determinísticos e veem o resultado logo depois da chamada.
"""
import threading
import time
import uuid as _uuid

from flask import current_app

from models import db

VALIDADE_SEGUNDOS = 6 * 3600
_tarefas = {}
_trava = threading.Lock()


class Tarefa:
    def __init__(self, tipo, user_id):
        self.id = str(_uuid.uuid4())
        self.tipo = tipo
        self.user_id = user_id
        self.estado = "rodando"          # rodando | pronta | erro
        self.feito = 0
        self.total = 0
        self.etapa = "Começando…"
        self.resultado = None
        self.erro = ""
        self.criada_em = time.time()
        self.terminada_em = None

    def progresso(self, feito=None, total=None, etapa=None):
        if feito is not None:
            self.feito = feito
        if total is not None:
            self.total = total
        if etapa is not None:
            self.etapa = etapa

    def to_dict(self):
        return {"id": self.id, "tipo": self.tipo, "estado": self.estado, "feito": self.feito,
                "total": self.total, "etapa": self.etapa, "resultado": self.resultado,
                "erro": self.erro}


def _limpar(agora):
    for k in [k for k, t in _tarefas.items()
              if t.terminada_em and agora - t.terminada_em > VALIDADE_SEGUNDOS]:
        del _tarefas[k]


def em_andamento(tipo):
    with _trava:
        return [t for t in _tarefas.values() if t.tipo == tipo and t.estado == "rodando"]


def iniciar(tipo, user_id, funcao, *args, **kwargs):
    """Roda `funcao(tarefa, *args, **kwargs)` numa thread com app context
    próprio. O retorno (um dict) vira `tarefa.resultado`; uma exceção vira
    `estado="erro"` com a mensagem — a mensagem é mostrada a quem pediu, então
    as funções levantam erros escritos para gente (ver `ErroDaTarefa`)."""
    app = current_app._get_current_object()
    t = Tarefa(tipo, user_id)
    with _trava:
        _limpar(time.time())
        _tarefas[t.id] = t

    def executar():
        try:
            t.resultado = funcao(t, *args, **kwargs)
            t.estado = "pronta"
        except ErroDaTarefa as e:
            db.session.rollback()
            t.estado, t.erro = "erro", str(e)
        except Exception as e:                          # noqa: BLE001 — vira mensagem na tela
            db.session.rollback()
            app.logger.exception("cadernos: tarefa %s falhou", tipo)
            t.estado, t.erro = "erro", f"Falha inesperada: {e.__class__.__name__}: {e}"
        finally:
            t.terminada_em = time.time()

    if app.config.get("TESTING"):
        executar()
        return t

    def rodar():
        with app.app_context():
            try:
                executar()
            finally:
                db.session.remove()

    threading.Thread(target=rodar, daemon=True, name=f"cadernos-{tipo}").start()
    return t


def obter(id_, user_id):
    """A tarefa, só para quem a iniciou."""
    with _trava:
        t = _tarefas.get(id_)
    return t if t and t.user_id == user_id else None


class ErroDaTarefa(Exception):
    """Erro esperado (pacote inválido, permissão...) com mensagem para a tela."""

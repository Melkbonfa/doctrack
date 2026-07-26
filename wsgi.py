"""wsgi.py — entrypoint de produção (waitress / gunicorn / IIS).

Existe porque a preparação do banco saiu do import de `servidor` (ver
`servidor.init_app`): apontar o servidor WSGI direto para `servidor:app`
subiria o app sem criar schema, sem rodar os backfills e sem agendar as fotos
diárias. Use sempre `wsgi:app`:

    waitress-serve --listen=0.0.0.0:5000 wsgi:app

Importar este módulo prepara o banco e sobe o agendador interno — é o efeito
desejado aqui e só aqui.
"""
from servidor import app, socketio, init_app, rodar_tarefas_diarias
from scheduler import iniciar_agendador

init_app()
iniciar_agendador(app, rodar_tarefas_diarias)

# `application` é o nome que alguns hosts (IIS/wfastcgi) procuram por convenção.
application = app

__all__ = ["app", "application", "socketio"]

"""Fixtures pytest para DocTrack v3.

Cada teste roda contra um SQLite em arquivo temporário, com seed mínimo
(admin + gestor + tecnico + leitura + 2 documentos).

Duas decisões que valem a explicação, porque a suíte levava 8min30s para 256
testes e ~82% disso era esta pasta, não código de produção:

1. `BCRYPT_LOG_ROUNDS=4`. O padrão (12) custa 187ms por hash — medido. Com 4
   seeds por teste mais os logins das fixtures de token, davam ~250s só de
   bcrypt. Em teste o custo do hash não protege nada; em produção continua 12.

2. Schema e seed criados UMA vez por sessão em um arquivo modelo, copiado para
   cada teste. O `create_all()` + `drop_all()` por teste custava 644ms (37
   tabelas), ~165s no total. Copiar o arquivo pronto sai em milissegundos e dá
   uma garantia extra: os ids do seed são idênticos em todo teste.

As variáveis de ambiente são definidas ANTES de importar `servidor` de
propósito — inclusive DATABASE_URL. O módulo não escreve mais no banco no
import (ver servidor.init_app), mas apontar para um arquivo temporário garante
que nem um import acidental de outro módulo alcance o doctrack.db real.
"""
import os
import shutil
import sys
import tempfile
import pytest

# Garantir JWT_SECRET antes de importar servidor
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-pytest-32-chars-long")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5000")
# bcrypt no mínimo (4 rounds): 187ms -> 1ms por hash. Produção segue em 12.
os.environ.setdefault("BCRYPT_LOG_ROUNDS", "4")
# Rede de segurança: nenhum caminho de código deve tocar o banco real.
_SENTINELA_DB = os.path.join(tempfile.gettempdir(), "doctrack_pytest_sentinela.db")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_SENTINELA_DB}")
# O agendador interno não tem o que fazer numa suíte de testes.
os.environ.setdefault("DOCTRACK_AGENDADOR", "0")

# Adicionar raiz e scripts/ ao path (importar_entregaveis mora em scripts/)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(1, os.path.join(ROOT, "scripts"))

SEED_USERS = [
    ("Admin Test",   "admin@test.com",   "admin",   "admin123"),
    ("Gestor Test",  "gestor@test.com",  "gestor",  "demo123"),
    ("Tecnico Test", "tecnico@test.com", "tecnico", "demo123"),
    ("Leitura Test", "leitura@test.com", "leitura", "demo123"),
]


def _semear(db):
    """Popula o banco modelo. Só é executado uma vez por sessão."""
    from models import User, Documento

    for nome, email, role, senha in SEED_USERS:
        u = User(nome=nome, email=email, role=role, ativo=True)
        u.set_senha(senha)
        db.session.add(u)

    docs = [
        Documento(setor="PRE", equipamento="MAQ-A", documento="POP-001", sku="SKU-A",
                  codigo_doc="COD-A", responsavel="Carlos Mota", status="Homologado",
                  armazenamento="P:/Qualidade/POP-001.pdf"),
        Documento(setor="Manuais", equipamento="MAQ-B", documento="Manual-002", sku="SKU-B",
                  codigo_doc="COD-B", status="Em andamento", tipo_doc="Manual_Usuario",
                  fabricante="Siemens", armazenamento="P:/Tecnico/Manual-002.pdf"),
    ]
    for d in docs:
        db.session.add(d)

    db.session.commit()


@pytest.fixture(scope="session")
def _banco_modelo(tmp_path_factory):
    """Arquivo SQLite com schema + seed prontos, criado uma vez por sessão."""
    from sqlalchemy import create_engine
    from servidor import app as flask_app
    from models import db

    caminho = tmp_path_factory.mktemp("modelo") / "modelo.db"
    engine = create_engine(f"sqlite:///{caminho}")
    with flask_app.app_context():
        db.engines[None] = engine
        db.create_all()
        _semear(db)
        db.session.remove()
    engine.dispose()      # libera o arquivo no Windows antes de ser copiado
    return str(caminho)


@pytest.fixture
def app(tmp_path, _banco_modelo):
    """App Flask com DB isolado por teste (cópia do banco modelo)."""
    from sqlalchemy import create_engine
    from servidor import app as flask_app
    from models import db

    db_file = tmp_path / "test.db"
    shutil.copyfile(_banco_modelo, db_file)

    flask_app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_file}"
    flask_app.config["TESTING"] = True

    engine = create_engine(f"sqlite:///{db_file}")
    with flask_app.app_context():
        db.engines[None] = engine
        yield flask_app
        db.session.remove()
    engine.dispose()


@pytest.fixture(autouse=True)
def _limpar_ratelimit():
    """Zera o contador de tentativas entre testes.

    O estado do rate limit é de módulo (um processo, um dicionário), então sem
    isto um teste que erra a senha de propósito influenciaria o próximo.
    """
    import ratelimit
    ratelimit.resetar()
    yield
    ratelimit.resetar()


@pytest.fixture
def client(app):
    return app.test_client()


def _login(client, email, senha):
    res = client.post("/api/auth/login", json={"email": email, "senha": senha})
    assert res.status_code == 200, f"Login falhou: {res.get_json()}"
    return res.get_json()["access_token"]


@pytest.fixture
def admin_token(client):
    return _login(client, "admin@test.com", "admin123")


@pytest.fixture
def gestor_token(client):
    return _login(client, "gestor@test.com", "demo123")


@pytest.fixture
def tecnico_token(client):
    return _login(client, "tecnico@test.com", "demo123")


@pytest.fixture
def leitura_token(client):
    return _login(client, "leitura@test.com", "demo123")


@pytest.fixture
def auth_headers():
    def _make(token):
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    return _make

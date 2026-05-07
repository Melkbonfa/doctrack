"""Fixtures pytest para DocTrack v3.

Cada teste roda contra um SQLite em arquivo temporário, com seed mínimo
(admin + gestor + tecnico + leitura + 3 documentos).
"""
import os
import sys
import tempfile
import pytest

# Garantir JWT_SECRET antes de importar servidor
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-pytest-32-chars-long")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5000")

# Adicionar raiz ao path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture
def app(tmp_path):
    """App Flask com DB isolado por teste (arquivo em tmp_path)."""
    from servidor import app as flask_app
    from models import db, User, Documento

    db_file = tmp_path / "test.db"
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_file}"
    flask_app.config["TESTING"] = True

    with flask_app.app_context():
        # Recriar tabelas no DB de teste
        db.engine.dispose()
        db.create_all()

        # Seed users
        seed_users = [
            ("Admin Test",   "admin@test.com",   "admin",   "admin123"),
            ("Gestor Test",  "gestor@test.com",  "gestor",  "demo123"),
            ("Tecnico Test", "tecnico@test.com", "tecnico", "demo123"),
            ("Leitura Test", "leitura@test.com", "leitura", "demo123"),
        ]
        for nome, email, role, senha in seed_users:
            u = User(nome=nome, email=email, role=role, ativo=True)
            u.set_senha(senha)
            db.session.add(u)

        # Seed documentos
        docs = [
            Documento(equipamento="MAQ-A", documento="POP-001", categoria="Qualidade",
                      origem="Producao", versao="1.0", tipo_documento="Qualidade", subtipo="POP",
                      etapa_elaboracao="Concluído", etapa_revisao1="Concluído",
                      etapa_diagramacao="Concluído", etapa_revisao2="Concluído"),
            Documento(equipamento="MAQ-B", documento="IT-002", categoria="Tecnico",
                      origem="P&D", versao="2.1", tipo_documento="Técnico", subtipo="IT",
                      etapa_elaboracao="Em andamento", etapa_revisao1="Pendente",
                      etapa_diagramacao="Pendente", etapa_revisao2="Pendente"),
            Documento(equipamento="MAQ-C", documento="Manual-003", categoria="Documentacao",
                      origem="Producao", versao="", tipo_documento="Técnico", subtipo="Manual",
                      etapa_elaboracao="Pendente", etapa_revisao1="Pendente",
                      etapa_diagramacao="Pendente", etapa_revisao2="Pendente"),
        ]
        for d in docs:
            db.session.add(d)

        db.session.commit()

        yield flask_app

        db.session.remove()
        db.drop_all()


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

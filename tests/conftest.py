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
        # Substituir o engine padrão pelo banco de testes
        from sqlalchemy import create_engine
        db.engines[None] = create_engine(f"sqlite:///{db_file}")
        # Recriar tabelas no DB de teste
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

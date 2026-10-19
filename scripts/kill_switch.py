r"""kill_switch.py — operação da trava de emergência do DocTrack.

Três coisas, nesta ordem de uso (pelo Python do venv — o `python` do PATH não
tem as dependências do projeto):

    .\venv\Scripts\python scripts\kill_switch.py hash      gera os dois segredos
    .\venv\Scripts\python scripts\kill_switch.py lock      trava o sistema
    .\venv\Scripts\python scripts\kill_switch.py unlock    destrava
    .\venv\Scripts\python scripts\kill_switch.py status    só consulta

`lock`, `unlock` e `status` aceitam `--url https://SEU-SERVIDOR` (padrão:
$DOCTRACK_URL, ou localhost:5000).

`hash` é o passo de instalação: pede o token do gatilho e a senha-mestra, imprime
os hashes bcrypt para colar no .env (ou no painel do Render) e não guarda nada.

`lock`/`unlock` são conveniência — do outro lado é só um POST, e é de propósito
que seja: numa emergência você pode não ter este repositório à mão, e um curl do
celular precisa bastar:

    curl -X POST https://SEU-SERVIDOR/api/kill-switch/lock \
         -H "X-Kill-Token: SEU_TOKEN" \
         -H "Content-Type: application/json" \
         -d '{"motivo":"credencial vazada"}'

Nenhum subcomando aceita o segredo por argumento: linha de comando fica no
histórico do shell e na lista de processos da máquina.
"""
import argparse
import getpass
import json
import os
import secrets
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


# ── GERAÇÃO DOS SEGREDOS ──────────────────────────────────────────────────────

def _checar_dependencias():
    """Confere flask/flask-bcrypt ANTES de pedir os segredos.

    O hash só é gerado no fim, depois de digitar token e senha duas vezes cada.
    Descobrir ali que o `python` do PATH não é o do venv custa a sessão inteira
    — e é o erro mais provável, porque `python scripts/kill_switch.py` é o que
    está escrito em toda a documentação.
    """
    try:
        import flask                      # noqa: F401
        import flask_bcrypt               # noqa: F401
        return True
    except ModuleNotFoundError as erro:
        exe = os.path.join(ROOT, "venv", "Scripts", "python.exe")
        if not os.path.exists(exe):
            exe = os.path.join(ROOT, "venv", "bin", "python")
        print(f"ERRO: dependencia ausente ({erro.name}).")
        print(f"Este Python ({sys.executable}) nao e o do projeto.")
        print("\nRode pelo venv:\n")
        print(f'  "{exe}" scripts/kill_switch.py hash')
        return False


def _bcrypt_hash(valor):
    """Usa o mesmo bcrypt do app, com o custo de PRODUÇÃO (12).

    Explicitamente 12 e não o que estiver em BCRYPT_LOG_ROUNDS: se este script
    rodar num shell com a variável baixada para testes, o hash sairia fraco e
    ninguém perceberia — ele é colado no .env e vive lá por anos.
    """
    from flask import Flask
    from models import bcrypt

    app = Flask(__name__)
    app.config["BCRYPT_LOG_ROUNDS"] = 12
    bcrypt.init_app(app)
    with app.app_context():
        return bcrypt.generate_password_hash(valor).decode()


def _pedir(rotulo, minimo):
    while True:
        valor = getpass.getpass(f"{rotulo}: ")
        if len(valor) < minimo:
            print(f"  ! precisa de pelo menos {minimo} caracteres")
            continue
        if valor != getpass.getpass(f"{rotulo} (confirme): "):
            print("  ! não conferiu, tente de novo")
            continue
        return valor


CHAVES = ("DOCTRACK_KILL_TOKEN_HASH", "DOCTRACK_UNLOCK_HASH")


def _escrever_env(caminho, valores):
    """Grava (ou substitui) as duas chaves no .env, preservando o resto.

    Existe porque copiar hash na mão erra: no PowerShell, `Add-Content` sem
    aspas SIMPLES faz o shell expandir o `$2b$12$...` como variável e a linha
    chega vazia ou pela metade — sem erro nenhum, e o app só reclama depois, com
    "kill switch não configurado". Aqui o valor nunca passa pelo shell.

    ASCII e sem BOM: hash bcrypt não tem acento, e o BOM entraria no nome da
    primeira chave (o python-dotenv leria "<BOM>JWT_SECRET"). Mesmo cuidado que
    o deploy_windows.ps1 já toma ao criar o arquivo.
    """
    caminho = os.path.abspath(caminho)
    linhas = []
    if os.path.exists(caminho):
        backup = caminho + ".bak"
        with open(caminho, encoding="utf-8-sig") as arq:
            original = arq.read()
        with open(backup, "w", encoding="ascii", newline="\n") as arq:
            arq.write(original)
        print(f"  = backup em {backup}")
        # Descarta versões anteriores das duas chaves (inclusive as truncadas
        # por uma tentativa manual) para não deixar duplicata no arquivo.
        linhas = [l for l in original.splitlines()
                  if not l.strip().startswith(tuple(c + "=" for c in CHAVES))]

    for chave in CHAVES:
        linhas.append(f"{chave}={valores[chave]}")

    with open(caminho, "w", encoding="ascii", newline="\n") as arq:
        arq.write("\n".join(linhas) + "\n")
    print(f"  + {caminho} atualizado ({len(CHAVES)} chaves)")


def cmd_hash(args):
    if not _checar_dependencias():
        return 2

    print(__doc__.strip().splitlines()[0])
    print()
    print("O TOKEN dispara a trava (vai no header X-Kill-Token, pode ficar num")
    print("gerenciador de senhas no celular). A SENHA-MESTRA destrava e é a única")
    print("forma de voltar — guarde-a fora do servidor e fora do banco.")
    print()
    print(f"Sugestão de token: {secrets.token_urlsafe(32)}")
    print()

    token = _pedir("Token do gatilho", 24)
    senha = _pedir("Senha-mestra de desbloqueio", 12)

    print("\nGerando hashes (bcrypt, 12 rounds)...\n")
    valores = {
        "DOCTRACK_KILL_TOKEN_HASH": _bcrypt_hash(token),
        "DOCTRACK_UNLOCK_HASH":     _bcrypt_hash(senha),
    }

    if args.escrever:
        _escrever_env(args.escrever, valores)
        print()
        print("Reinicie o serviço para valer (PowerShell como Administrador):")
        print("    Restart-Service DocTrack")
        print("Depois confirme com:")
        print("    .\\venv\\Scripts\\python scripts\\kill_switch.py status")
    else:
        print("Cole no .env do servidor (ou no painel de variáveis do Render):\n")
        for chave, valor in valores.items():
            print(f"{chave}={valor}")
        print()
        print("No PowerShell, use ASPAS SIMPLES ao colar — sem elas o shell")
        print("expande o $ do hash e a linha chega vazia. Ou deixe o script")
        print("escrever por você:  ... hash --escrever .env")
        print()
        print("Reinicie o serviço depois de salvar. Sem as DUAS variáveis o gatilho")
        print("recusa travar — travar sem senha de volta é destruir, não proteger.")
    return 0


# ── DISPARO REMOTO ────────────────────────────────────────────────────────────

def _chamar(url, caminho, corpo=None, headers=None, metodo="POST"):
    destino = url.rstrip("/") + caminho
    dados = json.dumps(corpo or {}).encode() if metodo == "POST" else None
    req = urllib.request.Request(destino, data=dados, method=metodo)
    req.add_header("Content-Type", "application/json")
    for chave, valor in (headers or {}).items():
        req.add_header(chave, valor)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as erro:
        corpo_erro = erro.read().decode() or "{}"
        try:
            return erro.code, json.loads(corpo_erro)
        except ValueError:
            return erro.code, {"erro": corpo_erro[:200]}
    except Exception as erro:
        return 0, {"erro": f"falha de conexão: {erro}"}


def _relatar(status, corpo):
    if status == 0:
        print(f"ERRO: {corpo.get('erro')}")
        return 2
    print(f"HTTP {status}")
    for chave, valor in corpo.items():
        print(f"  {chave}: {valor}")
    return 0 if 200 <= status < 300 else 1


def cmd_lock(args):
    token = os.environ.get("DOCTRACK_KILL_TOKEN") or getpass.getpass("Token do gatilho: ")
    motivo = args.motivo or input("Motivo (aparece na tela de bloqueio): ").strip()
    status, corpo = _chamar(args.url, "/api/kill-switch/lock",
                            {"motivo": motivo}, {"X-Kill-Token": token})
    return _relatar(status, corpo)


def cmd_unlock(args):
    senha = getpass.getpass("Senha-mestra de desbloqueio: ")
    status, corpo = _chamar(args.url, "/api/kill-switch/unlock", {"senha": senha})
    codigo = _relatar(status, corpo)
    if codigo == 0:
        print("\nTodas as sessões abertas antes da trava foram encerradas.")
    return codigo


def cmd_status(args):
    return _relatar(*_chamar(args.url, "/api/kill-switch/status", metodo="GET"))


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Trava de emergência do DocTrack.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    subs = parser.add_subparsers(dest="comando", required=True)

    p_hash = subs.add_parser("hash", help="gera os hashes dos dois segredos")
    p_hash.add_argument("--escrever", metavar="ENV", nargs="?", const=".env",
                        help="grava as duas chaves direto no .env informado "
                             "(padrão: .env na raiz do projeto), com backup")
    p_hash.set_defaults(fn=cmd_hash)

    def _com_url(nome, ajuda, fn):
        p = subs.add_parser(nome, help=ajuda)
        p.add_argument("--url", default=os.environ.get("DOCTRACK_URL", "http://localhost:5000"),
                       help="endereço do servidor (padrão: $DOCTRACK_URL ou localhost:5000)")
        p.set_defaults(fn=fn)
        return p

    _com_url("lock", "trava o sistema", cmd_lock).add_argument(
        "--motivo", default="", help="motivo mostrado na tela de bloqueio")
    _com_url("unlock", "destrava o sistema", cmd_unlock)
    _com_url("status", "consulta o estado da trava", cmd_status)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())

"""
scripts/importar_onenote.py — Importa para o módulo Cadernos um pacote gerado por
scripts/onenote/extrair_onenote.ps1.

Uso:
    python scripts/importar_onenote.py PACOTE --dono EMAIL [--area pdr] [--nome "..."]
           [--simular] [--arquivo-morto PASTA]
           [--banco sqlite:///caminho.db --arquivos PASTA]   # alvo de teste
           [--producao]                                       # alvo = PostgreSQL do .env

  --simular        converte tudo e mostra o relatório, sem gravar nada (nem precisa de banco).
  --arquivo-morto  pasta com os .one/.onetoc2 do caderno: entram como "Arquivos do
                   caderno" (pasta "OneNote original"), fora da exportação. Sem ela,
                   vale a pasta originais_onenote/ do pacote, se houver.

A gravação em si é a mesma da tela "Importar do OneNote": cadernos/importacao.py.

Travas, porque a máquina de desenvolvimento deste projeto é o servidor de produção:
  * PostgreSQL só com --producao explícito;
  * --banco exige --arquivos, para os blobs de um banco de teste não caírem na
    pasta de arquivos de produção (e vice-versa);
  * as tabelas do módulo precisam já existir (quem cria schema é o servidor,
    ADR-0002), senão o script para antes de escrever qualquer coisa.

Reimportar é seguro: caderno, seções e páginas são achados pela chave de origem
(`importador_onenote.chave_origem`). Página já existente que NUNCA foi editada no
DocTrack (versão 1) é atualizada; editada, é pulada e listada no relatório.
"""
import argparse
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)


def _args():
    p = argparse.ArgumentParser(description="Importa um caderno do OneNote para o DocTrack.")
    p.add_argument("pacote")
    p.add_argument("--dono", help="e-mail do usuário dono do caderno no DocTrack")
    p.add_argument("--area", default="pdr")
    p.add_argument("--nome", help="nome do caderno no DocTrack (padrão: o do OneNote)")
    p.add_argument("--simular", action="store_true")
    p.add_argument("--arquivo-morto", dest="arquivo_morto")
    p.add_argument("--banco")
    p.add_argument("--arquivos")
    p.add_argument("--producao", action="store_true")
    return p.parse_args()


def _relatorio(man, convertidas):
    from cadernos.importacao import contar
    c, autores, avisos = contar(man, convertidas)
    print(f"\nCaderno: {man['caderno']['nome']}  ({len(man['secoes'])} seções)")
    for k, v in c.items():
        print(f"  {k:<20} {v}")
    print(f"  autores no OneNote   {', '.join(autores)}")
    for a in avisos:
        print(f"  AVISO: {a}")


def main():
    # Console do Windows (cp1252) não imprime tudo que vem do OneNote.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = _args()
    # O ambiente vem ANTES de qualquer import do projeto: arquivos_store lê
    # DOCTRACK_ARQUIVOS no import, e o conversor já importa o pacote cadernos.
    # (Foi assim que a primeira execução apontou para a pasta de produção.)
    if a.banco:
        if not a.arquivos:
            sys.exit("--banco exige --arquivos (pasta dos blobs desse banco).")
        os.environ["DATABASE_URL"] = a.banco
    if a.arquivos:
        os.environ["DOCTRACK_ARQUIVOS"] = a.arquivos
    os.environ.setdefault("DOCTRACK_AGENDADOR", "0")
    from cadernos import importacao
    from cadernos.tarefas import ErroDaTarefa
    try:
        man = importacao.ler_manifesto(a.pacote)
    except ErroDaTarefa as e:
        sys.exit(str(e))
    convertidas = importacao.converter(a.pacote, man)
    _relatorio(man, convertidas)
    if a.simular:
        print("\n--simular: nada foi gravado.")
        return

    if not a.dono:
        sys.exit("Informe --dono (e-mail do dono do caderno no DocTrack).")

    from servidor import app                       # import não escreve no banco
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    print(f"\nAlvo: {uri.split('@')[-1] if '@' in uri else uri}")
    if uri.startswith("postgresql") and not a.producao:
        sys.exit("O alvo é PostgreSQL (produção?). Para gravar nele, rode de novo com --producao.")
    if not uri.startswith("postgresql") and not a.banco:
        sys.exit("Sem --banco e sem PostgreSQL: alvo ambíguo. Use --banco/--arquivos ou --producao.")

    import arquivos_store
    print(f"Arquivos: {arquivos_store.RAIZ}")
    if a.arquivos and os.path.abspath(arquivos_store.RAIZ) != os.path.abspath(a.arquivos):
        sys.exit(f"A pasta de arquivos efetiva ({arquivos_store.RAIZ}) não é a pedida ({a.arquivos}). "
                 "Nada foi gravado.")

    with app.app_context():
        _gravar(a, man, convertidas)


def _gravar(a, man, convertidas):
    from models import User
    from cadernos import importacao
    from cadernos.tarefas import ErroDaTarefa

    dono = User.query.filter_by(email=a.dono, ativo=True).first()
    if not dono:
        sys.exit(f"Usuário {a.dono} não encontrado ou inativo.")
    if not dono.tem_area(a.area):
        sys.exit(f"{a.dono} não tem a área '{a.area}'.")
    originais = a.arquivo_morto or os.path.join(a.pacote, "originais_onenote")
    try:
        rel = importacao.gravar(a.pacote, man, convertidas, dono=dono, area=a.area, nome=a.nome,
                                originais=originais, log=print)
    except ErroDaTarefa as e:
        sys.exit(str(e))
    with open(os.path.join(a.pacote, "relatorio_importacao.json"), "w", encoding="utf-8") as fh:
        json.dump(rel, fh, ensure_ascii=False, indent=2)
    print(f"\nPronto: {rel['criadas']} páginas criadas, {rel['atualizadas']} atualizadas, "
          f"{len(rel['puladas_editadas_no_doctrack'])} puladas (editadas no DocTrack). "
          f"Caderno {rel['caderno']['uuid']}.")


if __name__ == "__main__":
    main()

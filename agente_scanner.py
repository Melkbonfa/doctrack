"""
agente_scanner.py — Scanner de Arquivos para DocTrack v3 Enterprise
Valida existência e organização de documentos no filesystem.
"""

import os
import json
from datetime import datetime

BASE_DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "documentos")

DIRECTORY_STRUCTURE = {
    "Tecnico":    ["Manual_Usuario", "Manual_Servico"],
    "Qualidade":  ["POP", "IT"],
    "Engenharia": ["P&D"],
}

VALID_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".ppt", ".pptx", ".dwg", ".dxf", ".txt",
}

KEYWORD_MAP = {
    "manual": "Manual",
    "pop": "POP",
    "it": "IT",
    "instrução": "IT",
    "procedimento": "POP",
}

KEYWORD_MAP_FAB = {
    "fabricante": "Fabricante",
    "fornecedor": "Fornecedor",
}


def ensure_directory_structure():
    """Cria a estrutura de diretórios padrão se não existir."""
    os.makedirs(BASE_DOCS_DIR, exist_ok=True)
    for tipo, subtipos in DIRECTORY_STRUCTURE.items():
        tipo_dir = os.path.join(BASE_DOCS_DIR, tipo)
        os.makedirs(tipo_dir, exist_ok=True)
        for subtipo in subtipos:
            os.makedirs(os.path.join(tipo_dir, subtipo), exist_ok=True)


def validate_file_location(doc):
    """Valida se um documento tem o arquivo correspondente cadastrado e acessível."""
    issues = []
    armazenamento = doc.get("armazenamento", "")
    documento_id = doc.get("id")
    documento_nome = doc.get("documento", "")

    if not armazenamento:
        issues.append({
            "tipo": "SEM_LOCAL",
            "mensagem": f"Documento '{documento_nome}' sem local de armazenamento definido",
            "documento_id": documento_id,
            "severidade": "warning",
        })
        return issues

    if not os.path.exists(armazenamento):
        issues.append({
            "tipo": "ARQUIVO_NAO_ENCONTRADO",
            "mensagem": f"Arquivo não encontrado no caminho: {armazenamento}",
            "documento_id": documento_id,
            "severidade": "error",
        })

    return issues


def get_directory_tree():
    """Retorna a árvore de diretórios de documentos."""
    tree = {}
    if not os.path.exists(BASE_DOCS_DIR):
        return tree
    for tipo in sorted(os.listdir(BASE_DOCS_DIR)):
        tipo_path = os.path.join(BASE_DOCS_DIR, tipo)
        if not os.path.isdir(tipo_path):
            continue
        tree[tipo] = {}
        for subtipo in sorted(os.listdir(tipo_path)):
            sub_path = os.path.join(tipo_path, subtipo)
            if not os.path.isdir(sub_path):
                continue
            files = [
                f for f in os.listdir(sub_path)
                if os.path.isfile(os.path.join(sub_path, f))
                and os.path.splitext(f)[1].lower() in VALID_EXTENSIONS
            ]
            tree[tipo][subtipo] = {"count": len(files), "files": files[:50]}
    return tree


def scan_documents(documents):
    """Escaneia todos os documentos e retorna inconsistências."""
    ensure_directory_structure()
    all_issues = []
    stats = {
        "total_verificados": len(documents),
        "com_local": 0,
        "sem_local": 0,
        "arquivos_encontrados": 0,
        "arquivos_nao_encontrados": 0,
        "diretorio_incorreto": 0,
    }

    for doc in documents:
        armazenamento = doc.get("armazenamento", "")
        if armazenamento:
            stats["com_local"] += 1
        else:
            stats["sem_local"] += 1

        issues = validate_file_location(doc)
        for issue in issues:
            if issue["tipo"] == "ARQUIVO_NAO_ENCONTRADO":
                stats["arquivos_nao_encontrados"] += 1
            elif issue["tipo"] == "DIRETORIO_INCORRETO":
                stats["diretorio_incorreto"] += 1

        if armazenamento and os.path.exists(armazenamento):
            stats["arquivos_encontrados"] += 1

        all_issues.extend(issues)

    return {
        "timestamp": datetime.now().isoformat(),
        "stats": stats,
        "issues": all_issues,
        "directory_structure": get_directory_tree(),
    }


def discover_files():
    """Descobre arquivos no diretório de documentos."""
    ensure_directory_structure()
    discovered = []
    for root, _dirs, files in os.walk(BASE_DOCS_DIR):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext not in VALID_EXTENSIONS:
                continue
            full = os.path.join(root, f)
            discovered.append({
                "filename": f,
                "path": full,
                "relative_path": os.path.relpath(full, BASE_DOCS_DIR),
                "size": os.path.getsize(full),
                "extension": ext,
                "modified": datetime.fromtimestamp(os.path.getmtime(full)).isoformat(),
            })
    return {
        "timestamp": datetime.now().isoformat(),
        "base_dir": BASE_DOCS_DIR,
        "total_files": len(discovered),
        "files": discovered,
    }


def save_discovery_report(report):
    """Salva relatório de descoberta em JSON."""
    report_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
    os.makedirs(report_dir, exist_ok=True)
    filename = f"discovery_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    filepath = os.path.join(report_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return filepath


# ── Legacy compatibility ──────────────────────────────────────────────────────

class ScanResult:
    def __init__(self, erros=None, stats=None):
        self.erros = erros or []
        self.stats = stats or {}

    def to_dict(self):
        return {"erros": self.erros, "stats": self.stats}


def run_scan():
    """Legacy scan function for backward compatibility."""
    from models import Documento
    docs = [d.to_dict() for d in Documento.query.all()]
    result = scan_documents(docs)
    return ScanResult(erros=result["issues"], stats=result["stats"])

"""
areas.py — Registro central das Áreas de P&D do DocTrack.

Fonte única de verdade para o hub, os sub-hubs, os checkboxes de área no
cadastro de usuário e os selos. Adicionar uma nova área da empresa = adicionar
uma entrada em AREAS (e, se tiver módulos próprios, preencher "modulos").

Campos de cada área:
  slug    — identificador estável (vai para users.areas e para as rotas)
  nome    — rótulo exibido no card do hub
  sub     — subtítulo curto (maiúsculas)
  accent  — cor de acento do card (hex)
  home    — para onde o card do hub leva (sub-hub ou app da área)
  icon    — markup interno do <svg> (sem a tag <svg>), herda currentColor
  modulos — módulos da área para o sub-hub: {label, url, role, icon}
            role=None: visível a qualquer membro da área; "gestor": admin/gestor;
            "tecnico": técnico pra cima (esconde de `leitura`).
"""

# Ícones (markup interno do <svg viewBox="0 0 24 24">), na linha do hub atual.
_IC_DOCS = ('<path d="M14 3v4a1 1 0 0 0 1 1h4"/>'
            '<path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z"/>'
            '<path d="M9 13h6"/><path d="M9 17h6"/>')
_IC_PROJ = ('<rect x="9" y="3" width="6" height="4" rx="2"/>'
            '<path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2"/>'
            '<path d="M9 12l1.5 1.5L13 11"/><path d="M9 16l1.5 1.5L13 15"/>')
_IC_EQUIP = ('<path d="M14 3v4a1 1 0 0 0 1 1h4"/>'
             '<path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z"/>'
             '<path d="M9 13h6"/><path d="M9 17h6"/>')
_IC_REAG = ('<path d="M9 3h6"/>'
            '<path d="M10 3v6.5L5.2 18a2 2 0 0 0 1.7 3h10.2a2 2 0 0 0 1.7-3L14 9.5V3"/>'
            '<path d="M8 14h8"/>')
_IC_EQUIP_MOD = ('<rect x="4" y="4" width="16" height="16" rx="2"/>'
                 '<path d="M9 9h6v6H9z"/><path d="M9 2v2"/><path d="M15 2v2"/>'
                 '<path d="M9 20v2"/><path d="M15 20v2"/><path d="M2 9h2"/>'
                 '<path d="M2 15h2"/><path d="M20 9h2"/><path d="M20 15h2"/>')
_IC_MISSOES = ('<rect x="3" y="4" width="5" height="16" rx="1.5"/>'
               '<rect x="10" y="4" width="5" height="10" rx="1.5"/>'
               '<rect x="17" y="4" width="4" height="13" rx="1.5"/>')


AREAS = [
    {
        "slug": "pde",
        "nome": "P&D Equipamentos",
        "sub": "DOCUMENTOS · PROJETOS · MISSÕES",
        "accent": "#22d3ee",
        "home": "/hub/pde",
        "icon": _IC_EQUIP,
        "modulos": [
            {"label": "Equipamentos", "url": "/equipamentos", "role": None, "module": "equip", "icon": _IC_EQUIP_MOD},
            {"label": "Documentos", "url": "/", "role": None, "module": "docs", "icon": _IC_DOCS},
            {"label": "Projetos", "url": "/projetos", "role": "gestor", "module": "ent", "icon": _IC_PROJ},
            {"label": "Missões", "url": "/missoes", "role": "tecnico", "module": "missoes", "icon": _IC_MISSOES},
        ],
    },
    {
        "slug": "pdr",
        "nome": "P&D Reagentes",
        "sub": "REAGENTES",
        "accent": "#a855f7",
        "home": "/pdr/",
        "icon": _IC_REAG,
        # Módulos do PDR (Dashboard/Documentos/Projetos) vivem dentro do app /pdr.
        "modulos": [],
    },
]

AREA_SLUGS = [a["slug"] for a in AREAS]


def get_area(slug):
    for a in AREAS:
        if a["slug"] == slug:
            return a
    return None


def parse_areas(valor):
    """Converte o CSV de users.areas em lista de slugs válidos (preserva ordem)."""
    if not valor:
        return []
    out = []
    for s in str(valor).split(","):
        s = s.strip().lower()
        if s in AREA_SLUGS and s not in out:
            out.append(s)
    return out


def dump_areas(slugs):
    """Serializa uma lista de slugs (já validados) para o CSV de users.areas."""
    vistos = []
    for s in (slugs or []):
        s = str(s).strip().lower()
        if s in AREA_SLUGS and s not in vistos:
            vistos.append(s)
    return ",".join(vistos)

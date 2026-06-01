# Spec: Redesign da Aba Documentos + Tema Claro/Escuro

**Data:** 2026-06-01  
**Status:** Aprovado para implementação

---

## Escopo

Duas mudanças independentes no DocTrack v4.0:

1. **Redesign da aba Documentos** — substituir tabela por grade de cards de equipamento com modal rico e editável
2. **Modo claro/escuro** — toggle global de tema persistido no localStorage

---

## 1. Remoção do setor PDE

Remover completamente toda referência ao setor PDE do sistema.

### Backend (models.py / servidor.py)
- Remover `"PDE"` da constante `SETORES`
- Remover `STATUS_PDE` das constantes
- Remover lógica de `status_global` para PDE no método `Documento.to_dict()`
- Remover cálculo de métricas PDE em `GET /api/metrics` e `GET /api/data`
- O endpoint `GET /api/documentos?setor=PDE` pode continuar existindo (retorna lista vazia); não é necessário bloquear

### Frontend (app.js / dashboard.html)
- Remover aba "PDE" da página Documentos
- Remover fatia PDE do gráfico de distribuição por setor (dashboard)
- Remover barras PDE do gráfico de status por setor (dashboard)
- Remover coluna/referência PDE dos KPIs globais
- Remover opção PDE do dropdown de setor no modal de criação de documento
- Remover botão "+ Novo Doc PDE"

### Dados existentes
- Documentos com `setor="PDE"` existentes no banco não são deletados — ficam inativos visualmente (não aparecem na UI). Nenhuma migração de dados necessária.

---

## 2. Grade de equipamentos

### 2.1 Estrutura da página Documentos

Substituir a tabela com tabs (PRE | Manuais | PDE) por uma grade unificada de cards de equipamento.

**Barra de controles (topo da página):**
- Campo de busca de texto: filtra por `equipamento`, `SKU`, `fabricante`
- Chips de filtro rápido (um ativo por vez, padrão = "Todos"):
  - `Todos · N`
  - `Pendente · N` — equipamentos com pelo menos um documento em status inicial (Elaborar)
  - `Em progresso · N` — pelo menos um em andamento, nenhum pendente
  - `Finalizado · N` — IT/PRE homologado E todos os 5 manuais concluídos
  - `IT/PRE pendente · N` — status PRE = "Elaborar"
  - `Manuais incompletos · N` — manuais concluídos < 5
- Botão `+ Novo equipamento` (oculto para role `leitura`)

**Contadores nos chips** são recalculados sempre que a lista de equipamentos muda (WebSocket ou reload).

### 2.2 Card de equipamento

Cada card representa um equipamento único (agrupado por `equipamento + SKU`).

```
┌─────────────────────────────────┐  ← borda topo: verde/amarelo/vermelho
│  Nome do equipamento            │
│  SKU-001 · Fabricante           │
│  ┌──────────────┬─────────────┐ │
│  │   IT / PRE   │   Manuais   │ │
│  │  Homologado  │    3 / 5    │ │
│  └──────────────┴─────────────┘ │
└─────────────────────────────────┘
```

**Cor da borda superior (status global do equipamento):**
- Vermelho: IT/PRE = "Elaborar" OU manuais concluídos = 0
- Amarelo: qualquer documento em andamento (nem tudo pendente, nem tudo finalizado)
- Verde: IT/PRE = "Homologado" E manuais concluídos = 5

**Regra de precedência:** vermelho > amarelo > verde.

**Campos visíveis no card:**
- Nome do equipamento
- SKU
- Fabricante (se existir documento Manuais; caso contrário omitir)
- Bloco IT/PRE: status atual em texto colorido
- Bloco Manuais: `X / 5` colorido conforme progresso

**Equipamento sem documento Manuais:** bloco Manuais mostra `—` em cinza.  
**Equipamento sem documento IT/PRE:** bloco IT/PRE mostra `—` em cinza.

**Interação:** clicar em qualquer parte do card abre o modal do equipamento.

### 2.3 Agrupamento de equipamentos

A grade é montada no frontend a partir dos documentos existentes:
- Agrupar por `(equipamento, sku)` — chave composta
- Para cada grupo, buscar o documento `setor=PRE` (para bloco IT/PRE) e os documentos `setor=Manuais` (para bloco Manuais)
- Ordenação padrão: alfabética por nome do equipamento

### 2.4 Modal do equipamento

Abre como modal centralizado (o mesmo padrão de modal já usado no sistema).

**Header:**
- Nome do equipamento + SKU
- Fabricante (se houver)
- Botão fechar (×)

**Abas:**
- `IT / PRE` (ativa por padrão)
- `Manuais`

---

#### Aba IT / PRE

Todos os campos são editáveis inline. O modal abre já em modo edição (sem botão "Editar" separado).

| Campo | Tipo | Notas |
|---|---|---|
| Equipamento | `<input text>` | Alteração propaga para todos os docs do mesmo equipamento (comportamento existente) |
| SKU | `<input text>` | Propagação global de SKU (comportamento existente) |
| Código do documento | `<input text>` | |
| Responsável | `<input text>` | |
| Status | `<select>` | Elaborar / Treinamento Piloto / Enviado para Homologação / Homologado |
| Data treinamento piloto | `<input date>` | |
| Data homologação | `<input date>` | |
| Obs. treinamento | `<textarea>` | |
| Obs. homologação | `<textarea>` | |
| Armazenamento | `<input text>` + botão abrir pasta | Link clicável se preenchido |

**Se não existir documento IT/PRE para este equipamento:** exibir botão "Criar documento IT/PRE" no lugar do formulário.

**Footer da aba:** `Salvar alterações` · `Cancelar`

---

#### Aba Manuais

**Campos compartilhados (sincronizados entre os 5 tipos):**
| Campo | Tipo |
|---|---|
| Fabricante | `<input text>` |
| Armazenamento base | `<input text>` + botão abrir pasta |

**Para cada um dos 5 tipos** (Manual ES · Manual Usuário · QI/QO/QD · Manual Serviço · Spare Parts):
| Campo | Tipo |
|---|---|
| Código do documento | `<input text>` |
| Status | `<select>` — Elaborar / Em andamento / Concluído |

**Se não existirem documentos Manuais:** exibir botão "Criar manuais para este equipamento" (cria os 5 de uma vez, comportamento existente).

**Footer da aba:** `Salvar alterações` · `Cancelar`

---

## 3. Modo claro / escuro

### Toggle
- Ícone sol/lua no canto superior direito da barra de navegação (ao lado do perfil)
- Alterna entre dois temas
- Preferência salva em `localStorage` com chave `doctrack_theme` (valores: `"dark"` | `"light"`)
- Padrão: `"dark"` (mantém o visual atual)

### Implementação
- Adicionar classe `theme-light` no elemento `<body>` quando modo claro ativo
- Definir variáveis CSS no `:root` para as cores principais (background, surface, border, text, text-muted)
- Sobrescrever as variáveis dentro de `body.theme-light`
- Não duplicar regras de componente — apenas as variáveis mudam

**Variáveis a definir:**
```css
:root {
  --bg-base: #0f0f1a;
  --bg-surface: #1a1a2e;
  --bg-elevated: #1e1e3a;
  --bg-inset: #12122a;
  --border: #2a2a4a;
  --text: #ffffff;
  --text-muted: #a0a0c0;
  --accent: #4a4af4;
}

body.theme-light {
  --bg-base: #f0f2f8;
  --bg-surface: #ffffff;
  --bg-elevated: #f8f9fc;
  --bg-inset: #eef0f6;
  --border: #d0d4e8;
  --text: #1a1a2e;
  --text-muted: #6b7280;
  --accent: #4a4af4;
}
```

- Cores semânticas (verde/amarelo/vermelho de status) permanecem iguais nos dois temas
- Aplicar `transition: background-color 0.2s, color 0.2s` no `body` para troca suave

---

## Arquivos afetados

| Arquivo | Mudanças |
|---|---|
| `static/app.js` | Nova lógica de grade, modal com abas, chips de filtro, toggle de tema |
| `templates/dashboard.html` | Estrutura HTML da grade, modal, toggle, variáveis CSS |
| `static/style.css` (se existir) ou `<style>` no HTML | Variáveis de tema, estilos dos cards, chips |
| `models.py` | Remover PDE de `SETORES` e constantes |
| `servidor.py` | Remover PDE de métricas e validações |

---

## Fora do escopo desta entrega

- Paginação da grade (entregar com scroll, paginar depois se necessário)
- Responsividade mobile (manter o que já existe)
- Alteração no fluxo de importação do Excel (PDE pode continuar sendo importado, só não aparece)
- Novos campos ou tipos de documento além dos existentes

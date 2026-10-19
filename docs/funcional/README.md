# Documentação funcional por módulo

O que cada módulo resolve e quais regras de negócio ele impõe. É a camada que
não sai do código automaticamente: a referência gerada diz *quais* rotas e
colunas existem, e estes documentos dizem *o que elas significam*.

Também não sai dos planos em [`../planos/`](../planos/) e
[`../superpowers/`](../superpowers/): aqueles dizem o que **ia** ser feito,
estes dizem o que **ficou**.

| Módulo | Área | Quem alcança | Documento |
|---|---|---|---|
| Documentos | PDE | qualquer membro da área | [documentos.md](documentos.md) |
| Equipamentos | PDE | qualquer membro da área | [equipamentos.md](equipamentos.md) |
| Consumíveis | PDE | qualquer membro da área | [consumiveis.md](consumiveis.md) |
| Projetos e Entregáveis | PDE | gestor (técnico em modo restrito) | [projetos-entregaveis.md](projetos-entregaveis.md) |
| Missões | PDE | técnico para cima | [missoes.md](missoes.md) |
| Custos | PDE | admin e gestor | [custos.md](custos.md) |
| Tempos | PDE | técnico para cima | [tempos.md](tempos.md) |
| PDR | PDR | membros da área PDR | [pdr.md](pdr.md) |
| Acesso e usuários | — | todos | [acesso-usuarios.md](acesso-usuarios.md) |

## Como ler junto com o resto

- **Qual rota faz isso?** → [`../referencia/api.md`](../referencia/api.md)
- **O que é essa coluna?** → [`../referencia/dados.md`](../referencia/dados.md)
- **Quem pode fazer isso?** → [`../referencia/permissoes.md`](../referencia/permissoes.md)
- **Por que é assim?** → [`../arquitetura/decisoes/`](../arquitetura/decisoes/)

## Manutenção

Estes arquivos são escritos à mão e **nenhum teste garante que estejam certos** —
diferente da camada de referência. Ao mudar uma regra de negócio, o documento do
módulo é parte da mudança, não um passo posterior.

Quando um documento e o código discordarem, o código vence — e o documento está
com defeito.

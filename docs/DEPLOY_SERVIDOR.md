# DocTrack — Implantação no servidor (sem admin)

O DocTrack é distribuído como **executável de pasta única** (PyInstaller). Não precisa
instalar Python, Node, GTK, nem ter privilégios de administrador no servidor.

## Gerar o pacote (na sua máquina de desenvolvimento)

```powershell
.\scripts\build_exe.ps1
```

Saída: **`dist\DocTrack\`** — uma pasta contendo:
- `DocTrack.exe` — o servidor
- `_internal\` — bibliotecas e assets embutidos (templates, static, etc.)
- `doctrack.db` — banco já populado (gravável, fica ao lado do .exe)
- `.env` — configuração (gerada com uma `JWT_SECRET` aleatória)

## Implantar no servidor

1. **Copie a pasta `DocTrack` inteira** para o servidor (ex.: `C:\DocTrack`).
2. (Opcional) Edite o `.env` ao lado do `.exe`:
   - `DOCTRACK_FILE_ROOTS=\\loccus-srv03\Projetos$\Engenharia` — pasta(s) de documentos
     (separe várias com `;`). Use a forma **UNC**: mapeamento de unidade é por sessão de
     logon, então rodando como serviço o DocTrack não enxerga `P:`.
   - `DOCTRACK_PATH_ALIASES=P:=\\loccus-srv03\Projetos$` — apelidos `LETRA:=UNC`. É o que
     faz o caminho colado da barra do Explorer (`P:\Engenharia\...`) ser reconhecido como
     a mesma pasta da UNC acima. Sem isto, esses caminhos batem em
     "fora das pastas permitidas". Vazio = autodetecta os mapeamentos da sessão atual,
     o que **não** funciona rodando como serviço.
   - `CORS_ORIGINS=*` — origens liberadas.
   - `DOCTRACK_ARQUIVOS=C:\DocTrack\arquivos` — pasta dos arquivos **enviados**
     para a plataforma (a cópia que o usuário sobe em cada documento). Padrão:
     `arquivos\` ao lado do `.exe`. **Nunca aponte para dentro de `_internal\`** —
     essa pasta é substituída a cada atualização (ver o passo de atualização no
     fim deste documento) e os arquivos enviados seriam apagados.
   - `DOCTRACK_UPLOAD_MAX_MB=80` — teto de upload. O maior documento observado no
     share tem 56 MB.
3. **Mapeie o drive `P:`** (rede) se for usar o preview de documentos. (Não exige admin.)
   Não é obrigatório: com a UNC em `DOCTRACK_FILE_ROOTS` o acesso funciona sem o mapeamento.
4. **Execute `DocTrack.exe`** (duplo clique ou por uma PowerShell normal). Uma janela de
   console abre mostrando os logs. Para parar, feche a janela ou `Ctrl+C`.

Acesse:
- No próprio servidor: **http://localhost:5000**
- De outras máquinas na rede: **http://<IP-do-servidor>:5000**

## Acesso pela rede (firewall) — único ponto que pode exigir o TI

Vincular a porta 5000 **não** precisa de admin. Mas, para que **outras máquinas**
acessem, a **porta 5000 (entrada/TCP)** precisa estar liberada no Firewall do Windows do
servidor. Criar essa regra exige admin — **peça ao TI uma vez**:

```powershell
# (executar como administrador, uma única vez)
New-NetFirewallRule -DisplayName "DocTrack 5000" -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow
```

Sem essa regra, o app funciona normalmente em `localhost` no próprio servidor.

## Manter sempre no ar (sem admin)

- Forma simples: deixar a janela do `DocTrack.exe` aberta (some se a sessão do usuário cair).
- Iniciar com o login do usuário: coloque um atalho do `DocTrack.exe` na pasta
  **Inicializar** (`shell:startup`) do Windows.
- Se houver admin disponível e quiser que rode como serviço/independente de login,
  use o script `scripts/setup_windows_server.ps1` (PM2) — porém exige Node.js + admin.

## Observações

- O PDF dos relatórios é gerado **no navegador** (jsPDF); o executável **não** inclui
  WeasyPrint/GTK/matplotlib. O endpoint legado `/api/report/pdf` foi removido em
  jul/2026 — era código morto, sem nenhuma chamadora viva.
- O `pandas` só é usado para semear o banco a partir do Excel e **não** é embutido no
  `.exe`. O pacote já vai com o `doctrack.db` pronto.
- Para atualizar a versão no servidor: gere um novo pacote, e no servidor substitua o
  `DocTrack.exe` e a pasta `_internal\` — **preserve** o `doctrack.db`, o `.env` e a
  pasta `arquivos\` existentes.
- **Backup:** `scripts\gerar_backup.ps1` salva o banco **e** a pasta de arquivos na
  mesma execução. As duas metades precisam vir do mesmo momento: banco sem os
  arquivos aponta para blobs que não existem, e arquivos sem o banco são um monte
  de nomes em hash sem significado.

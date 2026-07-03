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
   - `DOCTRACK_FILE_ROOTS=P:\Engenharia` — pasta(s) de documentos (separe várias com `;`).
   - `CORS_ORIGINS=*` — origens liberadas.
3. **Mapeie o drive `P:`** (rede) se for usar o preview de documentos. (Não exige admin.)
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
  WeasyPrint/GTK/matplotlib. O endpoint legado `/api/report/pdf` fica inativo.
- O `pandas` só é usado para semear o banco a partir do Excel e **não** é embutido no
  `.exe`. O pacote já vai com o `doctrack.db` pronto.
- Para atualizar a versão no servidor: gere um novo pacote, e no servidor substitua o
  `DocTrack.exe` e a pasta `_internal\` — **preserve** o `doctrack.db` e o `.env` existentes.

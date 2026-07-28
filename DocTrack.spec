# -*- mode: python ; coding: utf-8 -*-
# Build de pasta única do DocTrack (roda sem admin, sem instalar Python).
#   ASSET_DIR (somente leitura) = pasta do bundle ; RUN_DIR (gravável) = ao lado do .exe
#   Gerar com:  .\venv\Scripts\pyinstaller.exe DocTrack.spec --noconfirm

datas = [
    ('templates', 'templates'),   # inclui audit_log_report.html
    ('static', 'static'),         # inclui socket-client.js e app-realtime.js
]

hiddenimports = [
    'engineio.async_drivers.threading',   # modo assíncrono do Socket.IO
]

# Libs pesadas que NÃO são usadas pelo servidor web (PDF é feito no navegador):
excludes = [
    'pandas', 'numpy', 'matplotlib', 'weasyprint', 'psycopg2', 'psycopg2-binary',
    'scipy', 'PIL', 'tkinter', 'PyQt5', 'PySide2', 'gunicorn', 'IPython', 'pytest',
]

a = Analysis(
    ['servidor.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DocTrack',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,          # janela de console mostra os logs do servidor
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='DocTrack',
)

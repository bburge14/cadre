# Build with: pyinstaller windows/app.spec  (must run ON Windows --
# PyInstaller does not cross-compile from Linux/macOS to Windows)
from pathlib import Path

repo_root = Path(SPECPATH).parent

a = Analysis(
    [str(repo_root / 'app.py')],
    pathex=[str(repo_root)],
    binaries=[],
    datas=[
        (str(repo_root / 'templates'), 'templates'),
        (str(repo_root / 'static'), 'static'),
        (str(repo_root / 'presets'), 'presets'),
    ],
    hiddenimports=['yaml', 'dotenv', 'werkzeug.security', 'jinja2.ext'],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='AgentStackCreatorApp',
    debug=False,
    strip=False,
    upx=False,
    console=False,
)

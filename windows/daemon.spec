# Build with: pyinstaller windows/daemon.spec  (must run ON Windows --
# PyInstaller does not cross-compile from Linux/macOS to Windows)
from pathlib import Path

repo_root = Path(SPECPATH).parent

a = Analysis(
    [str(repo_root / 'session_daemon.py')],
    pathex=[str(repo_root)],
    binaries=[],
    datas=[],
    hiddenimports=['winpty', 'psutil'],
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
    name='AgentStackCreatorDaemon',
    debug=False,
    strip=False,
    upx=False,
    console=False,
)

# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for GabaMic Windows executable.

Build (on Windows, with the venv active):
    pip install pyinstaller pyinstaller-hooks-contrib
    pyinstaller GabaMic.spec --noconfirm

Output: dist\GabaMic\GabaMic.exe  + supporting DLLs in the same folder.
Zip dist\GabaMic\ and distribute — or let GitHub Actions do it automatically.

The Whisper speech model is NOT bundled.
It downloads on first launch (~150 MB) and is cached in %USERPROFILE%\.cache.
All subsequent launches work fully offline.
"""

from PyInstaller.utils.hooks import collect_all, collect_submodules

# ── Seed the lists that Analysis() will extend ───────────────────────────────
datas = [
    # Ship config.json next to the exe so users can edit hotkey / model / language
    ("config.json", "."),
    # Include the gabamic package explicitly (auto-detected, but belt-and-suspenders)
    ("gabamic", "gabamic"),
]
binaries = []
hiddenimports = []

# ── collect_all() grabs every binary, data file, and sub-import for a package ─
# This is necessary for packages that load native extensions at runtime
# (ctranslate2, tokenizers) or that discover backends dynamically (webview).
for _pkg in (
    "ctranslate2",       # CTranslate2 engine + OpenMP DLLs
    "faster_whisper",    # faster-whisper Python wrappers
    "tokenizers",        # HuggingFace tokenizers (Rust extension)
    "sounddevice",       # PortAudio bindings
    "webview",           # pywebview + Edge WebView2 backend
):
    _d, _b, _h = collect_all(_pkg)
    datas        += _d
    binaries     += _b
    hiddenimports += _h

# huggingface_hub is used by faster-whisper to download the model on first run
hiddenimports += collect_submodules("huggingface_hub")

# pynput loads its Windows backend dynamically — name it explicitly
hiddenimports += [
    "pynput.keyboard._win32",
    "pynput.mouse._win32",
]

# ── Analysis ──────────────────────────────────────────────────────────────────
block_cipher = None

a = Analysis(
    ["app_win.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # macOS-only — will never be present on Windows anyway, but exclude
        # explicitly so PyInstaller doesn't waste time searching for them
        "rumps",
        "AppKit",
        "Foundation",
        "objc",
        # Heavy libs not used by GabaMic
        "tkinter",
        "matplotlib",
        "scipy",
        "PIL",
        "cv2",
        "pandas",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GabaMic",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # No console window — startup/runtime errors are shown via MessageBoxW
    # (see _show_error() in app_win.py)
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,   # set to "GabaMic.ico" once an icon file is available
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="GabaMic",
)

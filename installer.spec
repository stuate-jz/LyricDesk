# -*- mode: python ; coding: utf-8 -*-
"""安装程序的打包配置。

依赖 dist\\LyricDesk.exe 已经构建好（它会被打进安装包作为安装内容）。
"""

import os

PROJECT_DIR = os.path.abspath(os.path.dirname(SPEC))
PAYLOAD_EXE = os.path.join(PROJECT_DIR, "dist", "LyricDesk.exe")

if not os.path.exists(PAYLOAD_EXE):
    raise SystemExit(
        "找不到 dist\\LyricDesk.exe，请先运行：\n"
        "    python -m PyInstaller desktop-lyric.spec --noconfirm"
    )

datas = [
    (PAYLOAD_EXE, "payload"),
    (os.path.join(PROJECT_DIR, "packaging", "使用说明.txt"), "payload"),
    (os.path.join(PROJECT_DIR, "packaging", "更新说明.txt"), "payload"),
    (os.path.join(PROJECT_DIR, "packaging", "许可协议.txt"), "."),
    (os.path.join(PROJECT_DIR, "packaging", "许可协议.txt"), "payload"),
    (os.path.join(PROJECT_DIR, "desktop-lyric.ico"), "."),
]

excludes = [
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtUiTools",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.QtCharts",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtStateMachine",
    "PySide6.QtTextToSpeech",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtSpatialAudio",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "tkinter",
    "unittest",
    "doctest",
    "pydoc",
    "pdb",
    "lib2to3",
]

a = Analysis(
    [os.path.join(PROJECT_DIR, "installer", "setup_app.py")],
    pathex=[PROJECT_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=["winreg"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="桌面歌词-安装程序-v1.0",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(PROJECT_DIR, "desktop-lyric.ico"),
    version=os.path.join(PROJECT_DIR, "packaging", "installer_version_info.txt"),
)

# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置。

默认打包成单文件 exe；设置环境变量 LD_ONEFILE=0 可打包成文件夹版本。
"""

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ONEFILE = os.environ.get("LD_ONEFILE", "1") == "1"
PROJECT_DIR = os.path.abspath(os.path.dirname(SPEC))
VERSION_FILE = os.path.join(PROJECT_DIR, "packaging", "version_info.txt")

hiddenimports = [
    "winrt.windows.media.control",
    "winrt.windows.foundation",
    "winrt.windows.foundation.collections",
    "winrt.windows.storage.streams",
]
hiddenimports += collect_submodules("winrt")

# requests 需要 certifi 的根证书
datas = collect_data_files("certifi")
# 内置歌词字体（得意黑，SIL OFL 1.1，随程序分发）
datas += [
    (os.path.join(PROJECT_DIR, "assets", "fonts", "SmileySans-Oblique.otf"), "assets/fonts"),
    (os.path.join(PROJECT_DIR, "assets", "fonts", "SmileySans-LICENSE.txt"), "assets/fonts"),
    (
        os.path.join(PROJECT_DIR, "assets", "fonts", "LXGWMarkerGothic-Regular.ttf"),
        "assets/fonts",
    ),
    (
        os.path.join(PROJECT_DIR, "assets", "fonts", "LXGWMarkerGothic-LICENSE.txt"),
        "assets/fonts",
    ),
]

# Qt 自带对话框（字体选择等）的中文翻译。PySide6 装在哪由 Python 决定，
# 所以路径用 QLibraryInfo 查，不写死；不进包的话打包版的字体对话框会是英文。
try:
    from PySide6.QtCore import QLibraryInfo

    _qt_translations = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
except Exception:  # noqa: BLE001
    import PySide6

    _qt_translations = os.path.join(os.path.dirname(PySide6.__file__), "translations")

for _qm in ("qtbase_zh_CN.qm", "qt_zh_CN.qm"):
    _src = os.path.join(_qt_translations, _qm)
    if os.path.exists(_src):
        datas.append((_src, "PySide6/translations"))

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
    "PySide6.QtDataVisualization",
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
    [os.path.join(PROJECT_DIR, "main.py")],
    pathex=[PROJECT_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# 排除 ICU（icudt78.dll / icuuc.dll 等，约 13 MB）：
# 这个程序用不到 ICU，而把它们打进包里反而会让 QtCore 报
# 「DLL load failed: 找不到指定的程序」。之前不含 ICU 的版本一直是正常的。
a.binaries = [
    item for item in a.binaries
    if "icu" not in os.path.basename(item[0]).lower()
]

if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="LyricDesk",
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
        version=VERSION_FILE,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="LyricDesk",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=os.path.join(PROJECT_DIR, "desktop-lyric.ico"),
        version=VERSION_FILE,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="LyricDesk",
    )

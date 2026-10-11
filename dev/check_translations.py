"""回归检查：Qt 自带对话框的中文翻译能不能装上。

「从系统字体中选择…」弹出的是 Qt 的 QFontDialog，它的标题/按钮来自
qtbase_zh_CN.qm。这里用 QDialogButtonBox 的「确定/取消」当探头：
没装翻译是 OK / Cancel，装了是 确定 / 取消，结论一样、但不用真弹模态框。

    python dev\\check_translations.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from PySide6.QtCore import QLibraryInfo  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialogButtonBox  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  —— {detail}" if detail else ""))
    if not ok:
        FAILED.append(name)


def standard_buttons() -> tuple[str, str]:
    box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    texts = [b.text() for b in box.buttons()]
    return texts[0] if texts else "", texts[1] if len(texts) > 1 else ""


def main() -> int:
    app = QApplication(sys.argv)

    path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    print(f"Qt 翻译目录：{path}")
    for name in ("qtbase_zh_CN.qm", "qt_zh_CN.qm"):
        check(f"{name} 存在", (Path(path) / name).exists())

    before = standard_buttons()
    print(f"  装翻译前：{before}")
    check("装翻译前确实是英文（说明这个检查抓得到问题）", before[0] == "OK", str(before))

    from lyricdesk.app import install_translations

    translators = install_translations(app)
    after = standard_buttons()
    print(f"  装翻译后：{after}  （加载了 {len(translators)} 个翻译器）")
    check("装翻译后变成中文", after[0] == "确定" and after[1] == "取消", str(after))
    check("翻译器对象被持有（不会被 GC）", len(translators) >= 1)

    if FAILED:
        print("\n失败：", ", ".join(FAILED))
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

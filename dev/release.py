r"""发新版：本地这一整套（改版本号 → 打包 → 生成发布页）一条命令跑完。

用法：
    python dev\release.py 1.5.3 --repo pursue-studies/LyricDesk ^
        --notes "· 新增：xxx|· 修复：yyy"

    --notes 用 | 分隔每一条，会写进 packaging\update.json（发布页和程序的更新提示都用它）
    --skip-build   只改版本号、生成发布页文件，不重新打包
    --verify       跑完顺手核对一次 Gitee 仓库上的状态
    --with-portable  额外产出一个免安装 zip（默认不产，只发安装程序）

跑完会打印「接下来你要做的几件事」，照着点就行。
最后一步会把 release-page\ 同步到 docs\（GitHub Pages 用的是 docs\ 那一份）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
REPO_DEFAULT = "pursue-studies/LyricDesk"


def run(command: list[str], *, cwd: Path = ROOT) -> int:
    print("  $", " ".join(str(item) for item in command))
    result = subprocess.run(command, cwd=str(cwd))
    return result.returncode


def find_iscc() -> Path | None:
    local = os.environ.get("LOCALAPPDATA", "")
    for candidate in (
        Path(local) / "Programs" / "Inno Setup 7" / "ISCC.exe",
        Path(local) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    ):
        if candidate.exists():
            return candidate
    return None


def write_notes(version: str, notes: str) -> None:
    path = ROOT / "packaging" / "update.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = version
    data["date"] = date.today().isoformat()
    data["notes"] = notes.replace("|", "\n")
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("  已写入 packaging/update.json")


def package(version: str, app_short: str) -> Path:
    """把 exe 和说明文件装进一个文件夹，再压成便携版 zip。"""
    dist = ROOT / "dist"
    folder = dist / f"{app_short} v{version}"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)

    shutil.copy2(dist / "LyricDesk.exe", folder / "LyricDesk.exe")
    for name in ("使用说明.txt", "更新说明.txt", "许可协议.txt"):
        source = ROOT / "packaging" / name
        if source.exists():
            shutil.copy2(source, folder / name)
    shutil.copy2(
        ROOT / "packaging" / "update.json", folder / "更新源模板.json"
    )
    fonts = ROOT / "assets" / "fonts"
    if (fonts / "SmileySans-LICENSE.txt").exists():
        shutil.copy2(fonts / "SmileySans-LICENSE.txt", folder / "字体授权-得意黑.txt")
    if (fonts / "LXGWMarkerGothic-LICENSE.txt").exists():
        shutil.copy2(
            fonts / "LXGWMarkerGothic-LICENSE.txt", folder / "字体授权-霞鹜漫黑.txt"
        )

    archive = dist / f"{app_short}-v{version}-便携版.zip"
    if archive.exists():
        archive.unlink()
    shutil.make_archive(str(archive.with_suffix("")), "zip", root_dir=dist, base_dir=folder.name)
    print(f"  便携版：{archive.name}")
    return archive


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    version = sys.argv[1].strip().lstrip("v")

    repo = REPO_DEFAULT
    notes = ""
    skip_build = "--skip-build" in sys.argv
    do_verify = "--verify" in sys.argv
    with_portable = "--with-portable" in sys.argv
    args = sys.argv[2:]
    for index, item in enumerate(args):
        if item == "--repo" and index + 1 < len(args):
            repo = args[index + 1].strip().strip("/")
        if item == "--notes" and index + 1 < len(args):
            notes = args[index + 1]
    if repo.lower().startswith("gitee:"):
        repo = repo[6:]

    print(f"=== 发布 v{version} → {repo} ===\n")

    if notes:
        print("[1/7] 写入更新说明")
        write_notes(version, notes)
    else:
        print("[1/7] 没给 --notes，沿用 packaging/update.json 里已有的说明")
    print()

    print("[2/7] 同步版本号")
    run([PYTHON, str(ROOT / "dev" / "bump_version.py"), version])
    print()

    if skip_build:
        print("[3/7] --skip-build：跳过打包\n")
    else:
        print("[3/7] 打包 exe（PyInstaller，约 1 分钟）")
        if run([PYTHON, "-m", "PyInstaller", "desktop-lyric.spec", "--noconfirm"]) != 0:
            print("打包失败，已中断。")
            return 1
        print()
        print("[4/7] 生成安装程序（Inno Setup）")
        iscc = find_iscc()
        if iscc is None:
            print("  找不到 ISCC.exe（Inno Setup），跳过安装程序；便携版不受影响。")
        elif run([str(iscc), "installer.iss"]) != 0:
            print("安装程序生成失败，已中断。")
            return 1
        print()

    print("[5/7] 整理便携版压缩包")
    if with_portable:
        package(version, "桌面歌词")
    else:
        print("  跳过（现在只发安装程序；要便携版就加 --with-portable）")
    print()

    print("[6/7] 生成发布页文件")
    run([PYTHON, str(ROOT / "dev" / "make_release_files.py"), repo])
    upload = ROOT / "dist" / "上传到Gitee"
    upload.mkdir(parents=True, exist_ok=True)
    for name in ("README.md", "update.json", "index.html"):
        source = ROOT / "release-page" / name
        if source.exists():
            shutil.copy2(source, upload / name)
    shots = ROOT / "release-page" / "screenshots"
    if shots.exists():
        target = upload / "screenshots"
        target.mkdir(parents=True, exist_ok=True)
        for item in shots.glob("*.png"):
            shutil.copy2(item, target / item.name)
    print()

    print("[7/7] 同步 GitHub Pages 用的 docs/ 目录")
    if run([PYTHON, str(ROOT / "dev" / "build_pages.py")]) != 0:
        print("docs/ 同步没通过（多半是页面里混进了外链资源），已中断。")
        return 1
    print()

    if do_verify:
        print("[附加] 核对 Gitee 上的状态")
        run([PYTHON, str(ROOT / "dev" / "verify_release.py"), repo])
        print()

    base = f"https://gitee.com/{repo}"
    gh_repo = "stuate-jz/LyricDesk"
    gh_base = f"https://github.com/{gh_repo}"
    print("=" * 62)
    print("接下来你要做的（照顺序点就行）")
    print("=" * 62)
    print()
    print("① Gitee：发新版本，附件传 dist\\LyricDesk-Setup-v{0}.exe".format(version))
    print(f"   打开  {base}/releases/new")
    print(f"   标签名称：v{version}　标题：桌面歌词 v{version}")
    print("   说明：把 dist\\上传到Gitee\\update.json 里 notes 的内容复制进去")
    if with_portable:
        print(f"         （可选）dist\\桌面歌词-v{version}-便携版.zip")
    print("   点「发布」；顺手把仓库首页 README 换成 dist\\上传到Gitee\\README.md 的内容")
    print()
    print("② GitHub：发新版本（标签同名），附件传同一个文件")
    print(f"   打开  {gh_base}/releases/new")
    print(f"   标签名称：v{version}　标题：桌面歌词 v{version}")
    print(f"   附件：dist\\LyricDesk-Setup-v{version}.exe（文件名本来就是 ASCII，直接传，不用改名）")
    print("   说明：同 ① 的 notes")
    print()
    print("③ 提交并推送 docs/ 与版本号改动")
    print("   git add -A && git commit -m \"chore: v{0}\" && git push".format(version))
    print("   （docs/ 推上去 1~2 分钟后，https://stuate-jz.github.io/LyricDesk/ 才会更新）")
    print()
    print("④ 验证")
    print(f"   程序右键菜单 →「检查更新…」，应提示已是最新 v{version}")
    print(f"   或跑：python dev\\verify_release.py {repo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

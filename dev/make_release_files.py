r"""按你的仓库地址，生成「发布页」需要上传的文件。

用法：
    python dev\make_release_files.py 用户名/LyricDesk
    python dev\make_release_files.py 用户名/LyricDesk --installer LyricDesk-Setup-v1.6.0.exe

会写出：
    release-page\README.md      → 贴到仓库首页，就是发布页（Gitee 会自动渲染）
    release-page\update.json    → 程序检查更新用的版本文件
并把地址、更新源一行打印出来。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE_DIR = ROOT / "release-page"


def latest_release_info() -> dict:
    path = ROOT / "packaging" / "update.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def build_readme(repo: str, info: dict, installer: str) -> str:
    version = info["version"]
    releases = f"https://gitee.com/{repo}/releases"
    notes = [
        line.strip() for line in str(info.get("notes", "")).split("\n") if line.strip()
    ]
    note_lines = "\n".join(
        f"- {line.lstrip('·•-* ').strip()}" for line in notes
    ) or "- 详见 Releases 页面"

    parts = [
        "<!-- 这个文件是发布页，直接改内容重新提交即可 -->",
        "",
        '<div align="center">',
        "",
        '<img src="screenshots/3d.png" width="640" alt="立体卡片效果">',
        "",
        "<h1>桌面歌词 LyricDesk</h1>",
        "",
        "**悬浮在桌面上的歌词组件** —— 不挑播放器，带歌词跳动动画，不改你的壁纸",
        "",
        f"**当前版本 v{version}**　·　[⬇ 下载最新版]({releases})　·　[全部版本]({releases})",
        "",
        "镜像仓库：[GitHub](https://github.com/stuate-jz/LyricDesk)　·　发布页：[stuate-jz.github.io/LyricDesk](https://stuate-jz.github.io/LyricDesk/)",
        "",
        "</div>",
        "",
        "---",
        "",
        "## ⬇ 下载",
        "",
        f"### ⚙ [**{installer}**]({releases})",
        "",
        "双击一路「下一步」装好即可（不需要管理员权限，不需要改任何系统设置）。",
        "",
        "**以后升级不用再手动下载**：程序自带检查更新，发现新版本会在托盘提醒，",
        "点一下「立即更新」就会自动下载、安装并重新打开。",
        "",
        f"> 文件在 [**Releases 页面**]({releases}) 的附件里。",
        "",
        "---",
        "",
        "支持任何向 Windows 报告播放状态的播放器：QQ音乐、酷狗音乐、网易云音乐、",
        "酷我音乐、Spotify、PotPlayer、foobar2000 等；同时开多个可以右键指定跟随哪一个。",
        "",
        "## 这个版本更新了什么",
        "",
        note_lines,
        "",
        "## 四种界面",
        "",
        "| 界面 | 样子 | 适合 |",
        "| --- | --- | --- |",
        "| 立体卡片 | 左边专辑、右边歌词，文字向内倾斜 | 默认，最好看 |",
        "| 唱片播放器 | 唱片 + 曲名 / 歌手 / 频谱 / 进度条 / 切歌 | 想要个桌面播放器 |",
        "| 纯歌词面板 | 只有歌词，透明浮在壁纸上 | 极简 |",
        "| 分离面板 | 唱片和歌词是两扇独立窗口，各拖各的 | 想自己摆位置 |",
        "",
        "![唱片播放器](screenshots/album.png)",
        "",
        "![分离面板](screenshots/split.png)",
        "",
        "## 怎么用",
        "",
        "1. 下载上面的安装程序，双击，一路「下一步」装好（不需要管理员权限）",
        "2. 装完程序会自己启动，并缩到右下角托盘，桌面上出现歌词",
        "3. 打开任意音乐软件放歌，歌词自动跟上",
        "4. 左键拖动摆位置；**右键是常用操作**（界面模式、字体、行数、锁定、播放控制…），",
        "   完整的设置（配色、倾斜、尺寸、语言…）在右键菜单最后的 **「设置…」** 里",
        "",
        "想换字体：右键 → 歌词字体 —— 内置了「得意黑」「霞鹜漫黑」，",
        "也可以用「导入字体文件…」把自己下载的 ttf / otf 字体导进来，导入一次以后一直在。",
        "",
        "卸载：开始菜单 → 桌面歌词 → 卸载，或者「设置 → 应用」里卸载。",
        "",
        "## 常见问题",
        "",
        "**桌面显示「未检测到正在播放的歌曲」？**",
        "不少音乐软件的「系统播放控件 / 媒体控制」默认是关的，关掉之后 Windows 里",
        "没有任何播放信息，任何歌词插件都读不到。到音乐软件设置里打开它即可：",
        "网易云 → 设置 → 常规 → 系统媒体控制；酷狗、QQ音乐 等也有类似开关。",
        "",
        "**怎么退出？**",
        "右键桌面上的歌词 → 最小化到托盘，程序仍在后台；彻底退出请右键右下角的",
        "音符图标 → 退出。托盘图标可能被收进「^」溢出区。",
        "",
        "**鼠标穿透之后点不动了？**",
        "按 `Ctrl + Alt + L` 随时开关，也可以右键托盘图标解除。",
        "",
        "**为什么杀毒软件会提示？**",
        "这是 Python 打包的程序，部分杀软对这类自解压程序会误报；",
        "程序只从公开曲库读取歌词和封面，不上传任何个人数据。",
        "",
        "**以后怎么升级？**",
        "程序自带检查更新：右键 → **设置… → 更新与关于 → 设置更新源…**，把下面这行填进去：",
        "",
        "```",
        f"gitee:{repo}",
        "```",
        "",
        "填好之后每次启动会自动检查一次，有新版本会发托盘通知；",
        "也可以随时在菜单里点「检查更新…」手动查。",
        "",
        "## 系统要求",
        "",
        f"- {info.get('requirements', 'Windows 10 1809 或更高（Win11 最佳）')}",
        "- 需要能上网（用于获取歌词与专辑封面）",
        "",
        "## 许可",
        "",
        "免费使用。内置字体「得意黑」「霞鹜漫黑」均为 SIL OFL 1.1 授权，可自由分发。",
        "",
    ]
    return "\n".join(parts)


def main() -> int:
    if len(sys.argv) < 2 or "/" not in sys.argv[1]:
        print(__doc__)
        return 2

    repo = sys.argv[1].strip().strip("/")
    if repo.lower().startswith("gitee:"):
        repo = repo[6:]

    info = latest_release_info()
    version = info["version"]
    installer = f"LyricDesk-Setup-v{version}.exe"

    args = sys.argv[2:]
    for index, item in enumerate(args):
        if item == "--installer" and index + 1 < len(args):
            installer = args[index + 1]

    releases = f"https://gitee.com/{repo}/releases"

    payload = dict(info)
    payload["url"] = releases
    payload["page_url"] = releases
    payload["source_hint"] = f"gitee:{repo}"
    payload["_说明"] = [
        "发布页和桌面歌词共用的版本信息，每次发新版只改 version / date / notes / url。",
        "url 就是程序里「打开下载页」按钮打开的地方；",
        "想让它一键直接下载，把 url 换成 Release 附件的直链即可。",
    ]
    (PAGE_DIR / "update.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (PAGE_DIR / "README.md").write_text(
        build_readme(repo, info, installer), encoding="utf-8"
    )

    print("已生成：")
    print("  release-page/README.md     （贴到仓库首页就是发布页）")
    print("  release-page/update.json   （程序检查更新用）")
    print()
    print("你的地址：")
    print(f"  仓库首页 / 发布页   https://gitee.com/{repo}")
    print(f"  下载页（Releases）  {releases}")
    print(f"  更新源（填进程序）  gitee:{repo}")
    print(f"  要上传的附件        {installer}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

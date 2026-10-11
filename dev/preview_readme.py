r"""用 Gitee 自己的 Markdown 接口渲染 README，做成可以看的预览页。

    python dev\preview_readme.py <输出目录>

这样能在上传前就知道 Gitee 上会长什么样。
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent

CSS = """
body{margin:0;background:#fff;color:#24292f;
 font:16px/1.75 -apple-system,"Segoe UI","Microsoft YaHei UI",sans-serif;}
.md{max-width:900px;margin:0 auto;padding:32px 40px 80px}
.md h1,.md h2{border-bottom:1px solid #d8dee4;padding-bottom:.3em;margin:24px 0 16px}
.md h1{font-size:2em}.md h2{font-size:1.5em}.md h3{font-size:1.25em}
.md a{color:#0969da;text-decoration:none}.md a:hover{text-decoration:underline}
.md code{background:#eff1f3;border-radius:6px;padding:.2em .4em;font-size:85%}
.md pre{background:#f6f8fa;border-radius:6px;padding:16px;overflow:auto}
.md table{border-collapse:collapse;display:block;width:max-content;max-width:100%;overflow:auto}
.md th,.md td{border:1px solid #d0d7de;padding:6px 13px}
.md tr:nth-child(2n){background:#f6f8fa}
.md blockquote{margin:0;padding:0 1em;color:#57606a;border-left:.25em solid #d0d7de}
.md img{max-width:100%}
.md hr{height:.25em;background:#d0d7de;border:0}
"""


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)

    markdown = (ROOT / "release-page" / "README.md").read_text(encoding="utf-8")

    # 预览页直接写在 release-page 里，这样 screenshots/xxx 这种相对路径能正常显示

    response = requests.post(
        "https://gitee.com/api/v5/markdown",
        json={"text": markdown},
        timeout=(6, 30),
        headers={
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
    )
    print("Gitee 渲染接口:", response.status_code)
    body = response.text
    if "\\u" in body[:40] or body.startswith('"'):
        import json as _json

        body = _json.loads(body)

    # Gitee 的接口把中文按 latin-1 处理过一次，这里修正回来
    try:
        fixed = body.encode("latin-1").decode("utf-8")
        if "桌面歌词" in fixed or "LyricDesk" in fixed:
            body = fixed
            print("已修正编码")
    except (UnicodeEncodeError, UnicodeDecodeError):
        print("编码无需修正")

    page = (
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<title>Gitee 渲染预览</title><style>" + CSS + "</style></head>"
        "<body><div class='md'>" + body + "</div></body></html>"
    )
    path = ROOT / "release-page" / "_preview.html"
    path.write_text(page, encoding="utf-8")
    print("已写出:", path)
    if out != path.parent:
        import shutil

        shutil.copy2(path, out / "readme_preview.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

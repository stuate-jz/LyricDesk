"""从视频/浏览器标题里洗出干净的「歌名 - 歌手」。

B 站网页标题形如：

    【4K修复】周杰伦 - 七里香 (Official MV)_哔哩哔哩_bilibili

洗成：

    周杰伦 - 七里香

只影响「搜索曲库时用的关键词」，不改写 settings.song_offsets 的 key
（那会影响老用户已经记下的偏移）。
"""

from __future__ import annotations

import re

# 视频平台标题里的噪声。注意：只删「明确是噪声」的记号，
# 《歌名》里的书名号、【纯音乐】这类内容标签都要留着。
_NOISE_PATTERNS = (
    r"_哔哩哔哩_bilibili",
    r"_bilibili",
    r"哔哩哔哩",
    r"bilibili",
    # 【4K修复】【1080P】【完整版】【中日字幕】…… ；没有关键词的【…】不动
    r"【[^】]{0,14}(?:4K|8K|1080P?|720P?|高清|超清|修复|完整版|合集|搬运|中字|字幕|Hi-?Res|无损|SQ)】",
    # (Official MV) (Music Video) (Lyric Video) (Audio) (MV)
    r"\(\s*(?:Official\s*)?(?:Music\s*)?(?:MV|Video|Audio|Lyric\s*Video|HD|4K)\s*\)",
    # 【MV】【HD】【4K】
    r"【(?:MV|Official|HD|4K|8K|HQ)】",
    # [MV] [Official] [HD] [4K]
    r"\[\s*(?:Official\s*)?(?:Music\s*)?(?:MV|Video|HD|4K|8K|HQ)\s*\]",
    # 官方MV / 官方视频 / 官方音频
    r"官方(?:MV|视频|音频)",
    # 来源尾巴：- YouTube / - AcFun
    r"\s*[-–—|]\s*YouTube.*$",
    r"\s*[-–—|]\s*AcFun.*$",
)


def clean_title(text: str) -> str:
    """去掉视频标题里的平台噪声，返回干净的关键词（可能为空字符串）。"""
    value = (text or "").strip()
    if not value:
        return ""
    for pattern in _NOISE_PATTERNS:
        value = re.sub(pattern, " ", value, flags=re.IGNORECASE)
    # 删完可能留下空括号
    value = re.sub(r"[（(]\s*[)）]", " ", value)
    value = re.sub(r"[\[【]\s*[\]】]", " ", value)
    # 收尾：多余的分隔符 / 空白
    value = re.sub(r"\s*[-–—|｜]\s*$", "", value)
    value = re.sub(r"^\s*[-–—|｜]\s*", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value.strip(" -–—|｜·、,，:：")

"""歌词搜索、下载、解析与本地缓存。"""

from __future__ import annotations

import base64
import difflib
import hashlib
import json
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import requests

from .config import cache_dir
from .titles import clean_title

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
QQ_HEADERS = {
    "User-Agent": UA,
    "Referer": "https://y.qq.com/portal/player.html",
    "Accept": "application/json, text/plain, */*",
}
QQ_SEARCH_URL = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
QQ_MUSICU_URL = "https://u.y.qq.com/cgi-bin/musicu.fcg"
QQ_LEGACY_LYRIC_URL = "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg"
NE_SEARCH_URL = "https://music.163.com/api/search/get/web"
NE_LYRIC_URL = "https://music.163.com/api/song/lyric"
KG_SEARCH_URL = "http://mobilecdn.kugou.com/api/v3/search/song"
KG_MATCH_URL = "http://krcs.kugou.com/search"
KG_LYRIC_URL = "http://lyrics.kugou.com/download"
LRCLIB_URL = "https://lrclib.net/api"

NE_HEADERS = {"User-Agent": UA, "Referer": "https://music.163.com/"}
KG_HEADERS = {"User-Agent": UA, "Referer": "https://www.kugou.com/"}

MISS_TTL = 900.0
# 3：开始按「歌词覆盖率」换源，老的缓存（可能是残缺歌词）一律作废重取
CACHE_VERSION = 3
TIMEOUT = 8.0

_SESSION = requests.Session()
_SESSION.headers.update(QQ_HEADERS)

_TIME_TAG = re.compile(r"\[(\d{1,3}):(\d{1,2}(?:[.:]\d{1,3})?)\]")
_CREDIT_RE = re.compile(
    r"^\s*(?:"
    r"作词|作曲|编曲|演唱|原唱|制作人|制作|监制|出品|统筹|视觉|封面|策划|发行|词曲|词|曲|"
    r"(?:人声|和声)?录音(?:师|棚|室)?|混音(?:师|室)?|母带(?:师|室)?|和声|"
    r"吉他|贝斯|鼓|键盘|弦乐|OP|SP|"
    r"lyrics?\s*(?:by|edit\w*)?|music\s*by|written\s*by|composed\s*by|arranged\s*by|"
    r"produced\s*by|mixed\s*by|mastered\s*by|vocal\s*(?:edit\w*|by)?|"
    r"lyricist|composer|arranger|producer|mixing|mastering|"
    r"guitar|bass|drums|piano|strings|recording|label"
    r")\s*[:：]",
    re.IGNORECASE,
)
_BRACKET_ONLY = re.compile(r"^[\[【(（].*[\]】)）]$")
# 「XX：YY」这种短行——歌词里极少出现冒号，前 30 秒里的基本是署名/版权信息
_COLON_LABEL = re.compile(r"^.{0,12}?[:：]")

# 开头这一段里出现的署名行和「歌名 - 歌手」标题行都当作噪声丢掉
_CREDIT_WINDOW = 30.0


# ----------------------------------------------------------------------
# 数据结构
# ----------------------------------------------------------------------


@dataclass
class LyricLine:
    time: float
    text: str
    end: float = 0.0

    @property
    def is_gap(self) -> bool:
        return not self.text.strip()


@dataclass
class Lyrics:
    lines: list[LyricLine]
    source: str
    title: str
    artist: str
    albummid: str = ""
    album: str = ""
    cover_url: str = ""

    def index_at(self, position: float) -> int:
        """返回 position 时刻应高亮的行号；无歌词时返回 -1。"""
        if not self.lines:
            return -1
        lo, hi = 0, len(self.lines) - 1
        if position < self.lines[0].time:
            return -1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.lines[mid].time <= position:
                lo = mid
            else:
                hi = mid - 1
        return lo


# ----------------------------------------------------------------------
# 文本规范化与打分
# ----------------------------------------------------------------------


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = re.sub(r"[\s\-_·、,，.。!！?？'\"“”‘’()（）\[\]【】]", "", text)
    return text


def _ratio(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def score_candidate(candidate: dict, title: str, artist: str, duration: float) -> float:
    cand_title = normalize(candidate.get("title") or "")
    cand_artist = normalize(candidate.get("artist") or "")
    want_title = normalize(title)
    want_artist = normalize(artist)

    title_score = _ratio(want_title, cand_title)
    artist_score = _ratio(want_artist, cand_artist) if want_artist else 0.0
    base = 0.60 * title_score + 0.40 * artist_score

    cand_dur = float(candidate.get("duration") or 0.0)
    if duration > 5 and cand_dur > 5:
        # 时长是最能区分「同一首歌的不同版本」的线索：
        # Live / 抖音剪辑 / 翻唱 的时间轴对不上，多半是因为选错了版本。
        delta = abs(duration - cand_dur)
        if delta <= 3.0:
            return min(1.0, base + 0.15)      # 时长几乎一致，优先
        if delta <= 8.0:
            return base * 0.95
        if delta <= 20.0:
            return base * 0.75                # 可能是另一个版本了
        return base * 0.45                    # 差太多，基本不可能是同一首
    return base


def make_candidate(title, artist, duration, **extra) -> dict:
    """所有歌词源统一成同一种候选结构。"""
    return {
        "title": (title or "").strip(),
        "artist": (artist or "").strip(),
        "duration": float(duration or 0.0),
        "extra": extra,
    }


# ----------------------------------------------------------------------
# QQ音乐
# ----------------------------------------------------------------------


def search_qq(query: str, limit: int = 8) -> list[dict]:
    response = _SESSION.get(
        QQ_SEARCH_URL,
        params={
            "p": 1,
            "n": limit,
            "w": query,
            "format": "json",
            "cr": 1,
            "t": 0,
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    songs = payload.get("data", {}).get("song", {}).get("list", []) or []

    results: list[dict] = []
    for song in songs:
        singers = song.get("singer") or []
        if isinstance(singers, str):
            artist = singers
        else:
            artist = "/".join(s.get("name", "") for s in singers if isinstance(s, dict))
        mid = song.get("songmid") or song.get("mid")
        if not mid:
            continue
        results.append(
            make_candidate(
                song.get("songname") or song.get("title"),
                artist,
                song.get("interval"),
                songmid=mid,
                songid=song.get("songid") or song.get("id"),
                albummid=song.get("albummid") or "",
                album=song.get("albumname") or "",
            )
        )
    return results


def fetch_qq_lyric_candidate(candidate: dict) -> str | None:
    extra = candidate.get("extra") or {}
    return fetch_qq_lyric(extra.get("songmid", ""), extra.get("songid"))


# ----------------------------------------------------------------------
# 酷狗音乐
# ----------------------------------------------------------------------


def search_kugou(query: str, limit: int = 8) -> list[dict]:
    response = requests.get(
        KG_SEARCH_URL,
        params={"format": "json", "keyword": query, "page": 1, "pagesize": limit},
        headers=KG_HEADERS,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    items = ((response.json().get("data") or {}).get("info")) or []
    results = []
    for item in items:
        if not item.get("hash"):
            continue
        results.append(
            make_candidate(
                item.get("songname"),
                item.get("singername"),
                item.get("duration"),
                hash=item.get("hash"),
                album_id=item.get("album_id", 0),
            )
        )
    return results


def fetch_kugou_lyric(candidate: dict) -> str | None:
    extra = candidate.get("extra") or {}
    response = requests.get(
        KG_MATCH_URL,
        params={
            "ver": 1,
            "man": "yes",
            "client": "mobi",
            "hash": extra.get("hash"),
            "album_id": extra.get("album_id", 0),
            "duration": int(candidate.get("duration") or 0),
        },
        headers=KG_HEADERS,
        timeout=TIMEOUT,
    )
    candidates = response.json().get("candidates") or []
    for item in candidates[:3]:
        try:
            detail = requests.get(
                KG_LYRIC_URL,
                params={
                    "ver": 1,
                    "client": "pc",
                    "id": item.get("id"),
                    "accesskey": item.get("accesskey"),
                    "fmt": "lrc",
                    "charset": "utf8",
                },
                headers=KG_HEADERS,
                timeout=TIMEOUT,
            )
            content = detail.json().get("content")
        except Exception:
            continue
        if content:
            return base64.b64decode(content).decode("utf-8", "replace")
    return None


# ----------------------------------------------------------------------
# 网易云音乐
# ----------------------------------------------------------------------


def search_netease(query: str, limit: int = 8) -> list[dict]:
    response = requests.post(
        NE_SEARCH_URL,
        data={"s": query, "type": 1, "offset": 0, "limit": limit},
        headers=NE_HEADERS,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    songs = ((response.json().get("result") or {}).get("songs")) or []
    results = []
    for song in songs:
        if not song.get("id"):
            continue
        artists = song.get("artists") or []
        artist = "/".join(a.get("name", "") for a in artists if isinstance(a, dict))
        results.append(
            make_candidate(
                song.get("name"),
                artist,
                (song.get("duration") or 0) / 1000.0,
                songid=song.get("id"),
            )
        )
    return results


def fetch_netease_lyric(candidate: dict) -> str | None:
    song_id = (candidate.get("extra") or {}).get("songid")
    if not song_id:
        return None
    response = requests.get(
        NE_LYRIC_URL,
        params={"id": song_id, "lv": -1, "kv": -1, "tv": -1},
        headers=NE_HEADERS,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return ((response.json().get("lrc") or {}).get("lyric")) or None


def fetch_qq_lyric(songmid: str, songid: int | None) -> str | None:
    """优先走 musicu 接口（新版歌曲也能拿到带时间轴的 LRC）。"""
    if songid:
        try:
            text = _qq_lyric_musicu(songmid, int(songid))
            if text:
                return text
        except Exception:
            pass
    try:
        text = _qq_lyric_legacy(songmid)
        if text:
            return text
    except Exception:
        pass
    return None


def _b64_decode(value: str) -> str:
    padded = value + "=" * (-len(value) % 4)
    return base64.b64decode(padded).decode("utf-8", "replace")


def _qq_lyric_musicu(songmid: str, songid: int) -> str | None:
    payload = {
        "comm": {
            "ct": 11,
            "cv": "1003006",
            "v": "1003006",
            "uin": "0",
            "format": "json",
            "platform": "wk_v17",
        },
        "req_1": {
            "module": "music.musichallSong.PlayLyricInfo",
            "method": "GetPlayLyricInfo",
            "param": {"songMID": songmid, "songID": songid, "format": 1, "style": 1},
        },
    }
    response = _SESSION.get(
        QQ_MUSICU_URL,
        params={"format": "json", "data": json.dumps(payload, ensure_ascii=False)},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    data = response.json().get("req_1", {}).get("data", {}) or {}
    lyric = data.get("lyric")
    if not lyric:
        return None
    return _b64_decode(lyric)


def _qq_lyric_legacy(songmid: str) -> str | None:
    response = _SESSION.get(
        QQ_LEGACY_LYRIC_URL,
        params={"songmid": songmid, "format": "json", "g_tk": 5381},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    lyric = data.get("lyric")
    if not lyric:
        return None
    return _b64_decode(lyric)


# ----------------------------------------------------------------------
# 开放歌词库兜底
# ----------------------------------------------------------------------


def search_lrclib(title: str, artist: str, duration: float) -> str | None:
    headers = {"User-Agent": "LyricDesk/1.0 (local desktop widget)"}
    try:
        response = requests.get(
            f"{LRCLIB_URL}/get",
            params={
                "track_name": title,
                "artist_name": artist,
                "duration": round(duration),
            },
            headers=headers,
            timeout=6.0,
        )
        if response.status_code == 200:
            synced = response.json().get("syncedLyrics")
            if synced:
                return synced
    except Exception:
        pass
    try:
        response = requests.get(
            f"{LRCLIB_URL}/search",
            params={"track_name": f"{title} {artist}".strip()},
            headers=headers,
            timeout=6.0,
        )
        if response.status_code != 200:
            return None
        for item in response.json()[:5]:
            synced = item.get("syncedLyrics")
            if synced:
                return synced
    except Exception:
        pass
    return None


# ----------------------------------------------------------------------
# LRC 解析
# ----------------------------------------------------------------------


def parse_lrc(
    text: str, title: str = "", duration: float = 0.0, artist: str = ""
) -> list[LyricLine]:
    if not text:
        return []
    lines: list[LyricLine] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stamps = list(_TIME_TAG.finditer(raw))
        if not stamps:
            continue
        content = raw[stamps[-1].end():].strip()
        for match in stamps:
            minutes = int(match.group(1))
            seconds = float(match.group(2).replace(":", "."))
            lines.append(LyricLine(time=minutes * 60 + seconds, text=content))

    if not lines:
        return []

    lines.sort(key=lambda item: item.time)

    # 去掉重复时间戳产生的空行
    deduped: list[LyricLine] = []
    for line in lines:
        if deduped and abs(deduped[-1].time - line.time) < 0.001:
            if not deduped[-1].text and line.text:
                deduped[-1] = line
            continue
        deduped.append(line)

    norm_title = normalize(title)
    norm_title_artist = normalize(f"{title}{artist}") if artist else ""
    cleaned: list[LyricLine] = []
    for line in deduped:
        text_value = line.text.strip()
        if line.time < _CREDIT_WINDOW:
            if _CREDIT_RE.match(text_value) or _BRACKET_ONLY.match(text_value):
                continue
            if text_value:
                if len(text_value) <= 45 and _COLON_LABEL.match(text_value):
                    continue
                simplified = normalize(text_value)
                if norm_title and simplified == norm_title:
                    continue
                if norm_title_artist and simplified == norm_title_artist:
                    continue
                # 「歌名 (副标题) - 歌手」这类标题行
                if (
                    norm_title
                    and simplified.startswith(norm_title)
                    and len(simplified) <= len(norm_title) + 32
                ):
                    continue
        cleaned.append(LyricLine(time=line.time, text=text_value))

    if not cleaned:
        cleaned = deduped

    tail = duration if duration > cleaned[-1].time else cleaned[-1].time + 6.0
    for index, line in enumerate(cleaned):
        line.end = cleaned[index + 1].time if index + 1 < len(cleaned) else tail
        if line.end <= line.time:
            line.end = line.time + 2.5

    return cleaned


# ----------------------------------------------------------------------
# 缓存
# ----------------------------------------------------------------------


def _cache_path(key: str) -> Path:
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()
    return cache_dir() / f"{digest}.json"


def load_cached(title: str, artist: str) -> Lyrics | None:
    path = _cache_path(f"{normalize(title)}|{normalize(artist)}")
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if data.get("v") != CACHE_VERSION:
        return None
    if data.get("kind") == "miss":
        if time.time() - data.get("ts", 0) < MISS_TTL:
            return Lyrics(lines=[], source="miss", title=title, artist=artist)
        return None
    if data.get("kind") != "lyrics":
        return None
    lines = [
        LyricLine(time=float(item[0]), text=str(item[1]), end=float(item[2]))
        for item in data.get("lines", [])
        if len(item) >= 2
    ]
    return Lyrics(
        lines=lines,
        source=data.get("source", "cache"),
        title=data.get("title", title),
        artist=data.get("artist", artist),
        albummid=data.get("albummid", ""),
        album=data.get("album", ""),
    )


def save_cached(title: str, artist: str, lyrics: Lyrics) -> None:
    path = _cache_path(f"{normalize(title)}|{normalize(artist)}")
    try:
        if not lyrics.lines:
            payload = {"v": CACHE_VERSION, "kind": "miss", "ts": time.time()}
        else:
            payload = {
                "v": CACHE_VERSION,
                "kind": "lyrics",
                "source": lyrics.source,
                "title": lyrics.title,
                "artist": lyrics.artist,
                "albummid": lyrics.albummid,
                "album": lyrics.album,
                "saved": time.time(),
                "lines": [[line.time, line.text, line.end] for line in lyrics.lines],
            }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# ----------------------------------------------------------------------
# 主入口
# ----------------------------------------------------------------------


# 歌词源优先级：中文曲库覆盖从好到差，最后用开放的 LRCLIB 兜底
_PROVIDERS: tuple[tuple[str, str, callable, callable], ...] = (
    ("qq", "QQ音乐", search_qq, fetch_qq_lyric_candidate),
    ("kugou", "酷狗", search_kugou, fetch_kugou_lyric),
    ("netease", "网易云", search_netease, fetch_netease_lyric),
)

GOOD_MATCH = 0.90   # 到这一步就不再看后面的源
MIN_MATCH = 0.55    # 低于这个分数宁可不显示

# 歌词至少要覆盖到歌曲时长的这个比例，否则就换下一个候选。
# 有些曲库的同名条目只有半首（试过一首 200 秒的歌歌词只到 59 秒，
# 结果后半段一直停在最后一行不动），所以要按「覆盖度」再筛一遍。
MIN_COVERAGE = 0.6
MAX_CANDIDATE_TRIES = 4


def _coverage(lines: list[LyricLine], duration: float) -> float:
    """歌词覆盖了歌曲时长的多少（不知道时长就不判断，直接算满分）。"""
    if not lines or duration <= 15.0:
        return 1.0
    return min(1.0, max(0.0, lines[-1].time / duration))


def _provider_of(key: str) -> tuple[str, callable]:
    for item_key, label, _search, resolver in _PROVIDERS:
        if item_key == key:
            return label, resolver
    return key, None


def provider_for_player(app_id: str) -> str:
    """正在用哪个播放器，就优先用哪一家的歌词。

    同一家曲库的歌词，通常就是那个播放器正在显示的那一版 —— 时间轴
    最容易对上（Live 版、剪辑版的差别多半就出在跨库取词上）。
    """
    lowered = (app_id or "").lower()
    if "qqmusic" in lowered:
        return "qq"
    if "cloudmusic" in lowered or "netease" in lowered:
        return "netease"
    if "kugou" in lowered:
        return "kugou"
    return ""


def _try_candidate(
    entry: tuple[float, str, dict], title: str, artist: str, duration: float
) -> tuple[float, Lyrics] | None:
    """抓这个候选的歌词，返回 (综合分, 歌词)；抓不到返回 None。"""
    score, key, candidate = entry
    label, resolver = _provider_of(key)
    if resolver is None:
        return None
    try:
        raw = resolver(candidate)
    except Exception:  # noqa: BLE001
        return None
    lines = parse_lrc(raw or "", title, duration, artist)
    if not lines:
        return None
    extra = candidate.get("extra") or {}
    lyrics = Lyrics(
        lines=lines,
        source=label,
        title=candidate.get("title") or title,
        artist=candidate.get("artist") or artist,
        albummid=extra.get("albummid", ""),
        album=extra.get("album", ""),
    )
    # 匹配分和覆盖度各占一半：宁可要一个名字稍微差点但歌词完整的
    weight = score * (0.5 + 0.5 * _coverage(lines, duration))
    return weight, lyrics


def fetch(
    title: str, artist: str, duration: float = 0.0, prefer: str = ""
) -> Lyrics:
    """按「歌名 + 歌手」在多个曲库中找最合适的一首，取回带时间轴的歌词。

    prefer 是优先使用的曲库 key（qq / kugou / netease）——
    用户在放哪个播放器，就先试它自己家的曲库。

    视频平台的标题常带 `_哔哩哔哩_bilibili` / `【4K修复】` 这类噪声，
    搜曲库之前先洗一遍；歌曲 key（settings.song_offsets）仍用原始标题，不受影响。
    """
    title = clean_title(title) or (title or "")
    artist = clean_title(artist) or (artist or "")

    queries = []
    if artist:
        queries.append(f"{title} {artist}".strip())
    if title:
        queries.append(title)

    providers = list(_PROVIDERS)
    if prefer:
        providers = [item for item in providers if item[0] == prefer] + [
            item for item in providers if item[0] != prefer
        ]

    def best_of(key: str, search) -> tuple[float, str, dict] | None:
        """在这个曲库里搜一遍，返回分数最高的候选。"""
        candidates: list[dict] = []
        for query in queries:
            try:
                candidates = search(query)
            except Exception:  # noqa: BLE001
                candidates = []
            if candidates:
                break
        if not candidates:
            return None
        local: tuple[float, str, dict] | None = None
        for candidate in candidates:
            score = score_candidate(candidate, title, artist, duration)
            if local is None or score > local[0]:
                local = (score, key, candidate)
        return local

    # 第一轮：按优先级找，遇到高分就停（省时间，绝大多数歌在这一步就够了）
    pool: list[tuple[float, str, dict]] = []
    for key, _label, search, _resolver in providers:
        local = best_of(key, search)
        if local is None:
            continue
        pool.append(local)
        if local[0] >= GOOD_MATCH:
            break

    pool.sort(key=lambda item: -item[0])
    # 分数太低的直接不要，宁可不显示
    pool = [item for item in pool if item[0] >= MIN_MATCH]

    best_effort: tuple[float, Lyrics] | None = None
    tried = 0
    for entry in pool:
        if tried >= MAX_CANDIDATE_TRIES:
            break
        tried += 1
        outcome = _try_candidate(entry, title, artist, duration)
        if outcome is None:
            continue
        weight, lyrics = outcome
        coverage = _coverage(lyrics.lines, duration)
        if coverage >= MIN_COVERAGE:
            return lyrics
        # 歌词明显不全（或者根本不是这首歌），先记着，继续看别的源
        if best_effort is None or weight > best_effort[0]:
            best_effort = (weight, lyrics)

    # 走到这儿说明找到的歌词覆盖不全 —— 回头把刚才没搜过的源也试一遍
    searched = {key for _score, key, _candidate in pool}
    for key, _label, search, _resolver in providers:
        if key in searched:
            continue
        local = best_of(key, search)
        if local is None or local[0] < MIN_MATCH:
            continue
        outcome = _try_candidate(local, title, artist, duration)
        if outcome is None:
            continue
        weight, lyrics = outcome
        if _coverage(lyrics.lines, duration) >= MIN_COVERAGE:
            return lyrics
        if best_effort is None or weight > best_effort[0]:
            best_effort = (weight, lyrics)

    if best_effort is not None:
        return best_effort[1]

    raw = search_lrclib(title, artist, duration)
    lines = parse_lrc(raw or "", title, duration, artist)
    if lines:
        return Lyrics(lines=lines, source="LRCLIB", title=title, artist=artist)

    return Lyrics(lines=[], source="", title=title, artist=artist)

"""独立进程生成的歌词位图，避免 QPainter.drawPath 长时间占住 UI 的 GIL。"""

from __future__ import annotations

import atexit
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from multiprocessing import shared_memory
from multiprocessing.connection import Client, Listener
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QImage

from . import render as render_module
from .render import ImageLineArt, make_sprite, render_line_images

WORKER_FLAG = "--lyricdesk-line-art-worker"
FORMAT = QImage.Format.Format_ARGB32_Premultiplied
_LIVE_SHARED: dict[str, shared_memory.SharedMemory] = {}
_LIVE_SHARED_LIMIT = 64


@dataclass
class SharedLineArt:
    key: tuple
    image_art: ImageLineArt
    cleanup: Callable[[], None]


def _color_from_hex(value: str | None) -> QColor | None:
    if not value:
        return None
    color = QColor(value)
    return color if color.isValid() else None


def _share_image(image: QImage | None) -> dict | None:
    if image is None:
        return None
    size = int(image.sizeInBytes())
    shm = shared_memory.SharedMemory(create=True, size=max(1, size))
    try:
        shm.buf[:size] = image.bits()
    except Exception:
        shm.close()
        shm.unlink()
        raise
    _LIVE_SHARED[shm.name] = shm
    while len(_LIVE_SHARED) > _LIVE_SHARED_LIMIT:
        old_name = next(iter(_LIVE_SHARED))
        old = _LIVE_SHARED.pop(old_name)
        try:
            old.close()
        except Exception:  # noqa: BLE001
            pass
    return {
        "name": shm.name,
        "size": size,
        "width": image.width(),
        "height": image.height(),
        "stride": image.bytesPerLine(),
    }


def _attach_image(spec: dict | None) -> tuple[QImage | None, object | None]:
    if spec is None:
        return None, None
    shm = shared_memory.SharedMemory(name=spec["name"])
    image = QImage(
        shm.buf,
        int(spec["width"]),
        int(spec["height"]),
        int(spec["stride"]),
        FORMAT,
    )
    return image, shm


def _render_request(key: tuple, request: dict) -> dict:
    render_module.set_letter_spacing(
        float(request.get("letter_spacing") or 0.0)
    )
    sprite = make_sprite(
        str(request["text"]),
        str(request["family"]),
        int(request["size"]),
        QFont.Weight(int(request["weight"])),
    )
    image_art = render_line_images(
        sprite,
        QColor(str(request["base_color"])),
        (
            tuple(request["grad_colors"])
            if request.get("grad_colors") is not None
            else None
        ),
        _color_from_hex(request.get("glow_color")),
        float(request.get("outline_width") or 0.0),
        _color_from_hex(request.get("outline_color")),
        bool(request.get("shadow", True)),
        float(request.get("dpr") or 1.0),
        bool(request.get("glow", False)),
    )
    shared = {
        "base": _share_image(image_art.base),
        "highlight": _share_image(image_art.highlight),
        "soft_highlight": _share_image(image_art.soft_highlight),
    }
    return {
        "type": "result",
        "key": key,
        "shared": shared,
        "advance": image_art.advance,
        "ascent": image_art.ascent,
        "descent": image_art.descent,
        "offset_x": image_art.offset_x,
        "baseline_y": image_art.baseline_y,
        "height": image_art.height,
        "font_size": image_art.font_size,
        "dpr": image_art.dpr,
        "text": image_art.text,
    }


def serve(address, authkey: bytes) -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance() or QGuiApplication([])
    from .fonts import register_all

    register_all()
    connection = Client(address, authkey=authkey)
    try:
        while True:
            message = connection.recv()
            if message is None:
                break
            if isinstance(message, dict) and message.get("type") == "ack":
                for name in message.get("names") or ():
                    old = _LIVE_SHARED.pop(str(name), None)
                    if old is not None:
                        try:
                            old.close()
                            old.unlink()
                        except Exception:  # noqa: BLE001
                            pass
                continue
            request_id, key, request = message
            try:
                response = _render_request(key, request)
                response["id"] = request_id
            except Exception as exc:  # noqa: BLE001
                response = {
                    "type": "error",
                    "id": request_id,
                    "key": key,
                    "message": repr(exc),
                }
            connection.send(response)
    finally:
        for old in _LIVE_SHARED.values():
            try:
                old.close()
                old.unlink()
            except Exception:  # noqa: BLE001
                pass
        _LIVE_SHARED.clear()
        connection.close()
        app.quit()
    return 0


class LineArtClient:
    """后台子进程 + 双向管道；主线程只负责排队和把共享内存转 QPixmap。"""

    def __init__(self) -> None:
        self._authkey = os.urandom(24)
        self._listener = Listener(address=("127.0.0.1", 0), authkey=self._authkey)
        self._requests: queue.Queue[tuple[int, tuple, dict] | None] = queue.Queue()
        self._results: queue.Queue[dict] = queue.Queue()
        self._connection = None
        self._process: subprocess.Popen | None = None
        log_path = Path(os.environ.get("TEMP") or ".") / "lyricdesk-line-art-worker.log"
        try:
            self._log = log_path.open("ab", buffering=0)
        except OSError:
            self._log = None
        self._next_id = 0
        self._closed = False
        threading.Thread(
            target=self._boot,
            name="line-art-bridge",
            daemon=True,
        ).start()

    def _command(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, WORKER_FLAG]
        entry = Path(__file__).resolve().parent.parent / "main.py"
        return [sys.executable, str(entry), WORKER_FLAG]

    def _boot(self) -> None:
        host, port = self._listener.address
        command = [
            *self._command(),
            "--address",
            f"{host}:{port}",
            "--authkey",
            self._authkey.hex(),
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=self._log or subprocess.DEVNULL,
                creationflags=creationflags,
            )
            self._connection = self._listener.accept()
            self._listener.close()
        except Exception:  # noqa: BLE001
            try:
                self._listener.close()
            except Exception:  # noqa: BLE001
                pass
            return
        threading.Thread(
            target=self._send_loop,
            name="line-art-sender",
            daemon=True,
        ).start()
        self._receive_loop()

    def _send_loop(self) -> None:
        while not self._closed:
            try:
                message = self._requests.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                if message is None:
                    self._connection.send(None)
                    return
                self._connection.send(message)
            except Exception:  # noqa: BLE001
                return

    def _receive_loop(self) -> None:
        while not self._closed:
            try:
                message = self._connection.recv()
            except Exception:  # noqa: BLE001
                return
            if message is None:
                return
            self._results.put(message)

    def submit(self, key: tuple, request: dict) -> None:
        self._next_id += 1
        self._requests.put((self._next_id, key, request))

    def poll(self, limit: int = 1) -> list[SharedLineArt]:
        output: list[SharedLineArt] = []
        while len(output) < limit:
            try:
                message = self._results.get_nowait()
            except queue.Empty:
                break
            if message.get("type") != "result":
                if message.get("type") == "error":
                    try:
                        path = (
                            Path(os.environ.get("TEMP") or ".")
                            / "lyricdesk-line-art-error.log"
                        )
                        path.write_text(
                            str(message.get("message") or "unknown error"),
                            encoding="utf-8",
                        )
                    except Exception:  # noqa: BLE001
                        pass
                continue
            shms: list[object] = []
            try:
                base, base_shm = _attach_image(message["shared"].get("base"))
                highlight, highlight_shm = _attach_image(
                    message["shared"].get("highlight")
                )
                soft, soft_shm = _attach_image(
                    message["shared"].get("soft_highlight")
                )
                shms.extend(
                    shm for shm in (base_shm, highlight_shm, soft_shm) if shm is not None
                )
                image_art = ImageLineArt(
                    base=base,
                    highlight=highlight,
                    soft_highlight=soft,
                    advance=float(message["advance"]),
                    ascent=float(message["ascent"]),
                    descent=float(message["descent"]),
                    offset_x=float(message["offset_x"]),
                    baseline_y=float(message["baseline_y"]),
                    height=float(message["height"]),
                    font_size=int(message["font_size"]),
                    dpr=float(message["dpr"]),
                    text=str(message.get("text") or ""),
                )
            except Exception:  # noqa: BLE001
                for shm in shms:
                    try:
                        shm.close()
                        shm.unlink()
                    except Exception:  # noqa: BLE001
                        pass
                continue

            names = tuple(
                str(spec["name"])
                for spec in message["shared"].values()
                if spec is not None
            )

            def cleanup(items=tuple(shms), shared_names=names) -> None:
                self._requests.put({"type": "ack", "names": shared_names})
                for shm in items:
                    try:
                        shm.close()
                        shm.unlink()
                    except Exception:  # noqa: BLE001
                        pass

            output.append(
                SharedLineArt(
                    key=tuple(message["key"]),
                    image_art=image_art,
                    cleanup=cleanup,
                )
            )
        return output

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._requests.put(None)
        time.sleep(0.05)
        try:
            if self._connection is not None:
                self._connection.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._listener.close()
        except Exception:  # noqa: BLE001
            pass
        if self._process is not None and self._process.poll() is None:
            try:
                self._process.terminate()
                self._process.wait(timeout=2)
            except Exception:  # noqa: BLE001
                pass
        if self._log is not None:
            try:
                self._log.close()
            except Exception:  # noqa: BLE001
                pass


_CLIENT: LineArtClient | None = None
_CLIENT_LOCK = threading.Lock()


def enabled() -> bool:
    """自动化测试默认走同步路径；需要实测子进程时可显式打开。"""
    if os.environ.get("LYRICDESK_FORCE_LINE_WORKER") == "1":
        return True
    return os.environ.get("QT_QPA_PLATFORM", "").lower() != "offscreen"


def client() -> LineArtClient:
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None:
            _CLIENT = LineArtClient()
            atexit.register(_CLIENT.close)
        return _CLIENT


def worker_main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        address_index = args.index("--address")
        auth_index = args.index("--authkey")
        address = args[address_index + 1]
        host, port_text = address.rsplit(":", 1)
        authkey = bytes.fromhex(args[auth_index + 1])
        return serve((host, int(port_text)), authkey)
    except Exception:
        try:
            path = Path(os.environ.get("TEMP") or ".") / "lyricdesk-line-art-crash.log"
            path.write_text(traceback.format_exc(), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        return 1

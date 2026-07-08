"""TCP image file transfer helpers.

Protocol:
1. Sender writes a 4-byte big-endian JSON header length.
2. Sender writes a UTF-8 JSON header with filename and size.
3. Sender streams exactly size bytes.
4. Receiver replies with ``OK\n`` after the file is saved.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import socket
from typing import Optional, Tuple, Union


DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 5001
DEFAULT_CHUNK_SIZE = 64 * 1024
DEFAULT_RECEIVE_DIR = Path("received_photos")

PathLike = Union[str, Path]


class ImageTransferError(RuntimeError):
    """Raised when TCP image transfer fails."""


@dataclass(frozen=True)
class SendResult:
    path: Path
    size: int
    host: str
    port: int


@dataclass(frozen=True)
class ReceiveResult:
    path: Path
    size: int
    peer: Tuple[str, int]


def send_file(
    file_path: PathLike,
    *,
    host: str,
    port: int = DEFAULT_PORT,
    timeout_seconds: float = 10.0,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> SendResult:
    """Send one file to a TCP receiver."""

    path = Path(file_path)
    if not path.is_file():
        raise ImageTransferError(f"File does not exist: {path}")

    size = path.stat().st_size
    header = json.dumps(
        {"filename": path.name, "size": size},
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(header) > 65535:
        raise ImageTransferError("Transfer header is unexpectedly large")

    try:
        with socket.create_connection((host, port), timeout=timeout_seconds) as sock:
            sock.settimeout(timeout_seconds)
            sock.sendall(len(header).to_bytes(4, "big"))
            sock.sendall(header)
            with path.open("rb") as image_file:
                while True:
                    chunk = image_file.read(chunk_size)
                    if not chunk:
                        break
                    sock.sendall(chunk)
            ack = sock.recv(16)
    except OSError as exc:
        raise ImageTransferError(f"Cannot send {path} to {host}:{port}: {exc}") from exc

    if ack.strip() != b"OK":
        raise ImageTransferError(f"Receiver did not acknowledge transfer: {ack!r}")

    return SendResult(path=path, size=size, host=host, port=port)


def receive_one_file(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    output_dir: PathLike = DEFAULT_RECEIVE_DIR,
    timeout_seconds: Optional[float] = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> ReceiveResult:
    """Listen for one TCP image transfer and save it."""

    destination_dir = Path(output_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if timeout_seconds is not None:
                server.settimeout(timeout_seconds)
            server.bind((host, port))
            server.listen(1)
            conn, peer = server.accept()
            with conn:
                if timeout_seconds is not None:
                    conn.settimeout(timeout_seconds)
                header_size = int.from_bytes(_recv_exact(conn, 4), "big")
                if header_size <= 0 or header_size > 65535:
                    raise ImageTransferError(f"Invalid header size: {header_size}")
                header = json.loads(_recv_exact(conn, header_size).decode("utf-8"))
                filename = _safe_filename(str(header.get("filename", "photo.jpg")))
                size = int(header["size"])
                if size < 0:
                    raise ImageTransferError(f"Invalid file size: {size}")

                target_path = _next_available_path(destination_dir / filename)
                remaining = size
                with target_path.open("wb") as output:
                    while remaining > 0:
                        chunk = conn.recv(min(chunk_size, remaining))
                        if not chunk:
                            raise ImageTransferError("Connection closed before file ended")
                        output.write(chunk)
                        remaining -= len(chunk)
                conn.sendall(b"OK\n")
    except OSError as exc:
        raise ImageTransferError(f"Cannot receive file on {host}:{port}: {exc}") from exc
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ImageTransferError(f"Invalid transfer metadata: {exc}") from exc

    return ReceiveResult(path=target_path, size=size, peer=peer)


def _recv_exact(conn: socket.socket, byte_count: int) -> bytes:
    data = bytearray()
    while len(data) < byte_count:
        chunk = conn.recv(byte_count - len(data))
        if not chunk:
            raise ImageTransferError("Connection closed unexpectedly")
        data.extend(chunk)
    return bytes(data)


def _safe_filename(filename: str) -> str:
    allowed = []
    for char in Path(filename).name:
        if char.isalnum() or char in ("-", "_", ".", " "):
            allowed.append(char)
        else:
            allowed.append("_")
    cleaned = "".join(allowed).strip(" .")
    return cleaned or "photo.jpg"


def _next_available_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1

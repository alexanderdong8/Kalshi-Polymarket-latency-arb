"""Keyboard listener for manual abort.

Reads stdin one character at a time in cbreak mode and sets an asyncio.Event
when the abort key is pressed. POSIX-only (termios/tty); on Windows or a
non-TTY stdin it returns immediately and abort is driven by SIGUSR1 only.
"""
from __future__ import annotations

import asyncio
import sys

try:
    import termios
    import tty
    _HAS_TERMIOS = True
except ImportError:  # pragma: no cover - Windows
    _HAS_TERMIOS = False


async def listen_for_abort_key(abort_event: asyncio.Event, key: str = "a") -> None:
    """Set abort_event whenever `key` is pressed. Restores terminal on cancel.

    When stdin is not a TTY (e.g. piped input, CI) or termios is unavailable,
    this blocks forever without reading — so it can sit in the task set without
    tripping a FIRST_COMPLETED shutdown. Abort then comes from SIGUSR1 only.
    """
    if not _HAS_TERMIOS or not sys.stdin.isatty():
        await asyncio.Event().wait()
        return
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        loop = asyncio.get_running_loop()
        while True:
            ch = await loop.run_in_executor(None, sys.stdin.read, 1)
            if not ch:
                # EOF — nothing more to read.
                return
            if ch == key:
                abort_event.set()
    except asyncio.CancelledError:
        raise
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:
            pass

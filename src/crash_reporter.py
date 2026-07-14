"""Crash diagnostics and guards for Qt/asyncio callbacks."""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Optional


MAX_LOG_BYTES = 2 * 1024 * 1024
_hook_log_path: Optional[Path] = None


def default_log_path() -> Path:
    return Path.home() / ".v-link" / "vlink-crash.log"


def _resolve_log_path(log_path: str | os.PathLike | None = None) -> Path:
    return Path(log_path) if log_path else default_log_path()


def _prepare_log(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.exists() and path.stat().st_size >= MAX_LOG_BYTES:
            previous = path.with_suffix(path.suffix + ".1")
            try:
                previous.unlink(missing_ok=True)
            except OSError:
                pass
            path.replace(previous)
    except OSError:
        pass


def record_message(source: str, message: str, log_path: str | os.PathLike | None = None):
    path = _resolve_log_path(log_path or _hook_log_path)
    try:
        _prepare_log(path)
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with path.open("a", encoding="utf-8") as stream:
            stream.write(
                f"\n[{timestamp}] source={source} pid={os.getpid()} "
                f"thread={threading.current_thread().name}\n{message}\n"
            )
    except Exception:
        pass


def record_exception(
    source: str,
    exc: BaseException,
    log_path: str | os.PathLike | None = None,
    tb: TracebackType | None = None,
):
    path = _resolve_log_path(log_path or _hook_log_path)
    try:
        _prepare_log(path)
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with path.open("a", encoding="utf-8") as stream:
            stream.write(
                f"\n[{timestamp}] source={source} pid={os.getpid()} "
                f"thread={threading.current_thread().name}\n"
            )
            traceback.print_exception(type(exc), exc, tb or exc.__traceback__, file=stream)
    except Exception:
        pass


def install_exception_hooks(log_path: str | os.PathLike | None = None) -> Path:
    """Prevent PyQt from converting an unhandled callback exception into qFatal."""
    global _hook_log_path
    path = _resolve_log_path(log_path)
    _hook_log_path = path

    if not getattr(sys.excepthook, "_vlink_exception_hook", False):
        def sys_hook(exc_type, exc_value, exc_tb):
            record_exception("sys.excepthook", exc_value, path, exc_tb)
            try:
                sys.__excepthook__(exc_type, exc_value, exc_tb)
            except Exception:
                pass

        sys_hook._vlink_exception_hook = True
        sys.excepthook = sys_hook

    if hasattr(threading, "excepthook") and not getattr(
        threading.excepthook, "_vlink_exception_hook", False
    ):
        def thread_hook(args):
            record_exception(
                f"threading.excepthook:{args.thread.name}",
                args.exc_value,
                path,
                args.exc_traceback,
            )

        thread_hook._vlink_exception_hook = True
        threading.excepthook = thread_hook

    return path


def install_asyncio_exception_handler(
    loop: asyncio.AbstractEventLoop,
    log_path: str | os.PathLike | None = None,
):
    path = _resolve_log_path(log_path or _hook_log_path)
    previous_handler = loop.get_exception_handler()

    def handler(active_loop: asyncio.AbstractEventLoop, context: dict):
        exc = context.get("exception")
        message = str(context.get("message") or "Unhandled asyncio error")
        if isinstance(exc, BaseException):
            record_exception(f"asyncio:{message}", exc, path)
        else:
            record_message("asyncio", message, path)

        try:
            if previous_handler:
                previous_handler(active_loop, context)
            else:
                active_loop.default_exception_handler(context)
        except Exception:
            pass

    loop.set_exception_handler(handler)


def install_qasync_timer_guard(log_path: str | os.PathLike | None = None) -> bool:
    """Ignore and clean up a stale qasync timer event instead of aborting PyQt."""
    try:
        import qasync

        timer_class = getattr(qasync, "_SimpleTimer", None)
        if timer_class is None or getattr(timer_class.timerEvent, "_vlink_timer_guard", False):
            return timer_class is not None

        original_timer_event = timer_class.timerEvent
        path = _resolve_log_path(log_path or _hook_log_path)

        def guarded_timer_event(timer, event):
            try:
                return original_timer_event(timer, event)
            except KeyError as exc:
                timer_id = event.timerId()
                callbacks = getattr(timer, "_SimpleTimer__callbacks", None)
                if isinstance(callbacks, dict):
                    callbacks.pop(timer_id, None)
                try:
                    timer.killTimer(timer_id)
                except Exception:
                    pass
                record_exception("qasync._SimpleTimer.timerEvent", exc, path)
                return None

        guarded_timer_event._vlink_timer_guard = True
        timer_class.timerEvent = guarded_timer_event
        return True
    except Exception as exc:
        record_exception("install_qasync_timer_guard", exc, log_path)
        return False

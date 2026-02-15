"""
V-Link localization helper.
Supports language modes: system / ru / en.
"""

from __future__ import annotations

import json
import locale
import os
import sys
from pathlib import Path
from typing import Any


SUPPORTED_LANGS = ("ru", "en")
SUPPORTED_MODES = ("system", "ru", "en")


class I18N:
    def __init__(self):
        self.mode = "system"
        self.language = "ru"
        self._catalog: dict[str, str] = {}
        self._fallback_catalog: dict[str, str] = {}

    def _locale_dirs(self) -> list[Path]:
        dirs: list[Path] = []
        if hasattr(sys, "_MEIPASS"):
            dirs.append(Path(sys._MEIPASS) / "resources" / "locales")
        dirs.append(Path(__file__).resolve().parents[2] / "resources" / "locales")
        return dirs

    def _read_catalog(self, lang: str) -> dict[str, str]:
        filename = f"{lang}.json"
        for base_dir in self._locale_dirs():
            path = base_dir / filename
            try:
                if not path.exists():
                    continue
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items()}
            except Exception:
                continue
        return {}

    @staticmethod
    def _normalize_mode(mode: str | None) -> str:
        value = str(mode or "system").strip().lower()
        if value in SUPPORTED_MODES:
            return value
        return "system"

    @staticmethod
    def detect_system_language() -> str:
        candidates = []
        try:
            value = locale.getlocale()[0]
            if value:
                candidates.append(value)
        except Exception:
            pass
        try:
            value = locale.getdefaultlocale()[0]
            if value:
                candidates.append(value)
        except Exception:
            pass
        env_lang = os.environ.get("LANG", "")
        if env_lang:
            candidates.append(env_lang)

        for raw in candidates:
            probe = str(raw).lower()
            if probe.startswith("en"):
                return "en"
            if probe.startswith("ru"):
                return "ru"
        return "ru"

    def resolve_language(self, mode: str | None) -> str:
        normalized = self._normalize_mode(mode)
        if normalized in SUPPORTED_LANGS:
            return normalized
        return self.detect_system_language()

    def load(self, mode: str | None) -> str:
        self.mode = self._normalize_mode(mode)
        self.language = self.resolve_language(self.mode)
        self._fallback_catalog = self._read_catalog("ru")
        self._catalog = self._read_catalog(self.language)
        return self.language

    def t(self, key: str, **kwargs: Any) -> str:
        value = self._catalog.get(key)
        if value is None:
            value = self._fallback_catalog.get(key, key)
        if kwargs:
            try:
                return str(value).format(**kwargs)
            except Exception:
                return str(value)
        return str(value)


i18n = I18N()


def t(key: str, **kwargs: Any) -> str:
    return i18n.t(key, **kwargs)

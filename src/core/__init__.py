"""
V-Link - Core Module
"""

from .settings import Settings, DEFAULT_SETTINGS
from .autostart import is_autostart_enabled, set_autostart
from .updater import Updater
from .clipboard_sync import ClipboardSyncManager
from .i18n import i18n, t

__all__ = [
    'Settings',
    'DEFAULT_SETTINGS',
    'is_autostart_enabled',
    'set_autostart',
    'Updater',
    'ClipboardSyncManager',
    'i18n',
    't',
]

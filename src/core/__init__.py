"""
V-Link - Core Module
"""

from .settings import Settings, DEFAULT_SETTINGS
from .autostart import is_autostart_enabled, set_autostart
from .updater import Updater

__all__ = [
    'Settings',
    'DEFAULT_SETTINGS',
    'is_autostart_enabled',
    'set_autostart',
    'Updater',
]

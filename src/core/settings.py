"""
V-Link - Settings Manager
РЈРїСЂР°РІР»РµРЅРёРµ РЅР°СЃС‚СЂРѕР№РєР°РјРё РїСЂРёР»РѕР¶РµРЅРёСЏ
"""

import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict


DEFAULT_SETTINGS = {
    'port': 8765,
    'download_dir': str(Path.home() / "Downloads" / "V-Link"),
    'secure_mode': False,
    'nonstandard_network_mode': False,
    'relay_mode': False,
    'relay_server_url': '',
    'relay_channel': 'default',
    'relay_client_id': '',
    'adaptive_profile': {},
    'autostart': False,
    'start_minimized': False,
    'close_to_tray': True,
    'show_notifications': True,
    'theme': 'dark',
    'auto_check_updates': True,
    'last_update_check': '',
    'skipped_version': '',
}


class Settings:
    """РњРµРЅРµРґР¶РµСЂ РЅР°СЃС‚СЂРѕРµРє"""
    
    def __init__(self):
        self.config_dir = Path.home() / ".v-link"
        self.config_file = self.config_dir / "settings.json"
        self.settings: Dict[str, Any] = {}
        
        self._load()
    
    def _load(self):
        """Р—Р°РіСЂСѓР·РёС‚СЊ РЅР°СЃС‚СЂРѕР№РєРё"""
        self.settings = DEFAULT_SETTINGS.copy()
        
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                    self.settings.update(saved)
            except Exception:
                pass
    
    def _save(self):
        """РЎРѕС…СЂР°РЅРёС‚СЊ РЅР°СЃС‚СЂРѕР№РєРё"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.settings, f, indent=2, ensure_ascii=False)
    
    def get(self, key: str, default: Any = None) -> Any:
        """РџРѕР»СѓС‡РёС‚СЊ Р·РЅР°С‡РµРЅРёРµ"""
        return self.settings.get(key, default)
    
    def set(self, key: str, value: Any):
        """РЈСЃС‚Р°РЅРѕРІРёС‚СЊ Р·РЅР°С‡РµРЅРёРµ"""
        self.settings[key] = value
        self._save()

    def set_many(self, values: Dict[str, Any]):
        """Update multiple settings with a single save operation."""
        if not values:
            return
        self.settings.update(values)
        self._save()
    
    @property
    def port(self) -> int:
        return self.get('port', 8765)
    
    @property
    def download_dir(self) -> str:
        return self.get('download_dir')
    
    @property
    def start_minimized(self) -> bool:
        return self.get('start_minimized', False)

    @property
    def secure_mode(self) -> bool:
        return bool(self.get('secure_mode', False))

    @property
    def close_to_tray(self) -> bool:
        return bool(self.get('close_to_tray', True))

    @property
    def adaptive_profile(self) -> dict:
        value = self.get('adaptive_profile', {})
        return value if isinstance(value, dict) else {}

    @property
    def autostart(self) -> bool:
        return bool(self.get('autostart', False))

    @property
    def nonstandard_network_mode(self) -> bool:
        return bool(self.get('nonstandard_network_mode', True))

    @property
    def relay_mode(self) -> bool:
        return bool(self.get('relay_mode', False))

    @property
    def relay_server_url(self) -> str:
        return str(self.get('relay_server_url', '') or '').strip()

    @property
    def relay_channel(self) -> str:
        value = str(self.get('relay_channel', 'default') or '').strip()
        return value or 'default'

    @property
    def relay_client_id(self) -> str:
        current = str(self.get('relay_client_id', '') or '').strip()
        if current:
            return current
        generated = uuid.uuid4().hex[:16]
        self.settings['relay_client_id'] = generated
        self._save()
        return generated


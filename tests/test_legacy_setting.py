from core.i18n import i18n
from core.settings import DEFAULT_SETTINGS
from PyQt6.QtWidgets import QApplication, QLabel
from ui.settings_dialog import SettingsDialog


class MemorySettings:
    def __init__(self):
        self.values = dict(DEFAULT_SETTINGS, secure_shared_secret='fixture-key', secure_mode=True)

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set_many(self, updates):
        self.values.update(updates)


def test_legacy_setting_is_default_off_and_explicitly_saved():
    app = QApplication.instance() or QApplication([])
    settings = MemorySettings()
    i18n.load('en')
    dialog = SettingsDialog(settings)
    try:
        assert not dialog.legacy_secure_check.isChecked()
        assert dialog.legacy_secure_check.isEnabled()
        assert any('old protocol exposes the encryption key' in label.text() for label in dialog.findChildren(QLabel))
        dialog.legacy_secure_check.setChecked(True)
        dialog._save_and_close()
        assert settings.values['allow_legacy_secure'] is True
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
        i18n.load('ru')

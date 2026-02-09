# V-Link ⚡

**V-Link** — быстрое и удобное приложение для передачи файлов между устройствами в одной локальной сети.

## ✨ Возможности

- 🚀 **Высокая скорость**: асинхронная передача и адаптивные параметры потока.
- 🔒 **Безопасный режим (опционально)**: шифрование, проверка целостности и аутентификация.
- 🔎 **Умное обнаружение устройств**: mDNS/Zeroconf + fallback по альтернативным IP.
- 🌐 **Стабильность в сложной сети**: работа в сценариях с VPN и несколькими интерфейсами.
- 🔋 **Low-power режим**: минимальная нагрузка в фоне.
- 🪟 **Удобство Windows**: трей-режим, автозапуск, drag-and-drop.

## 📦 Скачать

- Актуальные версии: [GitHub Releases](https://github.com/Volfheim/V-Link/releases)

## 🧰 Запуск из исходников

```bash
git clone https://github.com/Volfheim/V-Link.git
cd V-Link
pip install -r requirements.txt
python src/main.py
```

## 🏗 Сборка

```bash
python build.py
```

Готовый `.exe` будет в папке `dist/`.

## 🧪 Технологии

- Python 3.13
- PyQt6
- aiohttp
- zeroconf
- qasync
- cryptography (Fernet)
- PyInstaller

## 📝 Изменения

- Подробная история: [CHANGELOG.md](CHANGELOG.md)

## 👨‍💻 Автор

- **Volfheim**

## 📄 Лицензия

- [MIT License](LICENSE)

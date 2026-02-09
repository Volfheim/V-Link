# V-Link

V-Link is a desktop app for fast file transfer between devices in the same local network.

## Key Features

- High-speed transfer with async streaming and adaptive chunk size.
- Secure mode (optional): stream encryption, integrity checks, and authentication.
- Smart discovery with mDNS/Zeroconf and fallback IP routing.
- VPN-tolerant behavior in mixed home-network scenarios.
- Low-power background mode.
- Tray mode and Windows autostart support.

## Download

- Releases: https://github.com/Volfheim/V-Link/releases

## Run From Source

```bash
git clone https://github.com/Volfheim/V-Link.git
cd V-Link
pip install -r requirements.txt
python src/main.py
```

## Build

```bash
python build.py
```

The built executable appears in `dist/`.

## Tech Stack

- Python 3.13
- PyQt6
- aiohttp
- zeroconf
- qasync
- cryptography (Fernet)
- PyInstaller

## Changelog

- See `CHANGELOG.md`.

## Author

- Volfheim

## License

- See `LICENSE`.

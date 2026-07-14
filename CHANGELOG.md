# История изменений (Changelog)

Все заметные изменения в проекте V-Link будут документированы в этом файле.

## [2.4.4] - 2026-07-14
### Notifications
* Kept the Explorer action visible for transfers with long file names.
* Moved transfer size before the file name and removed redundant notification text.

## [2.4.3] - 2026-07-14
### Stability
* Prevented unhandled PyQt callback exceptions from terminating the application through `qFatal`.
* Added persistent crash diagnostics to `~/.v-link/vlink-crash.log`.
* Guarded stale qasync timer events that may appear after a long sleep or tray idle period.
* Background task failures are now consumed and logged instead of being silently discarded.

### Notifications
* Clicking a completed-transfer notification now opens the folder or selects the file in Windows Explorer.
* Transfer notifications now include a clear click action and stay visible longer.

## [2.4.2] - 2026-06-09
### Features & Improvements
* **WebDAV Support:** Added read-only WebDAV server (supporting `OPTIONS`, `PROPFIND`, `GET`, `HEAD`) to easily transfer large folders (500+ GB) from PC to phone. Directly accessible from native File apps on iOS/Android.
* **UI Fixes:** Fixed overlapping elements (ZIP download and Date sort selector) on mobile screens.
* **Overscroll Fix:** Fixed the white background block shown when scrolling down past page limits on mobile browsers.
* **Performance Optimizations:** Removed redundant SHA-256 calculation for file-info queries, reducing CPU usage during mobile sync. Moved blocking directory scan operations to background threads (`run_in_executor`).

## [2.4.1] - 2026-06-09
### Bugfixes
* Fixed server crash at startup due to missing handlers (`_handle_mobile_browse`, `_handle_mobile_download_folder`, `_handle_mobile_file_info`) in the `TransferServer` class.

## [2.4.0] - 2026-06-09
### Mobile Folder Transfer & OOM protection
* Added folder navigation (breadcrumbs) and folder contents listing in the mobile web interface.
* Implemented queue-based file-by-file upload from mobile phone to PC, preventing browser OOM crashes on large folders (up to 600 GB).
* Added checkmarks for already uploaded files to support skipping duplicates and resuming transfer after network dropouts.
* Added on-the-fly ZIP streaming for downloading folders from PC to phone (restricted to 4 GB).
* Added direct browser download for files larger than 50 MB, bypassing JavaScript buffer to avoid tab crashes.

## [2.3.2] - 2026-05-13
### Mobile connectivity
* Removed the alternate-address selector from the phone connection dialog.
* Mobile web server now prefers physical LAN interfaces and skips VPN/virtual adapters before fallback binding.
* Added a local LAN self-check with a clear warning when the PC VPN/firewall blocks the phone URL.

## [2.3.1] - 2026-05-13
### Mobile connectivity
* Mobile connection dialog now offers all detected PC local addresses and regenerates the QR code when another address is selected.
* Improved mobile address selection for LAN + VPN setups by preferring Wi-Fi/Ethernet interfaces over VPN interfaces.
* Added VPN/local-network access guidance to the phone connection dialog.

## [2.3.0] - 2026-05-12
### Transfer fixes
* Fixed direct desktop-to-desktop upload regression after folder-transfer changes.
* Added folder transfer without archiving from desktop and mobile web, preserving relative paths.
* Added a detailed confirmation dialog for desktop folder transfers.
* Improved transfer progress display with live transferred/total size.
* Improved mobile web upload progress and recursive file listing/downloads.

### Network & security
* Secure mode now uses a per-install shared key instead of a public hardcoded secret.
* Relay transport preserves folder paths and sanitizes relay channel names.
* Improved LAN-vs-VPN IP prioritization for mixed local network/VPN environments.

## [2.2.0] - 2026-02-15
### 🌍 Localization (i18n)
* **Full Support**: Added complete English and Russian localization for Desktop UI and Web Interface.
* **Smart Detection**: Defaults to system language ("System"), with manual override in Settings.
* **Web Interface**: Mobile web UI now adapts to the application language (RU/EN).
* **Restart Prompt**: User is prompted to restart the app when changing language settings.

### 📡 Network & Connectivity
* **VPN/Multi-net Fixes**: Improved discovery logic to prioritize physical LAN/Wi-Fi interfaces over VPN/Virtual adapters.
* **Auto-Compatibility**: Automatically enables compatibility mode if complex network environments (VPN, Hotspot, Multiple subnets) are detected.

### 🛠 Technical & Cleanup

* **Build Optimization**: Build process no longer generates versioned filenames (just `V-Link.exe`), preventing clutter.
* **Refactoring**: Introduced `i18n` core module and localized JSON resources.

## [2.1.2] - 2026-02-12
### 💄 UI Polish
*   **Access Denied Action**: Кнопка "Попробовать снова" заменена на "Закрыть окно", так как для доступа всегда требуется новый токен.

## [2.1.1] - 2026-02-12
### 💄 UI Polish
*   **Access Denied Page**: Страница ошибки 403 теперь имеет красивый адаптивный дизайн в темной теме, вместо простого текста.

## [2.1.0] - 2026-02-12
### 📱 Mobile Web Experience
*   **Полный редизайн**: Веб-интерфейс для телефонов переписан с нуля.
    *   **Dark Mode**: Стильная темная тема, соответствующая приложению.
    *   **Native Feel**: Крупные кнопки, анимации и удобство для тач-экранов.
    *   **Интерактивность**: Прогресс-бар загрузки, всплывающие уведомления и автообновление списка файлов.
    *   **Локализация**: Интерфейс полностью на русском языке.

## [2.0.2] - 2026-02-11
### UX/UI Polish
* **Header Layout**: Fixed issue where the update button would overlap or hide the application title. Titles now have a minimum width to prevent compression.
* **Localization**: The "Restart after update" dialog now uses localized "Да/Нет" buttons instead of system defaults (Yes/No).
* **Terminology**: Renamed "Мобильный" button to "Мобильник".

## [2.0.1] - 2026-02-11
### Fixes & Stability
* **Fixed Autostart**: Transitioned to reliable registry-based autostart with auto-repair on launch.
* **Single Instance**: Added protection against multiple instances (port conflict prevention).
* **Window Visibility**: Fixed hidden window bug on startup.
* **Network**: Improved port fallback and binding logic.

## [2.0.0] - 2026-02-11
### New Features
* Mobile Web Share via QR code (Android/iOS in browser, no app install required).
* Session token protection for mobile web access while mobile dialog is open.
* Clipboard synchronization between V-Link peers:
  * Text sync enabled by default.
  * Image sync optional in settings (size-limited for stability).

### Improvements
* Added "Mobile" button in main window.
* Added clipboard settings block in Settings dialog.
* Fixed settings flow regression around manual update-check dialog.

## [1.9.5] - 2026-02-11
### Новые функции
* **Ручная проверка обновлений**: Добавлена кнопка «Проверить обновления» в Настройки -> О программе (исправлен краш).
* (Проверка при запуске сохранена).

### Косметика
* Удалена надпись "Powered by Volfheim" из настроек.

## [1.9.4] - 2026-02-11
### Изменения
* **Надежное обновление**: Исправлена ошибка "DLL Load Failed" при установке новой версии (добавлена разблокировка файлов).
* **Проверка при запуске**: V-Link проверяет наличие новой версии при каждом запуске.
* (Кнопка ручной проверки временно убрана для стабилизации).
### Изменения
* **Проверка обновлений при запуске**: теперь V-Link проверяет наличие новой версии при каждом запуске программы, игнорируя 12-часовой таймер.
* (Таймер 12 часов теперь действует только при восстановлении окна из трея).

## [1.9.3] - 2026-02-10
### Улучшения
* Пункт **«Открыть папку загрузок»** в меню иконки трея.
* Уведомления теперь показывают направление (📥 Получен / 📤 Отправлен) и размер файла.

## [1.9.2] - 2026-02-10
### Исправления
* **Критический фикс автообновления** — `move` между дисками (C: → E:) ломал EXE. Заменён на `copy /B`. Добавлена очистка Zone.Identifier (Defender), верификация файла и увеличенные задержки.
* Версия приложения теперь отображается в тултипе иконки в трее.
* Диалог обновления теперь показывает чистый текст вместо сырого Markdown.

## [1.9.1] - 2026-02-10
### Улучшения
* **Нестандартные сети (Вариант B)**: режим больше не урезает скорость передачи — всегда используется полная скорость с авто-оптимизацией. При ошибке передачи автоматически переключается на консервативный профиль.
* Режим нестандартных сетей теперь выключен по умолчанию — включается вручную для вузовских/гостевых сетей.

### Исправления
* Убран искусственный лимит на размер файла (было 10 ГБ) — теперь без ограничений.
* Исправлен баг: устройства иногда отображали сами себя в списке. Улучшена детекция собственных адресов (обновление IP-кеша + hostname-based check).

## [1.9.0] - 2026-02-10
### 🔥 Главное
* Добавлено **автоматическое обновление** с GitHub: приложение проверяет наличие новых версий, скачивает и устанавливает обновление в один клик.

### ✨ Новые функции
* Проверка обновлений при запуске и разворачивании окна из трея (с кешем 12 часов).
* Кнопка обновления в заголовке окна — появляется только при наличии новой версии.
* Диалог обновления с описанием изменений из GitHub Release.
* Прогресс скачивания в статус-баре.
* Возможность пропустить версию (кнопка «Пропустить»).
* Подтверждение перед перезапуском, настройки сохраняются.

### 🔧 Технические детали
* Новый модуль `core/updater.py`: проверка API, скачивание EXE, bat-скрипт для замены.
* Обновление не активируется в режиме экономии (low power) и при запуске из исходников.
* Автозапуск (реестр) автоматически обновляется при смене имени EXE.

## [1.8.5] - 2026-02-10
### Исправления
* Устранена ошибка «all ports 8765-8774 are busy» при старте: добавлен fallback на любой свободный порт ОС (port 0), если весь диапазон занят.
* Улучшена проверка `EADDRINUSE` через `errno` (кроссплатформенная совместимость).
* Корректная очистка `runner`/`site` при ошибке запуска сервера.

## [1.8.4] - 2026-02-10
### Performance UX
* Ускорен визуальный запуск: окно появляется сразу, сетевые сервисы поднимаются в фоне.
* Ускорено закрытие: завершение сервисов переведено в неблокирующий режим (без "подвисания" окна).
* Добавлено сообщение "сервисы запускаются", если пользователь начал передачу слишком рано.
* Relay warm-up на старте сделан неблокирующим, чтобы не тормозить запуск приложения.

## [1.8.3] - 2026-02-10
### Hotspot Optimization
* Улучшена работа в сценарии, когда ноутбук/ПК раздаёт Wi‑Fi (Windows Mobile Hotspot).
* Совместимый профиль для нестандартных сетей стал приоритетным для новых установок.
* Добавлено авто-определение хотспота и автоматическое включение совместимого профиля.
* Улучшен discovery-скан в hotspot/ограниченных сетях: быстрее подбор кандидатов и маршрута.
* Добавлен быстрый пункт в трей: `Хот-спот Windows` (открывает настройки хотспота).

### UX
* Раздел `Сеть` оставлен внизу настроек.
* Таймер передачи без миллисекунд (`<1 сек` для коротких файлов), чтобы убрать визуальный рассинхрон.

## [1.8.2] - 2026-02-10
### Fixes & UX
* Раздел `Сеть` в окне настроек перенесён вниз (после остальных разделов).
* Таймер передачи больше не показывает миллисекунды: для коротких передач отображается `<1 сек`, что убирает визуальный рассинхрон между устройствами.
* Нестандартный режим и сообщения об ошибках уточнены: акцент на локальный режим без relay-сервера.
* Улучшен сбор альтернативных IP-кандидатов при отправке (по имени и endpoint), чтобы снизить ложные недоступности.

## [1.8.1] - 2026-02-10
### Fixes
* Discovery no longer hides peers only because temporary ping failed.
* Devices can stay visible as "may be unavailable", then show warning only on actual transfer attempt.
* Relaxed strict reachability filter for mDNS/compatibility paths.
* Improved Relay settings hints with clear examples for `Relay URL` and `Channel`.

## [1.8.0] - 2026-02-10
### 🔥 Главное
* Добавлен полноценный **Relay-режим** для сетей, где прямые подключения между клиентами блокируются (campus/guest Wi-Fi, AP isolation).
* Relay интегрирован в UX как отдельный транспорт и автоматический fallback при недоступности прямого маршрута.

### ✨ Новые функции
* Новый модуль `network/relay.py`:
    * синхронизация peers через relay-сервер,
    * очередь входящих relay-передач,
    * relay upload/download с прогрессом в общем списке передач,
    * совместимость с безопасным режимом (проверка совпадения режима между устройствами).
* Новые настройки сети:
    * `Relay-режим`,
    * `Relay URL`,
    * `Канал`.
* Добавлен reference relay-сервер: `relay/relay_server.py`.

### 🛠 Улучшения UX
* Relay-устройства отображаются отдельно в списке (`[Relay] ...`) с понятным endpoint (`relay-cloud`).
* При недоступности прямого маршрута приложение автоматически пробует Relay (если peer найден в relay).
* Добавлены отдельные предупреждения для relay-недоступности и некорректной relay-настройки.

### 🔧 Надёжность
* Relay и direct режимы разведены по lifecycle (start/stop/low-power), чтобы не ломать основной LAN-стек.
* Обновление списка устройств теперь синхронизирует и direct discovery, и relay peers.

## [1.6.1] - 2026-02-09
### 🔥 Главное
*   Финальная стабилизация сети, UX и режима безопасности.
*   Сборка оптимизирована и переведена на PyInstaller onefile (~43 MB).

### ✨ Новые функции
*   **Безопасный режим**: Добавлен переключатель в настройках. Включает шифрование потока (Fernet) и проверку целостности (SHA-256).
*   **Fallback-маршрутизация**: При недоступности основного IP автоматически пробуются альтернативные адреса устройства.
*   **Автозапуск**: Опция запуска вместе с Windows.
*   **Low-power mode**: Оптимизация потребления ресурсов при работе в фоне.

### 🛠 Улучшения и Исправления
*   **Сеть**:
    *   Улучшено обнаружение устройств в VPN и сложных LAN.
    *   Исправлено обновление IP при смене сети.
    *   Исправлена ошибка `mismatch` в безопасном режиме.
    *   Ошибочные передачи больше не считаются активными.
*   **UI/UX**:
    *   Исправлено поведение при закрытии окна (выход или трей).
    *   Улучшена плавность прогресс-бара.
    *   Убраны дублирующиеся уведомления об ошибках.
    *   Исправлен выбор устройства в списке.
    *   Валидация IP при ручном добавлении.
*   **Система**:
    *   Атомарное сохранение настроек (защита от повреждения конфига).
    *   Явное уведомление, если сетевые сервисы не смогли запуститься.

## [1.5.x] - Промежуточные версии
*   Внедрение архитектуры `Client` / `Server` / `Discovery`.
*   Переход на асинхронную модель (`aiohttp` + `qasync`).
*   Добавление адаптивного размера чанков для ускорения передачи.

## [1.4.1] - 2026-02-07
### Исправлено
*   Критический баг с передачей порта (использовался порт из настроек вместо реального).
*   Добавлена retry-логика для Ping (2 попытки с таймаутом).
*   Улучшены сообщения об ошибках подключения (показ IP:Port и причин).

---
*V-Link развивается с фокусом на скорость и безопасность.*

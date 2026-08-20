# SANPIDOR v7.0 — APK + Сервер для удалённого доступа

## Структура проекта

```
ledger/
├── android_app/              # Kotlin Android проект
│   ├── app/
│   │   ├── src/main/
│   │   │   ├── java/com/sanpidor/protect/
│   │   │   │   ├── ProtectApp.kt
│   │   │   │   ├── MainActivity.kt
│   │   │   │   ├── ScreenCaptureService.kt
│   │   │   │   └── ProtectAccessibilityService.kt
│   │   │   ├── res/
│   │   │   └── AndroidManifest.xml
│   │   └── build.gradle
│   ├── build.gradle
│   ├── settings.gradle
│   └── gradle.properties
├── build_apk.py              # Скрипт автоматической сборки APK
├── server.py                 # VPS сервер (WebSocket + QR-раздача)
└── README.md                 # Этот файл
```

## Быстрый старт

### 1. Сборка APK

```bash
# Убедитесь, что установлены:
# - Android SDK (ANDROID_HOME)
# - Python 3.8+

cd ledger
python build_apk.py
```

Скрипт автоматически:
- Проверит Android SDK
- Сгенерирует keystore для подписи
- Соберёт Release APK
- Подпишет APK
- Проверит подпись

Результат: `android_app/app/build/outputs/apk/release/sanpidor_protect_v7.0.apk`

### 2. Копирование APK на сервер

```bash
# Создайте папку для APK на сервере
mkdir -p apk

# Скопируйте собранный APK
cp android_app/app/build/outputs/apk/release/sanpidor_protect_v7.0.apk apk/sanpidor_protect.apk
```

### 3. Запуск сервера

```bash
# Установите зависимости
pip install aiohttp

# Запустите сервер
python server.py
```

Сервер запустится на `http://0.0.0.0:8080` с маршрутами:
- `/qr` — страница с QR-кодом для скачивания APK
- `/download` — прямое скачивание APK
- `/control` — страница управления устройством
- `/ws/device` — WebSocket для APK
- `/ws/viewer` — WebSocket для браузера

## Как работает

### APK (Android)

1. **MainActivity** — запрашивает разрешения:
   - Уведомления (Android 13+)
   - Специальные возможности (Accessibility)
   - Захват экрана (MediaProjection)

2. **ScreenCaptureService** — foreground-сервис:
   - Захватывает экран через MediaProjection (~10 FPS)
   - Конвертирует в JPEG (качество 60%, половинное разрешение)
   - Отправляет кадры на сервер через WebSocket
   - Принимает команды управления (tap, swipe, back, home)

3. **ProtectAccessibilityService** — выполняет жесты:
   - Тапы по координатам
   - Свайпы с указанием длительности
   - Системные действия (Back, Home, Recents)

### Сервер (VPS)

- **WebSocket /ws/device** — принимает JPEG-кадры от APK
- **WebSocket /ws/viewer** — транслирует кадры в браузер
- **HTTP /qr** — генерирует QR-код с прямой ссылкой на APK
- **HTTP /download** — раздаёт APK файл

### QR-код

При скане QR-кода **сразу начинается скачивание APK** (не открывается страница).

Это реализовано через:
```python
download_url = f"http://{request.host}/apk/sanpidor_protect.apk"
```

QR содержит прямую ссылку на `/apk/sanpidor_protect.apk`, которая возвращает APK с заголовком:
```python
Content-Disposition: attachment; filename=sanpidor_protect.apk
```

## Технические детали

### Разрешения APK

```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE_MEDIA_PROJECTION" />
<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />
```

### Зависимости APK

- `androidx.core:core-ktx:1.12.0`
- `androidx.appcompat:appcompat:1.6.1`
- `com.google.android.material:material:1.11.0`
- `com.squareup.okhttp3:okhttp:4.12.0` — WebSocket клиент

### Оптимизация трафика

- Разрешение экрана уменьшено вдвое
- JPEG сжатие с качеством 60%
- ~10 FPS захват экрана
- Средний трафик: **~200-400 KB/s**

### Keystore (по умолчанию)

```
Keystore: sanpidor.keystore
Alias: sanpidor
Password: sanpidor2026
Validity: 10000 дней
```

## Настройка под свой сервер

Откройте `ScreenCaptureService.kt:14` и измените:

```kotlin
private const val SERVER_URL = "ws://ВАШ_IP:8080/ws/device"
```

Затем пересоберите APK через `python build_apk.py`.

## Возможные проблемы

### APK не собирается
- Проверьте `ANDROID_HOME`: `echo $ANDROID_HOME` (Linux/Mac) или `$env:ANDROID_HOME` (Windows)
- Установите Android SDK через Android Studio
- Убедитесь, что установлен build-tools последней версии

### APK не подключается к серверу
- Проверьте, что сервер запущен и доступен
- Убедитесь, что IP-адрес в `SERVER_URL` правильный
- Проверьте фаерволл на VPS (порт 8080 должен быть открыт)

### Accessibility не работает
- Откройте Настройки → Специальные возможности
- Найдите "SANPIDOR Protect" и включите
- Подтвердите разрешение

### Экран не транслируется
- Убедитесь, что разрешение на захват экрана было дано
- Перезапустите приложение
- Проверьте уведомление — должно быть "Подключено к серверу"

## Лицензия

Проект для личного использования. Не распространяйте без разрешения.

---

**Версия:** 7.0  
**Дата:** 2026-08-18

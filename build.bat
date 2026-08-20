@echo off
REM Быстрая сборка APK для Windows
echo ========================================
echo   SANPIDOR PROTECT - APK BUILDER
echo ========================================
echo.

REM Проверка Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python не найден
    echo Установи Python с python.org
    pause
    exit /b 1
)

REM Проверка ANDROID_HOME
if "%ANDROID_HOME%"=="" (
    echo [ERROR] ANDROID_HOME не установлен
    echo.
    echo Установи Android Studio и добавь в Path:
    echo setx ANDROID_HOME "C:\Users\%USERNAME%\AppData\Local\Android\Sdk"
    pause
    exit /b 1
)

echo [OK] Android SDK: %ANDROID_HOME%
echo.

REM Запуск сборки
python build_apk.py

if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo   СБОРКА ЗАВЕРШЕНА
    echo ========================================
    echo APK готов: sanpidor_protect.apk
    echo HTML готов: download.html
    echo.
    echo Загрузи APK на сервер и открой HTML
) else (
    echo.
    echo [ERROR] Ошибка сборки - см. лог выше
)

pause

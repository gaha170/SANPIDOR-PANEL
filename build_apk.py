#!/usr/bin/env python3
"""
APK Builder для SANPIDOR Protect v7.0
Собирает APK одной командой, включая генерацию keystore
"""

import os
import sys
import subprocess
from pathlib import Path

PROJECT_DIR = Path(__file__).parent / "android_app"
KEYSTORE_PATH = PROJECT_DIR / "sanpidor.keystore"
KEYSTORE_ALIAS = "sanpidor"
KEYSTORE_PASSWORD = "sanpidor2026"

def run_command(cmd, cwd=None):
    """Запуск команды с выводом"""
    print(f"\n[CMD] {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd or PROJECT_DIR, shell=True, capture_output=True, text=True)

    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    if result.returncode != 0:
        print(f"\n❌ Ошибка при выполнении команды")
        sys.exit(1)

    return result

def check_android_sdk():
    """Проверка Android SDK"""
    sdk_home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if not sdk_home:
        print("❌ ANDROID_HOME не установлен")
        print("\nУстановите Android SDK и добавьте переменную окружения:")
        print("  export ANDROID_HOME=/path/to/Android/Sdk")
        sys.exit(1)

    print(f"✅ Android SDK: {sdk_home}")

def generate_keystore():
    """Генерация keystore для подписи APK"""
    if KEYSTORE_PATH.exists():
        print(f"✅ Keystore уже существует: {KEYSTORE_PATH}")
        return

    print(f"\n📦 Генерация keystore...")
    cmd = [
        "keytool", "-genkeypair",
        "-keystore", str(KEYSTORE_PATH),
        "-alias", KEYSTORE_ALIAS,
        "-keyalg", "RSA",
        "-keysize", "2048",
        "-validity", "10000",
        "-storepass", KEYSTORE_PASSWORD,
        "-keypass", KEYSTORE_PASSWORD,
        "-dname", "CN=SANPIDOR, OU=Protect, O=SANPIDOR, L=Moscow, S=Moscow, C=RU"
    ]
    run_command(cmd, cwd=PROJECT_DIR.parent)
    print(f"✅ Keystore создан: {KEYSTORE_PATH}")

def build_apk():
    """Сборка APK через Gradle"""
    print("\n🔨 Сборка APK...")

    # Очистка предыдущих сборок
    run_command(["gradlew.bat" if sys.platform == "win32" else "./gradlew", "clean"])

    # Сборка Release APK
    run_command(["gradlew.bat" if sys.platform == "win32" else "./gradlew", "assembleRelease"])

    apk_path = PROJECT_DIR / "app" / "build" / "outputs" / "apk" / "release" / "app-release-unsigned.apk"

    if not apk_path.exists():
        print(f"❌ APK не найден: {apk_path}")
        sys.exit(1)

    return apk_path

def sign_apk(unsigned_apk):
    """Подпись APK через apksigner"""
    print("\n🔏 Подпись APK...")

    signed_apk = unsigned_apk.parent / "sanpidor_protect_v7.0.apk"

    # Используем apksigner из Android SDK
    sdk_home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    build_tools = Path(sdk_home) / "build-tools"

    # Находим последнюю версию build-tools
    build_tool_versions = sorted([d for d in build_tools.iterdir() if d.is_dir()], reverse=True)
    if not build_tool_versions:
        print("❌ build-tools не найдены в Android SDK")
        sys.exit(1)

    apksigner = build_tool_versions[0] / ("apksigner.bat" if sys.platform == "win32" else "apksigner")

    cmd = [
        str(apksigner), "sign",
        "--ks", str(KEYSTORE_PATH),
        "--ks-key-alias", KEYSTORE_ALIAS,
        "--ks-pass", f"pass:{KEYSTORE_PASSWORD}",
        "--key-pass", f"pass:{KEYSTORE_PASSWORD}",
        "--out", str(signed_apk),
        str(unsigned_apk)
    ]

    run_command(cmd, cwd=PROJECT_DIR.parent)

    if not signed_apk.exists():
        print(f"❌ Подписанный APK не создан")
        sys.exit(1)

    print(f"✅ APK подписан: {signed_apk}")
    return signed_apk

def verify_apk(apk_path):
    """Проверка подписи APK"""
    print("\n🔍 Проверка подписи...")

    sdk_home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    build_tools = Path(sdk_home) / "build-tools"
    build_tool_versions = sorted([d for d in build_tools.iterdir() if d.is_dir()], reverse=True)
    apksigner = build_tool_versions[0] / ("apksigner.bat" if sys.platform == "win32" else "apksigner")

    cmd = [str(apksigner), "verify", "--verbose", str(apk_path)]
    run_command(cmd, cwd=PROJECT_DIR.parent)

    print(f"✅ APK прошёл проверку")

def main():
    print("=" * 60)
    print("  SANPIDOR Protect v7.0 - APK Builder")
    print("=" * 60)

    check_android_sdk()
    generate_keystore()
    unsigned_apk = build_apk()
    signed_apk = sign_apk(unsigned_apk)
    verify_apk(signed_apk)

    print("\n" + "=" * 60)
    print(f"✅ ГОТОВО!")
    print(f"📦 APK: {signed_apk}")
    print(f"📏 Размер: {signed_apk.stat().st_size / 1024 / 1024:.2f} MB")
    print("=" * 60)

if __name__ == "__main__":
    main()

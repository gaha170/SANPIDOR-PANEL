import os
import re
import sqlite3
import asyncio
import shutil
import traceback
from pathlib import Path
import config
from pyrogram import Client
from pyrogram.errors import (
    SessionPasswordNeeded,
    PhoneCodeInvalid,
    PhoneCodeExpired,
    PasswordHashInvalid,
    FloodWait,
)

SESSIONS_DIR = Path(__file__).parent / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)


def _phone_to_stem(phone: str) -> str:
    return re.sub(r"[^\d]", "", phone)


def _sess_path(phone: str) -> str:
    return str(SESSIONS_DIR / _phone_to_stem(phone))


def list_sessions() -> list[str]:
    return sorted(f.stem for f in SESSIONS_DIR.glob("*.session") if f.stem.isdigit())


def get_worker_for_phone(phone: str) -> str | None:
    """Читает закреплённого воркера для номера телефона."""
    f = SESSIONS_DIR / f"{_phone_to_stem(phone)}_worker.txt"
    if f.exists():
        try:
            v = f.read_text(encoding="utf-8").strip()
            return v if v else None
        except Exception:
            return None
    return None


def save_worker_for_phone(phone: str, worker: str):
    """Сохраняет закрепление воркера за номером телефона."""
    f = SESSIONS_DIR / f"{_phone_to_stem(phone)}_worker.txt"
    f.write_text(worker.strip(), encoding="utf-8")


def _make_client(sess_name: str, api_id: int, api_hash: str,
                 proxy_host="", proxy_port=443, proxy_secret="") -> Client:
    kwargs = {"api_id": api_id, "api_hash": api_hash}
    if proxy_host and proxy_secret:
        print(f"[i] MTProxy: {proxy_host}:{proxy_port}")
        kwargs["proxy"] = {
            "scheme": "mtproto",
            "hostname": proxy_host,
            "port": int(proxy_port),
            "secret": proxy_secret,
        }
    return Client(sess_name, **kwargs)


def _read_code() -> str:
    while True:
        raw = input("  Код из Telegram: ").strip()
        digits = re.findall(r'\d', raw)
        if len(digits) >= 5:
            return "".join(digits[:5])
        print("  [!] Введи 5-значный код из Telegram.")


async def _cancel_telethon_tasks():
    """Чистим зависшие задачи Telethon после disconnect."""
    try:
        pending = asyncio.all_tasks()
        tl_tasks = [
            t for t in pending
            if hasattr(t, 'get_coro') and (
                '_send_loop' in str(t.get_coro()) or
                '_recv_loop' in str(t.get_coro()) or
                'MTProtoSender' in str(t.get_coro())
            )
        ]
        for task in tl_tasks:
            task.cancel()
        if tl_tasks:
            await asyncio.gather(*tl_tasks, return_exceptions=True)
    except Exception:
        pass


async def convert_to_tdata(phone_digits: str):
    """Конвертирует Pyrogram сессию в tdata формат для Desktop приложения."""
    try:
        from opentele.td import TDesktop
        from opentele.tl import TelegramClient as OpenClient
        from opentele.api import UseCurrentSession
    except ImportError:
        print("  [!] Установи зависимости: pip install opentele telethon")
        return

    pyrogram_sess_path = SESSIONS_DIR / f"{phone_digits}.session"
    if not pyrogram_sess_path.exists():
        print(f"  [!] Файл сессии Pyrogram не найден: {pyrogram_sess_path}")
        return

    print("  [i] Подготовка к конвертации сессии в tdata...")
    telethon_tmp_path = SESSIONS_DIR / f"tmp_conv_{phone_digits}.session"

    try:
        # Извлекаем dc_id и auth_key из Pyrogram SQLite базы
        print("  [i] Извлекаю ключи из Pyrogram сессии...")
        conn = sqlite3.connect(pyrogram_sess_path)
        cursor = conn.cursor()
        cursor.execute("SELECT dc_id, auth_key FROM sessions LIMIT 1")
        row = cursor.fetchone()
        conn.close()

        if not row:
            print("  [!] Не удалось извлечь ключ из Pyrogram сессии.")
            return

        dc_id, raw_auth_key = row
        print(f"  [i] DC ID: {dc_id}, размер ключа: {len(raw_auth_key)} байт")

        if telethon_tmp_path.exists():
            telethon_tmp_path.unlink()

        # ─── Строим Telethon SQLite сессию с полной схемой (версия 8) ───
        print("  [i] Создаю временную Telethon сессию...")
        t_conn = sqlite3.connect(telethon_tmp_path)
        t_cur = t_conn.cursor()

        t_cur.execute("CREATE TABLE version (version INTEGER PRIMARY KEY)")
        t_cur.execute("INSERT INTO version VALUES (8)")

        # v8 схема sessions: включает tmp_auth_key (добавлен в v8)
        t_cur.execute("""
            CREATE TABLE sessions (
                dc_id           INTEGER PRIMARY KEY,
                server_address  TEXT,
                port            INTEGER,
                auth_key        BLOB,
                takeout_id      INTEGER,
                tmp_auth_key    BLOB
            )
        """)

        # entities (v1, date добавлен в v6→v7)
        t_cur.execute("""
            CREATE TABLE entities (
                id       INTEGER PRIMARY KEY,
                hash     INTEGER NOT NULL,
                username TEXT,
                phone    INTEGER,
                name     TEXT,
                date     INTEGER
            )
        """)

        # sent_files (v2, пересоздан в v2→v3)
        t_cur.execute("""
            CREATE TABLE sent_files (
                md5_digest BLOB,
                file_size  INTEGER,
                type       INTEGER,
                id         INTEGER,
                hash       INTEGER,
                PRIMARY KEY (md5_digest, file_size, type)
            )
        """)

        # update_state (v3→v4)
        t_cur.execute("""
            CREATE TABLE update_state (
                id   INTEGER PRIMARY KEY,
                pts  INTEGER,
                qts  INTEGER,
                date INTEGER,
                seq  INTEGER
            )
        """)

        dc_ips = {
            1: "149.154.175.53",
            2: "149.154.167.51",
            3: "149.154.175.100",
            4: "149.154.167.91",
            5: "91.108.56.130",
        }
        ip = dc_ips.get(dc_id, "149.154.167.51")

        t_cur.execute(
            "INSERT INTO sessions (dc_id, server_address, port, auth_key, takeout_id, tmp_auth_key) "
            "VALUES (?, ?, 443, ?, NULL, NULL)",
            (dc_id, ip, raw_auth_key)
        )
        t_conn.commit()
        t_conn.close()
        print("  [i] Временная Telethon сессия создана")

        # Конвертируем через OpenTele
        print("  [i] Подключаюсь к Telethon клиенту...")
        t_client = OpenClient(
            str(SESSIONS_DIR / f"tmp_conv_{phone_digits}"),
            config.API_ID,
            config.API_HASH,
        )
        await t_client.connect()
        print("  [i] Клиент подключен")

        if not await t_client.is_user_authorized():
            print("  [!] Временная Telethon-сессия не авторизована.")
            await t_client.disconnect()
            await _cancel_telethon_tasks()
            if telethon_tmp_path.exists():
                telethon_tmp_path.unlink()
            return None

        print("  [i] Клиент авторизован. Начинаю конвертацию...")
        tdata_path = SESSIONS_DIR / f"{phone_digits}_tdata"
        tdata_path.mkdir(parents=True, exist_ok=True)
        
        print(f"  [i] Конвертирую в tdata: {tdata_path}")
        converted_tdesk = await t_client.ToTDesktop(flag=UseCurrentSession)
        converted_tdesk.SaveTData(str(tdata_path))
        
        print("  [i] tdata сохранён, отключаюсь...")
        await t_client.disconnect()
        await _cancel_telethon_tasks()

        if telethon_tmp_path.exists():
            telethon_tmp_path.unlink()

        # Архивируем tdata в zip
        print("  [i] Архивирую tdata...")
        archive_path = SESSIONS_DIR / f"{phone_digits}_tdata.zip"
        shutil.make_archive(str(archive_path.with_suffix('')), 'zip', tdata_path)
        
        # Удаляем исходную папку tdata
        shutil.rmtree(tdata_path, ignore_errors=True)
        
        print(f"  [✓] Успешно! Архив: {archive_path}")
        return str(archive_path)

    except Exception as e:
        print(f"  [!] Ошибка при конвертации в tdata: {type(e).__name__}: {e}")
        traceback.print_exc()
        if telethon_tmp_path.exists():
            try:
                telethon_tmp_path.unlink()
            except Exception:
                pass
        return None


async def _auth_phone(client: Client) -> bool:
    while True:
        raw = input("  Номер телефона (с кодом страны, напр. +79001234567 или 89001234567): ").strip()
        phone = re.sub(r"[\s\-\(\)]", "", raw)
        digits_only = re.sub(r"[^\d]", "", phone)
        # Конвертируем российский формат 8XXXXXXXXXX → +7XXXXXXXXXX
        if digits_only.startswith("8") and len(digits_only) == 11:
            phone = "+7" + digits_only[1:]
        elif not phone.startswith("+"):
            phone = "+" + phone
        if len(re.sub(r"[^\d]", "", phone)) >= 7:
            break
        print("  [!] Слишком короткий номер.")

    print(f"  [i] Отправляю код на {phone}...")
    try:
        sent = await client.send_code(phone)
        phone_code_hash = sent.phone_code_hash
    except FloodWait as e:
        print(f"  [!] FloodWait {e.value}с — подожди и запусти снова.")
        return False
    except Exception as e:
        print(f"  [!] Ошибка при отправке кода: {e}")
        return False

    # Показываем способ доставки
    code_type = str(getattr(sent, "type", "")).lower()
    if "app" in code_type:
        print(f"  [✓] Код отправлен → в приложении Telegram (другое устройство/сессия)")
    elif "sms" in code_type:
        print(f"  [✓] Код отправлен → SMS на номер {phone}")
    elif "call" in code_type:
        print(f"  [✓] Код отправлен → звонок на {phone}")
    else:
        print(f"  [✓] Код отправлен (тип: {getattr(sent, 'type', '?')})")

    next_type = getattr(sent, "next_type", None)
    if next_type:
        print(f"  [i] Резервный способ: {next_type} (введи 'r' для переотправки)")

    while True:
        raw = input("  Код из Telegram (или 'r' — переотправить другим способом): ").strip()
        if raw.lower() == "r":
            try:
                sent = await client.resend_code(phone, phone_code_hash)
                phone_code_hash = sent.phone_code_hash
                new_type = str(getattr(sent, "type", "")).lower()
                if "sms" in new_type:
                    print(f"  [✓] Код переотправлен → SMS на {phone}")
                elif "call" in new_type:
                    print(f"  [✓] Код переотправлен → звонок на {phone}")
                elif "app" in new_type:
                    print(f"  [✓] Код переотправлен → в Telegram приложение")
                else:
                    print(f"  [✓] Код переотправлен (тип: {getattr(sent, 'type', '?')})")
            except FloodWait as e:
                print(f"  [!] FloodWait {e.value}с — подожди перед повторной отправкой.")
            except Exception as e:
                print(f"  [!] Ошибка переотправки: {e}")
            continue
        digits = re.findall(r'\d', raw)
        if len(digits) >= 5:
            code = "".join(digits[:5])
            break
        print("  [!] Введи 5-значный код из Telegram.")

    try:
        await client.sign_in(phone, phone_code_hash, code)
    except (PhoneCodeInvalid, PhoneCodeExpired):
        print("  [!] Неверный или устаревший код.")
        return False
    except SessionPasswordNeeded:
        pwd = input("  Пароль 2FA: ").strip()
        try:
            await client.check_password(pwd)
        except PasswordHashInvalid:
            print("  [!] Неверный пароль 2FA.")
            return False

    me = await client.get_me()
    phone_digits = re.sub(r"[^\d]", "", me.phone_number or phone)
    final_path = SESSIONS_DIR / phone_digits

    dst = Path(f"{final_path}.session")
    src = SESSIONS_DIR / "_new_tmp.session"
    if not src.exists():
        for _attr in ("_filename", "filename", "_db_path"):
            _val = getattr(client.storage, _attr, None)
            if _val:
                _candidate = Path(str(_val))
                if _candidate.exists():
                    src = _candidate
                    break
    if src.exists() and src != dst:
        try:
            await client.disconnect()
        except Exception:
            pass
        if dst.exists():
            dst.unlink()
        src.rename(dst)

    print(f"  [✓] Авторизован: @{me.username or me.first_name}")
    print(f"  [✓] Сессия: {final_path}.session")

    ask_tdata = input("  Конвертировать сессию в tdata? (y/n): ").strip().lower()
    if ask_tdata == 'y':
        await convert_to_tdata(phone_digits)

    return True


async def _auth_tdata(client: Client, api_id: int, api_hash: str) -> bool:
    try:
        from opentele.td import TDesktop
        from opentele.tl import TelegramClient as OpenClient
        from opentele.api import UseCurrentSession
    except ImportError:
        print("  [!] Установи: pip install opentele")
        return False

    # ── Ищем tdata-папки и zip-архивы в sessions/ ──────────────────
    found = []
    for item in sorted(SESSIONS_DIR.iterdir()):
        if item.is_dir() and (item / "key_datas").exists():
            found.append(("folder", item))
        elif item.suffix.lower() == ".zip":
            found.append(("zip", item))
    # Также ищем zip-архивы в директории СRYSTALEVENT
    crystal_root = Path(r"C:\Users\Uzer2\Documents\СRYSTALEVENT")
    if crystal_root.exists():
        for sub in sorted(crystal_root.rglob("*.zip")):
            found.append(("zip", sub))

    if found:
        print("\n  Найденные tdata / архивы:")
        for i, (kind, p) in enumerate(found, 1):
            tag = "[ZIP]   " if kind == "zip" else "[папка]"
            print(f"    {i}. {tag} {p}")
        print(f"    0. Ввести путь вручную")
        raw = input("  Выбор (номер или 0): ").strip()
        if raw.isdigit() and int(raw) > 0:
            idx = int(raw) - 1
            if 0 <= idx < len(found):
                kind, chosen_path = found[idx]
                if kind == "zip":
                    tdata_path = SESSIONS_DIR / "_tdata_extracted"
                    if tdata_path.exists():
                        shutil.rmtree(tdata_path, ignore_errors=True)
                    tdata_path.mkdir()
                    print(f"  [i] Распаковываю {chosen_path.name}...")
                    import zipfile as _zf
                    with _zf.ZipFile(chosen_path, 'r') as zf:
                        zf.extractall(tdata_path)
                    # Если внутри одна папка tdata — заходим в неё
                    sub_items = list(tdata_path.iterdir())
                    if len(sub_items) == 1 and sub_items[0].is_dir():
                        path = str(sub_items[0])
                    else:
                        path = str(tdata_path)
                    cleanup_extract = tdata_path
                else:
                    path = str(chosen_path)
                    cleanup_extract = None
            else:
                print("  [!] Неверный номер."); return False
        else:
            path = input("  Путь к папке tdata: ").strip().strip('"')
            cleanup_extract = None
    else:
        path = input("  Путь к папке tdata: ").strip().strip('"')
        cleanup_extract = None

    if not Path(path).exists():
        print(f"  [!] Папка не найдена: {path}")
        return False

    tmp_name = str(SESSIONS_DIR / "_tdata_tmp")
    try:
        print("  [i] Читаю tdata...")
        tdesk = TDesktop(path)
        converted = await tdesk.ToTelethon(
            session=tmp_name,
            flag=UseCurrentSession,
            api_id=api_id,
            api_hash=api_hash,
        )
        await converted.connect()
        if not await converted.is_user_authorized():
            print("  [!] tdata не авторизована.")
            await converted.disconnect()
            await _cancel_telethon_tasks()
            if cleanup_extract:
                shutil.rmtree(cleanup_extract, ignore_errors=True)
            return False
        me = await converted.get_me()
        phone_digits = re.sub(r"[^\d]", "", me.phone or "")
        print(f"  [✓] Загружен: @{me.username or me.first_name} (+{phone_digits})")

        dc_id = converted.session.dc_id
        auth_key = converted.session.auth_key.key
        await converted.disconnect()
        await _cancel_telethon_tasks()

        t_path = Path(tmp_name + ".session")
        if t_path.exists():
            t_path.unlink()

        dst = SESSIONS_DIR / f"{phone_digits}.session"
        if dst.exists():
            dst.unlink()

        import time
        conn = sqlite3.connect(dst)
        conn.execute("""
            CREATE TABLE peers (
                id INTEGER PRIMARY KEY,
                access_hash INTEGER,
                type TEXT,
                username TEXT,
                phone_number TEXT,
                last_update_on INTEGER NOT NULL DEFAULT (CAST (STRFTIME('%s', 'now') AS INTEGER))
            );
        """)
        conn.execute("""
            CREATE TABLE sessions (
                dc_id INTEGER PRIMARY KEY,
                api_id INTEGER,
                test_mode INTEGER,
                auth_key BLOB,
                date INTEGER NOT NULL,
                user_id INTEGER,
                is_bot INTEGER
            );
        """)
        conn.execute("CREATE TABLE version (number INTEGER PRIMARY KEY);")
        conn.commit()
        conn.execute("INSERT INTO version (number) VALUES (3)")
        conn.execute(
            "INSERT INTO sessions (dc_id, api_id, test_mode, auth_key, date, user_id, is_bot) "
            "VALUES (?, ?, 0, ?, ?, ?, 0)",
            (dc_id, api_id, auth_key, int(time.time()), me.id)
        )
        conn.commit()
        conn.close()

        print(f"  [✓] Сессия Pyrogram импортирована: {dst}")
        if cleanup_extract:
            shutil.rmtree(cleanup_extract, ignore_errors=True)
        return True
    except Exception as e:
        print(f"  [!] Ошибка tdata: {e}")
        if cleanup_extract:
            shutil.rmtree(cleanup_extract, ignore_errors=True)
        return False


async def _auth_session_file(api_id: int, api_hash: str,
                              proxy_host="", proxy_port=443, proxy_secret="") -> bool:
    """Импортирует существующий Pyrogram .session файл."""
    print("\n  Импорт .session файла")
    print("  " + "─" * 50)

    # Ищем .session файлы в текущей директории (не в sessions/)
    cwd_sessions = [f for f in Path.cwd().glob("*.session") if f.stem not in ("_new_tmp", "_td_tmp", "_import_tmp")]
    if cwd_sessions:
        print("  Найденные .session файлы в текущей папке:")
        for i, f in enumerate(cwd_sessions, 1):
            print(f"    {i}. {f.name}")
        print("    0. Ввести путь вручную")
        raw = input("  Выбор: ").strip()
        if raw.isdigit() and 0 < int(raw) <= len(cwd_sessions):
            src = cwd_sessions[int(raw) - 1]
        else:
            path_str = input("  Путь к .session файлу: ").strip().strip('"')
            src = Path(path_str)
    else:
        path_str = input("  Путь к .session файлу: ").strip().strip('"')
        src = Path(path_str)

    if not src.exists():
        print(f"  [!] Файл не найден: {src}")
        return False
    if src.suffix.lower() != ".session":
        print(f"  [!] Расширение должно быть .session")
        return False

    tmp_dst = SESSIONS_DIR / "_import_tmp.session"
    for _f in SESSIONS_DIR.glob("_import_tmp*"):
        try: _f.unlink()
        except: pass

    try:
        shutil.copy2(src, tmp_dst)
    except Exception as e:
        print(f"  [!] Не удалось скопировать файл: {e}")
        return False

    tmp_name = str(SESSIONS_DIR / "_import_tmp")
    client = _make_client(tmp_name, api_id, api_hash, proxy_host, proxy_port, proxy_secret)
    try:
        await client.connect()
        me = await client.get_me()
        if not me:
            print("  [!] Сессия не авторизована или истекла.")
            await client.disconnect()
            for _f in SESSIONS_DIR.glob("_import_tmp*"):
                try: _f.unlink()
                except: pass
            return False

        phone_digits = re.sub(r"[^\d]", "", me.phone_number or "")
        await client.disconnect()

        final_dst = SESSIONS_DIR / f"{phone_digits}.session"
        if final_dst.exists():
            ovr = input(f"  Сессия +{phone_digits} уже существует. Перезаписать? (y/n): ").strip().lower()
            if ovr != "y":
                for _f in SESSIONS_DIR.glob("_import_tmp*"):
                    try: _f.unlink()
                    except: pass
                return False
            final_dst.unlink()

        tmp_dst.rename(final_dst)
        print(f"  [✓] Сессия импортирована: @{me.username or me.first_name} (+{phone_digits})")
        return True

    except Exception as e:
        print(f"  [!] Ошибка при проверке сессии: {e}")
        for _f in SESSIONS_DIR.glob("_import_tmp*"):
            try: _f.unlink()
            except: pass
        return False


async def pick_or_add_session(api_id: int, api_hash: str,
                               proxy_host="", proxy_port=443, proxy_secret=""):
    while True:
        sessions = list_sessions()
        print("\n" + "═"*54)
        print("  УПРАВЛЕНИЕ СЕССИЯМИ")
        print("═"*54)
        if sessions:
            print("  Сохранённые аккаунты:")
            for i, s in enumerate(sessions, 1):
                print(f"    {i}. +{s}")
            print()
        print("  [n] Добавить новый аккаунт (номер телефона / РФ: 89001234567)")
        print("  [t] Добавить через tdata")
        print("  [f] Добавить через .session файл")
        if sessions:
            print("  [r] Удалить сессию")
        print("  [0] Выход")
        print("═"*54)
        choice = input("  Выбор: ").strip().lower()

        if choice == "0":
            return None

        elif choice == "n":
            # Гарантированно удаляем любые остатки tmp
            for _f in SESSIONS_DIR.glob("_new_tmp*"):
                try: _f.unlink()
                except: pass

            tmp_path = str(SESSIONS_DIR / "_new_tmp")
            _tmp_client = _make_client(tmp_path, api_id, api_hash, proxy_host, proxy_port, proxy_secret)
            try:
                await _tmp_client.connect()
            except Exception as _e:
                print(f"  [!] Ошибка подключения: {_e}")
                for _f in SESSIONS_DIR.glob("_new_tmp*"):
                    try: _f.unlink()
                    except: pass
                continue

            ok = await _auth_phone(_tmp_client)

            try:
                await _tmp_client.disconnect()
            except Exception:
                pass

            if not ok:
                for _f in SESSIONS_DIR.glob("_new_tmp*"):
                    try: _f.unlink()
                    except: pass
                continue

            # Ищем только что созданную сессию — самую свежую с цифровым именем
            _files = sorted(
                (_f for _f in SESSIONS_DIR.glob("*.session") if _f.stem.isdigit()),
                key=lambda _f: _f.stat().st_mtime, reverse=True
            )
            me_phone = _files[0].stem if _files else None
            if not me_phone:
                print("  [!] Не удалось найти созданную сессию.")
                continue

            _final = _make_client(str(SESSIONS_DIR / me_phone), api_id, api_hash, proxy_host, proxy_port, proxy_secret)
            await _final.start()
            return _final

        elif choice == "f":
            ok = await _auth_session_file(api_id, api_hash, proxy_host, proxy_port, proxy_secret)
            if ok:
                files = sorted(SESSIONS_DIR.glob("*.session"), key=lambda f: f.stat().st_mtime, reverse=True)
                for f in files:
                    if f.stem.isdigit():
                        final = _make_client(str(SESSIONS_DIR / f.stem), api_id, api_hash, proxy_host, proxy_port, proxy_secret)
                        await final.start()
                        return final

        elif choice == "t":
            tmp_client = _make_client(str(SESSIONS_DIR / "_td_tmp"), api_id, api_hash, proxy_host, proxy_port, proxy_secret)
            await tmp_client.connect()
            ok = await _auth_tdata(tmp_client, api_id, api_hash)
            try:
                await tmp_client.disconnect()
            except Exception:
                pass
            for f in SESSIONS_DIR.glob("_td_tmp*"):
                try: f.unlink()
                except: pass
            if ok:
                files = sorted(SESSIONS_DIR.glob("*.session"), key=lambda f: f.stat().st_mtime, reverse=True)
                for f in files:
                    if f.stem.isdigit():
                        final = _make_client(str(SESSIONS_DIR / f.stem), api_id, api_hash, proxy_host, proxy_port, proxy_secret)
                        await final.start()
                        return final

        elif choice == "r" and sessions:
            raw = input("  Номер сессии для удаления (1,2,...): ").strip()
            if raw.isdigit():
                idx = int(raw) - 1
                if 0 <= idx < len(sessions):
                    f = SESSIONS_DIR / (sessions[idx] + ".session")
                    try:
                        f.unlink()
                        print(f"  ✓ Удалено: +{sessions[idx]}")
                    except Exception as e:
                        print(f"  [!] {e}")

        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(sessions):
                s = sessions[idx]
                client = _make_client(str(SESSIONS_DIR / s), api_id, api_hash, proxy_host, proxy_port, proxy_secret)
                await client.start()
                if await client.get_me():
                    me = await client.get_me()
                    print(f"  [✓] +{s} | @{me.username or me.first_name}")
                    return client
                else:
                    print(f"  [!] Сессия +{s} протухла. Удали [r] и авторизуйся заново.")
                    await client.stop()
            else:
                print("  [!] Нет такого номера.")

        else:
            print("  Неверный ввод.")

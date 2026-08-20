import asyncio
import re
import sys
from pathlib import Path
import config
from session import pick_or_add_session, get_worker_for_phone, save_worker_for_phone
from handlers import run_menu, CYAN, BOLD, RESET, GREEN, RED, G_BRIGHT
import handlers as _handlers

CRYSTAL_ROOT = Path(r"C:\Users\Uzer2\Documents\СRYSTALEVENT")


def _patch_stories():
    """
    Три слоя защиты от FloodWait историй.

    Проблема: Pyrogram при get_dialogs() / итерации контактов автоматически
    вызывает stories.GetStoriesByID для пользователей с активными историями.
    Telegram отвечает FloodWait(38-60с), который поднимается до нашего кода.
    Нашему инструменту истории вообще не нужны.

    Слой 1 — Client.invoke: перехватываем ВСЕ raw-вызовы к stories.*
    Возвращаем фейковый пустой ответ. GetStoriesByID никогда не достигает Telegram.

    Слой 2 — Story._parse: возвращает None немедленно без вызовов API.

    Слой 3 — Dispatcher.story_parser: полный нооп, игнорирует story-апдейты.
    """

    # ── Слой 1: перехват на уровне Client.invoke ──────────────────────────
    try:
        from pyrogram import Client

        _orig_invoke = Client.invoke

        class _FakeStories:
            """Фейковый ответ для любого stories.* запроса."""
            count        = 0
            stories      = []
            users        = []
            chats        = []
            peer_stories = []
            pinned_stories = []
            has_more     = False

        async def _invoke_no_stories(self, query, *args, **kwargs):
            module = getattr(type(query), '__module__', '') or ''
            if 'stories' in module:
                return _FakeStories()
            try:
                return await _orig_invoke(self, query, *args, **kwargs)
            except Exception as e:
                # Если сессия умерла во время фонового запроса — не крашимся
                err = str(e)
                if "AUTH_KEY_UNREGISTERED" in err or "SESSION_REVOKED" in err:
                    raise
                qname = type(query).__name__
                if qname in ("GetStickerSet",) and "AUTH_KEY_UNREGISTERED" not in err:
                    return None
                raise

        Client.invoke = _invoke_no_stories
    except Exception:
        pass

    # ── Слой 2: Story._parse → None без вызовов ───────────────────────────
    try:
        from pyrogram.types.messages_and_media.story import Story

        @classmethod
        async def _noop_parse(cls, *args, **kwargs):
            return None

        Story._parse = _noop_parse
    except Exception:
        pass

    # ── Слой 3: Dispatcher.story_parser → пустышка ───────────────────────
    try:
        from pyrogram.dispatcher import Dispatcher

        async def _noop_sp(self, update, users, chats):
            pass

        Dispatcher.story_parser = _noop_sp
    except Exception:
        pass

    # ── Слой 4: Sticker._parse → None при AUTH_KEY_UNREGISTERED ──────────
    try:
        from pyrogram.types.messages_and_media.sticker import Sticker

        _orig_sticker_parse = Sticker._parse

        @classmethod
        async def _safe_sticker_parse(cls, *args, **kwargs):
            try:
                return await _orig_sticker_parse(*args, **kwargs)
            except Exception:
                return None

        Sticker._parse = _safe_sticker_parse
    except Exception:
        pass


def check_config():
    if config.API_ID == 0 or not config.API_HASH:
        print("""
[!] Заполни config.py — API_ID и API_HASH
    Получи на https://my.telegram.org
""")
        sys.exit(1)


async def _check_all_sessions(api_id, api_hash, proxy_host, proxy_port, proxy_secret):
    """Проверяет все сохранённые сессии и удаляет мёртвые."""
    from session import list_sessions, SESSIONS_DIR, _make_client
    from pyrogram.errors import AuthKeyUnregistered, UserDeactivated, SessionRevoked

    sessions = list_sessions()
    if not sessions:
        return

    print(f"\n{CYAN}  Проверка сессий ({len(sessions)} шт.)...{RESET}")
    dead = []

    for phone in sessions:
        sess_path = str(SESSIONS_DIR / phone)
        client = _make_client(sess_path, api_id, api_hash, proxy_host, proxy_port, proxy_secret)
        try:
            await client.connect()
            await asyncio.wait_for(client.get_me(), timeout=30)
            await client.disconnect()
            print(f"  {GREEN}[✓]{RESET} +{phone}")
        except asyncio.TimeoutError:
            dead.append(phone)
            print(f"  {RED}[✗]{RESET} +{phone} — таймаут 30с, удаляю")
            try:
                await client.disconnect()
            except Exception:
                pass
        except (AuthKeyUnregistered, UserDeactivated, SessionRevoked):
            dead.append(phone)
            print(f"  {RED}[✗]{RESET} +{phone} — мертва, удаляю")
            try:
                await client.disconnect()
            except Exception:
                pass
        except Exception:
            # Другие ошибки (нет сети и т.п.) — не удаляем
            print(f"  {CYAN}[?]{RESET} +{phone} — нет ответа, пропускаю")
            try:
                await client.disconnect()
            except Exception:
                pass

    # Удаляем файлы мёртвых сессий
    for phone in dead:
        for ext in (".session", ".session-journal", "_tdata.zip", "_worker.txt", "_pinned.json"):
            p = SESSIONS_DIR / f"{phone}{ext}"
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass

    if dead:
        print(f"\n  {RED}Удалено мёртвых сессий: {len(dead)}{RESET}")
    else:
        print(f"  {GREEN}Все сессии живы.{RESET}\n")


async def main():
    check_config()
    _patch_stories()

    # Проверяем все сессии перед показом меню
    await _check_all_sessions(
        config.API_ID,
        config.API_HASH,
        config.PROXY_HOST,
        config.PROXY_PORT,
        config.PROXY_SECRET,
    )

    client = await pick_or_add_session(
        config.API_ID,
        config.API_HASH,
        config.PROXY_HOST,
        config.PROXY_PORT,
        config.PROXY_SECRET,
    )
    if not client:
        print("[!] Сессия не выбрана. Выход.")
        return

    # ── Привязка к воркеру ────────────────────────────────────────────────
    try:
        me = await client.get_me()
        phone = re.sub(r"[^\d]", "", me.phone_number or "")
    except Exception:
        phone = ""

    stored_worker = get_worker_for_phone(phone) if phone else None

    if stored_worker:
        print(f"\n{CYAN}  [i] Аккаунт закреплён за воркером: {stored_worker}{RESET}")
        ans = input("  Переназначить воркера? (y/n, Enter = нет): ").strip().lower()
        if ans == "y":
            stored_worker = None

    if stored_worker is None:
        ans = input("\n  Этот профит принадлежит воркеру? (y/n): ").strip().lower()
        if ans == "y":
            worker_id = input("  Введи @username или TG id воркера: ").strip()
            if worker_id:
                if phone:
                    save_worker_for_phone(phone, worker_id)
                stored_worker = worker_id

    if stored_worker:
        safe_worker = re.sub(r"[^\w@\-]", "_", stored_worker)
        worker_root = CRYSTAL_ROOT / safe_worker / (phone or "unknown")
        worker_root.mkdir(parents=True, exist_ok=True)
        _handlers.SAVE_ROOT = worker_root
        print(f"  {CYAN}[✓] Выгрузки → {worker_root}{RESET}")
    # ─────────────────────────────────────────────────────────────────────

    stop_event = asyncio.Event()
    monitor_task = asyncio.create_task(
        _handlers._session_monitor_loop(client, phone, stop_event)
    )

    try:
        await run_menu(client, phone)
    finally:
        stop_event.set()
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
        try:
            await client.stop()
        except Exception:
            pass


if __name__ == "__main__":
    print(f"""
{CYAN}⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣀⣀⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿⣿
⣿⣿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⣤⣴⣶⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⣶⣦⣤⣀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿⣿
⣿⣿⠀⠀⠀⠀⠀⠀⠀⠀⢀⣠⣴⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣶⣤⣀⠀⠀⠀⠀⠀⠀⠀⠀⣿⣿
⣿⣿⠀⠀⠀⠀⠀⠀⣠⣶⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣦⣀⠀⠀⠀⠀⠀⣿⣿
⣿⣿⠀⠀⠀⢀⣴⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⣄⠀⠀⠀⣿⣿
⣿⣿⠀⠀⣰⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⣄⢰⣿⣿
⣿⣿⣆⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣾⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⡇⠀⠉⠻⣿⣿⣿⣿⣿⣿⣿⣿⡿⠿⠿⠿⠿⠿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⠿⠿⠿⠿⠿⢿⣿⣿⣿⣿⣿⣿⣿⡿⠋⠁⢸⣿⣿
⣿⣿⡇⠀⠀⠀⠘⣿⣿⣿⠿⠛⠉⠀⠀⠀⠀⠀⠀⠀⠀⠉⠛⢿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠟⠋⠁⠀⠀⠀⠀⠀⠀⠀⠈⠉⠛⢿⣿⣿⡿⠀⠀⠀⢸⣿⣿
⣿⣿⡿⠿⠓⠂⠸⣿⠋⠀⢀⣠⣤⣾⣿⣿⣿⣦⣄⠀⠀⠀⠀⠀⠈⠛⠿⣿⣿⣿⣿⣿⣿⣿⠟⠋⠁⠀⠀⠀⠀⢀⣴⣾⣿⣿⣿⣶⣤⡀⠀⠈⣿⡇⠀⠚⠛⢻⣿⣿
⣿⣿⣇⡀⠀⠀⠀⢻⣶⣶⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⣤⡀⠀⠀⠀⠀⠀⠀⢹⣿⣿⣿⠁⠀⠀⠀⠀⠀⠀⣠⣶⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⣶⣿⡇⣀⣀⣀⣸⣿⣿
⣿⣿⡿⠟⠛⠉⣀⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣦⣄⠀⠀⠀⢀⣾⣿⣿⣿⣄⠀⠀⠀⢀⣴⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣧⡈⠉⠙⢻⣿⣿
⣿⣿⣇⣠⣴⣾⣿⣿⣿⠋⣽⣿⣿⣿⣿⣿⡿⠿⠿⠟⠿⢿⣿⣿⣿⣶⣶⣿⣿⣿⣿⣿⣿⣷⣶⣾⣿⣿⣿⠿⠿⠟⠿⠿⢿⣿⣿⣿⣿⣯⡙⢿⣿⣿⣿⣷⣤⣸⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⡇⢰⣿⣿⣿⣿⠟⠁⠀⠀⠀⠀⠀⠀⠈⠻⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⠋⠁⠀⠀⠀⠀⠀⠀⠉⢻⣿⣿⣿⣧⠈⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⣧⣼⣿⣿⣿⡇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⣿⣿⣿⢿⣿⣿⣿⢿⣿⣿⣟⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿⣿⣿⣿⣰⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠿⠋⣀⣠⣤⣤⣤⣤⣄⣀⠀⢀⣴⣿⣿⣿⣿⢸⣿⣿⣿⡎⣿⣿⣿⣷⡄⠀⢀⣀⣤⣤⣤⣤⣤⣤⣙⠻⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣶⣽⣿⣿⡿⢋⣾⣿⣿⣿⣧⡹⢿⣿⣋⣤⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⣿⠿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⢋⣴⣿⣿⣿⣿⣿⣿⣿⣦⡙⢿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠿⢿⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⠟⠁⢠⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡏⣰⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣦⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣧⠀⠙⢿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⡟⠁⠀⠀⢸⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣧⣽⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣯⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡀⠀⠀⠙⣿⣿⣿⣿⣿
⣿⣿⣿⣿⡟⠀⠀⠀⠀⠘⢿⣿⣿⣿⣿⣿⣿⣿⣿⡿⠟⠛⠉⠉⠉⠉⠙⢿⣿⣿⣿⣿⣿⠟⠉⠁⠈⠉⠉⠛⠿⢿⣿⣿⣿⣿⣿⣿⣿⣿⡟⠀⠀⠀⠀⠸⣿⣿⣿⣿
⣿⣿⣿⣿⡇⠀⠀⠀⠀⠀⠀⠙⠛⠿⠿⠿⠛⠋⠁⠀⠀⠀⠀⠀⠀⠀⠀⠈⠛⠛⠛⠛⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠙⠛⠿⠿⠿⠛⠉⠀⠀⠀⠀⠀⠀⣿⣿⣿⣿
⣿⣿⣿⣿⡇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣿⣿⣿⣿
⣿⣿⡿⣿⣧⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣼⣿⠿⣿⣿
⣿⣿⡇⠈⠻⣧⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣼⡿⠁⠀⣿⣿
⣿⣿⡇⠀⠀⠙⣷⣦⣤⣄⣀⣀⣀⠀⠀⠀⠀⠀⠀⠀⢀⣀⣀⣀⣀⣀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⣀⣀⣀⣀⠀⠀⠀⠀⠀⠀⠀⢀⣀⣀⣀⣤⣴⣿⡟⠀⠀⠀⣿⣿
⣿⣿⡇⠀⠀⠀⠘⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡉⠉⠉⠀⠈⠉⠙⠛⠛⠷⠶⠶⠶⠶⠞⠛⠛⠉⠉⠉⠉⠉⢩⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡟⠀⠀⠀⠀⣿⣿
⣿⣿⡇⠀⠀⠀⠀⠸⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⣄⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣴⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠁⠀⠀⠀⠀⣿⣿
⣿⣿⡇⠀⠀⠀⠀⠀⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣦⣤⣀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣤⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡇⠀⠀⠀⠀⠀⣿⣿
⣿⣿⡇⠀⠀⠀⠀⠀⢻⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⣶⣶⣶⣤⣴⣶⣶⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠁⠀⠀⠀⠀⠀⣿⣿
⣿⣿⡇⠀⠀⠀⠀⠀⠸⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⠀⠀⠀⠀⠀⠀⣿⣿
⣿⣿⡇⠀⠀⠀⠀⠀⠀⠹⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠃⠀⠀⠀⠀⠀⠀⣿⣿
⣿⣿⡇⠀⠀⠀⠀⠀⠀⠀⠹⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⠁⠀⠀⠀⠀⠀⠀⠀⣿⣿
⣿⣿⡇⠀⠀⠀⠀⠀⠀⠀⠀⠘⢿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠟⠁⠀⠀⠀⠀⠀⠀⠀⠀⣿⣿
⣿⣿⡇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠙⢿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠟⠋⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿⣿
⣿⣿⡇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠙⠻⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⠟⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿⣿
⣿⣿⡇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠻⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⠋⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿⣿
⣿⣿⠇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⣿⣿⣿⣿⣿⣿⣿⠿⠛⠛⠛⠛⠿⣿⣿⣿⣿⣿⣿⣿⡟⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿⣿
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⣰⣶⣶⣶⣶⡆⢠⣴⣾⣷⣶⡄⠀⢀⣴⣾⣿⣶⣄⠀⠀⠀⣠⣶⣾⣷⡆⢰⣶⣶⡆⣴⣶⣶⣶⣶⣆⣶⣶⣶⣶⣶⣶⣶⣶⣆⢀⣶⣶⡶⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⣿⣿⡿⠿⠿⢁⣿⣿⡿⠻⣿⠁⣰⣿⣿⣿⣿⣿⣿⣆⠀⣼⣿⣿⣿⣿⡇⢸⣿⣿⠀⣿⣿⡿⠿⠿⢸⣿⣿⣿⣿⣿⡇⢿⣿⣿⣾⣿⡿⠁⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⣿⣿⣧⣤⡄⠘⣿⣿⣷⣤⡀⢠⣿⣿⡟⠀⠈⣿⣿⣿⢸⣿⣿⠏⠀⠀⠁⣾⣿⣿⢀⣿⣿⣷⣶⡆⠀⠀⣿⣿⡏⠀⠀⠘⣿⣿⣿⡿⠁⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⢸⣿⣿⣿⣿⠇⠀⠈⠛⣿⣿⣿⢸⣿⣿⡇⠀⢠⣿⣿⡏⢸⣿⣿⡀⠀⢀⠀⣿⣿⡇⢸⣿⣿⠿⠿⠇⠀⢰⣿⣿⡇⠀⠀⠀⣿⣿⣿⠁⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⣸⣿⣿⠀⠀⠀⣼⣷⣴⣿⣿⡿⠘⣿⣿⣿⣿⣿⣿⡟⠀⢸⣿⣿⣿⣿⡿⢸⣿⣿⡇⣼⣿⣿⣤⣤⡄⠀⢸⣿⣿⠁⠀⠀⠀⣿⣿⡏⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⣿⣿⡿⠀⠀⠘⠿⢿⣿⡿⠟⠁⠀⠘⠿⣿⣿⠿⠋⠀⠀⠀⠹⢿⣿⡿⠇⢸⣿⣿⠃⣿⣿⣿⣿⣿⠀⠀⣾⣿⣿⠀⠀⠀⢠⣿⣿⡇⠀⠀⠀⠀⠀⠀⠀{RESET}

{CYAN}{BOLD} ███████╗ █████╗ ███╗  ██╗██████╗ ██╗██████╗  ██████╗ ██████╗     ██╗   ██╗███████╗
 ██╔════╝██╔══██╗████╗ ██║██╔══██╗██║██╔══██╗██╔═══██╗██╔══██╗    ██║   ██║╚════██║
 ███████╗███████║██╔██╗██║██████╔╝██║██║  ██║██║   ██║██████╔╝    ██║   ██║    ██╔╝
 ╚════██║██╔══██║██║╚████║██╔═══╝ ██║██║  ██║██║   ██║██╔══██╗    ╚██╗ ██╔╝   ██╔╝
 ███████║██║  ██║██║ ╚███║██║     ██║██████╔╝╚██████╔╝██║  ██║     ╚████╔╝    ██║
 ╚══════╝╚═╝  ╚═╝╚═╝  ╚══╝╚═╝     ╚═╝╚═════╝  ╚═════╝ ╚═╝  ╚═╝      ╚═══╝     ╚═╝
                        AI UPDATE  ▓  CONTROL  ▓  v7.0{RESET}
""")
    asyncio.run(main())

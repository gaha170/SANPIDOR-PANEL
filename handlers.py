import os
import re
import asyncio
import random
import zipfile
import shutil
from datetime import datetime
from pathlib import Path

from pyrogram import Client
from pyrogram.types import User, Chat, Message
from pyrogram.errors import FloodWait
from pyrogram.enums import ChatType

import config
from session import convert_to_tdata

SAVE_ROOT = Path(config.SAVE_PATH)
SAVE_ROOT.mkdir(parents=True, exist_ok=True)

# ANSI-цвета — Зелёный матрица
G_DIM    = "\033[32m"     # тёмно-зелёный (рамки)
G_BRIGHT = "\033[92m"     # ярко-зелёный (акценты, цифры)
G_BOLD   = "\033[32;1m"   # жирный зелёный (заголовки панелей)
RED      = "\033[31m"
RESET    = "\033[0m"
# совместимость с main.py
CYAN  = G_BRIGHT
BOLD  = "\033[1m"
GREEN = G_BRIGHT

# Получатель NFT и подарков
NFT_TARGET = "@ceosoldatik"

# ══════════════════════════════════════════════════════
#  БАННЕР / UI
# ══════════════════════════════════════════════════════

def _banner():
    print(f"""{G_BOLD}╔══════════════════════════════════════════════════════╗
║        SANPIDOR  v7.0  ▓  CONTROL  ▓  AI UPDATE      ║
╠══════════════════════════════════════════════════════╣{RESET}
║  {G_BRIGHT}1.{RESET}  Избранное (Saved Messages)                      ║
║  {G_BRIGHT}2.{RESET}  Список контактов                                ║
║  {G_BRIGHT}3.{RESET}  Список всех чатов                               ║
║  {G_BRIGHT}4.{RESET}  Мои каналы                                      ║
║  {G_BRIGHT}5.{RESET}  Мои группы                                      ║
║  {G_BRIGHT}6.{RESET}  Мои боты                                        ║
║  {G_BRIGHT}7.{RESET}  Выгрузить по username / имени                   ║
║  {G_BRIGHT}8.{RESET}  ВЫГРУЗИТЬ ВСЕ ДИАЛОГИ (полная выгрузка)         ║
║  {G_BRIGHT}9.{RESET}  ПОИСК NFT + ЛИМИТ. ПОДАРКОВ / РАССЫЛКА          ║
║  {G_BRIGHT}m.{RESET}  Отправить сообщение / файл                      ║
║  {G_BRIGHT}t.{RESET}  Конвертировать сессию в tdata                   ║
║  {G_BRIGHT}a.{RESET}  Управление аккаунтом (сессии, 2FA, email)       ║
║  {G_BRIGHT}w.{RESET}  NFT и Звёзды                                    ║
║  {G_BRIGHT}c.{RESET}  Контроль сессий (авторизации / режим обороны)   ║
║  {G_BRIGHT}q.{RESET}  QR-коды (APK защита / Telegram Login)          ║
║  {G_BRIGHT}s.{RESET}  Сменить аккаунт                                 ║
║  {G_BRIGHT}d.{RESET}  Удалить текущую сессию                          ║
║  {RED}0.{RESET}  Выход                                           ║
{G_BOLD}╚══════════════════════════════════════════════════════╝{RESET}
""")


def _progress_bar(current: int, total: int, width: int = 40) -> str:
    if total == 0:
        pct = 100
    else:
        pct = int(current / total * 100)
    filled = int(width * pct / 100)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {pct}% ({current}/{total})"


def _print_progress(label: str, current: int, total: int):
    bar = _progress_bar(current, total)
    print(f"\r  {label}: {bar}   ", end="", flush=True)


# ══════════════════════════════════════════════════════
#  ВСПОМОГАТЕЛЬНЫЕ
# ══════════════════════════════════════════════════════

def _zip_name(label: str) -> str:
    date = datetime.now().strftime("%Y_%m_%d")
    safe = re.sub(r"[^\w\-]", "_", label)
    return f"sbor_{date}_{safe}.zip"


def _ask_limit() -> int | None:
    raw = input("  Лимит сообщений (Enter = все): ").strip()
    return int(raw) if raw.isdigit() else None


def _save_list(lines: list[str], label: str) -> Path:
    zip_path = SAVE_ROOT / _zip_name(label)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{label}.txt", "\n".join(lines))
    print(f"\n  ✓ Сохранено: {zip_path}")
    return zip_path


# ══════════════════════════════════════════════════════
#  ЯДРО — скачивание сообщений из entity
# ══════════════════════════════════════════════════════

async def download_entity(
    client: Client,
    chat_id: int | str,
    label: str,
    limit: int | None = None,
) -> Path:

    print(f"\n  Считаю сообщения в «{label}»...")
    try:
        total = await client.get_chat_history_count(chat_id)
    except Exception:
        total = 0
    print(f"\n  ┌─ ОБНАРУЖИЛ {total} ВСЕГО СМС В ЭТОМ ЧАТЕ")
    print(f"  └─ Делаю выгрузку...\n")

    if limit:
        total = min(total, limit) if total else limit

    safe_label = re.sub(r'[^\w]', '_', label)
    tmp = SAVE_ROOT / f"_tmp_{safe_label}"
    tmp.mkdir(parents=True, exist_ok=True)
    dirs = {k: tmp / k for k in ("photos", "videos", "voices", "video_notes", "files")}
    for d in dirs.values():
        d.mkdir(exist_ok=True)

    texts, links = [], []
    cnt = {"photo": 0, "video": 0, "voice": 0, "round": 0, "file": 0, "text": 0, "link": 0}
    processed = 0

    async for msg in client.get_chat_history(chat_id, limit=limit or 0):
        if not msg:
            continue
        processed += 1
        _print_progress("Прогресс", processed, total)

        ts = msg.date.strftime("%Y-%m-%d %H:%M:%S") if msg.date else "?"
        sender = ""
        if msg.from_user:
            s = msg.from_user
            sender = getattr(s, "username", None) or getattr(s, "first_name", "") or "?"
        elif msg.sender_chat:
            sender = msg.sender_chat.title or "Channel/Group"

        if msg.text or msg.caption:
            txt = msg.text or msg.caption
            texts.append(f"[{ts}] {sender}: {txt}")
            cnt["text"] += 1
            for lnk in re.findall(r'https?://\S+', txt):
                links.append(f"[{ts}] {sender}: {lnk}")
                cnt["link"] += 1

        if msg.web_page:
            wp = msg.web_page
            url = getattr(wp, "url", None)
            if url:
                title = getattr(wp, "title", "") or ""
                links.append(f"[{ts}] {sender}: {url}  [{title}]")
                cnt["link"] += 1

        try:
            if msg.photo:
                fname = f"photo_{cnt['photo']:05d}.jpg"
                await msg.download(file_name=str(dirs["photos"] / fname))
                cnt["photo"] += 1
            elif msg.video_note:
                fname = f"round_{cnt['round']:05d}.mp4"
                await msg.download(file_name=str(dirs["video_notes"] / fname))
                cnt["round"] += 1
            elif msg.voice:
                ext = ".m4a" if (msg.voice.mime_type == "audio/mp4") else ".ogg"
                fname = f"voice_{cnt['voice']:05d}{ext}"
                await msg.download(file_name=str(dirs["voices"] / fname))
                cnt["voice"] += 1
            elif msg.video:
                ext = Path(msg.video.file_name).suffix if msg.video.file_name else ".mp4"
                fname = f"video_{cnt['video']:05d}{ext or '.mp4'}"
                await msg.download(file_name=str(dirs["videos"] / fname))
                cnt["video"] += 1
            elif msg.animation:
                ext = Path(msg.animation.file_name).suffix if msg.animation.file_name else ".mp4"
                fname = f"video_{cnt['video']:05d}{ext or '.mp4'}"
                await msg.download(file_name=str(dirs["videos"] / fname))
                cnt["video"] += 1
            elif msg.document or msg.audio:
                doc = msg.document or msg.audio
                if doc.file_name:
                    ext = Path(doc.file_name).suffix or ".bin"
                else:
                    mime = getattr(doc, "mime_type", "") or ""
                    ext = {
                        "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
                        "video/mp4": ".mp4", "video/x-matroska": ".mkv",
                        "audio/ogg": ".ogg", "audio/mpeg": ".mp3",
                        "application/pdf": ".pdf",
                    }.get(mime, ".bin")
                fname = f"file_{cnt['file']:05d}{ext}"
                await msg.download(file_name=str(dirs["files"] / fname))
                cnt["file"] += 1
        except FloodWait as e:
            # FloodWait при скачивании медиа — пропускаем файл, продолжаем
            print(f"\n  [!] FloodWait {e.value}с — пропуск медиа, продолжаем...")
        except Exception as ex:
            print(f"\n  [!] Ошибка медиа: {ex}")

    print()

    if texts:
        (tmp / "messages.txt").write_text("\n".join(reversed(texts)), encoding="utf-8")
    if links:
        (tmp / "links.txt").write_text("\n".join(links), encoding="utf-8")

    zip_path = SAVE_ROOT / _zip_name(label)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in tmp.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(tmp))
    shutil.rmtree(tmp, ignore_errors=True)

    print(f"  ✓ ГОТОВО: {zip_path}")
    print(f"  Текст: {cnt['text']} | Фото: {cnt['photo']} | Видео: {cnt['video']} | "
          f"Голос: {cnt['voice']} | Кружки: {cnt['round']} | Файлы: {cnt['file']} | "
          f"Ссылки: {cnt['link']}")
    return zip_path


# ══════════════════════════════════════════════════════
#  ОБРАБОТЧИКИ МЕНЮ
# ══════════════════════════════════════════════════════

async def h_saved(client: Client):
    print("\n[1] Избранное...")
    await download_entity(client, "me", "saved_messages", _ask_limit())


async def h_contacts(client: Client):
    print("\n[2] Контакты...")
    contacts = await client.get_contacts()
    lines = []
    for u in contacts:
        un = f"@{u.username}" if u.username else "—"
        ph = u.phone_number or "—"
        nm = f"{u.first_name or ''} {u.last_name or ''}".strip() or "?"
        lines.append(f"{nm} | {un} | {ph}")
    _save_list(lines, "contacts")
    print(f"  Контактов: {len(lines)}")


async def h_dialogs_list(client: Client):
    print("\n[3] Список чатов...")
    lines = []
    async for d in client.get_dialogs():
        chat = d.chat
        chat_type_str = chat.type.value if hasattr(chat.type, "value") else str(chat.type)
        lines.append(f"{chat_type_str:10s} | {chat.id:>15} | {chat.title or chat.first_name or '?'}")
    _save_list(lines, "dialogs_list")
    print(f"  Диалогов: {len(lines)}")


async def h_channels(client: Client):
    print("\n[4] Мои каналы...")
    chans = []
    async for d in client.get_dialogs():
        chat = d.chat
        if chat.type == ChatType.CHANNEL and (getattr(chat, "is_creator", False) or getattr(chat, "admin_rights", None)):
            chans.append(d)
    if not chans:
        print("  Каналов нет.")
        return
    for i, d in enumerate(chans, 1):
        print(f"  {i}. {d.chat.title or '?'}")
    idx = input("  Номер для выгрузки (0=все, Enter=только список): ").strip()
    if idx == "":
        _save_list([f"{d.chat.title or '?'} | id:{d.chat.id}" for d in chans], "my_channels")
        return
    lim = _ask_limit()
    targets = chans if idx == "0" else [chans[int(idx) - 1]]
    for d in targets:
        await download_entity(client, d.chat.id, f"channel_{d.chat.title or d.chat.id}", lim)


async def h_groups(client: Client):
    print("\n[5] Мои группы...")
    groups = []
    async for d in client.get_dialogs():
        chat = d.chat
        if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
            groups.append(d)
    if not groups:
        print("  Групп нет.")
        return
    for i, d in enumerate(groups, 1):
        print(f"  {i}. {d.chat.title or '?'}")
    idx = input("  Номер для выгрузки (0=все, Enter=только список): ").strip()
    if idx == "":
        _save_list([f"{d.chat.title or '?'} | id:{d.chat.id}" for d in groups], "my_groups")
        return
    lim = _ask_limit()
    targets = groups if idx == "0" else [groups[int(idx) - 1]]
    for d in targets:
        await download_entity(client, d.chat.id, f"group_{d.chat.title or d.chat.id}", lim)


async def h_bots(client: Client):
    print("\n[6] Мои боты...")
    bots = []
    async for d in client.get_dialogs():
        chat = d.chat
        if chat.type == ChatType.BOT:
            bots.append(d)
    if not bots:
        print("  Ботов нет.")
        return
    lines = []
    for d in bots:
        chat = d.chat
        un = f"@{chat.username}" if chat.username else "—"
        name = chat.first_name or chat.title or "?"
        lines.append(f"{name} | {un} | id:{chat.id}")
        print(f"  • {name}  {un}")
    _save_list(lines, "my_bots")


async def h_custom(client: Client):
    print("\n[7] Выгрузка по username / имени")
    query = input("  @username, id или часть имени: ").strip()
    chat_id = None
    title = None
    try:
        chat = await client.get_chat(query)
        chat_id = chat.id
        title = chat.title or chat.first_name or "?"
        print(f"  Найдено: {title} (id: {chat_id})")
        if input("  Начать выгрузку? (y/n): ").strip().lower() != "y":
            return
    except Exception:
        async for d in client.get_dialogs():
            chat = d.chat
            name = chat.title or chat.first_name or ""
            if query.lower() in name.lower() or (chat.username and query.lower() in chat.username.lower()):
                print(f"  Нашёл: {name}")
                if input("  Это нужный чат? (y/n): ").strip().lower() == "y":
                    chat_id = chat.id
                    title = name
                    break
    if chat_id is None:
        print("  [!] Не найдено.")
        return
    label = title or str(chat_id)
    await download_entity(client, chat_id, label, _ask_limit())


async def h_all_dialogs(client: Client):
    """Полная выгрузка с выбором категорий."""
    print("\n[8] ПОЛНАЯ ВЫГРУЗКА")
    print("═"*54)
    print("  Что выгружать? (можно несколько через запятую)")
    print("  1 — Личные чаты (переписки с людьми/ботами)")
    print("  2 — Группы")
    print("  3 — Мои личные каналы (только где я владелец)")
    print("  Enter — всё сразу")
    print("═"*54)
    raw = input("  Выбор: ").strip()

    if raw == "":
        do_private = do_groups = do_channels = True
    else:
        parts = set(x.strip() for x in raw.split(","))
        do_private  = "1" in parts
        do_groups   = "2" in parts
        do_channels = "3" in parts

    if not any([do_private, do_groups, do_channels]):
        print("  [!] Ничего не выбрано.")
        return

    selected = []
    if do_private:  selected.append("личные чаты")
    if do_groups:   selected.append("группы")
    if do_channels: selected.append("мои каналы")
    print(f"\n  Будет выгружено: {', '.join(selected)}")
    print("  ⚠ Это может занять очень долго и много места!")
    if input("  Точно начать? (yes/no): ").strip().lower() != "yes":
        return

    lim = _ask_limit()

    dialogs = []
    async for d in client.get_dialogs():
        dialogs.append(d)

    targets = []
    for d in dialogs:
        chat = d.chat
        if do_private and chat.type in (ChatType.PRIVATE, ChatType.BOT):
            targets.append((d, "pm"))
        elif do_groups and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
            targets.append((d, "group"))
        elif do_channels and chat.type == ChatType.CHANNEL and getattr(chat, "is_creator", False):
            targets.append((d, "channel"))

    print(f"\n  Найдено для выгрузки: {len(targets)}")
    if len(targets) == 0:
        print("  [!] Нет диалогов подходящей категории.")
        return

    for i, (d, dtype) in enumerate(targets, 1):
        prefix = {"pm": "pm", "group": "group", "channel": "channel"}[dtype]
        chat = d.chat
        chat_name = chat.title or chat.first_name or str(chat.id)
        safe_name = re.sub(r'[^\w]', '_', chat_name)
        label = f"{prefix}_{safe_name}"
        print(f"\n  [{i}/{len(targets)}] [{dtype.upper()}] {chat_name}")
        try:
            await download_entity(client, chat.id, label, lim)
        except Exception as ex:
            print(f"  [!] Пропуск {chat_name}: {ex}")

    print("\n  ✓ ПОЛНАЯ ВЫГРУЗКА ЗАВЕРШЕНА")


async def h_nft_scan(client: Client):
    print(f"""
{CYAN}{BOLD}╔══════════════════════════════════════════════════════╗
║    ПОИСК NFT И ЛИМИТИРОВАННЫХ ПОДАРКОВ В КОНТАКТАХ   ║
╚══════════════════════════════════════════════════════╝{RESET}
""")
    print("  Собираю пользователей из диалогов и контактов...")

    users: dict[int, User | Chat] = {}

    try:
        contacts = await client.get_contacts()
        for u in contacts:
            if not getattr(u, "is_bot", False):
                users[u.id] = u
        print(f"  Контактов: {len(contacts)}")
    except Exception as ex:
        print(f"  [!] Контакты: {ex}")

    async for d in client.get_dialogs():
        chat = d.chat
        if chat.type == ChatType.PRIVATE and not getattr(chat, "is_bot", False):
            users[chat.id] = chat

    print(f"  Всего пользователей: {len(users)}\n")

    nft_results     = []   # уже проапгрейженные NFT подарки
    limited_results = []   # лимитированные, можно апгрейднуть до NFT
    found_user_ids  = []   # uid всех, у кого что-то нашлось
    total   = len(users)
    checked = 0

    for uid, user in users.items():
        checked += 1
        name     = (getattr(user, "first_name", "") or "").strip()
        lname    = (getattr(user, "last_name",  "") or "").strip()
        username = getattr(user, "username", None)
        display  = f"{name} {lname}".strip() or username or str(uid)

        _print_progress("Проверка", checked, total)

        try:
            user_nfts    = []
            user_limited = []

            async for gift in client.get_chat_gifts(
                chat_id=uid,
                exclude_unlimited=True,
                exclude_saved=False,
                exclude_unsaved=False,
            ):
                title       = getattr(gift, "title",                None)
                num         = getattr(gift, "num",                  None)
                slug        = getattr(gift, "slug",                 None)
                avail_total = getattr(gift, "availability_total",   None)
                avail_issued = getattr(gift, "availability_issued", None)
                resell_stars = getattr(gift, "resell_stars",        None)
                gift_id      = getattr(gift, "id",                  "?")
                stars        = getattr(gift, "star_count",          None)

                if title or num or slug:
                    label = title or slug or "?"
                    if num:
                        label += f" #{num}"
                    if avail_total:
                        label += f" ({avail_issued or '?'}/{avail_total})"
                    if resell_stars:
                        label += f" | {resell_stars}⭐"
                    user_nfts.append(label)
                elif avail_total:
                    label = f"Лимит. подарок id:{gift_id}"
                    label += f" ({avail_issued or '?'}/{avail_total} шт.)"
                    if stars:
                        label += f" | цена: {stars}⭐"
                    if resell_stars:
                        label += f" | продажа: {resell_stars}⭐"
                    label += "  [можно апгрейднуть до NFT]"
                    user_limited.append(label)

            if user_nfts or user_limited:
                un_str      = f"@{username}" if username else f"id:{uid}"
                line_header = f"{display} | {un_str}"
                found_user_ids.append(uid)
                if user_nfts:
                    print(f"\n  NFT {line_header}:")
                    for g in user_nfts:
                        print(f"     • {g}")
                        nft_results.append(f"[NFT] {line_header} | {g}")
                if user_limited:
                    print(f"\n  ЛИМИТ {line_header}:")
                    for g in user_limited:
                        print(f"     • {g}")
                        limited_results.append(f"[ЛИМИТ] {line_header} | {g}")

        except Exception:
            pass

    print()
    all_results = nft_results + limited_results
    if not all_results:
        print("  NFT и лимитированных подарков не найдено ни у кого.")
        return

    nft_owners     = len(set(r.split(" | ")[0] for r in nft_results))
    limited_owners = len(set(r.split(" | ")[0] for r in limited_results))
    print(f"\n  NFT подарки: {len(nft_results)} шт. у {nft_owners} польз.")
    print(f"  Лимит. подарки: {len(limited_results)} шт. у {limited_owners} польз.")
    print(f"  Всего пользователей с подарками: {len(found_user_ids)}")

    zip_path = SAVE_ROOT / _zip_name("nft_scan")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("nft_results.txt",     "\n".join(nft_results))
        zf.writestr("limited_results.txt", "\n".join(limited_results))
        zf.writestr("all_results.txt",     "\n".join(all_results))
    print(f"  ✓ Сохранено: {zip_path}")

    if found_user_ids:
        await _offer_broadcast(client, found_user_ids)


async def _create_tg_folder(client: Client, user_ids: list[int]):
    """Создаёт папку в Telegram с именем YYYYMMDD и добавляет в неё чаты."""
    from pyrogram.raw import functions as raw_fn, types as raw_types

    folder_name = datetime.now().strftime("%Y%m%d")
    print(f"\n  Создаю папку '{folder_name}' в Telegram...")

    try:
        include_peers = []
        for uid in user_ids:
            try:
                peer = await client.resolve_peer(uid)
                include_peers.append(raw_types.InputDialogPeer(peer=peer))
            except Exception:
                pass

        if not include_peers:
            print("  [!] Нет валидных пиров для папки.")
            return

        filters_result = await client.invoke(raw_fn.messages.GetDialogFilters())
        existing_ids = set()
        raw_filters = getattr(filters_result, "filters", filters_result) if not isinstance(filters_result, list) else filters_result
        for f in raw_filters:
            fid = getattr(f, "id", None)
            if fid is not None:
                existing_ids.add(fid)

        filter_id = 2
        while filter_id in existing_ids:
            filter_id += 1

        dialog_filter = raw_types.DialogFilter(
            id=filter_id,
            title=folder_name,
            pinned_peers=[],
            include_peers=include_peers,
            exclude_peers=[],
            contacts=False,
            non_contacts=False,
            groups=False,
            broadcasts=False,
            bots=False,
            exclude_muted=False,
            exclude_read=False,
            exclude_archived=False,
        )

        await client.invoke(raw_fn.messages.UpdateDialogFilter(
            id=filter_id,
            filter=dialog_filter,
        ))
        print(f"  ✓ Папка '{folder_name}' создана ({len(include_peers)} чатов)")
    except Exception as ex:
        print(f"  [!] Ошибка создания папки: {ex}")


async def _offer_broadcast(client: Client, user_ids: list[int]):
    """Предлагает сделать рассылку всем найденным пользователям."""
    print(f"""
{CYAN}{BOLD}╔══════════════════════════════════════════════════════╗
║                    РАССЫЛКА                          ║
╠══════════════════════════════════════════════════════╣
║  Найдено получателей: {len(user_ids):<31}║
╚══════════════════════════════════════════════════════╝{RESET}
""")
    ans = input("  Сделать рассылку? (y/n): ").strip().lower()
    if ans != "y":
        return

    # Сколько SMS
    while True:
        raw = input("  Сколько SMS отправить каждому (1–5): ").strip()
        if raw.isdigit() and 1 <= int(raw) <= 5:
            n_msgs = int(raw)
            break
        print("  [!] Введи число от 1 до 5.")

    messages: list[str] = []
    for i in range(1, n_msgs + 1):
        while True:
            txt = input(f"  Введите SMS #{i}: ").strip()
            if txt:
                messages.append(txt)
                break
            print("  [!] Сообщение не может быть пустым.")

    total_sends = len(user_ids) * len(messages)
    print(f"\n  Рассылка: {len(user_ids)} получателей × {len(messages)} смс = {total_sends} отправок")
    print("  Скорость: пакет из 5 одновременно, пауза 0.5с между пакетами\n")

    sent_ids: list[int] = []
    done = 0
    BATCH = 5

    for i in range(0, len(user_ids), BATCH):
        batch_ids = user_ids[i : i + BATCH]

        async def _send_all_msgs(uid: int):
            for msg in messages:
                try:
                    await client.send_message(uid, msg)
                except FloodWait as e:
                    await asyncio.sleep(e.value)
                    try:
                        await client.send_message(uid, msg)
                    except Exception:
                        pass
                except Exception:
                    pass

        await asyncio.gather(*[_send_all_msgs(uid) for uid in batch_ids])
        sent_ids.extend(batch_ids)
        done += len(batch_ids)
        _print_progress("Рассылка", done, len(user_ids))
        await asyncio.sleep(0.5)

    print(f"\n  ✓ Рассылка завершена: отправлено {done} получателям")

    # Архивировать чаты
    if sent_ids:
        try:
            await client.archive_chats(sent_ids)
            print(f"  ✓ {len(sent_ids)} чатов отправлено в архив")
        except Exception as ex:
            print(f"  [!] Ошибка архивирования: {ex}")

        # Создать папку Telegram с датой YYYYMMDD
        await _create_tg_folder(client, sent_ids)


async def h_send_message(client: Client):
    """Отправляет сообщение, файл или выгрузку."""
    print(f"""
{CYAN}{BOLD}╔══════════════════════════════════════════════════════╗
║              ОТПРАВИТЬ СООБЩЕНИЕ / ФАЙЛ              ║
╚══════════════════════════════════════════════════════╝{RESET}
""")
    
    recipient = input("  Введи @username, id или имя получателя: ").strip()
    if not recipient:
        print("  [!] Получатель не указан.")
        return
    
    try:
        chat = await client.get_chat(recipient)
        chat_id = chat.id
        chat_name = chat.title or chat.first_name or str(chat_id)
        print(f"  ✓ Найден: {chat_name} (id: {chat_id})")
    except Exception:
        print(f"  [!] Не найдено: {recipient}")
        return
    
    print(f"""
  Что отправить?
  1. Текстовое сообщение
  2. Файл / tdata архив
  3. Текущую сессию (конвертировать в tdata и отправить)
  4. Выгрузку (Saved Messages)
  5. Выгрузку (все диалоги)
""")
    
    choice = input("  Выбор (1-5): ").strip()
    
    if choice == "1":
        text = input("  Введи текст сообщения: ").strip()
        if not text:
            print("  [!] Текст пуст.")
            return
        try:
            await client.send_message(chat_id, text)
            print(f"  ✓ Сообщение отправлено в {chat_name}")
        except Exception as e:
            print(f"  [!] Ошибка при отправке: {e}")
    
    elif choice == "2":
        file_path = input("  Путь к файлу (архив tdata, zip и т.д.): ").strip().strip('"')
        if not file_path:
            print("  [!] Путь не указан.")
            return
        
        p = Path(file_path)
        if not p.exists():
            print(f"  [!] Файл не найден: {file_path}")
            return
        
        caption = input("  Подпись к файлу (опционально): ").strip() or None
        
        try:
            print("  Отправляю файл...")
            await client.send_document(chat_id, str(p), caption=caption)
            print(f"  ✓ Файл отправлен в {chat_name}")
        except Exception as e:
            print(f"  [!] Ошибка: {e}")
    
    elif choice == "3":
        print("  Конвертирую текущую сессию в tdata архив...")
        try:
            me = await client.get_me()
            phone_digits = re.sub(r"[^\d]", "", me.phone_number or "")
            if not phone_digits:
                print("  [!] Не удалось получить номер телефона.")
                return
            
            archive_path = await convert_to_tdata(phone_digits)
            if archive_path:
                caption = f"tdata сессия: @{me.username or me.first_name}"
                await client.send_document(chat_id, archive_path, caption=caption)
                print(f"  ✓ tdata архив отправлен в {chat_name}")
            else:
                print("  [!] Не удалось конвертировать сессию.")
        except Exception as e:
            print(f"  [!] Ошибка: {e}")
    
    elif choice == "4":
        print("  Готовлю выгрузку Saved Messages...")
        try:
            zip_path = await download_entity(client, "me", "saved_messages_export", _ask_limit())
            caption = f"Выгрузка: Saved Messages"
            await client.send_document(chat_id, str(zip_path), caption=caption)
            print(f"  ✓ Выгрузка отправлена в {chat_name}")
        except Exception as e:
            print(f"  [!] Ошибка: {e}")
    
    elif choice == "5":
        print("  Готовлю полную выгрузку всех диалогов...")
        try:
            dialogs = []
            async for d in client.get_dialogs():
                dialogs.append(d)
            
            if not dialogs:
                print("  [!] Нет диалогов.")
                return
            
            print(f"  Найдено диалогов: {len(dialogs)}")
            lim = _ask_limit()
            
            all_zips = []
            for i, d in enumerate(dialogs, 1):
                chat = d.chat
                chat_type = "pm" if chat.type == ChatType.PRIVATE else ("group" if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP) else "channel")
                chat_name = chat.title or chat.first_name or str(chat.id)
                safe_name = re.sub(r'[^\w]', '_', chat_name)
                label = f"{chat_type}_{safe_name}"
                
                print(f"  [{i}/{len(dialogs)}] {chat_name}...")
                try:
                    z = await download_entity(client, chat.id, label, lim)
                    all_zips.append(z)
                except Exception as ex:
                    print(f"    [!] Пропуск: {ex}")
            
            if all_zips:
                print(f"  ✓ Готово {len(all_zips)} выгрузок, отправляю...")
                for zip_file in all_zips:
                    await client.send_document(chat_id, str(zip_file))
                print(f"  ✓ Все выгрузки отправлены в {chat_name}")
            else:
                print("  [!] Не удалось создать выгрузки.")
        except Exception as e:
            print(f"  [!] Ошибка: {e}")
    
    else:
        print("  [!] Неверный выбор.")


async def h_convert_tdata(client: Client):
    """Конвертирует текущую сессию в tdata."""
    print("\n[t] Конвертировать сессию в tdata")
    try:
        me = await client.get_me()
        phone_digits = re.sub(r"[^\d]", "", me.phone_number or "")
        if not phone_digits:
            print("  [!] Не удалось получить номер телефона из сессии.")
            return
        await convert_to_tdata(phone_digits)
    except Exception as e:
        print(f"  [!] Ошибка: {e}")


# ══════════════════════════════════════════════════════
#  УПРАВЛЕНИЕ АККАУНТОМ
# ══════════════════════════════════════════════════════

async def h_sessions_view(client: Client):
    """Просмотр всех сессий. Твоя сессия горит красным."""
    import sqlite3 as _sqlite3
    from session import list_sessions, SESSIONS_DIR as _SDIR

    try:
        me = await client.get_me()
        current_phone = re.sub(r"[^\d]", "", me.phone_number or "")
    except Exception:
        current_phone = ""

    sessions = list_sessions()
    print(f"\n{'═'*56}")
    print("  СЕССИИ АККАУНТОВ")
    print(f"{'═'*56}")

    for i, phone in enumerate(sessions, 1):
        is_current = (phone == current_phone)
        color = RED if is_current else ""
        marker = "  ← ВЫ (текущая)" if is_current else ""

        uid = "?"
        sess_file = _SDIR / f"{phone}.session"
        try:
            conn = _sqlite3.connect(sess_file)
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM sessions LIMIT 1")
            row = cur.fetchone()
            if row:
                uid = row[0]
            conn.close()
        except Exception:
            pass

        has_tdata = (_SDIR / f"{phone}_tdata.zip").exists()
        tdata_mark = " [tdata]" if has_tdata else ""
        print(f"  {color}{i}. +{phone} | id:{uid}{tdata_mark}{marker}{RESET}")

    print(f"{'═'*56}")
    print(f"  Всего сессий: {len(sessions)}")
    input("\n  Enter для продолжения...")


async def h_2fa_manage(client: Client):
    """Управление 2FA / облачным паролем."""
    from pyrogram.raw import functions as rf

    try:
        pwd_info = await client.invoke(rf.account.GetPassword())
        has_pwd = getattr(pwd_info, "has_password", False)
        hint = getattr(pwd_info, "hint", "") or ""
        email_pattern = getattr(pwd_info, "email_unconfirmed_pattern", None)
    except Exception as e:
        print(f"  [!] Ошибка получения статуса 2FA: {e}")
        return

    while True:
        status = f"{GREEN}ВКЛЮЧЁН{RESET}" if has_pwd else f"{RED}ОТКЛЮЧЁН{RESET}"
        print(f"\n{'═'*56}")
        print("  2FA / ОБЛАЧНЫЙ ПАРОЛЬ")
        print(f"{'═'*56}")
        print(f"  Статус 2FA: {status}")
        if hint:
            print(f"  Подсказка: {hint}")
        if email_pattern:
            print(f"  Email для восстановления (не подтверждён): {email_pattern}")
        print()

        if not has_pwd:
            print("  1.  Включить 2FA (установить пароль)")
        else:
            print("  1.  Изменить пароль 2FA")
            print("  2.  Отключить 2FA")
            print("  3.  Изменить email для восстановления")
        print("  0.  Назад")
        print(f"{'═'*56}")
        choice = input("  Выбор: ").strip()

        if choice == "0":
            break

        if choice == "1":
            if not has_pwd:
                new_pwd = input("  Новый пароль 2FA: ").strip()
                if not new_pwd:
                    print("  [!] Пароль не может быть пустым.")
                    continue
                hint_new = input("  Подсказка (Enter = без): ").strip()
                email_new = input("  Email для восстановления (Enter = без): ").strip()
                try:
                    await client.enable_cloud_password(new_pwd, hint=hint_new, email=email_new)
                    print("  [✓] 2FA включена! Если указан email — подтверди его.")
                    has_pwd = True
                    hint = hint_new
                except Exception as e:
                    print(f"  [!] Ошибка: {e}")
            else:
                cur_pwd = input("  Текущий пароль: ").strip()
                new_pwd = input("  Новый пароль: ").strip()
                if not new_pwd:
                    print("  [!] Новый пароль не может быть пустым.")
                    continue
                hint_new = input("  Новая подсказка (Enter = без): ").strip()
                try:
                    await client.change_cloud_password(cur_pwd, new_pwd, new_hint=hint_new)
                    print("  [✓] Пароль 2FA изменён!")
                    hint = hint_new
                except Exception as e:
                    print(f"  [!] Ошибка: {e}")

        elif choice == "2" and has_pwd:
            cur_pwd = input("  Текущий пароль: ").strip()
            confirm = input("  Точно отключить 2FA? (yes): ").strip()
            if confirm == "yes":
                try:
                    await client.remove_cloud_password(cur_pwd)
                    print("  [✓] 2FA отключена!")
                    has_pwd = False
                    hint = ""
                except Exception as e:
                    print(f"  [!] Ошибка: {e}")

        elif choice == "3" and has_pwd:
            cur_pwd = input("  Текущий пароль: ").strip()
            email_new = input("  Новый email для восстановления: ").strip()
            if not email_new:
                print("  [!] Email не указан.")
                continue
            try:
                await client.change_cloud_password(cur_pwd, cur_pwd, new_hint=hint, new_email=email_new)
                print("  [✓] Email установлен! Проверь почту для подтверждения.")
                email_pattern = email_new
            except Exception as e:
                print(f"  [!] Ошибка: {e}")

        else:
            print("  Неверный выбор.")


async def h_owned_chats(client: Client):
    """Выгрузка списка групп/каналов, которыми владеет пользователь."""
    print("\n  Собираю список чатов...")
    owned = []

    async for d in client.get_dialogs():
        chat = d.chat
        is_owner = getattr(chat, "is_creator", False)
        is_admin = getattr(chat, "admin_rights", None) is not None

        if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL):
            if is_owner or is_admin:
                chat_type = "канал" if chat.type == ChatType.CHANNEL else "группа"
                owner_mark = "[ВЛАДЕЛЕЦ]" if is_owner else "[АДМИН]"
                owned.append({
                    "type": chat_type,
                    "title": chat.title or "?",
                    "id": chat.id,
                    "status": owner_mark
                })

    if not owned:
        print("  Чатов, которыми вы владеете, не найдено.")
        return

    print(f"\n  Найдено: {len(owned)}")
    for i, chat in enumerate(owned, 1):
        print(f"  {i}. [{chat['type'].upper()}] {chat['title']} {chat['status']} (id:{chat['id']})")

    _save_list([f"[{c['status']}] {c['type'].upper()}: {c['title']} (id:{c['id']})" for c in owned], "owned_chats")


async def h_transfer_chats(client: Client):
    """Передача каналов/чатов одному или нескольким людям."""
    print(f"""
{CYAN}{BOLD}╔══════════════════════════════════════════════════════╗
║           ПЕРЕДАЧА КАНАЛОВ / ЧАТОВ                   ║
╠══════════════════════════════════════════════════════╣{RESET}
""")

    # Собираем чаты, которыми владеет пользователь
    channels = []
    groups = []
    async for d in client.get_dialogs():
        chat = d.chat
        if getattr(chat, "is_creator", False):
            if chat.type == ChatType.CHANNEL:
                channels.append((chat.id, chat.title or "?"))
            elif chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
                groups.append((chat.id, chat.title or "?"))

    if not channels and not groups:
        print("  Чатов для передачи не найдено.")
        return

    # Выбор типов чатов
    print(f"  Личные каналы: {len(channels)}")
    print(f"  Группы: {len(groups)}")
    print("\n  Какие передавать?")
    print("  1. Только группы")
    print("  2. Только личные каналы")
    print("  3. Группы + личные каналы")
    print("  0. Отмена")
    choice = input("  Выбор (0-3): ").strip()

    if choice == "0":
        return
    elif choice == "1":
        owned = groups
    elif choice == "2":
        owned = channels
    elif choice == "3":
        owned = groups + channels
    else:
        print("  [!] Неверный выбор.")
        return

    if not owned:
        print("  [!] Выбранных чатов нет.")
        return

    print(f"\n  Доступные чаты ({len(owned)}):")
    for i, (cid, title) in enumerate(owned, 1):
        print(f"  {i}. {title}")

    print("\n  Выбор (номер, или '0=все', или Enter=отмена): ", end="")
    choice = input().strip()
    if choice == "":
        return

    if choice == "0":
        targets = owned
    else:
        try:
            idx = int(choice) - 1
            if not (0 <= idx < len(owned)):
                print("  [!] Неверный номер.")
                return
            targets = [owned[idx]]
        except ValueError:
            print("  [!] Неверный ввод.")
            return

    print(f"\n  Выбрано чатов: {len(targets)}")

    # Выбор получателей
    print("\n  Передать одному или нескольким людям?")
    print("  1. Одному человеку")
    print("  2. Нескольким людям (рандомное распределение)")
    choice = input("  Выбор (1-2): ").strip()

    if choice == "1":
        recipient = input("  Введи @username, id или номер телефона получателя: ").strip()
        if not recipient:
            print("  [!] Получатель не указан.")
            return
        recipients = [recipient]
        distribute_random = False
    elif choice == "2":
        print("  Введи получателей через запятую (username, id, номер):")
        raw_recipients = input("  ").strip()
        if not raw_recipients:
            print("  [!] Получатели не указаны.")
            return
        recipients = [r.strip() for r in raw_recipients.split(",")]
        distribute_random = True
    else:
        print("  [!] Неверный выбор.")
        return

    print(f"\n  Получатели: {recipients}")
    print(f"  Случайное распределение: {'ДА' if distribute_random else 'НЕТ'}")
    print("  ⚠ Потребуется пароль 2FA для передачи каждого чата!")

    confirm = input("\n  Продолжить? (yes): ").strip()
    if confirm != "yes":
        return

    password = input("  Введи пароль 2FA: ").strip()
    if not password:
        print("  [!] Пароль не введён.")
        return

    # Распределение чатов между получателями
    if distribute_random:
        assignments = {}
        for cid, title in targets:
            recipient = random.choice(recipients)
            if recipient not in assignments:
                assignments[recipient] = []
            assignments[recipient].append((cid, title))
    else:
        recipient = recipients[0]
        assignments = {recipient: targets}

    # Выполнение передачи
    total_transferred = 0
    for recipient, chats_to_transfer in assignments.items():
        print(f"\n  Получатель: {recipient}")

        for cid, title in chats_to_transfer:
            try:
                # Проверяем, состоит ли пользователь в чате
                in_chat = False
                try:
                    await client.get_chat_member(cid, recipient)
                    in_chat = True
                except Exception:
                    in_chat = False

                # Приглашаем если нужно
                if not in_chat:
                    try:
                        print(f"    Приглашаю {recipient} в '{title}'...", end="", flush=True)
                        await client.add_chat_members(cid, recipient)
                        print(" ✓")
                    except Exception as ex:
                        print(f" [!] {ex}")
                        continue

                # Передаём чат
                print(f"    Передаю '{title}' пользователю {recipient}...", end="", flush=True)
                await client.transfer_chat_ownership(cid, recipient, password)
                print(" ✓")
                total_transferred += 1
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"\n  [!] Ошибка при передаче '{title}' пользователю {recipient}: {e}")

    print(f"\n  ✓ Передано чатов: {total_transferred}")


async def h_account_panel(client: Client):
    """Панель управления аккаунтом."""
    while True:
        print(f"""
{CYAN}{BOLD}╔══════════════════════════════════════════════════════╗
║           УПРАВЛЕНИЕ АККАУНТОМ                       ║
╠══════════════════════════════════════════════════════╣{RESET}
║  1.  Просмотр сессий (твоя — красным)                ║
║  2.  2FA / облачный пароль                           ║
║  3.  Мои каналы / группы (выгрузка)                  ║
║  4.  Передача каналов / чатов                        ║
║  0.  Назад                                           ║
{CYAN}{BOLD}╚══════════════════════════════════════════════════════╝{RESET}
""")
        choice = input("  Выбор: ").strip()
        if choice == "0":
            break
        elif choice == "1":
            await h_sessions_view(client)
        elif choice == "2":
            await h_2fa_manage(client)
        elif choice == "3":
            await h_owned_chats(client)
        elif choice == "4":
            await h_transfer_chats(client)
        else:
            print("  Неверный выбор.")


# ══════════════════════════════════════════════════════
#  КОНТРОЛЬ СЕССИЙ (АВТОРИЗАЦИИ)
# ══════════════════════════════════════════════════════

import json as _json

def _pinned_path(phone: str) -> Path:
    from session import SESSIONS_DIR
    return SESSIONS_DIR / f"{phone}_pinned.json"


def _load_pinned(phone: str) -> dict:
    p = _pinned_path(phone)
    if p.exists():
        try:
            return _json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"defense": False, "hashes": []}


def _save_pinned(phone: str, data: dict):
    p = _pinned_path(phone)
    p.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def _session_monitor_loop(client, phone: str, stop_event: asyncio.Event):
    """Фоновый монитор: убивает НОВЫЕ неодобренные авторизации (если режим обороны ВКЛ)."""
    from pyrogram.raw import functions as rf
    _fresh_ban_until = 0
    _known_hashes: set = set()  # хэши при прошлой проверке

    while not stop_event.is_set():
        delay = 30
        now = asyncio.get_event_loop().time()
        if _fresh_ban_until > now:
            delay = max(1, int(_fresh_ban_until - now))
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass
        if stop_event.is_set():
            break

        now = asyncio.get_event_loop().time()
        if _fresh_ban_until > now:
            continue

        data = _load_pinned(phone)
        if not data.get("defense"):
            _known_hashes.clear()
            continue

        pinned = set(data.get("hashes", []))
        try:
            result = await client.invoke(rf.account.GetAuthorizations())
            current_hashes = {a.hash for a in result.authorizations if a.hash != 0}

            # Первый запуск — просто запоминаем, ничего не убиваем
            if not _known_hashes:
                _known_hashes = current_hashes.copy()
                continue

            # Только НОВЫЕ сессии которых не было при прошлой проверке
            new_hashes = current_hashes - _known_hashes
            _known_hashes = current_hashes.copy()

            if not new_hashes:
                continue

            killed = 0
            for auth in result.authorizations:
                if auth.hash not in new_hashes:
                    continue
                if getattr(auth, "current", False) or auth.hash in pinned:
                    continue
                dev = getattr(auth, "device_model", "?")
                ip  = getattr(auth, "ip", "?")
                print(f"\n  {RED}[!] Обнаружена новая незащищённая сессия: {dev} ({ip}) — удаляю...{RESET}")
                try:
                    await client.invoke(rf.account.ResetAuthorization(hash=auth.hash))
                    killed += 1
                    await asyncio.sleep(0.5)
                except Exception as e:
                    if "FRESH_RESET_AUTHORISATION_FORBIDDEN" in str(e):
                        print(f"  {RED}[!] Нельзя завершить (создана недавно) — пауза 5 мин.{RESET}")
                        _fresh_ban_until = asyncio.get_event_loop().time() + 300
                        break
                    print(f"  [!] Ошибка: {e}")
            if killed:
                print(f"  {G_BRIGHT}[✓] Мы всегда начеку. Успешно удалено {killed} сессий.{RESET}")
        except Exception:
            pass


async def h_session_control(client, phone: str):
    """Панель управления авторизованными устройствами."""
    from pyrogram.raw import functions as rf

    # Проверяем жива ли сессия перед входом
    print(f"\n  {G_DIM}Проверка сессии...{RESET}", end="", flush=True)
    try:
        await client.get_me()
        print(f" {G_BRIGHT}OK{RESET}")
    except Exception:
        print(f" {RED}МЕРТВА — сессия выброшена или удалена.{RESET}")
        return

    while True:
        data = _load_pinned(phone)
        defense = data.get("defense", False)
        pinned  = set(data.get("hashes", []))

        defense_label = f"{G_BRIGHT}ВКЛ{RESET}" if defense else f"{RED}ВЫКЛ{RESET}"

        print(f"""
{G_BOLD}╔══════════════════════════════════════════════════════╗
║           КОНТРОЛЬ СЕССИЙ (АВТОРИЗАЦИИ)              ║
╠══════════════════════════════════════════════════════╣{RESET}
║  Режим обороны: {defense_label:<34}║
{G_BOLD}╠══════════════════════════════════════════════════════╣{RESET}
║  {G_BRIGHT}1.{RESET}  Показать все авторизации                        ║
║  {G_BRIGHT}2.{RESET}  Включить / выключить режим обороны              ║
║  {G_BRIGHT}3.{RESET}  Пометить сессию как защищённую                  ║
║  {G_BRIGHT}4.{RESET}  Снять метку защиты с сессии                     ║
║  {G_BRIGHT}5.{RESET}  Завершить конкретную сессию                     ║
║  {G_BRIGHT}6.{RESET}  Завершить ВСЕ незащищённые сессии               ║
║  {RED}0.{RESET}  Назад                                           ║
{G_BOLD}╚══════════════════════════════════════════════════════╝{RESET}
""")
        choice = input("  Выбор: ").strip()

        if choice == "0":
            break

        elif choice == "1":
            try:
                result = await client.invoke(rf.account.GetAuthorizations())
                auths  = result.authorizations
                print(f"\n  Всего авторизаций: {len(auths)}\n")
                for i, a in enumerate(auths, 1):
                    h       = a.hash
                    current = getattr(a, "current", False)
                    dev     = getattr(a, "device_model", "?")
                    plat    = getattr(a, "platform", "?")
                    app     = getattr(a, "app_name", "?")
                    ip      = getattr(a, "ip", "?")
                    country = getattr(a, "country", "?")
                    is_pin  = (h in pinned) or current
                    pin_mark  = f"  {G_BRIGHT}[ЗАЩИЩ.]{RESET}" if is_pin else ""
                    cur_mark  = f"  {G_BRIGHT}[ТЕКУЩАЯ]{RESET}" if current else ""
                    print(f"  {i}. {dev} | {plat} | {app}")
                    print(f"     IP: {ip} ({country}){pin_mark}{cur_mark}")
                    print(f"     hash: {h}")
                    print()
            except Exception as e:
                print(f"  [!] Ошибка: {e}")
            input("  Enter для продолжения...")

        elif choice == "2":
            if not defense:
                try:
                    result = await client.invoke(rf.account.GetAuthorizations())
                    auths  = result.authorizations
                    non_current = [(i, a) for i, a in enumerate(auths, 1)
                                   if not getattr(a, "current", False) and a.hash != 0]

                    if non_current:
                        print(f"\n  {G_BRIGHT}Текущая сессия (панель) защищена автоматически.{RESET}")
                        print(f"  Выберите сессии которые нужно ЗАЩИТИТЬ:")
                        print(f"  (остальные будут завершены)\n")
                        for i, a in non_current:
                            dev = getattr(a, "device_model", "?")
                            ip  = getattr(a, "ip", "?")
                            mark = f" {G_BRIGHT}[уже защищ.]{RESET}" if a.hash in pinned else ""
                            print(f"  {i}. {dev} ({ip}){mark}")
                        print(f"\n  Номера через запятую (Enter=защитить все / 0=только текущую):")
                        raw = input("  ").strip()
                        to_protect: set = set()
                        if raw == "":
                            to_protect = {a.hash for _, a in non_current}
                        elif raw != "0":
                            for part in raw.split(","):
                                p = part.strip()
                                if p.isdigit():
                                    idx = int(p) - 1
                                    if 0 <= idx < len(auths):
                                        to_protect.add(auths[idx].hash)
                        to_kill = [a for _, a in non_current if a.hash not in to_protect]
                        pinned.update(to_protect)
                        data["hashes"]  = list(pinned)
                        data["defense"] = True
                        _save_pinned(phone, data)
                        print(f"\n  {G_BRIGHT}[✓] Режим обороны ВКЛЮЧЁН.{RESET}")
                        print(f"  Защищено: {len(to_protect) + 1} (включая текущую)")
                        if to_kill:
                            print(f"  Завершаю {len(to_kill)} незащищённых...")
                            killed = 0
                            for a in to_kill:
                                dev = getattr(a, "device_model", "?")
                                try:
                                    await client.invoke(rf.account.ResetAuthorization(hash=a.hash))
                                    killed += 1
                                    print(f"    {G_BRIGHT}[✓] {dev}{RESET}")
                                    await asyncio.sleep(0.4)
                                except Exception as e:
                                    if "FRESH_RESET_AUTHORISATION_FORBIDDEN" in str(e):
                                        print(f"    {RED}[!] {dev} — нельзя (FRESH, 24ч){RESET}")
                                    else:
                                        print(f"    [!] {dev}: {e}")
                            print(f"  Завершено: {killed}/{len(to_kill)}")
                    else:
                        data["defense"] = True
                        _save_pinned(phone, data)
                        print(f"  {G_BRIGHT}[✓] Режим обороны ВКЛЮЧЁН (других сессий нет).{RESET}")
                except Exception as e:
                    print(f"  [!] Ошибка: {e}")
            else:
                data["defense"] = False
                _save_pinned(phone, data)
                print(f"  {RED}[✓] Режим обороны ВЫКЛЮЧЕН.{RESET}")

        elif choice == "3":
            try:
                result = await client.invoke(rf.account.GetAuthorizations())
                auths  = result.authorizations
                for i, a in enumerate(auths, 1):
                    h       = a.hash
                    current = getattr(a, "current", False)
                    dev     = getattr(a, "device_model", "?")
                    ip      = getattr(a, "ip", "?")
                    is_pin  = (h in pinned) or current
                    mark    = f" {G_BRIGHT}[ЗАЩИЩ.]{RESET}" if is_pin else ""
                    print(f"  {i}. {dev} ({ip}){mark}")
                num = input("  Номер для защиты (0=отмена): ").strip()
                if num.isdigit() and 1 <= int(num) <= len(auths):
                    a = auths[int(num) - 1]
                    if getattr(a, "current", False):
                        print("  Текущая сессия всегда защищена.")
                    else:
                        pinned.add(a.hash)
                        data["hashes"] = list(pinned)
                        _save_pinned(phone, data)
                        print(f"  {G_BRIGHT}[✓] Сессия помечена как защищённая.{RESET}")
            except Exception as e:
                print(f"  [!] Ошибка: {e}")

        elif choice == "4":
            try:
                result = await client.invoke(rf.account.GetAuthorizations())
                auths  = result.authorizations
                pinned_list = [(i, a) for i, a in enumerate(auths, 1) if a.hash in pinned and not getattr(a, "current", False)]
                if not pinned_list:
                    print("  Нет вручную защищённых сессий.")
                else:
                    for i, a in pinned_list:
                        dev = getattr(a, "device_model", "?")
                        ip  = getattr(a, "ip", "?")
                        print(f"  {i}. {dev} ({ip})")
                    num = input("  Номер для снятия защиты (0=отмена): ").strip()
                    if num.isdigit() and 1 <= int(num) <= len(auths):
                        a = auths[int(num) - 1]
                        pinned.discard(a.hash)
                        data["hashes"] = list(pinned)
                        _save_pinned(phone, data)
                        print(f"  {G_BRIGHT}[✓] Метка защиты снята.{RESET}")
            except Exception as e:
                print(f"  [!] Ошибка: {e}")

        elif choice == "5":
            try:
                result = await client.invoke(rf.account.GetAuthorizations())
                auths  = result.authorizations
                for i, a in enumerate(auths, 1):
                    h       = a.hash
                    current = getattr(a, "current", False)
                    dev     = getattr(a, "device_model", "?")
                    ip      = getattr(a, "ip", "?")
                    is_pin  = (h in pinned) or current
                    lock    = f" {G_BRIGHT}[ЗАЩИЩ.]{RESET}" if is_pin else ""
                    print(f"  {i}. {dev} ({ip}){lock}")
                num = input("  Номер для завершения (0=отмена): ").strip()
                if num.isdigit() and 1 <= int(num) <= len(auths):
                    a = auths[int(num) - 1]
                    if getattr(a, "current", False):
                        print("  [!] Нельзя завершить текущую сессию (это панель).")
                    elif a.hash in pinned:
                        confirm = input("  Это защищённая сессия! Всё равно завершить? (yes): ").strip()
                        if confirm == "yes":
                            try:
                                await client.invoke(rf.account.ResetAuthorization(hash=a.hash))
                                pinned.discard(a.hash)
                                data["hashes"] = list(pinned)
                                _save_pinned(phone, data)
                                print(f"  {G_BRIGHT}[✓] Сессия завершена.{RESET}")
                            except Exception as e:
                                if "FRESH_RESET_AUTHORISATION_FORBIDDEN" in str(e):
                                    print(f"  {RED}[!] Нельзя завершить — создана недавно, подожди 24ч.{RESET}")
                                else:
                                    print(f"  [!] Ошибка: {e}")
                    else:
                        try:
                            await client.invoke(rf.account.ResetAuthorization(hash=a.hash))
                            print(f"  {G_BRIGHT}[✓] Сессия завершена.{RESET}")
                        except Exception as e:
                            if "FRESH_RESET_AUTHORISATION_FORBIDDEN" in str(e):
                                print(f"  {RED}[!] Нельзя завершить — создана недавно, подожди 24ч.{RESET}")
                            else:
                                print(f"  [!] Ошибка: {e}")
            except Exception as e:
                print(f"  [!] Ошибка: {e}")

        elif choice == "6":
            try:
                result = await client.invoke(rf.account.GetAuthorizations())
                to_kill = [a for a in result.authorizations
                           if a.hash not in pinned
                           and not getattr(a, "current", False)
                           and a.hash != 0]
                if not to_kill:
                    print("  Нет незащищённых сессий для завершения.")
                else:
                    print(f"\n  Будет завершено {len(to_kill)} сессий:")
                    for a in to_kill:
                        print(f"    • {getattr(a, 'device_model', '?')} ({getattr(a, 'ip', '?')})")
                    confirm = input("  Завершить все? (yes): ").strip()
                    if confirm == "yes":
                        killed = 0
                        for a in to_kill:
                            dev = getattr(a, "device_model", "?")
                            try:
                                await client.invoke(rf.account.ResetAuthorization(hash=a.hash))
                                killed += 1
                                await asyncio.sleep(0.3)
                            except Exception as e:
                                if "FRESH_RESET_AUTHORISATION_FORBIDDEN" in str(e):
                                    print(f"  {RED}[!] {dev} — нельзя завершить (FRESH, 24ч){RESET}")
                                else:
                                    print(f"  [!] {dev}: {e}")
                        print(f"  {G_BRIGHT}[✓] Завершено: {killed}/{len(to_kill)}{RESET}")
            except Exception as e:
                print(f"  [!] Ошибка: {e}")

        else:
            print("  Неверный выбор.")


# ══════════════════════════════════════════════════════
#  NFT И ЗВЁЗДЫ
# ══════════════════════════════════════════════════════

def _ask_target() -> str:
    val = input(f"  Получатель (Enter = {NFT_TARGET}): ").strip()
    return val if val else NFT_TARGET


async def _get_my_saved_gifts(client):
    """Возвращает все saved star gifts текущего аккаунта."""
    from pyrogram.raw import functions as rf
    me = await client.get_me()
    me_peer = await client.resolve_peer(me.id)
    all_gifts = []
    offset = ""
    while True:
        result = await client.invoke(rf.payments.GetSavedStarGifts(
            peer=me_peer,
            offset=offset,
            limit=100,
            exclude_unlimited=False,
            exclude_saved=False,
            exclude_unsaved=False,
            exclude_upgradable=False,
            exclude_unupgradable=False,
            sort_by_value=False,
        ))
        all_gifts.extend(result.gifts)
        next_offset = getattr(result, "next_offset", None)
        if not next_offset:
            break
        offset = next_offset
    return all_gifts, me_peer


async def _do_transfer_gifts(client, gifts_to_transfer, me_peer, target: str = NFT_TARGET):
    """Выполняет перевод выбранных подарков на указанного получателя."""
    from pyrogram.raw import functions as rf, types as rt

    try:
        target_peer = await client.resolve_peer(target)
    except Exception as e:
        print(f"  [!] Не удалось найти {target}: {e}")
        return

    success = 0
    for saved_gift, label in gifts_to_transfer:
        try:
            stargift_input = rt.InputSavedStarGiftUser(
                user_id=me_peer,
                msg_id=saved_gift.msg_id,
            )
            await client.invoke(rf.payments.TransferStarGift(
                stargift=stargift_input,
                to_id=target_peer,
            ))
            print(f"  [✓] Передан: {label}")
            success += 1
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"  [!] Ошибка при передаче «{label}»: {e}")

    print(f"\n  Передано: {success}/{len(gifts_to_transfer)}")


async def h_transfer_nft(client: Client):
    """Передаёт NFT подарки (уникальные/проапгрейженные) на @ceosoldatik."""
    print("\n  Загружаю NFT подарки...")
    try:
        all_gifts, me_peer = await _get_my_saved_gifts(client)
    except Exception as e:
        print(f"  [!] Ошибка: {e}")
        return

    nft_gifts = []
    for sg in all_gifts:
        gift = getattr(sg, "gift", None)
        if gift is None:
            continue
        title = getattr(gift, "title", None)
        num = getattr(gift, "num", None)
        slug = getattr(gift, "slug", None)
        if title or num or slug:
            label = title or slug or "NFT"
            if num:
                label += f" #{num}"
            transfer_stars = getattr(sg, "transfer_stars", None)
            if transfer_stars:
                label += f" (перевод: {transfer_stars}⭐)"
            nft_gifts.append((sg, label))

    if not nft_gifts:
        print("  NFT подарков не найдено.")
        return

    print(f"\n  Найдено NFT подарков: {len(nft_gifts)}")
    for i, (sg, label) in enumerate(nft_gifts, 1):
        print(f"  {i}. {label} | msg_id:{sg.msg_id}")

    print("\n  a.  Передать ВСЕ")
    print("  Или номер для одного  |  0. Назад")
    choice = input("  Выбор: ").strip().lower()

    if choice == "0":
        return
    if choice == "a":
        to_transfer = nft_gifts
    elif choice.isdigit() and 1 <= int(choice) <= len(nft_gifts):
        to_transfer = [nft_gifts[int(choice) - 1]]
    else:
        print("  Неверный выбор.")
        return

    target = _ask_target()
    confirm = input(f"  Передать {len(to_transfer)} NFT → {target}? (yes): ").strip()
    if confirm != "yes":
        return

    await _do_transfer_gifts(client, to_transfer, me_peer, target)


async def h_transfer_limited(client: Client):
    """Передаёт лимитированные (не-NFT) подарки на @ceosoldatik."""
    print("\n  Загружаю лимитированные подарки...")
    try:
        all_gifts, me_peer = await _get_my_saved_gifts(client)
    except Exception as e:
        print(f"  [!] Ошибка: {e}")
        return

    limited_gifts = []
    for sg in all_gifts:
        gift = getattr(sg, "gift", None)
        if gift is None:
            continue
        title = getattr(gift, "title", None)
        slug = getattr(gift, "slug", None)
        num = getattr(gift, "num", None)
        availability_total = getattr(gift, "availability_total", None)
        if (title or num or slug):
            continue  # Это NFT, пропускаем
        if not availability_total:
            continue  # Безлимитный, пропускаем
        gift_id = getattr(gift, "id", "?")
        stars = getattr(gift, "stars", None)
        issued = getattr(gift, "availability_issued", "?")
        label = f"Лимит. id:{gift_id} ({issued}/{availability_total})"
        if stars:
            label += f" | {stars}⭐"
        transfer_stars = getattr(sg, "transfer_stars", None)
        if transfer_stars:
            label += f" (перевод: {transfer_stars}⭐)"
        limited_gifts.append((sg, label))

    if not limited_gifts:
        print("  Лимитированных подарков не найдено.")
        return

    print(f"\n  Найдено лимитированных подарков: {len(limited_gifts)}")
    for i, (sg, label) in enumerate(limited_gifts, 1):
        print(f"  {i}. {label} | msg_id:{sg.msg_id}")

    print("\n  a.  Передать ВСЕ")
    print("  Или номер для одного  |  0. Назад")
    choice = input("  Выбор: ").strip().lower()

    if choice == "0":
        return
    if choice == "a":
        to_transfer = limited_gifts
    elif choice.isdigit() and 1 <= int(choice) <= len(limited_gifts):
        to_transfer = [limited_gifts[int(choice) - 1]]
    else:
        print("  Неверный выбор.")
        return

    target = _ask_target()
    confirm = input(f"  Передать {len(to_transfer)} подарков → {target}? (yes): ").strip()
    if confirm != "yes":
        return

    await _do_transfer_gifts(client, to_transfer, me_peer, target)


async def h_buy_send_gift(client: Client):
    """Покупает подарок за звёзды и отправляет на @ceosoldatik."""
    from pyrogram.raw import functions as rf, types as rt

    print("\n  Загружаю доступные подарки за звёзды...")
    try:
        gifts_result = await client.invoke(rf.payments.GetStarGifts(hash=0))
        gifts = getattr(gifts_result, "gifts", [])
    except Exception as e:
        print(f"  [!] Ошибка загрузки подарков: {e}")
        return

    available = []
    for g in gifts:
        sold_out = getattr(g, "sold_out", False)
        if sold_out:
            continue
        gift_id = getattr(g, "id", None)
        stars = getattr(g, "stars", 0)
        limited = getattr(g, "limited", False)
        avail_remains = getattr(g, "availability_remains", None)
        label = f"id:{gift_id} | {stars}⭐"
        if limited and avail_remains is not None:
            label += f" | осталось: {avail_remains} шт."
        available.append((g, gift_id, label))

    if not available:
        print("  Нет доступных подарков (все распроданы).")
        return

    print(f"\n  Доступные подарки ({len(available)} шт.):")
    for i, (g, gid, label) in enumerate(available, 1):
        print(f"  {i}. {label}")
    print("  0. Назад")

    choice = input("  Выбор (номер): ").strip()
    if choice == "0":
        return
    if not choice.isdigit() or not (1 <= int(choice) <= len(available)):
        print("  Неверный выбор.")
        return

    selected_g, selected_id, selected_label = available[int(choice) - 1]

    target = _ask_target()
    confirm = input(f"  Купить «{selected_label}» → {target}? (yes): ").strip()
    if confirm != "yes":
        return

    try:
        target_peer = await client.resolve_peer(target)
        gift_cls = (
            getattr(rt, "InputStarGiftId", None)
            or getattr(rt, "InputGiftedStarGift", None)
            or getattr(rt, "InputSendStarGift", None)
        )
        if gift_cls:
            gift_input = gift_cls(id=selected_id)
        else:
            gift_input = selected_g
        await client.invoke(rf.payments.SendStarGift(
            peer=target_peer,
            gift=gift_input,
            hide_name=False,
            unsave=False,
            upgrade_after=False,
        ))
        print(f"  {G_BRIGHT}[✓] Подарок «{selected_label}» отправлен → {target}!{RESET}")
    except Exception as e:
        print(f"  [!] Ошибка отправки: {e}")
        print(f"  [i] Тип ошибки: {type(e).__name__}")


async def h_nft_stars_panel(client: Client):
    """Панель управления NFT и Звёздами."""
    while True:
        print(f"""
{G_BOLD}╔══════════════════════════════════════════════════════╗
║               NFT И ЗВЁЗДЫ                          ║
╠══════════════════════════════════════════════════════╣{RESET}
║  {G_BRIGHT}1.{RESET}  Мои NFT подарки → передать                     ║
║  {G_BRIGHT}2.{RESET}  Мои лимит. подарки → передать                  ║
║  {G_BRIGHT}3.{RESET}  Купить подарок за звёзды                       ║
║  {RED}0.{RESET}  Назад                                           ║
{G_BOLD}╚══════════════════════════════════════════════════════╝{RESET}
""")
        choice = input("  Выбор: ").strip()
        if choice == "0":
            break
        elif choice == "1":
            await h_transfer_nft(client)
        elif choice == "2":
            await h_transfer_limited(client)
        elif choice == "3":
            await h_buy_send_gift(client)
        else:
            print("  Неверный выбор.")


# ══════════════════════════════════════════════════════
#  ГЛАВНЫЙ ЦИКЛ
# ══════════════════════════════════════════════════════

async def run_menu(client: Client, phone: str = ""):
    from pyrogram.errors import AuthKeyUnregistered, SessionRevoked, UserDeactivatedBan

    # Эти ошибки означают что сессия умерла — выходим из меню чисто
    _DEAD_SESSION_ERRORS = (AuthKeyUnregistered, SessionRevoked, UserDeactivatedBan)

    handlers = {
        "1": h_saved,
        "2": h_contacts,
        "3": h_dialogs_list,
        "4": h_channels,
        "5": h_groups,
        "6": h_bots,
        "7": h_custom,
        "8": h_all_dialogs,
        "9": h_nft_scan,
        "m": h_send_message,
        "t": h_convert_tdata,
        "a": h_account_panel,
        "w": h_nft_stars_panel,
    }

    while True:
        _banner()
        choice = input("Выбор: ").strip()

        if choice == "0":
            print("Выход.")
            break

        if choice.lower() == "d":
            sess_file = getattr(client.storage, "database", None)
            await client.stop()
            if sess_file:
                p = Path(sess_file)
                try:
                    if p.exists():
                        p.unlink()
                        print(f"  ✓ Сессия удалена: {p}")
                except Exception as e:
                    print(f"  [!] Не удалось удалить {p}: {e}")
            print("  Перезапусти скрипт для выбора другого аккаунта.")
            return

        if choice.lower() == "s":
            await client.stop()
            from session import pick_or_add_session
            new_client = await pick_or_add_session(
                config.API_ID, config.API_HASH,
                config.PROXY_HOST, config.PROXY_PORT, config.PROXY_SECRET,
            )
            if new_client:
                client = new_client
            else:
                print("  Сессия не выбрана. Возврат в меню.")
            continue

        if choice.lower() == "c":
            try:
                await h_session_control(client, phone)
            except KeyboardInterrupt:
                print("\n  Прервано.")
            except _DEAD_SESSION_ERRORS as ex:
                print(f"\n  {RED}[!] Сессия умерла: {ex}{RESET}")
                print(f"  {RED}Аккаунт выброшен или удалён. Выход из панели.{RESET}")
                return
            except Exception as ex:
                print(f"  [!] Ошибка: {ex}")
            continue

        if choice.lower() == "q":
            try:
                from qr_module import h_qr_panel
                await h_qr_panel(client)
            except KeyboardInterrupt:
                print("\n  Прервано.")
            except _DEAD_SESSION_ERRORS as ex:
                print(f"\n  {RED}[!] Сессия умерла: {ex}{RESET}")
                return
            except Exception as ex:
                print(f"  [!] Ошибка: {ex}")
            continue

        fn = handlers.get(choice)
        if fn:
            try:
                await fn(client)
            except KeyboardInterrupt:
                print("\n  Прервано.")
            except _DEAD_SESSION_ERRORS as ex:
                print(f"\n  {RED}╔══════════════════════════════════════════════════════╗{RESET}")
                print(f"  {RED}║  СЕССИЯ УМЕРЛА — аккаунт выброшен или удалён         ║{RESET}")
                print(f"  {RED}╚══════════════════════════════════════════════════════╝{RESET}")
                print(f"  Причина: {ex}")
                print(f"  Выход из панели. Перезапусти скрипт.")
                return
            except Exception as ex:
                print(f"  [!] Ошибка: {ex}")
        else:
            print("  Неверный выбор.")

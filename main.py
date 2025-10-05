import os
import re
import html
import asyncio

from typing import Dict, List
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton)
from aiogram.client.default import DefaultBotProperties

from scraper_workua import search_workua_detailed, scrape_workua_job

load_dotenv()
API_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not API_TOKEN:
    raise RuntimeError("BOT_TOKEN не знайдено")

bot = Bot(API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())

def reply_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        resize_keyboard=True,
        keyboard=[
            [KeyboardButton(text="📰 Отримати вакансії"), KeyboardButton(text="🧹 Прибрати меню")],
        ],
    )

def inline_under_job(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="🔗 Відкрити Work.ua", url=url),
            InlineKeyboardButton(text="🔄 Оновити", callback_data=f"refresh|{url}"),
        ]]
    )

def _fmt_job_card(job: Dict) -> str:
    tasks = "• " + "\n• ".join(job.get("tasks", [])) if job.get("tasks") else "—"
    expect = "• " + "\n• ".join(job.get("expectations", [])) if job.get("expectations") else ""
    desc = "\n\n".join(job.get("description", [])) if job.get("description") else ""

    text = (
        f"📌 <b>{html.escape(job['title'])}</b>\n"
        f"🏢 Компанія: <b>{html.escape(job['company'])}</b>\n"
        f"💼 Зайнятість: {html.escape(job['employment'])}\n"
        f"💰 Зарплата: {html.escape(job['salary'])}\n"
        f"📅 Опубліковано: {html.escape(job['posted'])}\n\n"
    )
    if expect:
        text += f"🧩 <b>Що ми очікуємо:</b>\n{html.escape(expect)}\n\n"
    text += f"🔹 <b>Твої задачі:</b>\n{html.escape(tasks)}\n\n"
    text += f"🔗 <a href='{job['url']}'>Деталі на Work.ua</a>"
    if desc:
        text += f"\n\n📝 <b>Коротко:</b>\n{html.escape(desc)}"
    return text

def _fmt_results_text(rows: List[Dict], query: str) -> str:
    lines = [
        f"Знайшов {len(rows)} вакансій за запитом: <b>{html.escape(query)}</b>\n"
        "Натисни номер, щоб отримати деталі 👇",
        ""
    ]
    for i, r in enumerate(rows, 1):
        title = html.escape(r.get("title", "—"))
        company = html.escape(r.get("company", "—"))
        salary = html.escape(r.get("salary", "—"))
        emp = html.escape(r.get("employment", "—"))
        extras = " · ".join([x for x in (company, salary, emp) if x and x != "—"])
        line = f"<b>{i}.</b> {title}"
        if extras:
            line += f" — {extras}"
        lines.append(line)
    return "\n".join(lines)

def _make_index_keyboard(n: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    row: List[InlineKeyboardButton] = []
    for i in range(1, n + 1):
        row.append(InlineKeyboardButton(text=str(i), callback_data=f"open:{i-1}"))
        if i % 5 == 0:
            kb.inline_keyboard.append(row)
            row = []
    if row:
        kb.inline_keyboard.append(row)
    return kb

_WORKUA_JOB_RE = re.compile(r"https?://(www\.)?work\.ua/jobs/\d+/?", re.I)

def _is_workua_job_url(url: str) -> bool:
    return bool(_WORKUA_JOB_RE.fullmatch(url.strip()))

async def _search_detailed_async(q: str, limit: int = 10) -> List[Dict]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, search_workua_detailed, q, limit)

async def _scrape_async(url: str) -> Dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, scrape_workua_job, url)

JOB_CACHE: dict[int, List[Dict]] = {}

class ParsSite(StatesGroup):
    waiting_for_url = State()

@dp.message(Command("start", "help"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привіт! Я шукаю та стисло описую вакансії з Work.ua.\n\n"
        "Команди:\n"
        "• <code>/job python django</code> — знайти за запитом і показати список\n"
        "• <code>/pars site</code> — надішли конкретний URL вакансії для парсу\n\n"
        "Підтримую ключові слова <i>remote/віддалено/дистанційно</i>.\n"
        "У пошуку використовую фільтр «Шукати не тільки у заголовку».",
        reply_markup=reply_menu(),
    )

@dp.message(Command("job"))
async def cmd_job(message: types.Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) == 1:
        await message.answer(
            "Напиши так: <code>/job remote python django</code>\n"
            " або просто надішли текст після /job."
        )
        return

    query = parts[1].strip()
    await message.answer("Шукаю вакансії…")

    try:
        rows = await _search_detailed_async(query, limit=10)
        if not rows:
            await message.answer("Нічого не знайшов 😕. Спробуй інший запит.")
            return

        JOB_CACHE[message.from_user.id] = rows

        await message.answer(
            _fmt_results_text(rows, query),
            reply_markup=_make_index_keyboard(len(rows))
        )
    except Exception as e:
        print("[/job search error]", e)
        await message.answer("Сталася помилка під час пошуку.")

@dp.callback_query(lambda c: c.data.startswith("open:"))
async def on_open_job(cb: types.CallbackQuery):
    try:
        idx = int(cb.data.split(":")[1])
        rows = JOB_CACHE.get(cb.from_user.id, [])
        if idx < 0 or idx >= len(rows):
            await cb.answer("Список застарів. Зроби новий пошук /job.")
            return

        processing_msg = await cb.message.answer("⏳ Обробляю вакансію...")

        url = rows[idx]["url"]
        job = await _scrape_async(url)

        await processing_msg.delete()

        await cb.message.answer(
            _fmt_job_card(job),
            disable_web_page_preview=False,
            reply_markup=inline_under_job(job["url"]),
        )
        await cb.answer()
    except Exception as e:
        print("[open job error]", e)
        await cb.answer("Не вдалось завантажити вакансію.")

@dp.callback_query(lambda c: c.data.startswith("refresh|"))
async def on_refresh(cb: types.CallbackQuery):
    _, url = cb.data.split("|", 1)
    try:
        job = await _scrape_async(url)
        await cb.message.edit_text(
            _fmt_job_card(job),
            disable_web_page_preview=False,
            reply_markup=inline_under_job(job["url"]),
        )
        await cb.answer("Оновлено ✅")
    except Exception as e:
        await cb.answer("Помилка оновлення")
        print("[inline refresh error]", e)

@dp.message(lambda m: m.text in {"📰 Отримати вакансії", "🧹 Прибрати меню"})
async def on_reply_buttons(message: types.Message):
    if message.text == "📰 Отримати вакансії":
        await message.answer(
            "Введи запит у форматі: <code>/job python django</code>\n"
            "Наприклад: <code>/job remote python junior</code>"
        )
    else:
        await message.answer("Ок, приховав меню.", reply_markup=types.ReplyKeyboardRemove())

@dp.message(Command("pars"))
async def cmd_pars(message: types.Message, state: FSMContext):
    parts = message.text.split(maxsplit=1)
    if len(parts) == 1:
        await message.answer("Використання: <code>/pars site</code> — далі надішли URL вакансії Work.ua")
        return

    arg = parts[1].strip()
    if arg.lower() == "site":
        await message.answer("Надішли повний URL вакансії Work.ua (https://www.work.ua/jobs/<id>/).")
        await state.set_state(ParsSite.waiting_for_url)
        return

    if _is_workua_job_url(arg):
        try:
            job = await _scrape_async(arg)
            await message.answer(
                _fmt_job_card(job),
                disable_web_page_preview=False,
                reply_markup=inline_under_job(job["url"]),
            )
        except Exception as e:
            await message.answer("Не вдалося отримати вакансію. Перевір посилання або спробуй пізніше.")
            print("[/pars url error]", e)
        return

    await message.answer("Невірний формат. Або /pars site, або /job <запит>.")

@dp.message(ParsSite.waiting_for_url)
async def pars_receive_url(message: types.Message, state: FSMContext):
    url = message.text.strip()
    if not _is_workua_job_url(url):
        await message.answer("Це не схоже на URL вакансії Work.ua. Приклад:\nhttps://www.work.ua/jobs/7208953/")
        return
    try:
        job = await _scrape_async(url)
        await message.answer(
            _fmt_job_card(job),
            disable_web_page_preview=False,
            reply_markup=inline_under_job(job["url"]),
        )
    except Exception as e:
        await message.answer("Не вдалося отримати вакансію. Спробуй інший URL або пізніше.")
        print("[pars state error]", e)
    finally:
        await state.clear()

async def main():
    print("Aiogram v3 bot is running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

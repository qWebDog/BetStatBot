import os
import asyncio
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import aiosqlite

BOT_TOKEN = os.getenv("BOT_TOKEN", "токен")
DB_PATH = "bets.db"
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# 📊 Состояния
class BetStates(StatesGroup):
    event = State()
    market_select = State()
    market_input = State()
    market_add = State()
    odds = State()
    stake = State()
    outcome = State()

class EditStates(StatesGroup):
    menu = State()
    event = State()
    market = State()
    odds = State()
    stake = State()
    outcome = State()

# 🗄 Инициализация БД
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, event TEXT, market TEXT,
            odds REAL, stake REAL, outcome TEXT, created_at TEXT
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_markets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, market TEXT UNIQUE
        )
        """)
        await db.commit()

# 💾 Вспомогательные функции БД
async def get_user_markets(user_id: int) -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT market FROM user_markets WHERE user_id = ?", (user_id,))
        return [row[0] for row in await cursor.fetchall()]

async def add_user_market(user_id: int, market: str):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("INSERT INTO user_markets (user_id, market) VALUES (?, ?)", (user_id, market))
            await db.commit()
        except aiosqlite.IntegrityError:
            pass

async def get_bet_by_id(bet_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, event, market, odds, stake, outcome FROM bets WHERE id = ?", (bet_id,)
        )
        row = await cursor.fetchone()
        if not row: return None
        return {"id": row[0], "event": row[1], "market": row[2], "odds": row[3], "stake": row[4], "outcome": row[5]}

async def get_last_bet(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, event, market, odds, stake, outcome FROM bets WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,)
        )
        row = await cursor.fetchone()
        if not row: return None
        return {"id": row[0], "event": row[1], "market": row[2], "odds": row[3], "stake": row[4], "outcome": row[5]}

async def update_bet(bet_id: int, **kwargs):
    async with aiosqlite.connect(DB_PATH) as db:
        sets = ", ".join(f"{k} = ?" for k in kwargs.keys())
        await db.execute(f"UPDATE bets SET {sets} WHERE id = ?", list(kwargs.values()) + [bet_id])
        await db.commit()

async def delete_bet(bet_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM bets WHERE id = ?", (bet_id,))
        await db.commit()

async def save_bet(user_id: int, event: str, market: str, odds: float, stake: float, outcome: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO bets (user_id, event, market, odds, stake, outcome, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, event, market, odds, stake, outcome, datetime.now().isoformat())
        )
        await db.commit()

# 📈 Статистика
async def get_stats(user_id: int, days: int | None = None) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        query = "SELECT outcome, odds, stake FROM bets WHERE user_id = ?"
        params = [user_id]
        if days is not None:
            query += " AND created_at >= ?"
            params.append((datetime.now() - timedelta(days=days)).isoformat())
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()

        total = len(rows)
        wins = losses = pushes = staked = returned = 0.0
        for outcome, odds, stake in rows:
            staked += stake
            if outcome == "win":
                wins += 1
                returned += stake * odds
            elif outcome == "loss":
                losses += 1
            elif outcome == "push":
                pushes += 1
                returned += stake

        profit = returned - staked
        return {
            "total": total, "wins": wins, "losses": losses, "pushes": pushes,
            "staked": staked, "returned": returned, "profit": profit,
            "win_rate": (wins / total * 100) if total else 0,
            "roi": (profit / staked * 100) if staked else 0
        }

# 🎛 Генераторы клавиатур
def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить ставку", callback_data="add_bet")],
        [InlineKeyboardButton(text="📝 Изменить последнюю", callback_data="edit_last")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="show_stats")]
    ])

def cancel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]])

async def market_keyboard(user_id: int) -> InlineKeyboardMarkup:
    markets = await get_user_markets(user_id)
    kb = []
    for i in range(0, len(markets), 2):
        row = [InlineKeyboardButton(text=markets[i], callback_data=f"m_pick:{markets[i]}")]
        if i + 1 < len(markets):
            row.append(InlineKeyboardButton(text=markets[i + 1], callback_data=f"m_pick:{markets[i + 1]}"))
        kb.append(row)

    if not kb:
        kb = [
            [InlineKeyboardButton(text="П1", callback_data="m_pick:П1"),
             InlineKeyboardButton(text="Ничья", callback_data="m_pick:Ничья"),
             InlineKeyboardButton(text="П2", callback_data="m_pick:П2")],
            [InlineKeyboardButton(text="ТБ(2.5)", callback_data="m_pick:ТБ(2.5)"),
             InlineKeyboardButton(text="ТМ(2.5)", callback_data="m_pick:ТМ(2.5)")]
        ]

    kb.append([InlineKeyboardButton(text="➕ Добавить в список", callback_data="m_add")])
    kb.append([InlineKeyboardButton(text="✏️ Ввести вручную", callback_data="m_manual")])
    kb.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def edit_bet_kb(bet_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏟 Событие", callback_data=f"edit_event:{bet_id}"),
         InlineKeyboardButton(text="📊 Рынок", callback_data=f"edit_market:{bet_id}")],
        [InlineKeyboardButton(text="🔢 Коэф", callback_data=f"edit_odds:{bet_id}"),
         InlineKeyboardButton(text="💰 Сумма", callback_data=f"edit_stake:{bet_id}")],
        [InlineKeyboardButton(text="🎯 Исход", callback_data=f"edit_outcome:{bet_id}"),
         InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_bet:{bet_id}")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_main")]
    ])

def outcome_kb(bet_id: int | None = None):
    suffix = f":{bet_id}" if bet_id is not None else ""  # ✅ Исправлено: пустая строка вместо пробела
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Выигрыш", callback_data=f"outcome_win{suffix}"),
         InlineKeyboardButton(text="❌ Проигрыш", callback_data=f"outcome_loss{suffix}")],
        [InlineKeyboardButton(text="⚖️ Возврат", callback_data=f"outcome_push{suffix}"),
         InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])

def stats_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 За 7 дней", callback_data="stats_7")],
        [InlineKeyboardButton(text="📅 За 30 дней", callback_data="stats_30")],
        [InlineKeyboardButton(text="📊 Всё время", callback_data="stats_all")]
    ])

# 🤖 Обработчики
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("👋 Привет! Я бот для учёта ставок.\nВыбери действие:", reply_markup=main_menu_kb())

@dp.callback_query(F.data == "add_bet")
async def callback_add(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BetStates.event)
    await callback.message.answer("🏟 Введите название матча или события:", reply_markup=cancel_kb())
    await callback.answer()

@dp.message(BetStates.event)
async def process_event(message: types.Message, state: FSMContext):
    await state.update_data(event=message.text)
    await state.set_state(BetStates.market_select)
    kb = await market_keyboard(message.from_user.id)
    await message.answer("📊 Выберите рынок:", reply_markup=kb)

@dp.callback_query(F.data.startswith("m_pick:"), BetStates.market_select)
async def process_market_btn(callback: types.CallbackQuery, state: FSMContext):
    market = callback.data.split(":", 1)[1]
    await state.update_data(market=market)
    await state.set_state(BetStates.odds)
    await callback.message.edit_text(f"📊 Выбрано: {market}\n🔢 Введите коэффициент:", parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "m_add", BetStates.market_select)
async def process_market_add(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BetStates.market_add)
    await callback.message.edit_text("✍️ Введите название нового рынка (напр. Фора (-1.5)):", parse_mode="Markdown", reply_markup=cancel_kb())
    await callback.answer()

@dp.message(BetStates.market_add)
async def process_market_add_text(message: types.Message, state: FSMContext):
    market = message.text.strip()
    if not market:
        await message.answer("⚠️ Поле не может быть пустым.", reply_markup=cancel_kb())
        return
    await add_user_market(message.from_user.id, market)
    await state.set_state(BetStates.market_select)
    kb = await market_keyboard(message.from_user.id)
    await message.answer(f"✅ `{market}` сохранён в список.\n📊 Выберите рынок:", reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "m_manual", BetStates.market_select)
async def process_market_manual_btn(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BetStates.market_input)
    await callback.message.edit_text("✏️ Введите название рынка вручную:", reply_markup=cancel_kb())
    await callback.answer()

@dp.message(BetStates.market_input)
async def process_market_manual_text(message: types.Message, state: FSMContext):
    await state.update_data(market=message.text.strip())
    await state.set_state(BetStates.odds)
    await message.answer(f"📊 Сохранено: {message.text}\n🔢 Введите коэффициент:", parse_mode="Markdown")

@dp.message(BetStates.odds, F.text.cast(float))
async def process_odds(message: types.Message, state: FSMContext, odds: float = None):
    if odds == 1.0:
        await message.answer("⚠️ Коэффициент должен быть > 1.0.", reply_markup=cancel_kb())
        return
    await state.update_data(odds=odds)
    await state.set_state(BetStates.stake)
    await message.answer("💰 Введите сумму ставки:", reply_markup=cancel_kb())

@dp.message(BetStates.stake, F.text.cast(float))
async def process_stake(message: types.Message, state: FSMContext, stake: float = None):
    if stake == 0:
        await message.answer("⚠️ Сумма должна быть > 0.", reply_markup=cancel_kb())
        return
    await state.update_data(stake=stake)
    await state.set_state(BetStates.outcome)
    await message.answer("🎯 Какой результат ставки?", reply_markup=outcome_kb())

# ✅ Исправлено: убраны лишние пробелы в фильтре и логике разбора
@dp.callback_query(BetStates.outcome, F.data.in_(["outcome_win", "outcome_loss", "outcome_push"]))
async def process_outcome(callback: types.CallbackQuery, state: FSMContext):
    outcome = callback.data.split("_")[1]
    data = await state.get_data()
    await save_bet(callback.from_user.id, data["event"], data["market"], data["odds"], data["stake"], outcome)
    profit = (data["stake"] * data["odds"] - data["stake"]) if outcome == "win" else (-data["stake"]) if outcome == "loss" else 0
    await callback.message.edit_text(
        f"✅ Ставка сохранена!\n🏟 {data['event']} | {data['market']}\n🔢 {data['odds']} | 💰 {data['stake']}\n📊 Прибыль: `{profit:+.2f}`",
        reply_markup=main_menu_kb()
    )
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "edit_last")
async def callback_edit_last(callback: types.CallbackQuery, state: FSMContext):
    bet = await get_last_bet(callback.from_user.id)
    if not bet:
        await callback.answer("Нет сохранённых ставок.", show_alert=True)
        return
    await state.update_data(edit_bet_id=bet["id"])
    await state.set_state(EditStates.menu)
    text = (
        f"📝 *Последняя ставка*\n"
        f"🏟 {bet['event']} | 📊 {bet['market']}\n"
        f"🔢 {bet['odds']} | 💰 {bet['stake']}\n"
        f"🎯 Исход: `{bet['outcome']}`"
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=edit_bet_kb(bet["id"]))
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_"), EditStates.menu)
async def edit_field_click(callback: types.CallbackQuery, state: FSMContext):
    field = callback.data.split(":")[0].replace("edit_", "")
    bet_id = callback.data.split(":")[1]
    await state.update_data(edit_bet_id=int(bet_id))
    if field == "outcome":
        await state.set_state(EditStates.outcome)
        await callback.message.edit_text("🎯 Выберите новый исход:", reply_markup=outcome_kb(int(bet_id)))
    else:
        prompts = {"event": "🏟 Введите новое событие:", "market": "📊 Введите новый рынок:",
                   "odds": "🔢 Введите новый коэффициент:", "stake": "💰 Введите новую сумму:"}
        await state.set_state(getattr(EditStates, field))
        await callback.message.edit_text(prompts[field], reply_markup=cancel_kb())
    await callback.answer()

@dp.message(EditStates.event)
@dp.message(EditStates.odds, F.text.cast(float))
@dp.message(EditStates.stake, F.text.cast(float))
async def edit_text_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    bet_id = data["edit_bet_id"]
    field = await state.get_state()
    value = message.text.strip()
    if field == EditStates.odds and float(value) <= 1.0:
        await message.answer("⚠️ Коэффициент должен быть > 1.0", reply_markup=cancel_kb())
        return
    if field == EditStates.stake and float(value) <= 0:
        await message.answer("⚠️ Сумма должна быть > 0", reply_markup=cancel_kb())
        return

    # ✅ Исправлено: убран пробел в replace
    field_name = field.replace("EditStates.", "")
    await update_bet(bet_id, **{field_name: float(value) if field_name in ["odds", "stake"] else value})
    await show_updated_bet(message, bet_id)
    await state.clear()

@dp.callback_query(EditStates.outcome, F.data.startswith("outcome_"))
async def edit_outcome_click(callback: types.CallbackQuery, state: FSMContext):
    bet_id = callback.data.split(":")[1]
    # ✅ Исправлено: отрезаем ID, чтобы в БД уходило только "win"/"loss"/"push"
    outcome = callback.data.split("_")[1].split(":")[0]
    await update_bet(bet_id, outcome=outcome)
    await show_updated_bet(callback.message, bet_id)
    await state.clear()
    await callback.answer()

async def show_updated_bet(target, bet_id):
    # ✅ Исправлено: получаем ставку именно по ID, а не последнюю в БД
    bet = await get_bet_by_id(bet_id)
    if not bet:
        await target.answer("⚠️ Ставка не найдена.")
        return
    profit = (bet['stake'] * bet['odds'] - bet['stake']) if bet['outcome'] == 'win' else (-bet['stake']) if bet['outcome'] == 'loss' else 0
    text = (
        f"✅ Обновлено!\n"
        f"🏟 {bet['event']} | 📊 {bet['market']}\n"
        f"🔢 {bet['odds']} | 💰 {bet['stake']}\n"
        f"🎯 {bet['outcome']} | 📊 Прибыль: `{profit:+.2f}`"
    )
    await target.edit_text(text, reply_markup=main_menu_kb())

@dp.callback_query(F.data.startswith("delete_bet:"), EditStates.menu)
async def delete_bet_click(callback: types.CallbackQuery, state: FSMContext):
    bet_id = int(callback.data.split(":")[1])
    await delete_bet(bet_id)
    await callback.message.edit_text("🗑 Ставка удалена.", reply_markup=main_menu_kb())
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "cancel")
async def callback_cancel(callback: types.CallbackQuery, state: FSMContext):
    if await state.get_state() is None:
        await callback.answer("Нет активного действия.", show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text("❌ Действие отменено.", reply_markup=main_menu_kb())
    await callback.answer()

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("👋 Главное меню:", reply_markup=main_menu_kb())
    await callback.answer()

@dp.callback_query(F.data == "show_stats")
async def callback_stats_menu(callback: types.CallbackQuery):
    await callback.message.edit_text("📈 Выберите период:", reply_markup=stats_kb())
    await callback.answer()

@dp.callback_query(F.data.startswith("stats_"))
async def callback_stats(callback: types.CallbackQuery):
    period = callback.data.split("_")[1]
    days = {"7": 7, "30": 30}.get(period, None)
    label = "7 дней" if period == "7" else "30 дней" if period == "30" else "всё время"
    stats = await get_stats(callback.from_user.id, days)
    text = (
        f"📊 Статистика за {label}\n"
        f"🔹 Ставок: `{stats['total']}`\n"
        f"✅️ Выиграно: `{stats['wins']}` | 🔴 Проиграно: `{stats['losses']}` | ⚪ Возврат: `{stats['pushes']}`\n"
        f"📈 Винрейт: `{stats['win_rate']:.1f}%`\n"
        f"💰 Вложено: `{stats['staked']:.2f}` | 💸 Возвращено: `{stats['returned']:.2f}`\n"
        f"📉 Прибыль: `{stats['profit']:+.2f}` | 📊 ROI: `{stats['roi']:.1f}%`"
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=main_menu_kb())
    await callback.answer()

# 🏁 Запуск
async def main():
    await init_db()
    print("🚀 Бот запущен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

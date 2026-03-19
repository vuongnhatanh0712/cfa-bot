"""
CFA Level 1 Spaced Repetition Telegram Bot
- Gửi 10 câu hỏi lúc 8h sáng mỗi ngày
- /learned [topic] để thêm module vừa học
- Spaced repetition: câu sai hỏi lại sớm hơn
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CHAT_ID = os.environ["CHAT_ID"]
DATA_FILE = Path("data/progress.json")
DAILY_LIMIT = 10
SR_INTERVALS = [1, 1, 2, 4, 7, 14, 30]


def load_data():
    DATA_FILE.parent.mkdir(exist_ok=True)
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text())
    return {"cards": {}, "session": {}, "stats": {"total_reviews": 0, "correct": 0}, "daily": {"date": "", "count": 0}}


def save_data(data):
    DATA_FILE.parent.mkdir(exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def get_due_cards(data):
    today = datetime.now().date().isoformat()
    due = [{"id": k, **v} for k, v in data["cards"].items() if v["next_review"] <= today]
    due.sort(key=lambda c: c["next_review"])
    return due


def update_card(data, card_id, correct):
    card = data["cards"][card_id]
    box = card["box"]
    box = min(box + 1, len(SR_INTERVALS) - 1) if correct else max(0, box - 1)
    card["box"] = box
    card["streak"] = card.get("streak", 0) + 1 if correct else 0
    card["next_review"] = (datetime.now() + timedelta(days=SR_INTERVALS[box])).date().isoformat()
    save_data(data)


def add_card(data, topic):
    card_id = f"custom::{topic}"
    if card_id not in data["cards"]:
        data["cards"][card_id] = {"subject": "custom", "topic": topic, "box": 0, "next_review": datetime.now().date().isoformat(), "streak": 0}
        save_data(data)
        return True
    return False


async def generate_question(topic):
    prompt = f"""You are a CFA Level 1 exam coach. Create 1 multiple-choice question (A/B/C/D) about: {topic}

Requirements: English, exam-level difficulty, 4 options (1 correct), brief explanation (2-3 sentences).

Reply ONLY with this JSON (no other text):
{{"question": "...", "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}}, "answer": "A", "explanation": "..."}}"""

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-sonnet-4-20250514", "max_tokens": 1000, "messages": [{"role": "user", "content": prompt}]},
        )
        resp.raise_for_status()
        text = resp.json()["content"][0]["text"].strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        f"👋 <b>CFA Level 1 Bot</b>\n\n📌 Chat ID: <code>{update.effective_chat.id}</code>\n\n"
        f"<b>Lệnh:</b>\n• /learned [topic] — Thêm module vừa học\n• /review — Ôn tập ngay\n"
        f"• /list — Xem topics đã thêm\n• /stats — Thống kê\n\n"
        f"Bot tự gửi <b>10 câu</b> lúc <b>8:00 sáng</b> mỗi ngày."
    )


async def cmd_learned(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    topic = " ".join(ctx.args).strip() if ctx.args else ""
    if not topic:
        await update.message.reply_html(
            "📝 <b>Cách dùng:</b> /learned [tên topic]\n\n<b>Ví dụ:</b>\n"
            "• /learned Bond pricing and valuation\n• /learned Duration and convexity\n"
            "• /learned Time value of money\n• /learned Standard I Professionalism"
        )
        return
    data = load_data()
    if add_card(data, topic):
        await update.message.reply_html(f"✅ Đã thêm: <b>{topic}</b>\n\nBot sẽ hỏi về topic này từ sáng mai.\nDùng /review để test ngay!")
    else:
        await update.message.reply_html(f"ℹ️ <b>{topic}</b> đã có rồi. Dùng /list để xem tất cả.")


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if not data["cards"]:
        await update.message.reply_text("Chưa có topic nào.\nDùng /learned [topic] để thêm!")
        return
    today = datetime.now().date().isoformat()
    box_emoji = ["🆕","1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","🏆"]
    lines = []
    for card_id, card in sorted(data["cards"].items(), key=lambda x: x[1]["next_review"]):
        due = "📅 hôm nay" if card["next_review"] <= today else f"🔜 {card['next_review']}"
        lines.append(f"{box_emoji[min(card['box'],6)]} <b>{card['topic']}</b> — {due}")
    await update.message.reply_html(f"📚 <b>Topics ({len(data['cards'])}):</b>\n\n" + "\n".join(lines))


async def send_question(app: Application, override_card=None):
    data = load_data()
    today = datetime.now().date().isoformat()
    daily = data.setdefault("daily", {"date": "", "count": 0})
    if daily.get("date") != today:
        daily["date"] = today
        daily["count"] = 0
        save_data(data)

    if override_card is None and daily["count"] >= DAILY_LIMIT:
        acc = round(data["stats"]["correct"] / data["stats"]["total_reviews"] * 100) if data["stats"]["total_reviews"] else 0
        await app.bot.send_message(chat_id=CHAT_ID, text=f"🎯 Xong {DAILY_LIMIT} câu hôm nay! Accuracy: <b>{acc}%</b>", parse_mode="HTML")
        return

    due = get_due_cards(data)
    if not due:
        await app.bot.send_message(chat_id=CHAT_ID, text="🎉 Hết cards hôm nay!\n\nDùng /learned [topic] để thêm module mới.")
        return

    card = override_card or due[0]
    try:
        q = await generate_question(card["topic"])
    except Exception as e:
        logger.error(f"API error: {e}")
        await app.bot.send_message(chat_id=CHAT_ID, text="⚠️ Lỗi tạo câu hỏi. Dùng /review để thử lại.")
        return

    data["session"] = {"card_id": card["id"], "answer": q["answer"], "explanation": q["explanation"], "topic": card["topic"]}
    save_data(data)

    box_emoji = ["🆕","1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","🏆"]
    count = daily["count"] + 1
    header = f"☀️ <b>Câu {count}/{DAILY_LIMIT}</b>  {box_emoji[min(card.get('box',0),6)]} Box {card.get('box',0)}\n🎯 <i>{card['topic']}</i>\n{'─'*28}\n\n"
    body = f"{q['question']}\n\nA) {q['options']['A']}\nB) {q['options']['B']}\nC) {q['options']['C']}\nD) {q['options']['D']}"

    await app.bot.send_message(
        chat_id=CHAT_ID, text=header + body, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("A", callback_data="ans:A"),
            InlineKeyboardButton("B", callback_data="ans:B"),
            InlineKeyboardButton("C", callback_data="ans:C"),
            InlineKeyboardButton("D", callback_data="ans:D"),
        ]])
    )


async def cb_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = load_data()
    session = data.get("session", {})
    if not session:
        await query.edit_message_text("⚠️ Session hết hạn. Dùng /review.")
        return

    chosen = query.data.split(":")[1]
    correct = chosen == session["answer"]
    update_card(data, session["card_id"], correct)
    data["stats"]["total_reviews"] += 1
    if correct:
        data["stats"]["correct"] += 1

    today = datetime.now().date().isoformat()
    daily = data.setdefault("daily", {"date": today, "count": 0})
    if daily.get("date") != today:
        daily["date"] = today
        daily["count"] = 0
    daily["count"] += 1
    save_data(data)

    card = data["cards"][session["card_id"]]
    interval = SR_INTERVALS[min(card["box"], len(SR_INTERVALS)-1)]
    result = f"✅ <b>Đúng!</b> Ôn lại sau {interval} ngày" if correct else f"❌ <b>Sai.</b> Đáp án: <b>{session['answer']}</b> · Ôn lại ngày mai"
    explanation = f"\n\n💡 <i>{session['explanation']}</i>"

    count = daily["count"]
    due = get_due_cards(data)
    acc = round(data["stats"]["correct"] / data["stats"]["total_reviews"] * 100) if data["stats"]["total_reviews"] else 0

    if count < DAILY_LIMIT and due:
        next_btn = InlineKeyboardMarkup([[InlineKeyboardButton(f"➡️ Câu tiếp ({count}/{DAILY_LIMIT})", callback_data="next:q")]])
        extra = ""
    else:
        next_btn = None
        extra = f"\n\n🎯 <b>Xong {DAILY_LIMIT} câu!</b> Accuracy: {acc}%" if count >= DAILY_LIMIT else f"\n\n🎉 Hết cards! Accuracy: {acc}%"

    await query.edit_message_text(
        query.message.text + f"\n\n{'─'*28}\n{result}{explanation}{extra}",
        parse_mode="HTML", reply_markup=next_btn
    )


async def cb_next(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup(None)
    await send_question(ctx.application)


async def cmd_review(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    due = get_due_cards(data)
    if not due:
        await update.message.reply_text("✅ Hết cards!\n\nDùng /learned [topic] để thêm module mới.")
        return
    await send_question(ctx.application, override_card=due[0])


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    total = data["stats"]["total_reviews"]
    correct = data["stats"]["correct"]
    acc = round(correct / total * 100) if total else 0
    box_counts = {}
    for c in data["cards"].values():
        box_counts[c["box"]] = box_counts.get(c["box"], 0) + 1
    box_str = " | ".join(f"Box{b}:{n}" for b, n in sorted(box_counts.items())) or "Chưa có"
    daily_count = data.get("daily", {}).get("count", 0)
    await update.message.reply_html(
        f"📊 <b>Thống kê</b>\n\n🗂 Topics: {len(data['cards'])}\n"
        f"📅 Cần ôn hôm nay: <b>{len(get_due_cards(data))}</b>\n"
        f"✅ Đã làm hôm nay: <b>{daily_count}/{DAILY_LIMIT}</b>\n"
        f"🎯 Accuracy: <b>{acc}%</b> ({correct}/{total})\n\n📦 {box_str}"
    )


def setup_scheduler(app: Application):
    scheduler = AsyncIOScheduler(timezone="Asia/Ho_Chi_Minh")
    scheduler.add_job(
        lambda: asyncio.run_coroutine_threadsafe(send_question(app), asyncio.get_event_loop()),
        trigger="cron", hour=8, minute=0,
    )
    scheduler.start()
    logger.info("Scheduler started: 10 questions at 8:00 AM GMT+7")


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("learned", cmd_learned))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("review", cmd_review))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("help", lambda u, c: u.message.reply_html(
        "📖 <b>Hướng dẫn</b>\n\n• /learned [topic] — Thêm module vừa học\n"
        "• /review — Ôn thêm\n• /list — Xem topics\n• /stats — Tiến độ\n\n"
        "Bot gửi 10 câu lúc 8:00 sáng mỗi ngày."
    )))
    app.add_handler(CallbackQueryHandler(cb_answer, pattern="^ans:"))
    app.add_handler(CallbackQueryHandler(cb_next, pattern="^next:"))
    setup_scheduler(app)
    logger.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

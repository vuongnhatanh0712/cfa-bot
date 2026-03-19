"""
CFA Level 1 Spaced Repetition Telegram Bot
- Gửi câu hỏi lúc 8h sáng mỗi ngày
- Spaced repetition: câu sai → hỏi lại sớm hơn
- Claude API tạo câu hỏi động từ curriculum
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
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CHAT_ID = os.environ["CHAT_ID"]          # Your personal Telegram chat ID
DATA_FILE = Path("data/progress.json")

# ── CFA Curriculum ────────────────────────────────────────────────────────────
CFA_CURRICULUM = {
    "ethics": {
        "name": "Ethics & Professional Standards",
        "weight": "15-20%",
        "topics": [
            "Standard I: Professionalism",
            "Standard II: Integrity of Capital Markets",
            "Standard III: Duties to Clients",
            "Standard IV: Duties to Employers",
            "Standard V: Investment Analysis & Recommendations",
            "Standard VI: Conflicts of Interest",
            "Standard VII: Responsibilities as CFA Member",
            "GIPS overview",
        ],
    },
    "quant": {
        "name": "Quantitative Methods",
        "weight": "8-12%",
        "topics": [
            "Time value of money (TVM)",
            "Statistics: mean, variance, skewness, kurtosis",
            "Probability distributions",
            "Sampling & hypothesis testing",
            "Simple & multiple regression",
            "Correlation analysis",
        ],
    },
    "economics": {
        "name": "Economics",
        "weight": "8-12%",
        "topics": [
            "Demand & supply analysis",
            "Elasticity",
            "Market structures",
            "GDP & business cycles",
            "Monetary & fiscal policy",
            "Currency exchange rates",
            "International trade",
        ],
    },
    "fra": {
        "name": "Financial Reporting & Analysis",
        "weight": "13-17%",
        "topics": [
            "Income statement analysis",
            "Balance sheet analysis",
            "Cash flow statement",
            "Financial ratios",
            "Inventory methods (FIFO, LIFO, weighted avg)",
            "Long-lived assets & depreciation",
            "Income taxes (deferred tax)",
            "Long-term liabilities",
        ],
    },
    "corporate": {
        "name": "Corporate Issuers",
        "weight": "8-12%",
        "topics": [
            "Capital structure",
            "Cost of capital (WACC)",
            "Dividend policy",
            "Working capital management",
            "ESG & stakeholder management",
        ],
    },
    "equity": {
        "name": "Equity Investments",
        "weight": "10-12%",
        "topics": [
            "Market organization & structure",
            "Security market indices",
            "Market efficiency (EMH)",
            "Equity analysis: DDM",
            "Free cash flow to equity",
            "Price multiples (P/E, P/B, P/S)",
            "EV/EBITDA",
        ],
    },
    "fixed_income": {
        "name": "Fixed Income",
        "weight": "10-12%",
        "topics": [
            "Bond features & pricing",
            "Yield measures (YTM, current yield)",
            "Duration & convexity",
            "Term structure of interest rates",
            "Credit risk & ratings",
            "Securitization basics",
        ],
    },
    "derivatives": {
        "name": "Derivatives",
        "weight": "5-8%",
        "topics": [
            "Forward contracts",
            "Futures contracts",
            "Options: calls & puts",
            "Put-call parity",
            "Swaps",
            "Option strategies (covered call, protective put)",
        ],
    },
    "alternatives": {
        "name": "Alternative Investments",
        "weight": "5-8%",
        "topics": [
            "Hedge funds: strategies & fees",
            "Private equity & venture capital",
            "Real estate valuation",
            "Commodities",
            "Infrastructure",
        ],
    },
    "portfolio": {
        "name": "Portfolio Management",
        "weight": "5-8%",
        "topics": [
            "Modern Portfolio Theory",
            "Capital Asset Pricing Model (CAPM)",
            "Capital Allocation Line (CAL)",
            "Efficient frontier",
            "Investment Policy Statement (IPS)",
            "Behavioral finance basics",
        ],
    },
}

# Spaced repetition intervals (days): box 0→1→2→4→7→14→30
SR_INTERVALS = [1, 1, 2, 4, 7, 14, 30]


# ── Data persistence ──────────────────────────────────────────────────────────
def load_data() -> dict:
    DATA_FILE.parent.mkdir(exist_ok=True)
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text())
    return {
        "cards": {},          # card_id → {topic, subject, box, next_review, streak}
        "session": {},        # current question session
        "stats": {
            "total_reviews": 0,
            "correct": 0,
            "streak_days": 0,
            "last_review_date": None,
        },
        "active_subjects": [],  # subjects unlocked by user
    }


def save_data(data: dict):
    DATA_FILE.parent.mkdir(exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


# ── Spaced repetition logic ───────────────────────────────────────────────────
def get_due_cards(data: dict) -> list[dict]:
    """Return cards due for review today, sorted by urgency."""
    today = datetime.now().date().isoformat()
    due = []
    for card_id, card in data["cards"].items():
        if card["next_review"] <= today:
            due.append({"id": card_id, **card})
    # Sort: overdue first, then by subject weight
    due.sort(key=lambda c: c["next_review"])
    return due


def update_card(data: dict, card_id: str, correct: bool):
    """Update card box based on answer correctness."""
    card = data["cards"][card_id]
    box = card["box"]
    if correct:
        box = min(box + 1, len(SR_INTERVALS) - 1)
        card["streak"] = card.get("streak", 0) + 1
    else:
        box = max(0, box - 1)  # Wrong: move back one box
        card["streak"] = 0

    card["box"] = box
    interval = SR_INTERVALS[box]
    next_date = (datetime.now() + timedelta(days=interval)).date().isoformat()
    card["next_review"] = next_date
    save_data(data)


def add_cards_for_topic(data: dict, subject_key: str, topic: str):
    """Create a new card for a topic if it doesn't exist."""
    card_id = f"{subject_key}::{topic}"
    if card_id not in data["cards"]:
        data["cards"][card_id] = {
            "subject": subject_key,
            "topic": topic,
            "box": 0,
            "next_review": datetime.now().date().isoformat(),
            "streak": 0,
        }
    save_data(data)


# ── Claude API ────────────────────────────────────────────────────────────────
async def generate_question(subject_key: str, topic: str) -> dict:
    """Call Claude to generate a multiple-choice question."""
    subject = CFA_CURRICULUM[subject_key]
    prompt = f"""Bạn là giáo viên luyện thi CFA Level 1. Tạo 1 câu hỏi trắc nghiệm (4 đáp án A/B/C/D) về topic sau:

Subject: {subject['name']}
Topic: {topic}

Yêu cầu:
- Câu hỏi bằng tiếng Anh (như đề thi thật)
- Độ khó vừa phải (exam-level)
- 4 lựa chọn, chỉ 1 đáp án đúng
- Giải thích ngắn gọn tại sao đáp án đúng (2-3 câu)

Trả lời ĐÚNG định dạng JSON sau (không có text khác):
{{
  "question": "...",
  "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
  "answer": "A",
  "explanation": "..."
}}"""

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        resp.raise_for_status()
        text = resp.json()["content"][0]["text"].strip()
        # Strip markdown code blocks if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)


# ── Telegram handlers ─────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    msg = (
        f"👋 Chào mừng đến CFA Level 1 Bot!\n\n"
        f"📌 Chat ID của bạn: <code>{chat_id}</code>\n\n"
        f"Lệnh có sẵn:\n"
        f"• /unlock — Mở khóa môn học mới\n"
        f"• /review — Ôn tập ngay bây giờ\n"
        f"• /stats — Xem thống kê\n"
        f"• /help — Hướng dẫn\n\n"
        f"Bot sẽ tự động gửi câu hỏi lúc <b>8:00 sáng</b> mỗi ngày."
    )
    await update.message.reply_html(msg)


async def cmd_unlock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Let user add subjects they've studied."""
    data = load_data()
    active = set(data.get("active_subjects", []))

    keyboard = []
    for key, subj in CFA_CURRICULUM.items():
        status = "✅" if key in active else "➕"
        keyboard.append([
            InlineKeyboardButton(
                f"{status} {subj['name']} ({subj['weight']})",
                callback_data=f"unlock:{key}"
            )
        ])
    keyboard.append([InlineKeyboardButton("✔️ Xong", callback_data="unlock:done")])

    await update.message.reply_text(
        "📚 Chọn các môn bạn đã học để thêm vào hệ thống ôn tập:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cb_unlock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = load_data()
    active = set(data.get("active_subjects", []))

    action = query.data.split(":", 1)[1]
    if action == "done":
        count = sum(
            len(CFA_CURRICULUM[s]["topics"])
            for s in active
            if s in CFA_CURRICULUM
        )
        await query.edit_message_text(
            f"✅ Đã lưu {len(active)} môn với tổng cộng {count} topics.\n"
            f"Dùng /review để ôn tập ngay, hoặc chờ 8h sáng mai!"
        )
        return

    if action in active:
        active.discard(action)
        # Remove cards for this subject
        data["cards"] = {
            k: v for k, v in data["cards"].items()
            if v["subject"] != action
        }
    else:
        active.add(action)
        # Add cards for all topics
        for topic in CFA_CURRICULUM[action]["topics"]:
            add_cards_for_topic(data, action, topic)

    data["active_subjects"] = list(active)
    save_data(data)

    # Refresh keyboard
    keyboard = []
    for key, subj in CFA_CURRICULUM.items():
        status = "✅" if key in active else "➕"
        keyboard.append([
            InlineKeyboardButton(
                f"{status} {subj['name']} ({subj['weight']})",
                callback_data=f"unlock:{key}"
            )
        ])
    keyboard.append([InlineKeyboardButton("✔️ Xong", callback_data="unlock:done")])

    await query.edit_message_reply_markup(InlineKeyboardMarkup(keyboard))


async def send_daily_question(app: Application, specific_card: dict = None):
    """Send one due card as a quiz to the user."""
    data = load_data()
    due = get_due_cards(data)

    if not due:
        await app.bot.send_message(
            chat_id=CHAT_ID,
            text="🎉 Không còn card nào cần ôn hôm nay!\n\nDùng /unlock để thêm môn mới.",
        )
        return

    card = specific_card or due[0]
    total_due = len(due)

    try:
        q = await generate_question(card["subject"], card["topic"])
    except Exception as e:
        logger.error(f"Claude API error: {e}")
        await app.bot.send_message(
            chat_id=CHAT_ID,
            text=f"⚠️ Lỗi tạo câu hỏi cho: {card['topic']}\nThử lại với /review"
        )
        return

    # Store session
    data["session"] = {
        "card_id": card["id"],
        "answer": q["answer"],
        "explanation": q["explanation"],
        "topic": card["topic"],
    }
    save_data(data)

    subject_name = CFA_CURRICULUM[card["subject"]]["name"]
    box_emoji = ["🆕", "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "🏆"]
    box = card.get("box", 0)

    header = (
        f"☀️ <b>Câu hỏi ôn tập buổi sáng</b>\n"
        f"📖 {subject_name}\n"
        f"🎯 Topic: <i>{card['topic']}</i>\n"
        f"{box_emoji[min(box, 6)]} Box {box} · {total_due} cards còn lại hôm nay\n"
        f"{'─' * 30}\n\n"
    )

    question_text = (
        f"{q['question']}\n\n"
        f"A) {q['options']['A']}\n"
        f"B) {q['options']['B']}\n"
        f"C) {q['options']['C']}\n"
        f"D) {q['options']['D']}"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("A", callback_data="ans:A"),
            InlineKeyboardButton("B", callback_data="ans:B"),
            InlineKeyboardButton("C", callback_data="ans:C"),
            InlineKeyboardButton("D", callback_data="ans:D"),
        ]
    ])

    await app.bot.send_message(
        chat_id=CHAT_ID,
        text=header + question_text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )


async def cb_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = load_data()
    session = data.get("session", {})
    if not session:
        await query.edit_message_text("⚠️ Session hết hạn. Dùng /review để tạo câu mới.")
        return

    chosen = query.data.split(":")[1]
    correct_ans = session["answer"]
    correct = chosen == correct_ans
    card_id = session["card_id"]

    update_card(data, card_id, correct)

    # Update stats
    data["stats"]["total_reviews"] += 1
    if correct:
        data["stats"]["correct"] += 1
    save_data(data)

    # Next review info
    card = data["cards"][card_id]
    next_review = card["next_review"]
    next_dt = datetime.fromisoformat(next_review)
    days_until = (next_dt - datetime.now()).days + 1

    if correct:
        result_line = f"✅ <b>Đúng rồi!</b> Box {card['box']} → ôn lại sau {days_until} ngày"
    else:
        result_line = f"❌ <b>Sai.</b> Đáp án đúng: <b>{correct_ans}</b> · ôn lại ngày mai"

    explanation = f"\n\n💡 <i>{session['explanation']}</i>"

    # Check if more cards due
    due = get_due_cards(data)
    if due:
        next_btn = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"➡️ Câu tiếp ({len(due)} còn lại)", callback_data="next:question")
        ]])
        extra = ""
    else:
        next_btn = None
        accuracy = (
            round(data["stats"]["correct"] / data["stats"]["total_reviews"] * 100)
            if data["stats"]["total_reviews"] else 0
        )
        extra = f"\n\n🎉 Xong hôm nay! Accuracy: <b>{accuracy}%</b>"

    await query.edit_message_text(
        query.message.text + f"\n\n{'─' * 30}\n{result_line}{explanation}{extra}",
        parse_mode="HTML",
        reply_markup=next_btn,
    )


async def cb_next(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup(None)
    await send_daily_question(ctx.application)


async def cmd_review(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Trigger a review session manually."""
    data = load_data()
    due = get_due_cards(data)
    if not due:
        accuracy = (
            round(data["stats"]["correct"] / data["stats"]["total_reviews"] * 100)
            if data["stats"]["total_reviews"] else 0
        )
        await update.message.reply_text(
            f"✅ Không còn card nào cần ôn hôm nay!\n"
            f"📊 Accuracy tổng: {accuracy}%\n\n"
            f"Dùng /unlock để thêm môn học mới."
        )
        return
    await send_daily_question(ctx.application)


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    stats = data["stats"]
    cards = data["cards"]

    total = stats["total_reviews"]
    correct = stats["correct"]
    accuracy = round(correct / total * 100) if total else 0

    # Cards by box
    box_counts = {}
    for card in cards.values():
        b = card["box"]
        box_counts[b] = box_counts.get(b, 0) + 1

    box_summary = " | ".join(
        f"Box{b}:{n}" for b, n in sorted(box_counts.items())
    ) or "Chưa có card"

    due_today = len(get_due_cards(data))
    active_subjects = len(data.get("active_subjects", []))

    await update.message.reply_html(
        f"📊 <b>Thống kê học tập</b>\n\n"
        f"🗂 Tổng cards: {len(cards)} ({active_subjects} môn)\n"
        f"📅 Cần ôn hôm nay: <b>{due_today}</b>\n"
        f"✅ Tổng reviews: {total}\n"
        f"🎯 Accuracy: <b>{accuracy}%</b>\n\n"
        f"📦 Phân bổ cards:\n{box_summary}\n\n"
        f"<i>Box 6 = đã thuộc rất tốt (30 ngày/lần)</i>"
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        "📖 <b>Hướng dẫn CFA Bot</b>\n\n"
        "<b>Cách hoạt động:</b>\n"
        "• Mỗi topic CFA là 1 'card' trong hệ thống\n"
        "• Card đúng → lên box cao hơn → ôn ít hơn\n"
        "• Card sai → xuống box → ôn lại sớm hơn\n"
        "• Box 0: mỗi ngày | Box 6: mỗi 30 ngày\n\n"
        "<b>Lệnh:</b>\n"
        "• /unlock — Chọn môn đã học\n"
        "• /review — Ôn ngay\n"
        "• /stats — Xem tiến độ\n\n"
        "<b>Lịch tự động:</b> 8:00 sáng mỗi ngày (GMT+7)"
    )


# ── Scheduler ─────────────────────────────────────────────────────────────────
def setup_scheduler(app: Application):
    scheduler = AsyncIOScheduler(timezone="Asia/Ho_Chi_Minh")
    scheduler.add_job(
        lambda: asyncio.ensure_future(send_daily_question(app)),
        trigger="cron",
        hour=8,
        minute=0,
    )
    return scheduler


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("unlock", cmd_unlock))
    app.add_handler(CommandHandler("review", cmd_review))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CallbackQueryHandler(cb_unlock, pattern="^unlock:"))
    app.add_handler(CallbackQueryHandler(cb_answer, pattern="^ans:"))
    app.add_handler(CallbackQueryHandler(cb_next, pattern="^next:"))

    scheduler = setup_scheduler(app)

    async def post_init(application):
        scheduler.start()
        logger.info("Scheduler started: daily question at 8:00 AM GMT+7")

    app.post_init = post_init

    logger.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

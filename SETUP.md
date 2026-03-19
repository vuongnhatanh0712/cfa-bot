# 📚 CFA Level 1 Spaced Repetition Bot — Hướng dẫn Setup

## Tổng quan

Bot Telegram tự động gửi câu hỏi CFA lúc **8:00 sáng** mỗi ngày.
- **Spaced repetition**: câu đúng → ôn lại thưa hơn, câu sai → ôn lại sớm hơn
- **Claude API** tạo câu hỏi mới mỗi lần (không lặp lại)
- **Miễn phí hosting** trên Railway (500h/tháng free tier)

---

## Bước 1 — Tạo Telegram Bot (5 phút)

1. Mở Telegram, tìm **@BotFather**
2. Gửi lệnh `/newbot`
3. Đặt tên bot: ví dụ `CFA Study Bot`
4. Đặt username: ví dụ `my_cfa_bot` (phải kết thúc bằng `bot`)
5. BotFather sẽ gửi lại **token** dạng: `7123456789:AAFxxxxxxxxxxxxxx`
   → Lưu lại, đây là `TELEGRAM_TOKEN`

---

## Bước 2 — Lấy Chat ID của bạn (2 phút)

1. Tìm bot vừa tạo trên Telegram, gửi `/start`
2. Mở trình duyệt, truy cập:
   ```
   https://api.telegram.org/bot<TELEGRAM_TOKEN>/getUpdates
   ```
   Thay `<TELEGRAM_TOKEN>` bằng token thật
3. Tìm trường `"chat": {"id": 123456789}` trong kết quả
   → Đây là `CHAT_ID` của bạn

---

## Bước 3 — Lấy Anthropic API Key (3 phút)

1. Vào https://console.anthropic.com
2. Chọn **API Keys** → **Create Key**
3. Copy key dạng `sk-ant-xxxxxx`
   → Đây là `ANTHROPIC_API_KEY`

> 💡 Chi phí: ~$0.003 mỗi câu hỏi. Ôn 3 câu/ngày = ~$0.009/ngày ≈ $0.27/tháng

---

## Bước 4 — Deploy lên Railway (10 phút)

### 4a. Push code lên GitHub

```bash
cd cfa-bot
git init
git add .
git commit -m "Initial CFA bot"
# Tạo repo mới trên github.com, rồi:
git remote add origin https://github.com/<username>/cfa-bot.git
git push -u origin main
```

### 4b. Deploy trên Railway

1. Vào https://railway.app → **Login with GitHub**
2. **New Project** → **Deploy from GitHub repo**
3. Chọn repo `cfa-bot`
4. Vào tab **Variables**, thêm 3 biến:

   | Key | Value |
   |-----|-------|
   | `TELEGRAM_TOKEN` | token từ BotFather |
   | `ANTHROPIC_API_KEY` | key từ Anthropic |
   | `CHAT_ID` | chat ID của bạn |

5. Railway tự deploy → xem logs để kiểm tra

> ✅ Nếu thấy `Bot starting...` và `Scheduler started` trong logs là thành công!

---

## Bước 5 — Sử dụng Bot

### Lần đầu tiên:
1. Gửi `/start` cho bot
2. Gửi `/unlock` → chọn các môn đã học
   - Tick: Ethics, Economics, Corporate Issuers, Alternatives (đã học)
   - Thêm dần khi học xong môn mới
3. Gửi `/review` để test ngay

### Hàng ngày:
- **8:00 sáng**: Bot tự gửi câu hỏi
- Bấm A/B/C/D để trả lời
- Bấm "Câu tiếp" nếu còn card

### Các lệnh:
| Lệnh | Chức năng |
|------|-----------|
| `/unlock` | Mở khóa môn mới khi học xong |
| `/review` | Ôn tập ngay (không cần đợi 8h) |
| `/stats` | Xem tiến độ, accuracy |
| `/help` | Hướng dẫn |

---

## Cách hoạt động Spaced Repetition

```
Trả lời ĐÚNG  → Box tăng lên → ôn lại thưa hơn
Trả lời SAI   → Box giảm xuống → ôn lại sớm hơn

Box 0: ôn mỗi ngày
Box 1: ôn sau 1 ngày
Box 2: ôn sau 2 ngày
Box 3: ôn sau 4 ngày
Box 4: ôn sau 7 ngày
Box 5: ôn sau 14 ngày
Box 6: ôn sau 30 ngày  ← đã thuộc rất tốt
```

---

## Test local (không bắt buộc)

```bash
pip install -r requirements.txt

# Windows:
set TELEGRAM_TOKEN=xxx
set ANTHROPIC_API_KEY=xxx
set CHAT_ID=xxx

# Mac/Linux:
export TELEGRAM_TOKEN=xxx
export ANTHROPIC_API_KEY=xxx
export CHAT_ID=xxx

python bot.py
```

---

## Troubleshooting

| Vấn đề | Giải pháp |
|--------|-----------|
| Bot không trả lời | Kiểm tra `TELEGRAM_TOKEN` đúng chưa |
| Không nhận được tin nhắn 8h | Kiểm tra `CHAT_ID` đúng chưa |
| Lỗi `Claude API error` | Kiểm tra `ANTHROPIC_API_KEY` và credit |
| Railway deploy fail | Xem build logs, thường do thiếu env vars |

---

## Workflow học với bot

1. **Học xong 1 môn** → `/unlock` để thêm môn đó vào bot
2. **Sáng hôm sau** → bot tự gửi câu hỏi
3. **Trả lời** → bot cho biết đúng/sai + giải thích
4. **2-3 tuần sau** → card đó lên box cao, xuất hiện ít hơn
5. **Trước ngày thi** → mọi card sẽ tự động xuất hiện lại theo lịch

> 💡 **Tip**: Khi học module mới với Claude (mục tiêu 1), paste tóm tắt vào chat rồi
> dùng `/review` để kiểm tra ngay hôm đó — kết hợp 2 mục tiêu cùng lúc!

# 🇻🇳 Personal Expense Tracker Telegram Bot
> Lightweight, ultra-fast personal expense logging from Vietnamese natural text using **Gemini 3.8 Flash** with Structured Outputs, **SQLite**, and **python-telegram-bot** (v21+ async).

---

## 🚀 Features

- **Natural Vietnamese Language Parsing:**
  - `50000 cơm gà d5` ➔ 50.000 ₫ (Ăn uống: Cơm gà d5)
  - `grab 35k đi học` ➔ 35.000 ₫ (Di chuyển: Grab đi học)
  - `sáng phở 45k cf 30k` ➔ Tự động bóc tách thành 2 giao dịch riêng biệt!
  - `hôm qua mua áo 250k shopee` ➔ Tự động tính ngày hôm qua (YYYY-MM-DD).
- **Flexible Currency Slang:**
  - `k`, `nghìn`, `ngàn`, `cành` (× 1.000)
  - `lít`, `xị` (× 100.000)
  - `củ`, `tr`, `triệu` (× 1.000.000)
- **Instant Undo / Delete Button:**
  - Mỗi khi ghi nhận chi tiêu, bot gửi kèm nút inline `[❌ Hoàn tác (Xóa)]` để bạn xóa nhanh nếu lỡ ghi sai.
- **Repository Pattern Database:**
  - Cơ sở dữ liệu SQLite bất đồng bộ (`aiosqlite`) sạch sẽ, dễ dàng nâng cấp sang Supabase hay Google Sheets trong tương lai.
- **Whitelist Security:**
  - Chỉ người dùng có Telegram User ID được cấu hình trong `ALLOWED_TELEGRAM_USER_ID` mới có thể trò chuyện và truy xuất dữ liệu từ bot.
- **Stats & Reports:**
  - `/today`: Xem tổng chi và danh sách các khoản hôm nay.
  - `/month`: Tổng kết chi tiêu tháng, tỷ lệ phần trăm theo từng danh mục.
  - `/stats`: Báo cáo so sánh hôm nay và tháng này.
  - `/recent`: Xem các giao dịch gần nhất kèm nút xóa từng khoản.

---

## 📁 Cấu trúc thư mục

```text
├── .antigravity/
│   └── rules.md          # Quy chuẩn kỹ thuật cho AI agent
├── .env.example          # Mẫu cấu hình biến môi trường
├── requirements.txt      # Thư viện phụ thuộc
├── config.py             # Cấu hình, nạp .env, định nghĩa danh mục chi tiêu
├── database.py           # SQLite Repository pattern (aiosqlite)
├── ai_parser.py          # Gemini 3.8 Flash + Pydantic Structured Outputs
├── bot.py                # Bot Telegram chính (handlers, commands, callback query)
└── README.md             # Hướng dẫn sử dụng
```

---

## 🛠️ Cài đặt & Khởi chạy

### 1. Cài đặt Python Dependencies
Khuyến nghị tạo môi trường ảo (virtual environment):
```bash
python -m venv venv
# Trên Windows:
venv\Scripts\activate
# Trên Linux/Mac:
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Cấu hình biến môi trường (`.env`)
Tạo file `.env` từ `.env.example`:
```bash
copy .env.example .env   # Trên Windows CMD/PowerShell
# hoặc: cp .env.example .env (Linux/Mac)
```

Điền các thông tin cần thiết vào file `.env`:
1. `GEMINI_API_KEY`: Lấy miễn phí tại [Google AI Studio](https://aistudio.google.com/).
2. `TELEGRAM_BOT_TOKEN`: Tạo bot mới qua [@BotFather](https://t.me/BotFather) trên Telegram.
3. `ALLOWED_TELEGRAM_USER_ID`: ID tài khoản Telegram của bạn (nhắn tin cho [@userinfobot](https://t.me/userinfobot) để lấy ID). Có thể nhập nhiều ID cách nhau bằng dấu phẩy.

### 3. Khởi chạy Bot
```bash
python bot.py
```

---

## 💡 Ví dụ câu lệnh & tin nhắn

| Tin nhắn người dùng | Kết quả nhận diện | Danh mục |
| :--- | :--- | :--- |
| `cơm tấm 35k` | 35.000 ₫ | Ăn uống |
| `grab 42k qua nhà bạn` | 42.000 ₫ | Di chuyển |
| `sáng phở 45k cf 25k` | 45.000 ₫ + 25.000 ₫ (2 khoản) | Ăn uống |
| `shopee áo polo 180k` | 180.000 ₫ | Mua sắm |
| `đóng tiền điện 450k` | 450.000 ₫ | Hóa đơn & Dịch vụ |
| `hôm qua mua vé xem phim 110k` | 110.000 ₫ (ghi nhận ngày hôm qua) | Giải trí |

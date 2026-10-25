"""Main Telegram Bot application for Personal Expense Tracker.

Built with python-telegram-bot (v21+ async) and integrated with Gemini 3.8 Flash.
"""

import html
import logging
from functools import wraps
from typing import List
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    constants,
)
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ai_parser import parser
from config import (
    ALLOWED_TELEGRAM_USER_IDS,
    PORT,
    TELEGRAM_BOT_TOKEN,
    format_currency,
    get_category_emoji,
    get_current_datetime,
    validate_config,
)
from database import repo

# =====================================================================
# Logging Configuration
# =====================================================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# =====================================================================
# Security Whitelist Decorator
# =====================================================================
def restricted(func):
    """Decorator to enforce whitelist authorization for Telegram commands and messages."""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user or user.id not in ALLOWED_TELEGRAM_USER_IDS:
            user_id = user.id if user else "Unknown"
            user_name = user.full_name if user else "Unknown"
            logger.warning("Unauthorized access attempt by %s (ID: %s)", user_name, user_id)

            unauthorized_msg = (
                "⛔ <b>Truy cập bị từ chối!</b>\n\n"
                f"Tài khoản của bạn: <b>{html.escape(user_name)}</b>\n"
                f"Telegram User ID: <code>{user_id}</code>\n\n"
                "Bạn chưa có quyền sử dụng bot này. Vui lòng thêm User ID trên vào biến "
                "<code>ALLOWED_TELEGRAM_USER_ID</code> trong file <code>.env</code>."
            )

            if update.message:
                await update.message.reply_text(
                    unauthorized_msg, parse_mode=ParseMode.HTML
                )
            elif update.callback_query:
                await update.callback_query.answer(
                    "⛔ Bạn không có quyền thực hiện thao tác này!", show_alert=True
                )
            return
        return await func(update, context, *args, **kwargs)

    return wrapped


# =====================================================================
# Command Handlers
# =====================================================================
@restricted
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send welcome message and instructions on /start."""
    user = update.effective_user
    name = user.first_name if user else "bạn"
    now = get_current_datetime()
    today_str = now.strftime("%d/%m/%Y")

    welcome_text = (
        f"👋 Xin chào <b>{html.escape(name)}</b>!\n\n"
        f"🤖 Tôi là trợ lý theo dõi chi tiêu cá nhân sử dụng <b>Gemini 3.8 Flash</b>.\n"
        f"📅 Hôm nay là: <code>{today_str}</code>\n\n"
        "✨ <b>Cách sử dụng cực kỳ đơn giản:</b>\n"
        "Bạn chỉ cần nhắn tin bình thường bằng tiếng Việt, ví dụ:\n"
        "• <code>50000 cơm gà d5</code>\n"
        "• <code>grab 35k đi học</code>\n"
        "• <code>sáng phở 45k cf 30k</code>\n"
        "• <code>hôm qua mua áo 250k shopee</code>\n\n"
        "📊 <b>Lệnh tra cứu nhanh:</b>\n"
        "• /today - Chi tiêu hôm nay\n"
        "• /month - Tổng kết chi tiêu tháng này\n"
        "• /stats - Thống kê tổng quan\n"
        "• /recent - Xem các giao dịch gần nhất\n"
        "• /help - Hướng dẫn chi tiết"
    )
    if update.message:
        await update.message.reply_text(welcome_text, parse_mode=ParseMode.HTML)


@restricted
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send detailed help on /help."""
    help_text = (
        "📖 <b>CẨM NANG GHI CHÉP CHI TIÊU NHANH</b>\n\n"
        "<b>1. Tiền tệ linh hoạt:</b>\n"
        "• <code>k</code>: 45k ➔ 45.000 ₫\n"
        "• <code>cành</code>: 50 cành ➔ 50.000 ₫\n"
        "• <code>lít</code> / <code>xị</code>: 1 lít ➔ 100.000 ₫\n"
        "• <code>tr</code> / <code>củ</code>: 1.5tr ➔ 1.500.000 ₫\n"
        "• Số tự nhiên: <code>70000 đổ xăng</code> ➔ 70.000 ₫\n\n"
        "<b>2. Ghi nhiều khoản trong 1 tin nhắn:</b>\n"
        "• <code>sáng phở 45k cf 30k</code> ➔ Lưu 2 khoản riêng biệt\n"
        "• <code>grab 32k, ăn trưa 40k, trà sữa 55k</code> ➔ Lưu 3 khoản\n\n"
        "<b>3. Hỗ trợ thời gian tương đối:</b>\n"
        "• <code>hôm qua ăn lẩu 300k</code> ➔ Lưu ngày hôm qua\n"
        "• <code>hôm kia gửi xe 10k</code> ➔ Lưu ngày hôm kia\n\n"
        "<b>4. Nút Hoàn tác / Xóa:</b>\n"
        "Mỗi lần ghi nhận chi tiêu, bot sẽ gửi kèm nút <b>[❌ Hoàn tác]</b> "
        "để bạn xóa ngay nếu ghi nhầm."
    )
    if update.message:
        await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)


@restricted
async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show expenses and summary for today on /today."""
    user = update.effective_user
    if not user or not update.message:
        return

    now = get_current_datetime()
    today_iso = now.strftime("%Y-%m-%d")
    today_display = now.strftime("%d/%m/%Y")

    summary = await repo.get_daily_summary(user.id, today_iso)
    expenses = await repo.get_expenses_by_date(user.id, today_iso)

    if not expenses:
        await update.message.reply_text(
            f"📅 Hôm nay (<code>{today_display}</code>) bạn chưa có khoản chi tiêu nào.\n"
            "Hãy gửi tin nhắn để ghi lại ngay nhé!",
            parse_mode=ParseMode.HTML,
        )
        return

    lines = [f"📅 <b>CHI TIÊU HÔM NAY ({today_display})</b>\n"]
    lines.append(f"💰 <b>Tổng cộng: {format_currency(summary['total'])}</b> ({summary['count']} khoản)\n")

    lines.append("<b>Chi tiết các khoản:</b>")
    for idx, exp in enumerate(expenses, 1):
        emoji = get_category_emoji(exp.category)
        lines.append(
            f"{idx}. {emoji} <b>{html.escape(exp.description)}</b>\n"
            f"   └ <code>{format_currency(exp.amount)}</code> ({exp.category})"
        )

    if summary["categories"]:
        lines.append("\n<b>Phân bổ theo danh mục:</b>")
        for cat in summary["categories"]:
            emoji = get_category_emoji(cat["category"])
            pct = (cat["total"] / summary["total"] * 100) if summary["total"] > 0 else 0
            lines.append(
                f"• {emoji} {cat['category']}: <b>{format_currency(cat['total'])}</b> ({pct:.1f}%)"
            )

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


@restricted
async def month_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show monthly spending breakdown on /month."""
    user = update.effective_user
    if not user or not update.message:
        return

    now = get_current_datetime()
    summary = await repo.get_monthly_summary(user.id, now.year, now.month)

    if summary["count"] == 0:
        await update.message.reply_text(
            f"📊 Tháng <b>{now.month:02d}/{now.year}</b> bạn chưa có dữ liệu chi tiêu nào.",
            parse_mode=ParseMode.HTML,
        )
        return

    lines = [f"📊 <b>TỔNG KẾT CHI TIÊU THÁNG {now.month:02d}/{now.year}</b>\n"]
    lines.append(f"💰 <b>Tổng chi tiêu: {format_currency(summary['total'])}</b>")
    lines.append(f"🔢 Số lượng giao dịch: <b>{summary['count']}</b> khoản\n")

    lines.append("<b>Danh mục chi tiêu:</b>")
    for cat in summary["categories"]:
        emoji = get_category_emoji(cat["category"])
        pct = (cat["total"] / summary["total"] * 100) if summary["total"] > 0 else 0
        lines.append(
            f"• {emoji} <b>{cat['category']}</b>: {format_currency(cat['total'])} "
            f"<i>({pct:.1f}%, {cat['count']} lần)</i>"
        )

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


@restricted
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show general spending overview on /stats."""
    user = update.effective_user
    if not user or not update.message:
        return

    now = get_current_datetime()
    today_iso = now.strftime("%Y-%m-%d")

    daily = await repo.get_daily_summary(user.id, today_iso)
    monthly = await repo.get_monthly_summary(user.id, now.year, now.month)

    text = (
        "📈 <b>BÁO CÁO THỐNG KÊ CHI TIÊU</b>\n\n"
        f"📅 <b>Hôm nay ({now.strftime('%d/%m/%Y')}):</b>\n"
        f"• Tổng: <b>{format_currency(daily['total'])}</b> ({daily['count']} khoản)\n\n"
        f"🗓️ <b>Tháng {now.month:02d}/{now.year}:</b>\n"
        f"• Tổng: <b>{format_currency(monthly['total'])}</b> ({monthly['count']} khoản)\n"
    )

    if monthly["categories"]:
        top_cat = monthly["categories"][0]
        top_emoji = get_category_emoji(top_cat["category"])
        text += (
            f"\n🔥 <i>Chi nhiều nhất tháng:</i>\n"
            f"• {top_emoji} {top_cat['category']} ({format_currency(top_cat['total'])})"
        )

    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


@restricted
async def recent_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display recent expenses with individual delete options on /recent."""
    user = update.effective_user
    if not user or not update.message:
        return

    expenses = await repo.get_recent_expenses(user.id, limit=8)
    if not expenses:
        await update.message.reply_text("📭 Bạn chưa có giao dịch chi tiêu nào gần đây.")
        return

    lines = ["🕒 <b>GIAO DỊCH GẦN NHẤT:</b>\n"]
    buttons = []

    for idx, exp in enumerate(expenses, 1):
        emoji = get_category_emoji(exp.category)
        lines.append(
            f"{idx}. {emoji} <b>{html.escape(exp.description)}</b> - {format_currency(exp.amount)}\n"
            f"   └ 📅 {exp.date} ({exp.category})"
        )
        buttons.append([
            InlineKeyboardButton(
                f"🗑️ Xóa #{idx} ({format_currency(exp.amount)})",
                callback_data=f"undo_{exp.id}",
            )
        ])

    keyboard = InlineKeyboardMarkup(buttons)
    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )


# =====================================================================
# Natural Language Text Message Handler
# =====================================================================
@restricted
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Parse incoming Vietnamese text messages into expenses via Gemini 3.8 Flash."""
    user = update.effective_user
    msg = update.message
    if not user or not msg or not msg.text:
        return

    user_text = msg.text.strip()

    # Send typing status indicator
    await context.bot.send_chat_action(chat_id=msg.chat_id, action=ChatAction.TYPING)

    # Call Gemini Parser
    try:
        now = get_current_datetime()
        result = await parser.parse_expense(user_text, current_dt=now)
    except Exception as exc:
        logger.error("Failed to parse text via Gemini: %s", exc, exc_info=True)
        await msg.reply_text(
            "⚠️ Có lỗi xảy ra khi phân tích tin nhắn qua AI. Vui lòng kiểm tra lại cấu hình API key hoặc thử lại sau.",
            reply_to_message_id=msg.message_id,
        )
        return

    # Case 1: Message is not an expense
    if not result.is_expense or not result.items:
        reply_text = result.user_reply or (
            "🤔 Tôi không tìm thấy thông tin khoản chi tiêu nào trong tin nhắn của bạn.\n"
            "Ví dụ bạn có thể nhắn: <code>cơm trưa 40k</code> hoặc <code>grab 35k</code> nhé!"
        )
        await msg.reply_text(
            reply_text,
            reply_to_message_id=msg.message_id,
            parse_mode=ParseMode.HTML,
        )
        return

    # Case 2: Expense(s) detected -> Save to Database
    items_to_save = [item.model_dump() for item in result.items]
    try:
        inserted_ids = await repo.add_expenses(
            user_id=user.id,
            items=items_to_save,
            raw_message=user_text,
        )
    except Exception as exc:
        logger.error("Database save failed: %s", exc, exc_info=True)
        await msg.reply_text(
            "❌ Có lỗi khi lưu dữ liệu vào cơ sở dữ liệu. Vui lòng thử lại.",
            reply_to_message_id=msg.message_id,
        )
        return

    # Format Confirmation Message
    total_amount = sum(item.amount for item in result.items)
    num_items = len(result.items)

    lines = []
    if num_items == 1:
        lines.append("✅ <b>Đã ghi nhận chi tiêu:</b>\n")
    else:
        lines.append(f"✅ <b>Đã ghi nhận {num_items} khoản chi tiêu:</b>\n")

    for idx, item in enumerate(result.items, 1):
        emoji = get_category_emoji(item.category)
        if num_items > 1:
            lines.append(f"<b>{idx}. {emoji} {item.category}:</b> {html.escape(item.description)}")
        else:
            lines.append(f"{emoji} <b>{item.category}:</b> {html.escape(item.description)}")
        lines.append(f"   💰 <code>{format_currency(item.amount)}</code> | 📅 {item.date}")

    if num_items > 1:
        lines.append(f"\n📊 <b>Tổng cộng: {format_currency(total_amount)}</b>")

    # Build Inline Buttons for Undo / Delete
    buttons = []
    if num_items == 1:
        # Single item -> 1 undo button
        buttons.append([
            InlineKeyboardButton(
                "❌ Hoàn tác (Xóa)", callback_data=f"undo_{inserted_ids[0]}"
            )
        ])
    else:
        # Multiple items -> "Hoàn tác tất cả" + individual buttons
        all_ids_str = "_".join(str(i) for i in inserted_ids)
        buttons.append([
            InlineKeyboardButton("❌ Hoàn tác tất cả", callback_data=f"undo_all_{all_ids_str}")
        ])
        # Individual delete buttons
        sub_buttons = [
            InlineKeyboardButton(f"Xóa #{idx}", callback_data=f"undo_{inserted_ids[idx-1]}")
            for idx in range(1, num_items + 1)
        ]
        buttons.append(sub_buttons)

    keyboard = InlineKeyboardMarkup(buttons)
    await msg.reply_text(
        "\n".join(lines),
        reply_markup=keyboard,
        reply_to_message_id=msg.message_id,
        parse_mode=ParseMode.HTML,
    )


# =====================================================================
# Callback Query Handlers (Undo & Delete)
# =====================================================================
@restricted
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button clicks for undoing/deleting recorded expenses."""
    query = update.callback_query
    if not query or not query.data:
        return

    user = update.effective_user
    if not user:
        return

    data = query.data

    # Pattern 1: Undo all items in a multi-item batch (undo_all_id1_id2_...)
    if data.startswith("undo_all_"):
        parts = data.replace("undo_all_", "").split("_")
        expense_ids = [int(p) for p in parts if p.isdigit()]
        if expense_ids:
            deleted_count = await repo.delete_expenses(expense_ids, user.id)
            await query.answer(f"Đã hoàn tác {deleted_count} khoản chi tiêu!", show_alert=False)
            if query.message:
                await query.edit_message_text(
                    f"🗑️ <b>Đã hoàn tác và xóa thành công {deleted_count} khoản chi tiêu.</b>\n"
                    "<i>(Dữ liệu đã được gỡ bỏ khỏi cơ sở dữ liệu)</i>",
                    parse_mode=ParseMode.HTML,
                )
        return

    # Pattern 2: Undo single item (undo_{id})
    if data.startswith("undo_"):
        expense_id_str = data.replace("undo_", "")
        if expense_id_str.isdigit():
            expense_id = int(expense_id_str)
            # Fetch expense first for descriptive confirmation
            expense = await repo.get_expense_by_id(expense_id, user.id)
            success = await repo.delete_expense(expense_id, user.id)

            if success:
                desc = f": <b>{html.escape(expense.description)}</b>" if expense else ""
                amount = f" ({format_currency(expense.amount)})" if expense else ""
                await query.answer("Đã hoàn tác thành công!", show_alert=False)
                if query.message:
                    await query.edit_message_text(
                        f"🗑️ <b>Đã xóa khoản chi tiêu{desc}{amount} thành công.</b>\n"
                        "<i>(Dữ liệu đã được gỡ bỏ khỏi cơ sở dữ liệu)</i>",
                        parse_mode=ParseMode.HTML,
                    )
            else:
                await query.answer("Khoản chi tiêu không tồn tại hoặc đã bị xóa trước đó.", show_alert=True)
        return

    await query.answer()


# =====================================================================
# Application Lifecycle & Main Function
# =====================================================================
async def post_init(application: Application) -> None:
    """Lifecycle hook executed once when bot application starts."""
    logger.info("Initializing SQLite database tables...")
    await repo.init_db()
    logger.info("SQLite database tables verified successfully.")

    # Log authorized users
    logger.info("Authorized Telegram User IDs: %s", ALLOWED_TELEGRAM_USER_IDS)


def _start_health_server(port: int) -> None:
    """Run a minimal HTTP healthcheck server for Cloud platforms like Render."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Expense Tracker Bot is running healthy!")

        def log_message(self, format, *args):
            pass

    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info("Health check server listening on 0.0.0.0:%s", port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()


def main() -> None:
    """Build and run the Telegram Bot application."""
    # Validate environment variables
    validate_config()

    if not TELEGRAM_BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN is missing. Bot cannot start.")
        return

    # If running on cloud platform that assigns a PORT (e.g. Render)
    if PORT > 0:
        _start_health_server(PORT)

    logger.info("Building Telegram application...")
    application = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Register Command Handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("today", today_command))
    application.add_handler(CommandHandler("month", month_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("recent", recent_command))

    # Register Callback Query Handler for Undo / Delete
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    # Register Text Message Handler (filters text without commands)
    application.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_message)
    )

    logger.info("Expense Tracker Bot is starting polling...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

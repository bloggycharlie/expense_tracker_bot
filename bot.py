"""Main Telegram Bot application for Personal Expense Tracker.

Built with python-telegram-bot (v21+ async) and integrated with Gemini 3.8 Flash.
"""

import datetime
import html
import io
import logging
import re
from functools import wraps
from typing import List, Optional
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
    LOCAL_TIMEZONE,
    PORT,
    TELEGRAM_BOT_TOKEN,
    format_currency,
    get_category_emoji,
    get_current_datetime,
    validate_config,
)
from database import repo
from visualizer import generate_category_pie_chart, generate_excel_export

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
# Budget & Formatting Helpers
# =====================================================================
def parse_budget_amount(text: str) -> Optional[float]:
    """Parse budget text supporting: '5tr', '1.5tr', '1,5 củ', '5000k', '5.000.000', or '0'."""
    clean = text.lower().strip()
    if clean in ("0", "tat", "tắt", "huy", "hủy", "none", "off", "disable"):
        return 0.0

    # Case A: Million suffix (tr, củ, triệu, m)
    m_million = re.match(r"^([\d\.,]+)\s*(tr|triệu|trieu|củ|cu|m)$", clean)
    if m_million:
        num_str = m_million.group(1).replace(",", ".")
        try:
            return float(num_str) * 1_000_000
        except ValueError:
            return None

    # Case B: Thousand suffix (k, nghìn, ngàn)
    m_thousand = re.match(r"^([\d\.,]+)\s*(k|nghìn|ngan|ngàn)$", clean)
    if m_thousand:
        num_str = m_thousand.group(1).replace(",", ".")
        try:
            return float(num_str) * 1_000
        except ValueError:
            return None

    # Case C: Plain number with dots/commas (e.g. 5.000.000 or 5000000)
    clean_digits = clean.replace(".", "").replace(",", "").replace(" ", "").replace("₫", "").replace("vnd", "")
    try:
        val = float(clean_digits)
        return val if val >= 0 else None
    except ValueError:
        return None


def resolve_category(input_str: str) -> Optional[str]:
    """Resolve user input string to one of the 5 canonical categories or '__total__'."""
    clean = input_str.strip().lower()

    if clean in ("tổng", "tong", "total", "tất cả", "tat ca", "all", "__total__"):
        return "__total__"
    if clean in ("ăn uống", "an uong", "ăn", "an", "food", "an sang", "an trua", "an toi", "đồ ăn", "do an"):
        return "Ăn uống"
    if clean in ("cà phê", "ca phe", "cf", "cafe", "coffee", "caffe", "nước", "nuoc", "trà sữa", "tra sua", "drink", "drinks"):
        return "Cà phê"
    if clean in ("công nghệ", "cong nghe", "tech", "sub", "subs", "subscription", "app", "apps", "phần mềm", "phan mem", "it", "saas"):
        return "Công nghệ"
    if clean in ("di chuyển", "di chuyen", "xăng", "xang", "grab", "be", "xe", "travel", "transport", "xe ôm", "xe om", "taxi"):
        return "Di chuyển"
    if clean in ("khác", "khac", "misc", "miscellaneous", "other", "others", "khac (misc)"):
        return "Khác"

    return None


def render_progress_bar(pct: float, length: int = 10) -> str:
    """Render visual emoji progress bar (e.g. 🟩🟩🟩⬜⬜⬜⬜⬜⬜⬜)."""
    filled = min(max(int(round(pct / 100 * length)), 0), length)
    empty = length - filled
    if pct >= 100:
        bar_char = "🟥"
    elif pct >= 80:
        bar_char = "🟨"
    else:
        bar_char = "🟩"
    return (bar_char * filled) + ("⬜" * empty)


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
        f"🤖 Tôi là trợ lý theo dõi chi tiêu cá nhân sử dụng <b>Gemini AI</b>.\n"
        f"📅 Hôm nay là: <code>{today_str}</code>\n\n"
        "✨ <b>Cách sử dụng cực kỳ đơn giản:</b>\n"
        "Bạn chỉ cần nhắn tin bình thường bằng tiếng Việt, ví dụ:\n"
        "• <code>50000 cơm gà d5</code>\n"
        "• <code>grab 35k đi học</code>\n"
        "• <code>sáng phở 45k cf 30k</code>\n"
        "• <code>hôm qua mua áo 250k shopee</code>\n\n"
        "📊 <b>Lệnh tra cứu & Quản lý:</b>\n"
        "• /today - Chi tiêu hôm nay\n"
        "• /month - Tổng kết chi tiêu tháng này\n"
        "• /budget - Quản lý hạn mức ngân sách tháng\n"
        "• /chart - Vẽ biểu đồ tròn cơ cấu chi tiêu tháng\n"
        "• /export - Xuất toàn bộ dữ liệu ra file Excel (.xlsx)\n"
        "• /recent - Xem các giao dịch gần nhất (kèm nút xóa)\n"
        "• /stats - Thống kê tổng quan\n"
        "• /help - Cẩm nang hướng dẫn chi tiết\n\n"
        "⏰ <i>Bot sẽ tự động gửi báo cáo điểm tin mỗi tối lúc 22:00!</i>"
    )
    if update.message:
        await update.message.reply_text(welcome_text, parse_mode=ParseMode.HTML)


@restricted
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send detailed help on /help."""
    help_text = (
        "📖 <b>CẨM NANG THEO DÕI & QUẢN LÝ TÀI CHÍNH</b>\n\n"
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
        "Mỗi lần ghi nhận chi tiêu, bot gửi kèm nút <b>[❌ Hoàn tác]</b> để bạn xóa ngay nếu ghi nhầm.\n\n"
        "<b>5. Quản lý Ngân sách theo Danh mục & Cảnh báo:</b>\n"
        "• <code>/budget</code>: Xem bảng tiến độ chi tiêu của từng danh mục\n"
        "• <code>/budget ăn uống 3tr</code>: Đặt hạn mức Ăn uống (3.000.000 ₫)\n"
        "• <code>/budget cà phê 800k</code>: Đặt hạn mức Cà phê (hoặc <code>/budget cf 800k</code>)\n"
        "• <code>/budget công nghệ 500k</code>: Đặt hạn mức Công nghệ / Subscriptions\n"
        "• <code>/budget di chuyển 1tr</code>: Đặt hạn mức Đi lại / Grab / Xăng\n"
        "• <code>/budget khác 500k</code>: Đặt hạn mức nhóm Khác / Misc\n"
        "• <code>/budget tổng 6tr</code>: Đặt tổng ngân sách tháng (hoặc <code>/budget 6tr</code>)\n"
        "• <code>/budget reset</code>: Xóa toàn bộ cấu hình ngân sách\n"
        "• Bot tự động gửi cảnh báo khi từng nhóm hoặc tổng chi chạm <b>80%</b> và <b>100%</b> ngân sách!\n\n"
        "<b>6. Biểu đồ & Xuất file:</b>\n"
        "• <code>/chart</code>: Vẽ biểu đồ tròn phân tích cơ cấu chi tiêu tháng\n"
        "• <code>/export</code>: Tải file Excel chuyên nghiệp với đầy đủ công thức\n\n"
        "<b>7. Báo cáo định kỳ tự động:</b>\n"
        "• 🌙 <b>22:00 mỗi tối</b>: Tự động tổng kết chi tiêu trong ngày\n"
        "• ☀️ <b>21:00 tối Chủ nhật</b>: Tự động tổng kết tuần"
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


@restricted
async def budget_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manage monthly expense budget per category and overall on /budget."""
    user = update.effective_user
    if not user or not update.message:
        return

    args = context.args
    now = get_current_datetime()

    # Case 1: Clearing/Resetting all budgets
    if args and args[0].lower() in ("reset", "clear", "xoa", "xóa"):
        await repo.clear_category_budgets(user.id)
        await update.message.reply_text(
            "✅ <b>Đã xóa toàn bộ cấu hình ngân sách (danh mục & tổng).</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    # Case 2: Setting a budget (overall or per category)
    if args:
        # Subcase 2A: Single argument -> overall total budget
        if len(args) == 1:
            parsed_total = parse_budget_amount(args[0])
            if parsed_total is not None:
                await repo.set_budget(user.id, parsed_total)
                if parsed_total == 0.0:
                    await update.message.reply_text(
                        "✅ <b>Đã tắt tổng ngân sách tháng.</b>", parse_mode=ParseMode.HTML
                    )
                else:
                    await update.message.reply_text(
                        f"🎯 <b>ĐÃ THIẾT LẬP TỔNG NGÂN SÁCH THÁNG {now.month:02d}/{now.year}</b>\n\n"
                        f"• Hạn mức: <b>{format_currency(parsed_total)}</b>\n\n"
                        "Bot sẽ cảnh báo khi tổng chi tiêu chạm ngưỡng <b>80%</b> và <b>100%</b> ngân sách!",
                        parse_mode=ParseMode.HTML,
                    )
                return

        # Subcase 2B: Multiple arguments -> Category + Amount
        # Try: Amount is the last argument
        cat_cand = " ".join(args[:-1])
        amt_cand = args[-1]
        resolved_cat = resolve_category(cat_cand)
        parsed_amt = parse_budget_amount(amt_cand)

        # If not matched, try: Amount is the first argument
        if resolved_cat is None or parsed_amt is None:
            amt_cand = args[0]
            cat_cand = " ".join(args[1:])
            resolved_cat = resolve_category(cat_cand)
            parsed_amt = parse_budget_amount(amt_cand)

        if resolved_cat is not None and parsed_amt is not None:
            if resolved_cat == "__total__":
                await repo.set_budget(user.id, parsed_amt)
                action_text = "tắt" if parsed_amt == 0 else f"đặt <b>{format_currency(parsed_amt)}</b> cho"
                await update.message.reply_text(
                    f"🎯 <b>Đã {action_text} Tổng ngân sách tháng {now.month:02d}/{now.year}.</b>",
                    parse_mode=ParseMode.HTML,
                )
            else:
                await repo.set_category_budget(user.id, resolved_cat, parsed_amt)
                emoji = get_category_emoji(resolved_cat)
                if parsed_amt == 0:
                    await update.message.reply_text(
                        f"✅ <b>Đã tắt ngân sách cho danh mục {emoji} {resolved_cat}.</b>",
                        parse_mode=ParseMode.HTML,
                    )
                else:
                    await update.message.reply_text(
                        f"🎯 <b>ĐÃ THIẾT LẬP NGÂN SÁCH {emoji} {resolved_cat.upper()}</b>\n\n"
                        f"• Hạn mức: <b>{format_currency(parsed_amt)}</b>\n\n"
                        f"Bot sẽ tự động cảnh báo khi bạn chi tiêu chạm <b>80%</b> và <b>100%</b> ngân sách nhóm này!",
                        parse_mode=ParseMode.HTML,
                    )
            return

        # Syntax Error fallback
        await update.message.reply_text(
            "⚠️ <b>Cú pháp đặt ngân sách không hợp lệ!</b>\n\n"
            "👉 <b>Đặt ngân sách theo từng danh mục:</b>\n"
            "• <code>/budget ăn uống 3tr</code>\n"
            "• <code>/budget cà phê 800k</code> (hoặc <code>/budget cf 800k</code>)\n"
            "• <code>/budget công nghệ 500k</code> (hoặc <code>/budget tech 500k</code>)\n"
            "• <code>/budget di chuyển 1tr</code> (hoặc <code>/budget grab 1tr</code>)\n"
            "• <code>/budget khác 500k</code> (hoặc <code>/budget misc 500k</code>)\n\n"
            "👉 <b>Đặt tổng ngân sách cả tháng:</b>\n"
            "• <code>/budget tổng 6tr</code> (hoặc <code>/budget 6tr</code>)\n"
            "• <code>/budget reset</code> (để xóa tất cả)",
            parse_mode=ParseMode.HTML,
        )
        return

    # Case 3: Viewing current budget dashboard
    monthly = await repo.get_monthly_summary(user.id, now.year, now.month)
    cat_spent_map = {c["category"]: c["total"] for c in monthly.get("categories", [])}
    total_spent = monthly["total"]

    cat_budgets = await repo.get_category_budgets(user.id)
    overall_budget = await repo.get_budget(user.id)

    lines = [f"🎯 <b>BẢNG THEO DÕI NGÂN SÁCH THÁNG {now.month:02d}/{now.year}</b>\n"]

    from config import CATEGORIES
    for cat in CATEGORIES:
        emoji = get_category_emoji(cat)
        spent = cat_spent_map.get(cat, 0.0)
        b_amount = cat_budgets.get(cat)

        if b_amount and b_amount > 0:
            rem = max(b_amount - spent, 0.0)
            pct = (spent / b_amount * 100)
            bar = render_progress_bar(pct, length=8)
            status_tag = "🟢 An toàn" if pct < 80 else ("⚠️ Sắp chạm!" if pct < 100 else "🚨 ĐÃ VƯỢT!")
            lines.append(
                f"<b>{emoji} {cat}:</b>\n"
                f"• Đã chi: <b>{format_currency(spent)}</b> / <b>{format_currency(b_amount)}</b> ({pct:.1f}%)\n"
                f"• [{bar}] {status_tag} (Còn lại: <b>{format_currency(rem)}</b>)\n"
            )
        else:
            lines.append(
                f"<b>{emoji} {cat}:</b>\n"
                f"• Đã chi: <b>{format_currency(spent)}</b> <i>(Chưa đặt hạn mức)</i>\n"
            )

    # Total summary row
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    if overall_budget and overall_budget > 0:
        tot_rem = max(overall_budget - total_spent, 0.0)
        tot_pct = (total_spent / overall_budget * 100)
        tot_bar = render_progress_bar(tot_pct, length=10)
        tot_tag = "🟢 An toàn" if tot_pct < 80 else ("⚠️ Sắp chạm!" if tot_pct < 100 else "🚨 ĐÃ VƯỢT!")
        lines.append(
            f"💰 <b>TỔNG CHI TIÊU THÁNG:</b>\n"
            f"• <b>{format_currency(total_spent)}</b> / <b>{format_currency(overall_budget)}</b> ({tot_pct:.1f}%)\n"
            f"• [{tot_bar}] {tot_tag}\n"
            f"• Còn lại: <b>{format_currency(tot_rem)}</b>"
        )
    else:
        lines.append(
            f"💰 <b>TỔNG CHI TIÊU THÁNG:</b> <b>{format_currency(total_spent)}</b> <i>(Chưa đặt tổng hạn mức)</i>"
        )

    lines.append("\n💡 <i>Bấm các nút bên dưới để xem hướng dẫn cài hạn mức nhanh:</i>")

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🍜 Ăn uống", callback_data="hint_budget_Ăn uống"),
            InlineKeyboardButton("☕ Cà phê", callback_data="hint_budget_Cà phê"),
        ],
        [
            InlineKeyboardButton("💻 Công nghệ", callback_data="hint_budget_Công nghệ"),
            InlineKeyboardButton("🛵 Di chuyển", callback_data="hint_budget_Di chuyển"),
        ],
        [
            InlineKeyboardButton("📦 Khác (Misc)", callback_data="hint_budget_Khác"),
            InlineKeyboardButton("💰 Tổng ngân sách", callback_data="hint_budget_Tổng"),
        ],
        [
            InlineKeyboardButton("🗑️ Xóa tất cả ngân sách", callback_data="clear_all_budgets"),
        ],
    ])

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )


@restricted
async def chart_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate and send category spending pie chart on /chart."""
    user = update.effective_user
    if not user or not update.message:
        return

    now = get_current_datetime()
    monthly = await repo.get_monthly_summary(user.id, now.year, now.month)
    categories = monthly.get("categories", [])
    total_amount = monthly.get("total", 0.0)

    if not categories or total_amount <= 0:
        await update.message.reply_text(
            f"📭 Tháng {now.month:02d}/{now.year} bạn chưa có khoản chi tiêu nào để vẽ biểu đồ."
        )
        return

    await context.bot.send_chat_action(
        chat_id=update.message.chat_id, action=ChatAction.UPLOAD_PHOTO
    )

    try:
        month_label = f"Tháng {now.month:02d}/{now.year}"
        img_buffer = generate_category_pie_chart(categories, month_label, total_amount)

        caption_lines = [
            f"📊 <b>BIỂU ĐỒ CHI TIÊU {month_label.upper()}</b>",
            f"💰 Tổng chi tiêu: <b>{format_currency(total_amount)}</b> ({monthly['count']} khoản)\n",
        ]
        for c in categories[:5]:
            emoji = get_category_emoji(c["category"])
            pct = (c["total"] / total_amount * 100) if total_amount > 0 else 0
            caption_lines.append(
                f"{emoji} {c['category']}: <b>{format_currency(c['total'])}</b> ({pct:.1f}%)"
            )

        await update.message.reply_photo(
            photo=img_buffer,
            caption="\n".join(caption_lines),
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        logger.error("Failed to generate chart: %s", exc, exc_info=True)
        await update.message.reply_text("❌ Có lỗi xảy ra khi tạo biểu đồ. Vui lòng thử lại sau.")


@restricted
async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Export all expenses to formatted Excel (.xlsx) file on /export."""
    user = update.effective_user
    if not user or not update.message:
        return

    await context.bot.send_chat_action(
        chat_id=update.message.chat_id, action=ChatAction.UPLOAD_DOCUMENT
    )

    expenses = await repo.get_all_expenses(user.id)
    if not expenses:
        await update.message.reply_text("📭 Bạn chưa có giao dịch nào trong dữ liệu để xuất file Excel.")
        return

    now = get_current_datetime()
    try:
        excel_buffer = generate_excel_export(expenses, title_label="Toàn bộ chi tiêu")
        filename = f"Bao_cao_chi_tieu_{now.strftime('%Y%m%d_%H%M')}.xlsx"

        total_spent = sum(e.amount for e in expenses)
        caption = (
            f"📑 <b>XUẤT DỮ LIỆU EXCEL THÀNH CÔNG</b>\n\n"
            f"• Tổng số giao dịch: <b>{len(expenses)}</b> khoản\n"
            f"• Tổng số tiền: <b>{format_currency(total_spent)}</b>\n"
            f"• Bao gồm: <i>Lịch sử chi tiết & Thống kê theo danh mục</i>\n\n"
            "✨ File đã được định dạng bảng biểu và công thức tính tổng tự động."
        )

        await update.message.reply_document(
            document=excel_buffer,
            filename=filename,
            caption=caption,
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        logger.error("Failed to export Excel file: %s", exc, exc_info=True)
        await update.message.reply_text("❌ Có lỗi khi tạo file Excel xuất dữ liệu. Vui lòng thử lại sau.")


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

    # In-line Budget Warning if user configured monthly category/total budgets
    try:
        monthly_status = await repo.get_monthly_summary(user.id, now.year, now.month)
        cat_spent_map = {c["category"]: c["total"] for c in monthly_status.get("categories", [])}
        cat_budgets = await repo.get_category_budgets(user.id)

        # 1. Check category alerts for the categories in this message
        affected_categories = {item.category for item in result.items}
        alerted_categories = set()
        for cat in affected_categories:
            cat_b = cat_budgets.get(cat)
            if cat_b and cat_b > 0:
                cat_s = cat_spent_map.get(cat, 0.0)
                cat_pct = (cat_s / cat_b * 100)
                emoji = get_category_emoji(cat)
                if cat_pct >= 100:
                    lines.append(
                        f"\n🚨 <b>VƯỢT HẠN MỨC {emoji} {cat.upper()}:</b>\n"
                        f"Đã tiêu <b>{format_currency(cat_s)}</b> / <b>{format_currency(cat_b)}</b> ({cat_pct:.1f}%)!"
                    )
                    alerted_categories.add(cat)
                elif cat_pct >= 80:
                    lines.append(
                        f"\n⚠️ <b>CHÚ Ý {emoji} {cat.upper()}:</b>\n"
                        f"Đã chạm <b>{cat_pct:.1f}%</b> hạn mức ({format_currency(cat_s)} / {format_currency(cat_b)})!"
                    )
                    alerted_categories.add(cat)

        # 2. Check total budget alert
        user_budget = await repo.get_budget(user.id)
        if user_budget and user_budget > 0:
            total_month_spent = monthly_status["total"]
            spent_pct = (total_month_spent / user_budget * 100)
            if spent_pct >= 100:
                lines.append(
                    f"\n🚨 <b>VƯỢT TỔNG NGÂN SÁCH THÁNG {now.month:02d}:</b>\n"
                    f"Tổng chi tiêu: <b>{format_currency(total_month_spent)}</b> / <b>{format_currency(user_budget)}</b> "
                    f"({spent_pct:.1f}% ngân sách)!"
                )
            elif spent_pct >= 80 and not alerted_categories:
                lines.append(
                    f"\n⚠️ <b>CHÚ Ý TỔNG NGÂN SÁCH THÁNG {now.month:02d}:</b>\n"
                    f"Tổng chi tiêu chạm <b>{spent_pct:.1f}%</b> "
                    f"({format_currency(total_month_spent)} / {format_currency(user_budget)})!"
                )
    except Exception as exc_budget:
        logger.warning("Error checking budget alert: %s", exc_budget)

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

    # Pattern 3: Budget hint button click
    if data.startswith("hint_budget_"):
        cat_name = data.replace("hint_budget_", "")
        emoji = get_category_emoji(cat_name) if cat_name != "Tổng" else "💰"
        sample_cmd = (
            f"/budget {cat_name.lower()} 1tr" if cat_name != "Tổng" else "/budget tổng 5tr"
        )
        sample_half = sample_cmd.replace("1tr", "500k")
        await query.answer()
        if query.message:
            await query.message.reply_text(
                f"👉 <b>Cài đặt ngân sách cho {emoji} {cat_name}:</b>\n\n"
                f"Hãy copy và gửi lệnh sau (thay bằng số tiền bạn muốn):\n"
                f"• <code>{sample_cmd}</code> (hoặc <code>{sample_half}</code>)\n\n"
                f"<i>(Gõ số 0 nếu muốn tắt ngân sách mục này: <code>/budget {cat_name.lower()} 0</code>)</i>",
                parse_mode=ParseMode.HTML,
            )
        return

    # Pattern 4: Clear all budgets
    if data == "clear_all_budgets":
        await repo.clear_category_budgets(user.id)
        await query.answer("Đã xóa tất cả ngân sách!", show_alert=False)
        if query.message:
            await query.edit_message_text(
                "🗑️ <b>Đã xóa toàn bộ cấu hình ngân sách (danh mục & tổng) thành công!</b>",
                parse_mode=ParseMode.HTML,
            )
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


# =====================================================================
# Scheduled Briefing Jobs (22:00 Daily & 21:00 Sunday)
# =====================================================================
async def scheduled_daily_report(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send daily 22:00 spending summary to authorized user(s)."""
    now = get_current_datetime()
    today_iso = now.strftime("%Y-%m-%d")
    today_display = now.strftime("%d/%m/%Y")

    for user_id in ALLOWED_TELEGRAM_USER_IDS:
        try:
            daily = await repo.get_daily_summary(user_id, today_iso)
            if daily["count"] > 0:
                expenses_today = await repo.get_expenses_by_date(user_id, today_iso)
                top_items = sorted(expenses_today, key=lambda x: x.amount, reverse=True)[:5]
                item_lines = [
                    f"{idx}. {get_category_emoji(e.category)} <b>{html.escape(e.description)}:</b> {format_currency(e.amount)}"
                    for idx, e in enumerate(top_items, 1)
                ]
                text = (
                    f"🌙 <b>ĐIỂM TIN CHI TIÊU HÔM NAY ({today_display})</b>\n\n"
                    f"💰 Hôm nay bạn đã chi: <b>{format_currency(daily['total'])}</b> ({daily['count']} khoản)\n\n"
                    f"<b>Top các khoản trong ngày:</b>\n" + "\n".join(item_lines) + "\n\n"
                    "👉 <i>Bạn còn khoản nào phát sinh hôm nay chưa kịp ghi không?</i>"
                )
            else:
                text = (
                    f"🌙 <b>ĐIỂM TIN TỐI ({today_display})</b>\n\n"
                    "✨ Hôm nay bạn chưa ghi nhận khoản chi tiêu nào.\n"
                    "Nếu có phát sinh chi tiêu trong ngày, hãy gửi tin nhắn để tôi ghi lại nhé!"
                )
            await context.bot.send_message(
                chat_id=user_id, text=text, parse_mode=ParseMode.HTML
            )
        except Exception as exc:
            logger.error("Failed to send daily briefing to user %s: %s", user_id, exc)


async def scheduled_weekly_report(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send Sunday 21:00 weekly summary to authorized user(s)."""
    now = get_current_datetime()
    for user_id in ALLOWED_TELEGRAM_USER_IDS:
        try:
            monthly = await repo.get_monthly_summary(user_id, now.year, now.month)
            budget = await repo.get_budget(user_id)
            budget_str = ""
            if budget and budget > 0:
                pct = (monthly["total"] / budget * 100)
                budget_str = f"\n• Ngân sách tháng: [{render_progress_bar(pct)}] <b>{pct:.1f}%</b> ({format_currency(monthly['total'])} / {format_currency(budget)})"

            text = (
                f"☀️ <b>TỔNG KẾT TUẦN & TÀI CHÍNH THÁNG {now.month:02d}/{now.year}</b>\n\n"
                f"• Tổng chi tiêu tháng: <b>{format_currency(monthly['total'])}</b> ({monthly['count']} khoản)"
                f"{budget_str}\n\n"
                "📊 Bạn có thể gõ <code>/chart</code> để xem biểu đồ hoặc <code>/export</code> để tải file Excel chi tiết nhé!"
            )
            await context.bot.send_message(
                chat_id=user_id, text=text, parse_mode=ParseMode.HTML
            )
        except Exception as exc:
            logger.error("Failed to send weekly briefing to user %s: %s", user_id, exc)


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
    application.add_handler(CommandHandler("budget", budget_command))
    application.add_handler(CommandHandler("chart", chart_command))
    application.add_handler(CommandHandler("export", export_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("recent", recent_command))

    # Register Callback Query Handler for Undo / Delete
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    # Register Text Message Handler (filters text without commands)
    application.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_message)
    )

    # Register Scheduled Briefing Jobs
    if application.job_queue:
        # Daily Briefing at 22:00
        application.job_queue.run_daily(
            scheduled_daily_report,
            time=datetime.time(hour=22, minute=0, tzinfo=LOCAL_TIMEZONE),
            name="daily_spending_report",
        )
        # Weekly Briefing at 21:00 on Sunday (day 6 in python weekday)
        application.job_queue.run_daily(
            scheduled_weekly_report,
            time=datetime.time(hour=21, minute=0, tzinfo=LOCAL_TIMEZONE),
            days=(6,),
            name="weekly_spending_report",
        )
        logger.info("Scheduled briefing jobs (22:00 daily, 21:00 Sunday) registered successfully.")

    logger.info("Expense Tracker Bot is starting polling...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

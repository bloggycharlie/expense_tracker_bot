"""Visualization and Export Services for Financial Tracker.

Generates modern charts with matplotlib and Excel workbooks with openpyxl.
"""

import io
from datetime import datetime
from typing import Any, Dict, List, Optional
import matplotlib
matplotlib.use("Agg")  # Non-interactive headless backend
import matplotlib.pyplot as plt
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from config import CATEGORY_EMOJIS, format_currency
from database import Expense


# Curated category color mapping
CATEGORY_COLORS: Dict[str, str] = {
    "Ăn uống": "#F59E0B",   # Amber / Orange
    "Cà phê": "#8B5CF6",    # Purple / Mocha
    "Công nghệ": "#3B82F6", # Bright Blue
    "Di chuyển": "#10B981", # Emerald Green
    "Khác": "#64748B",      # Slate Gray
}

# Fallback palette
CHART_COLORS = [
    "#F59E0B", "#8B5CF6", "#3B82F6", "#10B981", "#64748B",
    "#EC4899", "#06B6D4", "#EF4444",
]


def generate_category_pie_chart(
    category_data: List[Dict[str, Any]], month_label: str, total_amount: float
) -> io.BytesIO:
    """Generate a sleek, modern Donut Chart representing category spending breakdown."""
    if not category_data:
        raise ValueError("No category data available to plot chart.")

    # Sort categories by total descending
    sorted_cats = sorted(category_data, key=lambda x: x["total"], reverse=True)
    labels = [c["category"] for c in sorted_cats]
    amounts = [c["total"] for c in sorted_cats]
    slice_colors = [
        CATEGORY_COLORS.get(cat, CHART_COLORS[idx % len(CHART_COLORS)])
        for idx, cat in enumerate(labels)
    ]

    # Create figure with dark-themed aesthetic
    fig, ax = plt.subplots(figsize=(8, 7), dpi=150)
    fig.patch.set_facecolor("#0F172A")  # Dark slate background
    ax.set_facecolor("#0F172A")

    # Donut chart
    wedges, texts, autotexts = ax.pie(
        amounts,
        labels=None,  # Use clean legend instead of overlapping labels
        autopct="%1.1f%%",
        pctdistance=0.78,
        startangle=140,
        colors=slice_colors,
        wedgeprops=dict(width=0.45, edgecolor="#0F172A", linewidth=2.5),
    )

    # Style percentage texts inside donut
    for at in autotexts:
        at.set_color("#FFFFFF")
        at.set_fontsize(10)
        at.set_weight("bold")

    # Center circle annotation
    center_text = f"TỔNG CHI TIÊU\n{format_currency(total_amount)}"
    ax.text(
        0,
        0,
        center_text,
        horizontalalignment="center",
        verticalalignment="center",
        fontsize=13,
        weight="bold",
        color="#F8FAFC",
        linespacing=1.4,
    )

    # Title (Clean typography without emoji to ensure universal font rendering)
    ax.set_title(
        f"PHÂN TÍCH CHI TIÊU {month_label.upper()}",
        fontsize=14,
        weight="bold",
        color="#38BDF8",
        pad=20,
    )

    # Build descriptive Legend with clean bullets, Category names & Amounts
    legend_labels = []
    for c in sorted_cats:
        pct = (c["total"] / total_amount * 100) if total_amount > 0 else 0
        legend_labels.append(
            f"{c['category']}: {format_currency(c['total'])} ({pct:.1f}%)"
        )

    ax.legend(
        wedges,
        legend_labels,
        title="Danh mục chi tiêu",
        title_fontsize=11,
        loc="center left",
        bbox_to_anchor=(0.95, 0.5),
        frameon=True,
        facecolor="#1E293B",
        edgecolor="#334155",
        labelcolor="#E2E8F0",
        fontsize=10,
    )

    # Adjust layout and save to in-memory bytes
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf


def generate_excel_export(
    expenses: List[Expense], title_label: str = "Tất cả chi tiêu"
) -> io.BytesIO:
    """Generate a professionally styled Excel (.xlsx) workbook for expense tracking."""
    wb = Workbook()
    ws_main = wb.active
    ws_main.title = "Lịch sử chi tiêu"

    # Styling definitions
    font_title = Font(name="Segoe UI", size=15, bold=True, color="1E3A8A")
    font_header = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    font_data = Font(name="Segoe UI", size=10)
    font_total = Font(name="Segoe UI", size=11, bold=True, color="0F172A")

    fill_header = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    fill_zebra = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    fill_total = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")

    thin_border = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1"),
    )

    # Title Banner
    ws_main["A1"] = f"BÁO CÁO CHI TIÊU CÁ NHÂN - {title_label.upper()}"
    ws_main["A1"].font = font_title
    ws_main.merge_cells("A1:G1")

    ws_main["A2"] = f"Xuất lúc: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    ws_main["A2"].font = Font(name="Segoe UI", size=9, italic=True, color="64748B")
    ws_main.merge_cells("A2:G2")

    # Table Headers
    headers = [
        "STT",
        "Ngày",
        "Danh mục",
        "Nội dung chi tiêu",
        "Số tiền (VNĐ)",
        "Tin nhắn gốc",
        "Thời gian ghi",
    ]
    for col_idx, h in enumerate(headers, 1):
        cell = ws_main.cell(row=4, column=col_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border
    ws_main.row_dimensions[4].height = 28

    # Populate Data Rows
    current_row = 5
    for idx, exp in enumerate(expenses, 1):
        ws_main.cell(row=current_row, column=1, value=idx)
        ws_main.cell(row=current_row, column=2, value=exp.date)
        ws_main.cell(row=current_row, column=3, value=exp.category)
        ws_main.cell(row=current_row, column=4, value=exp.description)

        amt_cell = ws_main.cell(row=current_row, column=5, value=exp.amount)
        amt_cell.number_format = '#,##0 "₫"'

        ws_main.cell(row=current_row, column=6, value=exp.raw_message or "")
        ws_main.cell(row=current_row, column=7, value=str(exp.created_at or "")[:19])

        # Apply fonts and borders
        for col_idx in range(1, 8):
            c = ws_main.cell(row=current_row, column=col_idx)
            c.font = font_data
            c.border = thin_border
            if idx % 2 == 0:
                c.fill = fill_zebra
            if col_idx in (1, 2, 7):
                c.alignment = Alignment(horizontal="center", vertical="center")
            elif col_idx == 5:
                c.alignment = Alignment(horizontal="right", vertical="center")
            else:
                c.alignment = Alignment(horizontal="left", vertical="center")

        ws_main.row_dimensions[current_row].height = 20
        current_row += 1

    # Total Row
    if expenses:
        ws_main.merge_cells(f"A{current_row}:D{current_row}")
        total_label_cell = ws_main.cell(row=current_row, column=1, value="TỔNG CỘNG:")
        total_label_cell.font = font_total
        total_label_cell.alignment = Alignment(horizontal="right", vertical="center")

        sum_cell = ws_main.cell(row=current_row, column=5, value=f"=SUM(E5:E{current_row - 1})")
        sum_cell.font = font_total
        sum_cell.number_format = '#,##0 "₫"'
        sum_cell.alignment = Alignment(horizontal="right", vertical="center")

        for col_idx in range(1, 8):
            c = ws_main.cell(row=current_row, column=col_idx)
            c.fill = fill_total
            c.border = thin_border

        ws_main.row_dimensions[current_row].height = 24

    # Sheet 2: Category Summary
    ws_cat = wb.create_sheet(title="Tổng kết theo danh mục")
    ws_cat["A1"] = "TỔNG KẾT CHI TIÊU THEO DANH MỤC"
    ws_cat["A1"].font = font_title
    ws_cat.merge_cells("A1:D1")

    cat_headers = ["Danh mục", "Tổng tiền (VNĐ)", "Số giao dịch", "Tỷ trọng (%)"]
    for col_idx, h in enumerate(cat_headers, 1):
        c = ws_cat.cell(row=3, column=col_idx, value=h)
        c.font = font_header
        c.fill = fill_header
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = thin_border

    # Aggregate categories
    cat_summary: Dict[str, Dict[str, Any]] = {}
    total_spent = sum(e.amount for e in expenses)
    for e in expenses:
        if e.category not in cat_summary:
            cat_summary[e.category] = {"total": 0.0, "count": 0}
        cat_summary[e.category]["total"] += e.amount
        cat_summary[e.category]["count"] += 1

    row_c = 4
    for cat_name, stats in sorted(cat_summary.items(), key=lambda x: x[1]["total"], reverse=True):
        emoji = CATEGORY_EMOJIS.get(cat_name, "📁")
        ws_cat.cell(row=row_c, column=1, value=f"{emoji} {cat_name}").alignment = Alignment(horizontal="left")
        
        c_amt = ws_cat.cell(row=row_c, column=2, value=stats["total"])
        c_amt.number_format = '#,##0 "₫"'
        c_amt.alignment = Alignment(horizontal="right")

        ws_cat.cell(row=row_c, column=3, value=stats["count"]).alignment = Alignment(horizontal="center")

        pct = (stats["total"] / total_spent) if total_spent > 0 else 0
        c_pct = ws_cat.cell(row=row_c, column=4, value=pct)
        c_pct.number_format = "0.0%"
        c_pct.alignment = Alignment(horizontal="right")

        for col_idx in range(1, 5):
            cell = ws_cat.cell(row=row_c, column=col_idx)
            cell.font = font_data
            cell.border = thin_border

        row_c += 1

    # Auto-fit Column Widths across both sheets
    for ws in [ws_main, ws_cat]:
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf

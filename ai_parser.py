"""Gemini 3.8 Flash AI Parser for Vietnamese Expense Messages.

Utilizes the official google-genai SDK with Pydantic Structured Outputs.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import List, Optional
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from config import CATEGORIES, GEMINI_API_KEY, get_current_datetime

logger = logging.getLogger(__name__)


# =====================================================================
# Pydantic Schemas for Structured Outputs
# =====================================================================
class ParsedExpenseItem(BaseModel):
    """Structured representation of a single extracted expense item."""
    amount: float = Field(
        ...,
        description=(
            "The numeric amount in Vietnamese Dong (VND). Must be a clean number without currency signs. "
            "Convert slang: '45k' -> 45000, '50 cành' -> 50000, '1 lít' -> 100000, '1.5tr' or '1.5 củ' -> 1500000, '50000' -> 50000."
        ),
    )
    category: str = Field(
        ...,
        description=(
            f"One of the allowed categories: {', '.join(CATEGORIES)}. "
            "Choose 'Ăn uống' for meals/food; 'Cà phê' for coffee, tea, cafe drinks; "
            "'Công nghệ' for app subscriptions (Netflix, Spotify, iCloud, ChatGPT, SaaS); "
            "'Di chuyển' for transportation (grab, be, gas, parking); or 'Khác' for miscellaneous remaining expenses."
        ),
    )
    description: str = Field(
        ...,
        description="Clean, concise summary note of what was purchased (e.g., 'Phở sáng', 'Grab đi học', 'Cơm gà d5', 'Cà phê').",
    )
    date: str = Field(
        ...,
        description=(
            "Date of the transaction in 'YYYY-MM-DD' format. "
            "If user mentions relative dates like 'hôm qua' (yesterday), calculate relative to CURRENT_DATE. Otherwise use CURRENT_DATE."
        ),
    )


class ExpenseParseResponse(BaseModel):
    """Complete structured response from Gemini model."""
    is_expense: bool = Field(
        ...,
        description="True if the message represents one or more financial expenses. False if greeting, question, or general chat.",
    )
    items: List[ParsedExpenseItem] = Field(
        default_factory=list,
        description="List of detected expense items. Must be empty if is_expense is False.",
    )
    user_reply: Optional[str] = Field(
        default=None,
        description="Brief, helpful Vietnamese reply if is_expense is False (e.g. friendly greeting or syntax guidance).",
    )


# =====================================================================
# Gemini Client and Parser Service
# =====================================================================
class ExpenseAIParser:
    """Service wrapping Google GenAI SDK to parse natural Vietnamese expense texts."""

    def __init__(self, api_key: str = GEMINI_API_KEY):
        self.api_key = api_key
        self._client: Optional[genai.Client] = None

    @property
    def client(self) -> genai.Client:
        """Lazy initialization of genai.Client with timeout."""
        if self._client is None:
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY is not set. Please configure it in .env")
            self._client = genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(timeout=10000),
            )
        return self._client

    def _build_system_instruction(self, current_dt: datetime) -> str:
        current_date_str = current_dt.strftime("%Y-%m-%d")
        day_of_week = current_dt.strftime("%A")
        return f"""Bạn là trợ lý AI chuyên nghiệp phân tích chi tiêu cá nhân bằng tiếng Việt cho Telegram Bot.
NGÀY HIỆN TẠI: {current_date_str} ({day_of_week})

NHIỆM VỤ:
Trích xuất tất cả các khoản chi tiêu tài chính từ tin nhắn tiếng Việt tự nhiên của người dùng và trả về theo định dạng JSON có cấu trúc.

QUY TẮC NHẬN DIỆN TIỀN TỆ VIỆT NAM (VND):
- "k", "k vnd", "nghìn", "ngàn" = nhân 1.000 (Ví dụ: 45k -> 45000, 35k -> 35000)
- "cành" = nhân 1.000 (Ví dụ: 50 cành -> 50000)
- "lít", "xị" = nhân 100.000 (Ví dụ: 2 lít -> 200000)
- "củ", "tr", "triệu" = nhân 1.000.000 (Ví dụ: 1.5tr -> 1500000, 2 củ -> 2000000)
- Số nguyên trần (50000, 35000) = giữ nguyên giá trị số
- TẤT CẢ số tiền phải là số thực dương (float), không có dấu phẩy hay ký hiệu tiền tệ trong trường amount.

QUY TẮC TÁCH NHIỀU KHOẢN TRONG 1 TIN NHẮN (MULTI-ITEM):
- Nếu tin nhắn chứa nhiều khoản chi tiêu (Ví dụ: "sáng phở 45k cf 30k" hoặc "grab 32k, trưa bún bò 40k"), bạn BẮT BUỘC phải tách thành từng mục riêng trong danh sách items:
  1. Phở sáng (45.000 VND - Ăn uống)
  2. Cà phê (30.000 VND - Cà phê)

QUY TẮC XÁC ĐỊNH DANH MỤC (CATEGORY):
BẮT BUỘC chỉ chọn đúng 1 trong 5 danh mục sau:
1. "Ăn uống": đồ ăn, bữa ăn, thực phẩm, cơm, phở, bún, bánh mì, đồ ăn vặt, tiệm ăn, siêu thị thực phẩm... (LƯU Ý: cà phê, trà sữa, đồ uống giải khát phải xếp vào "Cà phê").
2. "Cà phê": cà phê, cf, coffee, trà sữa, trà đá, nước ép, sinh tố, đồ uống tại quán nước/tiệm cà phê (Highlands, Starbucks, Phê La, The Coffee House, Phúc Long, quán cóc...).
3. "Công nghệ": subscription các app/phần mềm, dịch vụ số (Netflix, Spotify, iCloud, ChatGPT, Claude, Youtube Premium, Google One, hosting, vps, domain, app store...).
4. "Di chuyển": chi phí đi lại gồm tiền xăng xe, xe ôm công nghệ, Grab, Be, Gojek, taxi, vé xe buýt, vé gửi xe, tiền gửi xe, tiền sửa xe, vá xe...
5. "Khác": các thứ còn lại nếu không thuộc 4 danh mục trên (mua sắm đồ dùng gia đình, quần áo, y tế, cắt tóc, v.v.).

QUY TẮC NGÀY THÁNG (DATE):
- Mặc định là ngày hôm nay: {current_date_str}
- Nếu người dùng nhắc "hôm qua", hãy tính trừ 1 ngày so với ngày hiện tại.
- - Nếu người dùng nhắc "hôm kia", hãy tính trừ 2 ngày so với ngày hiện tại.
- Định dạng ngày BẮT BUỘC là YYYY-MM-DD.

NẾU TIN NHẮN KHÔNG PHẢI KHOẢN CHI TIÊU MỚI (Ví dụ: chào hỏi, hỏi cách dùng, yêu cầu xóa/sửa/hủy bỏ giao dịch):
- Đặt is_expense = False
- items = []
- Nếu người dùng muốn XÓA/BỎ/HỦY khoản chi tiêu: điền user_reply hướng dẫn: "💡 Để xóa khoản chi tiêu, bạn vui lòng gõ lệnh /recent để xem danh sách gần đây và bấm nút [🗑️ Xóa] tương ứng, hoặc bấm nút [❌ Hoàn tác] ngay khi vừa ghi nhé!"
- Nếu là chào hỏi hoặc nội dung khác: điền user_reply câu chào lịch sự và hướng dẫn ngắn gọn (ví dụ: "Chào bạn! Hãy nhắn khoản chi tiêu để tôi ghi nhận, ví dụ: 'Cơm trưa 40k' hoặc 'Grab 35k đi làm' nhé!").
"""

    def _sync_parse(self, text: str, current_dt: datetime) -> ExpenseParseResponse:
        """Synchronous execution of Gemini API call with fast fallback models."""
        system_instruction = self._build_system_instruction(current_dt)
        candidate_models = ["gemini-3.5-flash-lite", "gemini-flash-lite-latest", "gemini-3.1-flash-lite"]

        last_error = None
        for model_name in candidate_models:
            try:
                interaction = self.client.interactions.create(
                    model=model_name,
                    input=f"{system_instruction}\n\nTin nhắn người dùng: {text}",
                    response_format={
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": ExpenseParseResponse.model_json_schema(),
                    },
                )
                output = interaction.output_text or "{}"
                return ExpenseParseResponse.model_validate_json(output)
            except Exception as exc:
                logger.warning("Interactions API with %s failed (%s), trying next...", model_name, exc)
                last_error = exc

        logger.error("All AI parse models failed. Last error: %s", last_error)
        raise last_error

    async def parse_expense(
        self, text: str, current_dt: Optional[datetime] = None
    ) -> ExpenseParseResponse:
        """Asynchronously parse Vietnamese natural text into structured expense items."""
        if current_dt is None:
            current_dt = get_current_datetime()

        # Run synchronous SDK call in thread pool to prevent blocking Telegram async loop
        return await asyncio.to_thread(self._sync_parse, text, current_dt)


# Default singleton instance
parser = ExpenseAIParser()

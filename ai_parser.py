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
            "Choose 'Ăn uống' for food, drinks, coffee, snacks; 'Di chuyển' for grab, taxi, gas, parking; "
            "'Mua sắm' for clothes, gadgets, shopping; 'Hóa đơn & Dịch vụ' for utilities, wifi, rent; "
            "'Giải trí' for movies, games, travel; 'Sức khỏe' for medicine, gym; 'Giáo dục' for books, courses; or 'Khác'."
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
        """Lazy initialization of genai.Client."""
        if self._client is None:
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY is not set. Please configure it in .env")
            self._client = genai.Client(api_key=self.api_key)
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
  2. Cà phê (30.000 VND - Ăn uống)

QUY TẮC XÁC ĐỊNH DANH MỤC (CATEGORY):
Chỉ chọn đúng 1 trong các danh mục sau:
1. "Ăn uống": đồ ăn, nước uống, phở, bún, cơm, bánh mì, trà sữa, cf, cà phê, siêu thị thực phẩm, ăn vặt...
2. "Di chuyển": grab, be, taxi, xe ôm, xăng, gửi xe, vé xe bus, vé tàu, vé máy bay, sửa xe...
3. "Mua sắm": quần áo, giày dép, shopee, lazada, tiktok shop, đồ gia dụng, thiết bị công nghệ...
4. "Hóa đơn & Dịch vụ": điện, nước, internet, tiền phòng/tiền nhà, netflix, spotify, icloud, cước điện thoại...
5. "Giải trí": xem phim rạp, karaoke, chơi game, concert, du lịch...
6. "Sức khỏe": thuốc, khám bệnh, nha khoa, phòng gym, yoga, thực phẩm chức năng...
7. "Giáo dục": học phí, sách vở, văn phòng phẩm, khóa học online...
8. "Khác": các khoản không thuộc nhóm trên.

QUY TẮC NGÀY THÁNG (DATE):
- Mặc định là ngày hôm nay: {current_date_str}
- Nếu người dùng nhắc "hôm qua", hãy tính trừ 1 ngày so với ngày hiện tại.
- Nếu người dùng nhắc "hôm kia", hãy tính trừ 2 ngày so với ngày hiện tại.
- Định dạng ngày BẮT BUỘC là YYYY-MM-DD.

NẾU TIN NHẮN KHÔNG PHẢI KHOẢN CHI TIÊU:
- Đặt is_expense = False
- items = []
- Điền user_reply một câu chào lịch sự và hướng dẫn ngắn gọn (ví dụ: "Chào bạn! Hãy nhắn cho tôi khoản chi của bạn, ví dụ: 'Cơm trưa 40k' hoặc 'Grab 35k đi làm' nhé!").
"""

    def _sync_parse(self, text: str, current_dt: datetime) -> ExpenseParseResponse:
        """Synchronous execution of Gemini API call with Structured Outputs."""
        system_instruction = self._build_system_instruction(current_dt)

        # Primary: Official Interactions API for gemini-3.8-flash
        try:
            interaction = self.client.interactions.create(
                model="gemini-3.8-flash",
                input=f"{system_instruction}\n\nTin nhắn người dùng: {text}",
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": ExpenseParseResponse.model_json_schema(),
                },
            )
            output = interaction.output_text or "{}"
            return ExpenseParseResponse.model_validate_json(output)

        except Exception as e_interactions:
            logger.warning(
                "Interactions API encountered an issue (%s), attempting fallback...",
                e_interactions,
            )

            # Fallback: Using models.generate_content with types.GenerateContentConfig
            try:
                config = types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ExpenseParseResponse,
                    system_instruction=system_instruction,
                    temperature=0.1,
                )
                response = self.client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=f"Tin nhắn người dùng: {text}",
                    config=config,
                )
                raw_text = response.text or "{}"
                return ExpenseParseResponse.model_validate_json(raw_text)
            except Exception as e_fallback:
                logger.error("All AI parse attempts failed. Error: %s", e_fallback)
                raise

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

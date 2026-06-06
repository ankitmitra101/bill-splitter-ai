import time
from pydantic import BaseModel, Field, ValidationError

from google import genai
from google.genai import types
from google.genai.errors import APIError

from config import config
from schemas.extracted import ExtractedReceipt, ExtractedLineItem

# ── Prompts ──────────────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """
You are an expert OCR and data extraction assistant for restaurant receipts.
Extract the structured data from the provided receipt image.

Rules:
1. Extract exactly what is printed on the receipt.
2. DO NOT perform any arithmetic. DO NOT guess or compute missing values.
3. If a value is missing or unreadable, return null.
4. All monetary amounts must be numbers in Rupees (e.g., 150.50). Do not include currency symbols.
5. Provide a confidence score between 0.0 and 1.0 based on image clarity and legibility.
"""

# ── Internal LLM Schema (Rupees) ──────────────────────────────────────────────
# We use this schema to parse the LLM output in Rupees, before converting
# the monetary fields to paise for our internal system.

class LLMLineItem(BaseModel):
    name: str
    qty: int | None = None
    amount: float | None = None  # Rupees


class LLMExtractedReceipt(BaseModel):
    restaurant_name: str | None = None
    date: str | None = None
    bill_number: str | None = None
    items: list[LLMLineItem] = Field(default_factory=list)
    subtotal: float | None = None
    service_charge_pct: float | None = None
    service_charge_amount: float | None = None
    discount_description: str | None = None
    discount_pct: float | None = None
    discount_amount: float | None = None
    gst_pct: float | None = None
    gst_amount: float | None = None
    round_off: float | None = None
    grand_total: float | None = None
    confidence_score: float = Field(default=1.0)


# ── Conversion Utilities ─────────────────────────────────────────────────────

def _rupees_to_paise(rupees: float | None) -> int | None:
    """Safely convert Rupee floats to Paise integers."""
    if rupees is None:
        return None
    return int(round(rupees * 100))


# ── Main Extraction Logic ────────────────────────────────────────────────────

def extract_receipt(image_bytes: bytes) -> ExtractedReceipt:
    """
    Extracts structured data from a receipt image bytes using Gemini 2.5 Flash via google-genai SDK.
    
    Implements a retry loop for transient API failures and relies on the SDK's
    native Pydantic parsing before converting amounts to paise.
    """
    if not config.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not configured.")

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    
    image_part = types.Part.from_bytes(
        data=image_bytes,
        mime_type="image/jpeg"
    )

    generation_config = types.GenerateContentConfig(
        temperature=config.GEMINI_TEMPERATURE,
        system_instruction=EXTRACTION_PROMPT,
        response_mime_type="application/json",
        response_schema=LLMExtractedReceipt,
    )

    last_exception = None
    
    for attempt in range(config.MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=[image_part],
                config=generation_config
            )
            
            # The SDK natively parses into the Pydantic schema
            llm_result: LLMExtractedReceipt = response.parsed
            
            if llm_result is None:
                raise ValueError("SDK failed to parse the response into the requested schema.")

            # Map LLM (Rupee) model -> Internal (Paise) model
            extracted_items = [
                ExtractedLineItem(
                    name=item.name,
                    qty=item.qty,
                    amount=_rupees_to_paise(item.amount)
                )
                for item in llm_result.items
            ]
            
            return ExtractedReceipt(
                restaurant_name=llm_result.restaurant_name,
                date=llm_result.date,
                bill_number=llm_result.bill_number,
                items=extracted_items,
                subtotal=_rupees_to_paise(llm_result.subtotal),
                service_charge_pct=llm_result.service_charge_pct,
                service_charge_amount=_rupees_to_paise(llm_result.service_charge_amount),
                discount_description=llm_result.discount_description,
                discount_pct=llm_result.discount_pct,
                discount_amount=_rupees_to_paise(llm_result.discount_amount),
                gst_pct=llm_result.gst_pct,
                gst_amount=_rupees_to_paise(llm_result.gst_amount),
                round_off=_rupees_to_paise(llm_result.round_off),
                grand_total=_rupees_to_paise(llm_result.grand_total),
                confidence_score=llm_result.confidence_score,
                ai_calls=attempt + 1
            )

        except (ValidationError, ValueError, APIError) as e:
            # Transient parsing or API errors
            last_exception = e
            time.sleep(config.RETRY_BACKOFF_FACTOR * (attempt + 1))
        except Exception as e:
            # Other network/unexpected errors
            last_exception = e
            time.sleep(config.RETRY_BACKOFF_FACTOR * (attempt + 1))

    raise RuntimeError(
        f"Failed to extract receipt after {config.MAX_RETRIES} attempts. Last error: {last_exception}"
    ) from last_exception

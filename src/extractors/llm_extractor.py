"""
Multimodal LLM extractor using Google Gemini API.

Sends the order image to a vision-capable LLM with a structured JSON schema
prompt and parses the response into an OrderData model.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from src.extractors.base import BaseExtractor, ExtractionError
from src.models.order import OrderData


EXTRACTION_PROMPT = """You are a precise data extraction assistant. Analyze this purchase order image and extract ALL information into the exact JSON schema below.

RULES:
- Extract every field visible in the image. Use empty string "" for missing text fields.
- Dates must be in YYYY-MM-DD format.
- All monetary values must be decimal numbers (e.g., "24.50", not "24,50").
- VAT percentages are plain numbers (e.g., "19" not "19%").
- Discount percentages are plain numbers (e.g., "5" not "5%").
- For paid_status: use "PAID" or "UNPAID".
- Payment method must be one of: "Bank Transfer", "Credit Card", "SEPA Direct Debit".
- If delivery address is same as billing, set delivery_address to null.

JSON SCHEMA:
{
  "order_date": "YYYY-MM-DD",
  "external_reference": "string (PO number / customer reference)",
  "debtor": {
    "company": "string",
    "first_name": "string",
    "last_name": "string",
    "alias": "string (short identifier)",
    "billing_address": {
      "street": "string",
      "zip": "string",
      "city": "string",
      "country": "string",
      "email": "string",
      "telephone": "string"
    },
    "delivery_address": null | { same fields as billing_address },
    "payment_method": "Bank Transfer|Credit Card|SEPA Direct Debit",
    "discount_percent": "0",
    "net_or_gross": "Net"
  },
  "items": [
    {
      "sku": "string (item/article number)",
      "description": "string",
      "quantity": "decimal",
      "unit_net_price": "decimal",
      "vat_percent": "decimal",
      "discount_percent": "decimal",
      "source_total": "decimal (line total from image)"
    }
  ],
  "source_total_net": "decimal or null",
  "source_total_vat": "decimal or null",
  "source_total_gross": "decimal or null",
  "paid_status": "PAID|UNPAID",
  "payment_date": "YYYY-MM-DD or null"
}

Return ONLY the JSON object, no markdown fences, no explanation."""


class LLMExtractor(BaseExtractor):
    """
    Extracts order data from images using Google Gemini multimodal API.

    Requires the GOOGLE_API_KEY environment variable to be set.
    """

    def __init__(
        self,
        model_name: str = "gemini-2.5-flash",
        api_key: str | None = None,
    ):
        self._model_name = model_name
        self._api_key = (
            api_key
            or os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("GEMINI_API_KEY", "")
        )

        # Fallback: check for .env file in project root
        if not self._api_key:
            env_path = Path(__file__).resolve().parent.parent.parent / ".env"
            if env_path.exists():
                try:
                    for line in env_path.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if "=" in line and not line.startswith("#"):
                            k, v = line.split("=", 1)
                            if k.strip() in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
                                self._api_key = v.strip().strip('"').strip("'")
                                break
                except Exception:
                    pass

    def extract(self, image_path: Path) -> OrderData:
        if not self._api_key:
            raise ExtractionError(
                "GOOGLE_API_KEY environment variable is not set. "
                "Set it or use --mock mode for offline testing."
            )

        image_path = Path(image_path)
        if not image_path.exists():
            raise ExtractionError(f"Image file not found: {image_path}")

        try:
            import google.generativeai as genai

            genai.configure(api_key=self._api_key)
            model = genai.GenerativeModel(self._model_name)

            # Upload and send image
            image_data = image_path.read_bytes()
            mime_type = self._guess_mime(image_path)

            response = model.generate_content(
                [
                    EXTRACTION_PROMPT,
                    {"mime_type": mime_type, "data": image_data},
                ],
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=4096,
                ),
            )

            raw_text = response.text.strip()

            # Strip markdown code fences if present
            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
            raw_text = re.sub(r"\s*```$", "", raw_text)

            data = json.loads(raw_text)
            return OrderData(**data)

        except json.JSONDecodeError as e:
            raise ExtractionError(f"LLM returned invalid JSON: {e}\nRaw: {raw_text[:500]}")
        except ImportError:
            raise ExtractionError(
                "google-generativeai package is not installed. "
                "Run: pip install google-generativeai"
            )
        except Exception as e:
            raise ExtractionError(f"LLM extraction failed: {e}")

    @staticmethod
    def _guess_mime(path: Path) -> str:
        ext = path.suffix.lower()
        return {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".tif": "image/tiff",
            ".tiff": "image/tiff",
            ".pdf": "application/pdf",
            ".webp": "image/webp",
        }.get(ext, "image/png")

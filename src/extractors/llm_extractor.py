"""
Multimodal LLM extractor using Google Gemini API.

Sends the order image to a vision-capable LLM with a structured JSON schema
prompt and parses the response into an OrderData model.
"""

from __future__ import annotations

import json
import os
import re
import time
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
        model_name: str | None = None,
        api_key: str | None = None,
    ):
        self._model_name = (
            model_name
            or os.environ.get("GEMINI_MODEL")
            or "gemini-3.5-flash"
        )
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
            # Upload and read image
            image_data = image_path.read_bytes()
            mime_type = self._guess_mime(image_path)

            candidate_models = [self._model_name]
            for alt in ["gemini-3.5-flash", "gemini-3.6-flash", "gemini-flash-latest"]:
                if alt not in candidate_models:
                    candidate_models.append(alt)

            raw_text = None
            used_model = None
            last_err = None

            try:
                import logging
                logging.getLogger("google_genai").setLevel(logging.ERROR)
                logging.getLogger("httpx").setLevel(logging.WARNING)

                from google import genai
                from google.genai import types

                client = genai.Client(api_key=self._api_key)
                part = types.Part.from_bytes(data=image_data, mime_type=mime_type)

                for m_name in candidate_models:
                    for attempt in range(2):
                        try:
                            response = client.models.generate_content(
                                model=m_name,
                                contents=[EXTRACTION_PROMPT, part],
                                config=types.GenerateContentConfig(
                                    temperature=0.1,
                                    max_output_tokens=4096,
                                ),
                            )
                            raw_text = response.text.strip()
                            used_model = m_name
                            break
                        except Exception as ex:
                            last_err = ex
                            err_str = str(ex).lower()
                            # If model is 404 or quota exhausted, try next model immediately
                            if any(k in err_str for k in ["quota", "resourceexhausted", "404", "not_found"]):
                                break
                            # If transient network disconnect, retry once after 2s
                            if attempt == 0 and any(k in err_str for k in ["disconnected", "reset", "closed", "timeout", "429"]):
                                time.sleep(2)
                                continue
                            break

                    if raw_text is not None:
                        break

            except ImportError:
                import google.generativeai as legacy_genai
                legacy_genai.configure(api_key=self._api_key)
                for m_name in candidate_models:
                    for attempt in range(2):
                        try:
                            model = legacy_genai.GenerativeModel(m_name)
                            response = model.generate_content(
                                [EXTRACTION_PROMPT, {"mime_type": mime_type, "data": image_data}],
                                generation_config=legacy_genai.types.GenerationConfig(temperature=0.1, max_output_tokens=4096),
                                request_options={"timeout": 60},
                            )
                            raw_text = response.text.strip()
                            used_model = m_name
                            break
                        except Exception as ex:
                            last_err = ex
                            err_str = str(ex).lower()
                            if any(k in err_str for k in ["quota", "resourceexhausted", "404", "not_found"]):
                                break
                            if attempt == 0 and any(k in err_str for k in ["disconnected", "reset", "closed", "timeout", "429"]):
                                time.sleep(2)
                                continue
                            break

                    if raw_text is not None:
                        break

            if raw_text is None:
                raise last_err or ExtractionError("All candidate models failed")

            # Print LLM response to terminal for inspection
            print("\n" + "=" * 65)
            print(f"  [GEMINI LLM RESPONSE] Model: {used_model}")
            print("=" * 65)
            try:
                print(raw_text)
            except Exception:
                safe_text = raw_text.encode("ascii", errors="replace").decode("ascii")
                print(safe_text)
            print("=" * 65 + "\n")

            # Strip markdown code fences if present
            clean_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
            clean_text = re.sub(r"\s*```$", "", clean_text)

            data = json.loads(clean_text)
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

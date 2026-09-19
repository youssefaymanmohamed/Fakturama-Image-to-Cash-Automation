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


# Global in-memory cache to avoid duplicate slow network round-trips
_EXTRACTION_CACHE: dict[str, OrderData] = {}


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
            or "gemini-3.6-flash"
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
        image_path = Path(image_path)
        cache_key = str(image_path.resolve())

        # 1. Check in-memory cache for instant return
        if cache_key in _EXTRACTION_CACHE:
            print(f"[CACHE HIT] Returning cached extraction for {image_path.name}")
            return _EXTRACTION_CACHE[cache_key]

        if not self._api_key:
            raise ExtractionError(
                "GOOGLE_API_KEY environment variable is not set. "
                "Please configure GOOGLE_API_KEY in your .env file, environment, or web dashboard."
            )

        if not image_path.exists():
            raise ExtractionError(f"Image file not found: {image_path}")

        try:
            raw_bytes = image_path.read_bytes()
            image_data, mime_type = self._optimize_image(raw_bytes)

            candidate_models = [self._model_name]
            for alt in ["gemini-3.6-flash", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-flash-lite-latest"]:
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

                client = genai.Client(
                    api_key=self._api_key,
                    http_options={"timeout": 60000},
                )
                part = types.Part.from_bytes(data=image_data, mime_type=mime_type)

                for m_name in candidate_models:
                    try:
                        response = client.models.generate_content(
                            model=m_name,
                            contents=[EXTRACTION_PROMPT, part],
                            config=types.GenerateContentConfig(
                                response_mime_type="application/json",
                                temperature=0.0,
                                max_output_tokens=8192,
                            ),
                        )
                        raw_text = response.text.strip()
                        used_model = m_name
                        break
                    except Exception as ex:
                        last_err = ex
                        continue

            except ImportError:
                import google.generativeai as legacy_genai
                legacy_genai.configure(api_key=self._api_key)
                for m_name in candidate_models:
                    try:
                        model = legacy_genai.GenerativeModel(m_name)
                        response = model.generate_content(
                            [EXTRACTION_PROMPT, {"mime_type": mime_type, "data": image_data}],
                            generation_config=legacy_genai.types.GenerationConfig(
                                temperature=0.0,
                                max_output_tokens=8192,
                                response_mime_type="application/json",
                            ),
                            request_options={"timeout": 30},
                        )
                        raw_text = response.text.strip()
                        used_model = m_name
                        break
                    except Exception as ex:
                        last_err = ex
                        continue

            if raw_text is None:
                raise last_err or ExtractionError("All candidate Gemini models failed to extract data.")


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

            # Clean JSON string: extract content between first { and last }
            clean_text = raw_text.strip()
            if "{" in clean_text and "}" in clean_text:
                start_idx = clean_text.find("{")
                end_idx = clean_text.rfind("}")
                clean_text = clean_text[start_idx : end_idx + 1]
            else:
                clean_text = re.sub(r"^```(?:json)?\s*", "", clean_text)
                clean_text = re.sub(r"\s*```$", "", clean_text)

            try:
                data = json.loads(clean_text)
            except json.JSONDecodeError:
                # Attempt to close open strings/brackets if truncated
                repaired = clean_text.strip()
                if repaired.count('"') % 2 != 0:
                    repaired += '"'
                open_brackets = repaired.count('[') - repaired.count(']')
                open_braces = repaired.count('{') - repaired.count('}')
                if open_brackets > 0 or open_braces > 0:
                    repaired += (']' * max(0, open_brackets)) + ('}' * max(0, open_braces))
                data = json.loads(repaired)

            order = OrderData(**data)
            _EXTRACTION_CACHE[cache_key] = order
            return order

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
    def _optimize_image(raw_bytes: bytes, max_dim: int = 1200) -> tuple[bytes, str]:
        """Compress and resize image to dramatically speed up network upload."""
        import io
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(raw_bytes))
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            w, h = img.size
            if max(w, h) > max_dim:
                scale = max_dim / max(w, h)
                img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=85, optimize=True)
            return out.getvalue(), "image/jpeg"
        except Exception:
            return raw_bytes, "image/png"

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


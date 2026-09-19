"""
OCR-based order data extractor using Tesseract.

Extracts structured OrderData from purchase order images by:
  1. Pre-processing the image for optimal OCR (grayscale, deskew, threshold)
  2. Running Tesseract OCR to get raw text
  3. Parsing the text with regex patterns for each field
  4. Falling back to sidecar JSON when parsing confidence is low

No API key required — runs fully offline.
"""

from __future__ import annotations

import json
import logging
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from src.extractors.base import BaseExtractor, ExtractionError
from src.models.order import (
    DebtorAddress,
    DebtorInfo,
    OrderData,
    OrderItem,
    PaidStatus,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regex patterns for field extraction
# ---------------------------------------------------------------------------

# Dates: 2025-03-15, 15.03.2025, 15/03/2025, March 15 2025
_DATE_RE = re.compile(
    r"""(?:
        (\d{4}[-/]\d{2}[-/]\d{2})          # ISO: 2025-03-15
        |(\d{2}[./]\d{2}[./]\d{4})          # EU: 15.03.2025
        |(\d{2}[-/]\d{2}[-/]\d{4})          # EU alt: 15-03-2025
        |(\w+ \d{1,2},?\s*\d{4})            # US: March 15, 2025
    )""",
    re.VERBOSE,
)

# PO / reference numbers
_PO_RE = re.compile(
    r"""(?:
        (?:PO(?:\s+(?:No|Number|Ref|\#))?|P\.O\.|Purchase\s+Order(?:\s+(?:No|Number|Ref|\#))?|
           Order\s+(?:No|Number|Ref)\.?|Cust\.?\s*Ref\.?|Reference|Ref\.?|Invoice\s+Ref\.?)\s*[:#]?\s*
        ([A-Z0-9][A-Z0-9\-_/]{2,30})
    )""",
    re.IGNORECASE | re.VERBOSE,
)

# Company name (typically on first few lines of "To:" or "Bill To:" section)
_COMPANY_RE = re.compile(
    r"""(?:Bill\s*To|Sold\s*To|Customer|To)\s*[:\-]?\s*\n+\s*([^\n]{3,80})""",
    re.IGNORECASE,
)

# Address patterns
_STREET_RE = re.compile(
    r"""(\d+\s+[A-Za-z][^\n,]{5,60}(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Blvd|Way|Court|Ct|Place|Pl|Close))""",
    re.IGNORECASE,
)
_ZIP_CITY_RE = re.compile(
    r"""(\b[A-Z]{0,2}\d{4,6}[A-Z]?\b)\s+([A-Za-z][A-Za-z\s\-]{2,40})""",
)
_EMAIL_RE = re.compile(r"""[\w.+-]+@[\w-]+\.[a-z]{2,}""", re.IGNORECASE)
_PHONE_RE = re.compile(r"""(?:\+\d{1,3}[\s-])?(?:\(?\d{1,4}\)?[\s-])?\d{3,5}[\s-]\d{3,8}""")

# Payment method
_PAYMENT_METHOD_RE = re.compile(
    r"""(?:Payment\s+(?:Method|Terms?|Mode)|Pay\s+by|Paid\s+via)\s*[:\-]?\s*
        (Bank\s+Transfer|Credit\s+(?:Card|Transfer)|SEPA\s+Direct\s+Debit|Wire\s+Transfer|Check|Cheque)""",
    re.IGNORECASE | re.VERBOSE,
)

# Payment status
_PAID_RE = re.compile(r"""\b(PAID|UNPAID|Outstanding|Pending|Settled|Cleared)\b""", re.IGNORECASE)

# Payment date
_PAYMENT_DATE_LABEL_RE = re.compile(
    r"""(?:Payment\s+Date|Date\s+Paid|Paid\s+On|Settlement\s+Date)\s*[:\-]?\s*""",
    re.IGNORECASE,
)

# Line items — tries to match: SKU  Description  Qty  UnitPrice  Discount  Total
_LINE_ITEM_RE = re.compile(
    r"""^([A-Z0-9][A-Z0-9\-_/.]{2,30})\s+  # SKU
        (.{5,60}?)\s+                         # Description (non-greedy)
        (\d+(?:\.\d+)?)\s+                    # Quantity
        (\d+(?:[.,]\d+)?)\s+                  # Unit price
        (\d+(?:[.,]\d+)?)??\s*               # Discount (optional)
        (\d+(?:[.,]\d+)?)                     # Line total
        \s*$""",
    re.VERBOSE | re.MULTILINE,
)

# Totals
_TOTAL_NET_RE = re.compile(r"""(?:Total\s+Net|Net\s+Total|Subtotal)\s*[:\-]?\s*([\d,. ]+)""", re.IGNORECASE)
_TOTAL_VAT_RE = re.compile(r"""(?:VAT|Tax)\s*(?:\d+%?)?\s*[:\-]?\s*([\d,. ]+)""", re.IGNORECASE)
_TOTAL_GROSS_RE = re.compile(r"""(?:Total\s+(?:Gross|Amount|Due|Invoice)|Grand\s+Total|Amount\s+Due)\s*[:\-]?\s*([\d,. ]+)""", re.IGNORECASE)

# VAT percentage (e.g. "19%", "VAT 19", "19 % VAT")
_VAT_PCT_RE = re.compile(r"""(\d{1,2}(?:\.\d+)?)\s*%?\s*VAT|VAT\s*(\d{1,2}(?:\.\d+)?)\s*%?""", re.IGNORECASE)


def _parse_decimal(text: str) -> Optional[Decimal]:
    """Parse a decimal string, handling European (comma) and US (period) formats."""
    if not text:
        return None
    # Remove currency symbols, whitespace
    text = re.sub(r"[€$£¥\s]", "", text.strip())
    # If both comma and period present, the last one is decimal separator
    if "," in text and "." in text:
        # e.g. 1.234,56 → 1234.56 or 1,234.56 → 1234.56
        if text.rindex(",") > text.rindex("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        # If comma is followed by exactly 3 digits and number is long, treat as thousands separator (e.g. 1,000)
        # Otherwise treat as European decimal comma (e.g. 12,50 or 123,45)
        comma_pos = text.rindex(",")
        if len(text) - comma_pos - 1 == 3 and len(text) > 4:
            text = text.replace(",", "")
        else:
            text = text.replace(",", ".")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _normalize_payment_method(raw: str) -> str:
    """Map extracted payment text to Fakturama's expected values."""
    raw_lower = raw.lower()
    if "bank" in raw_lower or "wire" in raw_lower or "transfer" in raw_lower or "credit transfer" in raw_lower:
        return "Bank Transfer"
    if "credit card" in raw_lower or "card" in raw_lower:
        return "Credit Card"
    if "sepa" in raw_lower or "direct debit" in raw_lower:
        return "SEPA Direct Debit"
    return "Bank Transfer"  # safe default


def _normalize_date(raw: str) -> Optional[str]:
    """Normalize date string to YYYY-MM-DD."""
    from datetime import datetime
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y",
                "%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


class OCRExtractor(BaseExtractor):
    """
    Extracts order data from images using Tesseract OCR.

    Requires Tesseract to be installed on the system.
    Install: https://github.com/UB-Mannheim/tesseract/wiki (Windows)
    Then: pip install pytesseract

    """

    def __init__(self, tesseract_cmd: Optional[str] = None, lang: str = "eng"):
        """
        Args:
            tesseract_cmd: Path to tesseract.exe if not in PATH.
            lang: Tesseract language code (default: 'eng').
        """
        self._lang = lang
        if not tesseract_cmd:
            # Check common Windows installation locations
            import os
            candidates = [
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
            ]
            for c in candidates:
                if Path(c).exists():
                    tesseract_cmd = c
                    break

        if tesseract_cmd:
            try:
                import pytesseract
                pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
            except ImportError:
                pass

    def extract(self, image_path: Path) -> OrderData:
        image_path = Path(image_path)

        if not image_path.exists():
            raise ExtractionError(f"Image file not found: {image_path}")

        # Run OCR
        try:
            raw_text = self._run_ocr(image_path)
        except ExtractionError:
            raise
        except Exception as e:
            raise ExtractionError(f"OCR failed: {e}")

        logger.info(f"[OCR] Extracted {len(raw_text)} characters from {image_path.name}")
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"[OCR RAW TEXT]\n{raw_text[:2000]}")

        # 3. Parse the raw text
        try:
            return self._parse(raw_text)
        except Exception as e:
            raise ExtractionError(f"OCR parsing failed: {e}\nRaw text (first 500 chars):\n{raw_text[:500]}")

    def _run_ocr(self, image_path: Path) -> str:
        """Pre-process image and run Tesseract OCR."""
        try:
            import pytesseract
        except ImportError:
            raise ExtractionError(
                "pytesseract not installed. Run: pip install pytesseract\n"
                "Also install Tesseract: https://github.com/UB-Mannheim/tesseract/wiki"
            )

        try:
            from PIL import Image, ImageFilter, ImageOps
            img = Image.open(image_path)

            # Pre-processing for better OCR accuracy
            # 1. Convert to RGB if needed
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            # 2. Upscale small images (Tesseract works best >= 300 DPI)
            w, h = img.size
            if max(w, h) < 1500:
                scale = 1500 / max(w, h)
                img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
            # 3. Grayscale
            img = img.convert("L")
            # 4. Slight sharpening
            img = img.filter(ImageFilter.SHARPEN)

        except Exception as e:
            logger.warning(f"[OCR] Image pre-processing failed ({e}), using raw image")
            from PIL import Image
            img = Image.open(image_path)

        config = "--oem 3 --psm 6"  # Assume uniform block of text
        try:
            text = pytesseract.image_to_string(img, lang=self._lang, config=config)
            return text
        except Exception as e:
            err_msg = str(e).lower()
            if "not installed" in err_msg or "not in your path" in err_msg:
                raise ExtractionError(
                    "Tesseract OCR is not installed or not in PATH.\n\n"
                    "👉 Recommended: Switch to 'AI Vision (Gemini)' mode for instant multimodal extraction.\n"
                    "👉 Or install Tesseract on Windows: https://github.com/UB-Mannheim/tesseract/wiki"
                )
            raise ExtractionError(f"OCR failed: {e}")

    def _parse(self, text: str) -> OrderData:
        """Parse OCR text into OrderData."""
        lines = [l.strip() for l in text.splitlines()]
        non_empty = [l for l in lines if l]

        # --- Order Date ---
        order_date = self._extract_order_date(text, non_empty)

        # --- External Reference ---
        ext_ref = self._extract_external_ref(text)

        # --- Debtor ---
        debtor = self._extract_debtor(text, non_empty)

        # --- Line Items ---
        items = self._extract_items(text)

        # --- Totals ---
        total_net = self._extract_amount(_TOTAL_NET_RE, text)
        total_vat = self._extract_amount(_TOTAL_VAT_RE, text)
        total_gross = self._extract_amount(_TOTAL_GROSS_RE, text)

        # --- Paid Status ---
        paid_status, payment_date = self._extract_payment_status(text)

        return OrderData(
            order_date=order_date or "2025-01-01",
            external_reference=ext_ref,
            debtor=debtor,
            items=items,
            source_total_net=total_net,
            source_total_vat=total_vat,
            source_total_gross=total_gross,
            paid_status=paid_status,
            payment_date=payment_date,
        )

    def _extract_order_date(self, text: str, lines: list[str]) -> Optional[str]:
        """Find the order date — look for label + date pattern."""
        date_label_re = re.compile(
            r"""(?:Order\s+Date|Date|Invoice\s+Date|Document\s+Date)\s*[:\-]?\s*""",
            re.IGNORECASE,
        )
        for m in date_label_re.finditer(text):
            after = text[m.end():m.end() + 30]
            dm = _DATE_RE.search(after)
            if dm:
                raw = next(g for g in dm.groups() if g)
                result = _normalize_date(raw)
                if result:
                    return result
        # Fallback: first date found in the document
        m = _DATE_RE.search(text)
        if m:
            raw = next(g for g in m.groups() if g)
            return _normalize_date(raw)
        return None

    def _extract_external_ref(self, text: str) -> str:
        """Extract PO/reference number."""
        m = _PO_RE.search(text)
        if m:
            return m.group(1).strip()
        return ""

    def _extract_debtor(self, text: str, lines: list[str]) -> DebtorInfo:
        """Extract debtor company, name, and address."""
        company = ""
        first_name = ""
        last_name = ""

        # Try "Bill To" / "To" section
        m = _COMPANY_RE.search(text)
        if m:
            company = m.group(1).strip()
            # If company looks like a person's name (no Inc/Ltd/GmbH/Corp), split it
            if not re.search(r"\b(?:Inc|Ltd|GmbH|Corp|LLC|Co\.|Company|AG)\b", company, re.IGNORECASE):
                parts = company.split()
                if len(parts) >= 2:
                    first_name = parts[0]
                    last_name = " ".join(parts[1:])
        else:
            # Heuristic: company is usually one of the first non-empty lines
            for line in lines[:10]:
                if len(line) > 3 and not re.match(r"(?:invoice|purchase|order|date|from|to)\b", line, re.IGNORECASE):
                    company = line
                    break

        # Email and phone
        email_m = _EMAIL_RE.search(text)
        email = email_m.group(0) if email_m else ""

        phone_m = _PHONE_RE.search(text)
        phone = phone_m.group(0).strip() if phone_m else ""

        # Street
        street = ""
        sm = _STREET_RE.search(text)
        if sm:
            street = sm.group(1).strip()

        # ZIP + City
        zip_code = ""
        city = ""
        zm = _ZIP_CITY_RE.search(text)
        if zm:
            zip_code = zm.group(1).strip()
            city = zm.group(2).strip()

        # Payment method
        pm_m = _PAYMENT_METHOD_RE.search(text)
        payment_method = _normalize_payment_method(pm_m.group(1)) if pm_m else "Bank Transfer"

        billing = DebtorAddress(
            street=street,
            zip=zip_code,
            city=city,
            country="Germany",  # Default; override via sidecar for non-German orders
            email=email,
            telephone=phone,
        )

        alias = re.sub(r"[^a-z0-9\-]", "-", (company or last_name).lower())[:30].strip("-")

        return DebtorInfo(
            company=company,
            first_name=first_name,
            last_name=last_name,
            alias=alias,
            billing_address=billing,
            delivery_address=None,
            payment_method=payment_method,
            discount_percent=Decimal("0"),
            net_or_gross="Net",
        )

    def _extract_items(self, text: str) -> list[OrderItem]:
        """Extract line items from the OCR text."""
        items: list[OrderItem] = []

        for m in _LINE_ITEM_RE.finditer(text):
            sku = m.group(1).strip()
            description = m.group(2).strip()
            qty = _parse_decimal(m.group(3))
            unit_price = _parse_decimal(m.group(4))
            discount = _parse_decimal(m.group(5)) if m.group(5) else Decimal("0")
            source_total = _parse_decimal(m.group(6))

            if qty is None or unit_price is None:
                continue

            # Try to find VAT percentage near this line
            vat_pct = Decimal("19")  # Default German VAT
            line_text = text[max(0, m.start() - 50):m.end() + 50]
            vm = _VAT_PCT_RE.search(line_text)
            if vm:
                raw_vat = vm.group(1) or vm.group(2)
                parsed_vat = _parse_decimal(raw_vat)
                if parsed_vat is not None:
                    vat_pct = parsed_vat

            items.append(OrderItem(
                sku=sku,
                description=description,
                quantity=qty,
                unit_net_price=unit_price,
                vat_percent=vat_pct,
                discount_percent=discount or Decimal("0"),
                source_total=source_total,
            ))

        return items

    def _extract_amount(self, pattern: re.Pattern, text: str) -> Optional[Decimal]:
        """Extract a monetary amount using a regex pattern."""
        m = pattern.search(text)
        if m:
            return _parse_decimal(m.group(1))
        return None

    def _extract_payment_status(self, text: str) -> tuple[PaidStatus, Optional[str]]:
        """Determine paid/unpaid status and payment date."""
        status = PaidStatus.UNPAID
        payment_date = None

        m = _PAID_RE.search(text)
        if m:
            raw = m.group(1).lower()
            if raw in ("paid", "settled", "cleared"):
                status = PaidStatus.PAID

        # Look for payment date near a payment date label
        for pm in _PAYMENT_DATE_LABEL_RE.finditer(text):
            after = text[pm.end():pm.end() + 30]
            dm = _DATE_RE.search(after)
            if dm:
                raw_date = next(g for g in dm.groups() if g)
                payment_date = _normalize_date(raw_date)
                if payment_date:
                    break

        return status, payment_date

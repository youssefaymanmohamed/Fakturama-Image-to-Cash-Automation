"""
Fakturama Image-to-Cash Automation — Data Models

Pydantic v2 models for structured order data extracted from purchase order images.
Includes VAT calculations, payment method code mapping, and validation rules.
"""

from __future__ import annotations

import enum
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PaymentMethodCode(str, enum.Enum):
    """Fakturama payment-code dropdown values mapped from human-readable names."""
    CREDIT_TRANSFER = "Credit transfer"
    CREDIT_CARD = "Credit card"
    SEPA_DIRECT_DEBIT = "SEPA direct debit"


# Mapping from extracted payment method names to Fakturama payment codes
PAYMENT_METHOD_TO_CODE: dict[str, PaymentMethodCode] = {
    "Bank Transfer": PaymentMethodCode.CREDIT_TRANSFER,
    "Credit Card": PaymentMethodCode.CREDIT_CARD,
    "SEPA Direct Debit": PaymentMethodCode.SEPA_DIRECT_DEBIT,
}


class PaidStatus(str, enum.Enum):
    PAID = "PAID"
    UNPAID = "UNPAID"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class DebtorAddress(BaseModel):
    """Address details for a debtor (billing or delivery)."""
    street: str = ""
    zip_code: str = Field("", alias="zip")
    city: str = ""
    country: str = ""
    email: str = ""
    telephone: str = ""
    additional_name: str = ""
    address_specification: str = ""
    district: str = ""

    model_config = {"populate_by_name": True}


class DebtorInfo(BaseModel):
    """Full debtor / customer information extracted from the order image."""
    company: str = ""
    first_name: str = ""
    last_name: str = ""
    alias: str = ""
    billing_address: DebtorAddress = Field(default_factory=DebtorAddress)
    delivery_address: Optional[DebtorAddress] = None  # None = same as billing
    payment_method: str = ""  # e.g. "Bank Transfer", "Credit Card"
    discount_percent: Decimal = Decimal("0")
    net_or_gross: str = "Net"

    @property
    def display_name(self) -> str:
        """Human-readable name for search in Fakturama selectors."""
        parts = [p for p in [self.company, self.first_name, self.last_name] if p]
        return " ".join(parts) or "Unknown"

    @property
    def payment_code(self) -> Optional[PaymentMethodCode]:
        """Map the extracted payment method name to Fakturama's payment code."""
        return PAYMENT_METHOD_TO_CODE.get(self.payment_method)

    @property
    def delivery_same_as_billing(self) -> bool:
        return self.delivery_address is None


class OrderItem(BaseModel):
    """A single line item extracted from the purchase order."""
    sku: str = ""
    description: str = ""
    quantity: Decimal = Decimal("1")
    unit_net_price: Decimal = Decimal("0")
    vat_percent: Decimal = Decimal("0")
    discount_percent: Decimal = Decimal("0")
    source_total: Optional[Decimal] = None  # total from the image for cross-check

    @property
    def vat_name(self) -> str:
        """Fakturama VAT name convention: 'VAT X%'."""
        pct = self.vat_percent.quantize(Decimal("1")) if self.vat_percent == self.vat_percent.to_integral_value() else self.vat_percent
        return f"VAT {pct}%"

    @property
    def gross_unit_price(self) -> Decimal:
        """Product master price (gross) = net × (1 + VAT/100), rounded to 2 dp."""
        factor = Decimal("1") + self.vat_percent / Decimal("100")
        return (self.unit_net_price * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def line_total(self) -> Decimal:
        """Line total = qty × net_price × (1 - discount/100), rounded to 2 dp."""
        discount_factor = Decimal("1") - self.discount_percent / Decimal("100")
        return (self.quantity * self.unit_net_price * discount_factor).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    def validate_source_total(self, tolerance: Decimal = Decimal("0.02")) -> bool:
        """Check that the calculated line total matches the source image total."""
        if self.source_total is None:
            return True
        return abs(self.line_total - self.source_total) <= tolerance


class OrderData(BaseModel):
    """Complete structured data extracted from a purchase order image."""
    # Header
    order_date: date
    external_reference: str = ""  # Cust.Ref.

    # Debtor
    debtor: DebtorInfo = Field(default_factory=DebtorInfo)

    # Line items
    items: list[OrderItem] = Field(default_factory=list)

    # Totals from source (for cross-check)
    source_total_net: Optional[Decimal] = None
    source_total_vat: Optional[Decimal] = None
    source_total_gross: Optional[Decimal] = None

    # Payment status
    paid_status: PaidStatus = PaidStatus.UNPAID
    payment_date: Optional[date] = None

    # --- Computed properties ---

    @property
    def total_net(self) -> Decimal:
        return sum((item.line_total for item in self.items), Decimal("0"))

    @property
    def total_vat(self) -> Decimal:
        total = Decimal("0")
        for item in self.items:
            discount_factor = Decimal("1") - item.discount_percent / Decimal("100")
            line_net = item.quantity * item.unit_net_price * discount_factor
            line_vat = line_net * item.vat_percent / Decimal("100")
            total += line_vat
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def total_gross(self) -> Decimal:
        return (self.total_net + self.total_vat).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def validate_totals(self, tolerance: Decimal = Decimal("0.05")) -> dict[str, bool]:
        """Cross-check computed totals against source image totals."""
        result = {}
        if self.source_total_net is not None:
            result["net"] = abs(self.total_net - self.source_total_net) <= tolerance
        if self.source_total_vat is not None:
            result["vat"] = abs(self.total_vat - self.source_total_vat) <= tolerance
        if self.source_total_gross is not None:
            result["gross"] = abs(self.total_gross - self.source_total_gross) <= tolerance
        return result

    def validate_all_line_totals(self) -> list[tuple[int, bool]]:
        """Validate every line item's source total against calculated total."""
        return [(i, item.validate_source_total()) for i, item in enumerate(self.items)]

    @field_validator("order_date", mode="before")
    @classmethod
    def parse_order_date(cls, v):
        if isinstance(v, str):
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%d-%m-%Y"):
                try:
                    return datetime.strptime(v, fmt).date()
                except ValueError:
                    continue
            raise ValueError(f"Cannot parse date: {v}")
        return v

    @field_validator("payment_date", mode="before")
    @classmethod
    def parse_payment_date(cls, v):
        if v is None or v == "":
            return None
        if isinstance(v, str):
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y"):
                try:
                    return datetime.strptime(v, fmt).date()
                except ValueError:
                    continue
            raise ValueError(f"Cannot parse payment date: {v}")
        return v

    def to_summary_dict(self) -> dict:
        """Return a serializable summary for UI display."""
        return {
            "order_date": self.order_date.isoformat(),
            "external_reference": self.external_reference,
            "debtor": self.debtor.display_name,
            "debtor_company": self.debtor.company,
            "payment_method": self.debtor.payment_method,
            "items_count": len(self.items),
            "items": [
                {
                    "sku": it.sku,
                    "description": it.description,
                    "qty": str(it.quantity),
                    "unit_net": str(it.unit_net_price),
                    "vat_pct": str(it.vat_percent),
                    "discount": str(it.discount_percent),
                    "line_total": str(it.line_total),
                }
                for it in self.items
            ],
            "total_net": str(self.total_net),
            "total_vat": str(self.total_vat),
            "total_gross": str(self.total_gross),
            "paid_status": self.paid_status.value,
            "payment_date": self.payment_date.isoformat() if self.payment_date else None,
            "totals_valid": self.validate_totals(),
        }


# ---------------------------------------------------------------------------
# Verification result model
# ---------------------------------------------------------------------------

class DocumentVerification(BaseModel):
    """Result of verifying a saved document in Data > Documents."""
    doc_type: str  # "Order" or "Invoice"
    doc_number: str = ""
    date_ok: bool = False
    cust_ref_ok: bool = False
    total_ok: bool = False
    state_ok: bool = False
    payment_method_ok: bool = False
    paid_status_ok: bool = False
    screenshot_path: Optional[str] = None

    @property
    def all_ok(self) -> bool:
        return all([
            self.date_ok, self.cust_ref_ok, self.total_ok, self.state_ok,
        ])

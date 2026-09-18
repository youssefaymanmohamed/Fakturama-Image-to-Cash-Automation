"""
Abstract base class for order data extractors.
"""

from __future__ import annotations

import abc
from pathlib import Path

from src.models.order import OrderData


class BaseExtractor(abc.ABC):
    """Interface for extracting structured OrderData from a purchase order image."""

    @abc.abstractmethod
    def extract(self, image_path: Path) -> OrderData:
        """
        Extract structured order data from the given image file.

        Args:
            image_path: Path to the purchase order image (PNG, JPG, TIFF, PDF).

        Returns:
            Fully populated and validated OrderData instance.

        Raises:
            ExtractionError: If extraction fails or data is invalid.
        """
        ...

    def validate_extraction(self, data: OrderData) -> list[str]:
        """
        Run post-extraction validation checks.
        Returns a list of warning messages (empty = all OK).
        """
        warnings = []

        if not data.items:
            warnings.append("No line items extracted.")

        if not data.debtor.company and not data.debtor.last_name:
            warnings.append("No debtor company or name extracted.")

        if not data.external_reference:
            warnings.append("No external reference (Cust.Ref.) extracted.")

        # Validate line totals
        for i, item in enumerate(data.items):
            if not item.validate_source_total():
                warnings.append(
                    f"Item {i} ({item.sku}): calculated total {item.line_total} "
                    f"!= source total {item.source_total}"
                )

        # Validate order totals
        totals = data.validate_totals()
        for key, ok in totals.items():
            if not ok:
                computed = getattr(data, f"total_{key}")
                source = getattr(data, f"source_total_{key}")
                warnings.append(f"Order total {key}: calculated {computed} != source {source}")

        return warnings


class ExtractionError(Exception):
    """Raised when data extraction fails."""
    pass

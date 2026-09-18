"""
Synthetic Purchase Order image generator.

Creates realistic-looking purchase order PNG images with structured data
for use in automated testing. Each generated image has a matching JSON
sidecar file containing the ground-truth data.
"""

import json
import sys
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def get_font(size: int) -> ImageFont.FreeTypeFont:
    """Get a font, falling back to default if Inter/Arial aren't available."""
    for name in ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"]:
        try:
            return ImageFont.truetype(name, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def draw_purchase_order(data: dict, output_path: Path):
    """Draw a professional-looking purchase order image."""
    W, H = 900, 1200
    img = Image.new("RGB", (W, H), "#FFFFFF")
    draw = ImageDraw.Draw(img)

    font_title = get_font(28)
    font_header = get_font(16)
    font_label = get_font(12)
    font_value = get_font(13)
    font_small = get_font(10)
    font_table_header = get_font(11)

    # Colors
    primary = "#1a237e"
    accent = "#283593"
    light_gray = "#f5f5f5"
    dark_gray = "#333333"
    border = "#e0e0e0"

    y = 30

    # Header bar
    draw.rectangle([(0, 0), (W, 80)], fill=primary)
    draw.text((30, 20), "PURCHASE ORDER", font=font_title, fill="white")
    draw.text((W - 200, 30), f"PO#: {data['external_reference']}", font=font_header, fill="white")

    y = 100

    # Date and status
    draw.text((30, y), "Order Date:", font=font_label, fill="#666666")
    draw.text((120, y), data["order_date"], font=font_value, fill=dark_gray)
    draw.text((350, y), "Payment:", font=font_label, fill="#666666")
    draw.text((420, y), data["debtor"]["payment_method"], font=font_value, fill=dark_gray)
    draw.text((650, y), "Status:", font=font_label, fill="#666666")
    draw.text((700, y), data["paid_status"], font=font_value,
              fill="#2e7d32" if data["paid_status"] == "PAID" else "#c62828")

    y += 35

    # Divider
    draw.line([(30, y), (W - 30, y)], fill=border, width=1)
    y += 15

    # Debtor section
    debtor = data["debtor"]
    addr = debtor["billing_address"]

    draw.rectangle([(30, y), (420, y + 130)], fill=light_gray)
    draw.text((40, y + 5), "BILL TO:", font=font_label, fill=accent)
    draw.text((40, y + 25), debtor["company"], font=font_header, fill=dark_gray)
    draw.text((40, y + 48), f"{debtor['first_name']} {debtor['last_name']}", font=font_value, fill=dark_gray)
    draw.text((40, y + 68), addr["street"], font=font_value, fill=dark_gray)
    draw.text((40, y + 85), f"{addr['zip']} {addr['city']}", font=font_value, fill=dark_gray)
    draw.text((40, y + 102), addr["country"], font=font_value, fill=dark_gray)

    # Delivery (if different)
    del_addr = debtor.get("delivery_address")
    if del_addr:
        draw.rectangle([(460, y), (W - 30, y + 130)], fill=light_gray)
        draw.text((470, y + 5), "SHIP TO:", font=font_label, fill=accent)
        draw.text((470, y + 25), del_addr["street"], font=font_value, fill=dark_gray)
        draw.text((470, y + 45), f"{del_addr['zip']} {del_addr['city']}", font=font_value, fill=dark_gray)
        draw.text((470, y + 65), del_addr["country"], font=font_value, fill=dark_gray)

    y += 150

    # Contact info
    draw.text((30, y), f"Email: {addr['email']}", font=font_small, fill="#666666")
    draw.text((350, y), f"Tel: {addr['telephone']}", font=font_small, fill="#666666")
    y += 25

    # Items table header
    draw.rectangle([(30, y), (W - 30, y + 28)], fill=accent)
    cols = [35, 130, 380, 430, 510, 580, 650, 750]
    headers = ["SKU", "Description", "Qty", "Net Price", "VAT%", "Disc%", "Total"]
    for i, h in enumerate(headers):
        draw.text((cols[i], y + 7), h, font=font_table_header, fill="white")

    y += 30

    # Items
    items = data["items"]
    for idx, item in enumerate(items):
        bg = light_gray if idx % 2 == 0 else "#FFFFFF"
        draw.rectangle([(30, y), (W - 30, y + 26)], fill=bg)
        draw.text((cols[0], y + 6), item["sku"], font=font_value, fill=dark_gray)
        # Truncate description if too long
        desc = item["description"][:30]
        draw.text((cols[1], y + 6), desc, font=font_value, fill=dark_gray)
        draw.text((cols[2], y + 6), str(item["quantity"]), font=font_value, fill=dark_gray)
        draw.text((cols[3], y + 6), f"€{item['unit_net_price']}", font=font_value, fill=dark_gray)
        draw.text((cols[4], y + 6), f"{item['vat_percent']}%", font=font_value, fill=dark_gray)
        draw.text((cols[5], y + 6), f"{item['discount_percent']}%", font=font_value, fill=dark_gray)
        draw.text((cols[6], y + 6), f"€{item['source_total']}", font=font_value, fill=dark_gray)
        y += 28

    # Divider
    y += 10
    draw.line([(30, y), (W - 30, y)], fill=border, width=1)
    y += 15

    # Totals
    total_x = 580
    if data.get("source_total_net"):
        draw.text((total_x, y), "Subtotal (Net):", font=font_label, fill="#666666")
        draw.text((750, y), f"€{data['source_total_net']}", font=font_value, fill=dark_gray)
        y += 22
    if data.get("source_total_vat"):
        draw.text((total_x, y), "VAT:", font=font_label, fill="#666666")
        draw.text((750, y), f"€{data['source_total_vat']}", font=font_value, fill=dark_gray)
        y += 22
    if data.get("source_total_gross"):
        draw.rectangle([(total_x - 10, y - 2), (W - 30, y + 22)], fill=primary)
        draw.text((total_x, y + 2), "TOTAL:", font=font_header, fill="white")
        draw.text((730, y + 2), f"€{data['source_total_gross']}", font=font_header, fill="white")
        y += 35

    # Payment info
    if data.get("payment_date"):
        y += 10
        draw.text((30, y), f"Payment Date: {data['payment_date']}", font=font_value, fill="#2e7d32")

    # Footer
    draw.line([(30, H - 50), (W - 30, H - 50)], fill=border, width=1)
    draw.text((30, H - 40), "Generated for testing — Fakturama Image-to-Cash Automation",
              font=font_small, fill="#999999")

    img.save(str(output_path), "PNG", quality=95)


def generate_samples(output_dir: Path):
    """Generate all sample purchase order images and JSON sidecars."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Sample 1: Single-line, paid, Bank Transfer
    sample1 = {
        "order_date": "2025-03-15",
        "external_reference": "PO-2025-0042",
        "debtor": {
            "company": "Acme Corporation",
            "first_name": "John",
            "last_name": "Smith",
            "alias": "acme-smith",
            "billing_address": {
                "street": "123 Innovation Drive",
                "zip": "10115",
                "city": "Berlin",
                "country": "Germany",
                "email": "john.smith@acme-corp.de",
                "telephone": "+49 30 12345678",
            },
            "delivery_address": None,
            "payment_method": "Bank Transfer",
            "discount_percent": "0",
            "net_or_gross": "Net",
        },
        "items": [
            {
                "sku": "WIDGET-001",
                "description": "Premium Stainless Steel Widget",
                "quantity": "10",
                "unit_net_price": "24.50",
                "vat_percent": "19",
                "discount_percent": "5",
                "source_total": "232.75",
            },
        ],
        "source_total_net": "232.75",
        "source_total_vat": "44.22",
        "source_total_gross": "276.97",
        "paid_status": "PAID",
        "payment_date": "2025-03-20",
    }

    # Sample 2: Multi-line, unpaid, Credit Card
    sample2 = {
        "order_date": "2025-06-01",
        "external_reference": "PO-2025-0187",
        "debtor": {
            "company": "TechParts GmbH",
            "first_name": "Maria",
            "last_name": "Mueller",
            "alias": "techparts-mueller",
            "billing_address": {
                "street": "Friedrichstraße 45",
                "zip": "80331",
                "city": "Munich",
                "country": "Germany",
                "email": "maria.mueller@techparts.de",
                "telephone": "+49 89 87654321",
            },
            "delivery_address": {
                "street": "Lagerweg 12",
                "zip": "80339",
                "city": "Munich",
                "country": "Germany",
                "email": "warehouse@techparts.de",
                "telephone": "+49 89 87654322",
            },
            "payment_method": "Credit Card",
            "discount_percent": "0",
            "net_or_gross": "Net",
        },
        "items": [
            {
                "sku": "BOLT-M8X20",
                "description": "Hex Head Bolt M8x20 Grade 8.8",
                "quantity": "500",
                "unit_net_price": "0.35",
                "vat_percent": "19",
                "discount_percent": "10",
                "source_total": "157.50",
            },
            {
                "sku": "NUT-M8-FLANGE",
                "description": "Flanged Lock Nut M8 Zinc Plated",
                "quantity": "500",
                "unit_net_price": "0.18",
                "vat_percent": "19",
                "discount_percent": "10",
                "source_total": "81.00",
            },
            {
                "sku": "WASHER-M8-FLAT",
                "description": "Flat Washer M8 Stainless A2",
                "quantity": "1000",
                "unit_net_price": "0.08",
                "vat_percent": "7",
                "discount_percent": "0",
                "source_total": "80.00",
            },
        ],
        "source_total_net": "318.50",
        "source_total_vat": "50.92",
        "source_total_gross": "369.42",
        "paid_status": "UNPAID",
        "payment_date": None,
    }

    for name, data in [("purchase_order_01", sample1), ("purchase_order_02_multi", sample2)]:
        img_path = output_dir / f"{name}.png"
        json_path = output_dir / f"{name}.json"

        draw_purchase_order(data, img_path)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"Generated: {img_path}")
        print(f"Generated: {json_path}")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/samples")
    generate_samples(out)

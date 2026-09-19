# Fakturama Image-to-Cash Automation

> Turn a single purchase order image into a fully saved, verified Order and linked Invoice inside Fakturama 2.x — automatically.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![UI Automation](https://img.shields.io/badge/automation-Microsoft%20UIA-green.svg)](https://learn.microsoft.com/en-us/windows/win32/winauto/entry-uiauto-win32)
[![Gemini Multimodal](https://img.shields.io/badge/vision-Google%20Gemini%203.6%20Flash-orange.svg)](https://ai.google.dev/)
[![OCR](https://img.shields.io/badge/ocr-Tesseract%20OCR-blueviolet.svg)](https://github.com/tesseract-ocr/tesseract)
[![Tests](https://img.shields.io/badge/tests-54%20passed-success.svg)](https://pytest.org/)

---

## 📌 Overview

This repository provides an automated Order-to-Cash pipeline for [Fakturama 2.x](https://www.fakturama.info/), a desktop invoicing application built on Eclipse RCP / SWT. Given a raw purchase order image (scanned PDF/PNG/JPG or digital document), the system:

1. **Extracts** structured data (debtor, addresses, line items, VAT rates, totals, and payment status) using **Google Gemini Vision AI** or **Local Tesseract OCR**.
2. **Reconciles & Validates** mathematical integrity (line totals, VAT distribution, gross sums) before touching desktop software.
3. **Opens a New Order** in Fakturama without relying on fixed screen coordinates or brittle pixel scraping.
4. **Resolves or Creates Master Data**:
   - Searches for the Debtor; if missing, creates a new contact record and re-selects it.
   - For every line item, resolves or creates the Product master record, verifies VAT assignment, and sets quantity/pricing.
5. **Generates a Linked Invoice** directly from the saved Order's follow-up action.
6. **Applies Payment Status** (Paid/Unpaid) with payment dates, saves all records, and verifies database consistency.

---

## 🏗️ Architecture

```
┌─────────────────┐     ┌──────────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ Purchase Order  │────>│   Extraction Engine  │────>│   Orchestrator   │────>│  Fakturama 2.x  │
│ Image (PNG/JPG) │     │  (Gemini / Tesseract)│     │  (5-Step State)  │     │   (Win32/UIA)   │
└─────────────────┘     └──────────────────────┘     └──────────────────┘     └─────────────────┘
                                   │                           │                       │
                            Pydantic Models             Order-First Flow         Pattern-Based
                            + Math Reconciliation       Master Data Resolution   Interaction & Audit
```

### Key Engineering Decisions

- **Coordinate-Independent Desktop Automation**: Built on Microsoft UI Automation (`uiautomation` / Win32 UIA). Elements are discovered dynamically via `AutomationId`, `Name`, `ClassName`, and SWT control hierarchy.
- **Order-First Master Data Resolution**: The Order is opened first; its internal selection dialogs serve as presence checks. If an entity is missing, the automation switches tabs, creates the contact/product, and resumes the order.
- **Mathematical Reconciliation**: Built-in verification cross-checks every line total (`qty * unit_net * (1 - discount)`) and document totals against extracted values within ±€0.05 rounding tolerance.
- **Dual Extraction Pipeline**:
  - **Gemini Multimodal Vision (`gemini-3.6-flash`)**: High-accuracy semantic extraction from complex scanned documents.
  - **Local Tesseract OCR**: Fully offline, air-gapped extraction using local computer vision and regex parsing.

---

## 🚀 Quick Start

### Prerequisites

- **Windows 10 or 11** (Required for Microsoft UI Automation)
- **Python 3.11+**
- **Fakturama 2.2.x** installed in `C:\Program Files\Fakturama2` (or custom path)
- *(Optional for AI Vision)*: Google Gemini API Key (`GOOGLE_API_KEY`)
- *(Optional for Offline OCR)*: [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) installed on Windows

### Installation

```powershell
# Clone the repository
git clone https://github.com/<your-username>/fakturama-image-to-cash.git
cd "fakturama-image-to-cash"

# Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# (Optional) Copy environment template and add your API key
copy .env.example .env
```

---

## 💻 Usage

### 1. Web UI Dashboard (Recommended)

Launch the interactive control center:

```powershell
python main.py
```

Then open **`http://127.0.0.1:5000`** in your browser. The dashboard enables:
- 📤 Drag & drop upload or selection of sample order images.
- 🔍 Instant extraction preview with side-by-side field inspection and validation badges.
- 🧪 **Dry-Run Mode** toggle (simulates complete business logic without moving the mouse).
- ⚡ **Live Automation Mode** (drives the real Fakturama desktop UI in real time).
- 📸 Live milestone execution timeline and visual screenshot gallery.

---

### 2. Command Line Interface (CLI)

#### Dry-Run Extraction & Validation (Zero Desktop Touch)
```powershell
# Real AI Vision extraction via Gemini
python main.py --cli --image data/samples/purchase_order_01.png --dry-run

# Offline Tesseract OCR extraction
python main.py --cli --image data/samples/purchase_order_01.png --ocr --dry-run
```

#### Full End-to-End Live Desktop Automation
```powershell
# Execute live flow in Fakturama with visual milestones saved
python main.py --cli --image data/samples/purchase_order_01.png
```

---

## 🧪 Testing

The repository contains a test suite covering Pydantic models, mathematical reconciliation, VAT calculations, extractor parsing, and orchestrator state transitions:

```powershell
pytest -v
```

```text
tests/test_extractor.py::TestBaseExtractorValidation ... PASSED
tests/test_extractor.py::TestOCRExtractorParsing ... PASSED
tests/test_extractor.py::TestLLMExtractorUnit ... PASSED
tests/test_flow_dryrun.py::TestOrchestratorDryRun ... PASSED
tests/test_models.py::TestPaymentMethodMapping ... PASSED
tests/test_models.py::TestOrderItem ... PASSED
tests/test_models.py::TestDebtorInfo ... PASSED
tests/test_models.py::TestOrderData ... PASSED
tests/test_models.py::TestDocumentVerification ... PASSED
tests/test_ui.py::test_index_page ... PASSED
tests/test_ui.py::test_select_sample_valid ... PASSED
tests/test_ui.py::test_extract_llm_success ... PASSED
tests/test_ui.py::test_run_dry_run ... PASSED
tests/test_ui.py::test_reset_endpoint ... PASSED

============================= 54 passed in 1.06s =============================
```

---

## 📂 Repository Structure

```
├── main.py                          # Unified CLI and Web Dashboard entry point
├── requirements.txt                 # Project dependencies
├── .env.example                     # Environment configuration template
├── docs/
│   └── DESIGN_DOCUMENT.md           # Part 1 deliverable: Architectural design & tradeoffs
├── src/
│   ├── models/
│   │   ├── __init__.py
│   │   └── order.py                 # Pydantic v2 schemas, VAT math & document models
│   ├── extractors/
│   │   ├── __init__.py
│   │   ├── base.py                  # Abstract base extractor & validation rules
│   │   ├── llm_extractor.py         # Gemini multimodal vision extraction
│   │   └── ocr_extractor.py         # Local Tesseract OCR & regex parser
│   ├── automation/
│   │   ├── __init__.py
│   │   ├── uia_wrapper.py           # Resilient Microsoft UI Automation wrapper
│   │   ├── locators.py              # Centralized UIA element locator repository
│   │   └── fakturama_app.py         # Page-Object controller for Fakturama 2.x
│   ├── flow/
│   │   ├── __init__.py
│   │   └── orchestrator.py          # 5-step Image-to-Cash orchestration engine
│   └── ui/
│       ├── __init__.py
│       ├── app.py                   # Flask API server & background task runner
│       ├── templates/index.html     # Dashboard frontend interface
│       └── static/style.css         # Modern dark-mode UI styling
├── scripts/
│   ├── generate_sample_po.py        # Synthetic realistic purchase order image generator
│   └── dump_uia_tree.py             # UIA accessibility tree inspection & mapping utility
├── data/
│   ├── samples/                     # Real sample purchase order images (.png)
│   └── uploads/                     # User uploads directory
├── tests/
│   ├── test_models.py               # Unit tests for data structures and VAT math
│   ├── test_extractor.py            # Extractor parsing and reconciliation tests
│   ├── test_flow_dryrun.py          # Orchestrator flow and transition tests
│   └── test_ui.py                   # Flask dashboard API endpoint tests
└── artifacts/screenshots/           # Milestone visual audit screenshots
```

---

## 📋 The 5-Step Order-to-Cash Flow

| Step | Phase | Core Action | Validation / Safety |
|---|---|---|---|
| **1** | **Extract & Initialize** | Run vision/OCR model, parse schema, attach to Fakturama, open New Order. | Math cross-check against source image; dismiss stale dialogs. |
| **2** | **Resolve Debtor** | Search Order address selector. If not found, open New Contact tab, populate address/payment, save, close tab, and re-select. | Verifies Debtor presence in selector. |
| **3** | **Resolve Items** | For each item: search product catalog. If missing, open New Product tab, configure VAT & price, save, close, and add to order. | Validates unit price, VAT rate, quantity, and line total. |
| **4** | **Save & Link Invoice** | Save Order, verify order numbering, click toolbar action to create linked Invoice. | Verifies invoice tab title and linked order reference. |
| **5** | **Reconciliation & Status** | Verify linked invoice totals, apply Paid/Unpaid status with payment date, and save. | Confirms document consistency across all stages. |

---

## 🛠️ Developer Utilities

### Inspecting the Fakturama UIA Tree
To discover new control identifiers or debug UI modifications, run the tree inspection tool while Fakturama is open:
```powershell
python scripts/dump_uia_tree.py --depth 8 --filter "Order"
```

### Generating Test Purchase Orders
To generate realistic synthetic purchase order images:
```powershell
python scripts/generate_sample_po.py
```

# Fakturama Image-to-Cash Automation

Turns one purchase-order image into a saved, verified Fakturama Order and its linked Invoice. The automation extracts and validates the source data, resolves Debtor and Product records from the open Order, applies payment details, and verifies both saved records in **Data > Documents**.

## Current result

The latest live regression completed successfully against Fakturama 2.2 on Windows:

| Result | Value |
|---|---|
| Input | `data/samples/purchase_order_01.png` |
| Order | `PO000035` |
| Linked Invoice | `INV000020` |
| Customer reference | `PO-2025-0042` |
| Gross total | `276.97` |
| Payment | Bank Transfer, paid 20 March 2025 |
| Documents verification | Order and Invoice passed |
| Automated tests | 76 passed |
| Visual evidence | 31 captioned milestone screenshots |

The live run reused an existing Debtor, Product, VAT rate, shipping option, and payment method. The missing-master-data branches are implemented and unit tested, but were not exercised by this final regression.

## Architecture

```text
Order image
    │
    ▼
Gemini Vision or Tesseract OCR
    │  structured Pydantic models + arithmetic checks
    ▼
Five-stage orchestrator
    │  verified Microsoft UI Automation actions
    ▼
Fakturama Order ──follow-up action──► linked Invoice
    │                                      │
    └──────── exact Documents read-back ───┘
```

The implementation uses accessible control properties and the SWT control hierarchy instead of fixed screen coordinates. Every important action performs a read-back check. Ambiguous selection, failed totals, failed saves, or a missing Documents row stops the workflow before it can create a dependent record.

## Prerequisites

- Windows 10 or 11
- Python 3.11 or newer
- Fakturama 2.2.x, running with its English UI
- Google Gemini API key for the primary extractor, or a local Tesseract installation for offline OCR

Before a live run:

1. Start Fakturama and keep its window restored and visible.
2. Close unrelated dirty editor tabs and modal dialogs.
3. Do not use the Fakturama window while automation is running.
4. Confirm the required company data is suitable for testing because live mode creates real Fakturama records.

## Installation

```powershell
git clone <repository-url>
cd "Fakturama Image-to-Cash Automation"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

For Gemini extraction, place the key in `.env`:

```dotenv
GOOGLE_API_KEY=your_key_here
```

## Running the project

### Dashboard

```powershell
python main.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). Select or upload an order image, extract its data, inspect the normalized fields, and choose dry-run or live automation. The result page displays progress, verification status, and the milestone screenshot gallery.

### Command line

Extract and validate without touching Fakturama:

```powershell
python main.py --cli --image data/samples/purchase_order_01.png --dry-run
```

Use local OCR instead of Gemini:

```powershell
python main.py --cli --image data/samples/purchase_order_01.png --ocr --dry-run
```

Run the full desktop workflow:

```powershell
python main.py --cli --image data/samples/purchase_order_01.png
```

Screenshots are written to `artifacts/screenshots` by default. Use `--screenshot-dir <path>` to change the destination.

## Implemented workflow

1. **Extract and validate:** Normalize the Order date, reference, Debtor, addresses, payment, items, VAT, discounts, and totals. Reconcile line and document arithmetic before UI work.
2. **Open the Order:** Preserve Fakturama's proposed number, set Date and Cust.Ref., and force the SWT price mode to Net while keeping VAT enabled.
3. **Resolve the Debtor:** Search from the open Order. Select one exact match or create the missing Debtor and payment method, then return and reselect it.
4. **Resolve every Product:** Search each exact SKU. Ensure the VAT rate exists, create a missing Product when required, reselect it, and verify quantity, unit net price, VAT, discount, and line total.
5. **Save and verify the Order:** Verify Net mode and gross total, save the active editor, then copy the exact generated-number row from Data > Documents and verify date, reference, state, and total.
6. **Create the linked Invoice:** Use the saved Order's follow-up action, apply the extracted payment method and paid fields, and save.
7. **Final verification:** Read the exact Invoice row from Documents and verify its state, total, reference, date, and payment state. No Delivery, Correction, or Dunning document is created.

The complete requirement mapping is in [Implementation Checklist](docs/IMPLEMENTATION_CHECKLIST.md), and the selected visual proof is in [Evidence](docs/EVIDENCE.md).

## Verification and tests

```powershell
python -m pytest -q
```

Current result:

```text
76 passed
```

The tests cover extraction models, decimal reconciliation, payment mappings, dry-run orchestration, dashboard routes, control validation, and the save lifecycle. Live UI validation is separate because it requires an active Fakturama session.

## Safety and failure behavior

- UI controls must be visible, enabled, onscreen, and have a nonempty rectangle.
- The workflow owns one selected business editor and verifies its identity before and after Save.
- Fakturama can reapply a Debtor or Product pricing preference, so the workflow triggers a real Gross-to-Net selection event and verifies the final total before saving.
- Documents verification filters by the generated document number and requires exactly one matching row.
- The Documents table is identified from its UIA role and hierarchy, so window resizing does not depend on a fixed pixel width.
- Every completed stage records a captioned screenshot. Failures preserve the completed evidence and error message.

## Known limitations

- The verified environment is Fakturama 2.2 with English labels and English month names. Other locales need locator and date-parser validation.
- Existing-record matching depends on accessible values exposed by Fakturama. Multiple exact matches or conflicting definitions require manual review.
- Payment-code creation maps Bank Transfer, Credit Card, and SEPA Direct Debit. Other business terms need an explicit mapping.
- The final live regression covered the existing-master-data path. Missing Debtor, VAT, Product, and payment-method creation still need a clean-workspace live regression.
- This is interactive desktop automation. Locking the session, minimizing Fakturama, changing focus, or using its controls during a run can invalidate the evidence.

## Troubleshooting

| Symptom | Check |
|---|---|
| No Fakturama window found | Start Fakturama, restore it, and dismiss modal dialogs. |
| Price total is net instead of gross | Confirm the real SWT price-mode selection fired; the workflow deliberately toggles Gross then Net. |
| Save remains dirty | Inspect the selected editor identity and enabled Save toolbar action reported in the error. |
| Documents copy is empty | Keep the Documents view visible and Fakturama restored; current code reacquires SWT controls and supports resized layouts. |
| Duplicate or ambiguous match | Review the master data manually; the workflow stops instead of guessing. |

## Repository structure

```text
main.py                         Dashboard and CLI entry point
src/extractors/                 Gemini and Tesseract extraction
src/models/order.py             Validated order schema and calculations
src/automation/uia_wrapper.py   Microsoft UIA primitives and verified save
src/automation/fakturama_app.py Fakturama business actions and read-back
src/flow/orchestrator.py        Continuous Order-first workflow
src/ui/                         Flask dashboard
tests/                          Automated test suite
docs/DESIGN_DOCUMENT.md         Part 1 design deliverable
docs/IMPLEMENTATION_CHECKLIST.md Requirement-by-requirement status
docs/EVIDENCE.md                Annotated screenshot evidence
artifacts/screenshots/          Complete per-run visual audit trail
```

## If I had 3 more hours

I would run the missing Debtor, payment method, VAT, and Product branches against a fresh Fakturama workspace and preserve their evidence. I would then validate a multi-line image and a second window size and locale. Finally, I would capture a compact UIA-tree snapshot on failure so layout regressions can be diagnosed without repeating the entire workflow.

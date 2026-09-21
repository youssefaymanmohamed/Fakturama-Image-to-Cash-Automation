# Fakturama Image-to-Cash Automation — Design Document

**Author:** Youssef Ayman  
**Scope:** Design for converting one order image into a verified Fakturama Order and linked Invoice without fixed coordinates.

## 1. Proposed system

The system has four layers:

1. **Extraction:** Gemini Vision is the primary extractor, with Tesseract OCR as an offline option. Both return the same validated `OrderData` model.
2. **Validation:** Pydantic normalizes dates, decimals, Debtor fields, addresses, payment data, and item rows. Decimal arithmetic recomputes line net, VAT, and gross totals before desktop automation starts.
3. **Desktop automation:** Microsoft UI Automation discovers Fakturama's SWT controls through accessible names, control types, patterns, and parent-child relationships.
4. **Orchestration and evidence:** One Order-first state machine resolves master data, saves the Order, creates its follow-up Invoice, verifies both Documents rows, and captures a screenshot after every completed milestone.

```text
Image ─► extraction ─► validated OrderData ─► Order-first orchestrator
                                                     │
                                                     ▼
                                      Fakturama through UI Automation
                                                     │
                                                     ▼
                                      read-back checks + screenshots
```

## 2. Image extraction and validation

The Gemini prompt requests strict JSON containing the Order date and reference; Debtor company, contact, aliases, billing and delivery addresses; payment method, paid state, and payment date; and every SKU, description, quantity, unit net price, VAT percentage, discount, and source total. Low model temperature reduces output variation. Tesseract offers a local OCR and parsing path when external model access is unavailable.

Extraction is treated as untrusted input. The system parses dates into date objects and money into `Decimal`, then checks:

```text
line net   = quantity × unit net × (1 - discount / 100)
line VAT   = line net × VAT / 100
gross      = total net + total VAT
```

Source and computed totals must agree within a small rounding tolerance. A missing required field, invalid date, or unexplained total mismatch should be reviewed before a live run.

## 3. Control discovery and grounding

Fakturama is an Eclipse RCP/SWT application. Its controls appear in the Windows UI Automation tree, allowing the workflow to use semantic properties instead of a fixed layout.

Locators use this order of preference:

1. stable accessible name or AutomationId;
2. control type within a named editor, tab, dialog, or navigation branch;
3. association between a label and the next visible input sibling;
4. relative geometry inside an already-grounded control only when SWT exposes no stronger identity.

Every candidate must be enabled, onscreen, and have a nonempty rectangle. The active business editor is identified by its selected tab, matching content pane, document type, and proposed number. This prevents a global search from changing a hidden template or the wrong tab.

SWT sometimes replaces controls while applying a filter or changing tabs. The wrapper therefore polls for state, reacquires disposed elements, waits for stable results, and reads the value back after each write. Combo-box items are clicked so SWT receives its real selection event; setting only the UIA value can leave Fakturama's internal pricing mode unchanged.

## 4. Order-first workflow

The system opens the New Order before resolving master data and leaves it open throughout the workflow.

- It preserves the proposed Order number, sets Date and Cust.Ref., and selects Net pricing.
- The Order's address selector is the Debtor existence check. One exact match is selected; no match enters the creation branch; ambiguous matches stop for review.
- Each item uses the Order's Product selector in source order. A missing Product triggers VAT validation and Product creation before returning to the same Order.
- Selecting a Debtor or Product can reapply a stored Gross preference. The workflow therefore forces and verifies Net mode after those actions and immediately before saving.
- The active editor is saved only after its identity, lines, and gross total have been verified.
- Data > Documents is filtered by the generated number. The exact Order row must match its date, reference, open state, and total before the Invoice is created.
- The Invoice is created from the saved Order's follow-up action to preserve linkage. Inherited details are checked, payment fields are applied, and the Invoice is saved and verified in Documents.

The flow ends after Invoice verification. It does not create a Delivery, Correction, or Dunning document.

## 5. Verification, failure handling, and evidence

Verification is layered:

- **Field level:** every write is followed by a UI read-back.
- **Line level:** quantity, unit price, VAT, discount, and calculated line price are compared with extracted values.
- **Editor level:** Save must leave the same selected editor clean and retain the proposed document number.
- **Document level:** the exact generated-number row is copied from the SWT Documents table and parsed into date, reference, state, and total fields.
- **Visual level:** each completed workflow step produces a timestamped screenshot and caption.

An ambiguous master-data result, changed editor identity, failed total, unverified Save, or missing Documents row stops the workflow. In particular, a failed Order read-back prevents Invoice creation.

## 6. Tradeoffs

**UI Automation instead of coordinates:** This survives resizing and DPI changes and supplies readable state for verification. It still depends on accessible labels and SWT behavior, so major Fakturama or locale changes require validation.

**Order-first instead of master-data-first:** Fakturama's own selectors become authoritative existence checks and the work follows the requested user path. The cost is more tab switching and careful editor ownership.

**Full UI instead of database writes:** UI automation preserves Fakturama validation, numbering, and document linkage and produces auditable evidence. It is slower and requires an unlocked interactive Windows session.

**Stop instead of guess:** Stopping on ambiguity avoids duplicate Debtors, incorrect VAT definitions, and invoices linked to the wrong Order. Some cases therefore require a human decision.

## 7. Current validation and remaining work

The successful live regression used the existing-record branch and produced Order `PO000035` and linked Invoice `INV000020`, both verified at `276.97`. The test suite reports 76 passing tests. The missing Debtor, payment method, VAT, and Product paths exist and have automated coverage, but still require a clean-workspace live regression. Other Fakturama locales and multi-line source images also need end-to-end validation.

With three additional hours, I would record those missing-master-data branches, run a multi-line order, validate a second locale and window size, and persist a focused UIA-tree snapshot whenever a control cannot be grounded.

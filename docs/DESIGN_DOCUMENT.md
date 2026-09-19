# Fakturama Image-to-Cash Automation — Design Document

**Author:** Youssef Ayman  
**Date:** September 2025  
**Scope:** 1–4 page design document describing the system architecture, grounding strategy, extraction approach, and key tradeoffs.

---

## 1. System Overview

The system transforms a single purchase order image into fully saved and verified Order + Invoice records inside Fakturama 2.x. It operates as a **Robotic Desktop Automation (RDA)** pipeline with three core subsystems:

1. **Extraction Engine** — Converts the image into structured data using multimodal LLM vision (Gemini) or OCR.
2. **UI Automation Engine** — Discovers and interacts with Fakturama's SWT/Eclipse RCP interface using Microsoft UI Automation (UIA), completely independent of screen coordinates.
3. **Orchestrator** — Sequences the end-to-end Order-first flow, including conditional master data creation, mathematical verification, and error recovery.

```
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐     ┌──────────────┐
│ Order Image │────>│  Extraction  │────>│   Orchestrator   │────>│  Fakturama   │
│  (PNG/JPG)  │     │  (LLM/OCR)   │     │ (5-step flow)    │     │  (SWT/UIA)   │
└─────────────┘     └──────────────┘     └──────────────────┘     └──────────────┘
                           │                      │                       │
                    Pydantic schema         Conditional logic        Save & Verify
                    + math checks           + state machine         + Screenshots
```

---

## 2. Control-Discovery / Grounding Strategy

### 2.1 Why UIA over Coordinate-Based Approaches

Fakturama is an Eclipse RCP application using SWT (Standard Widget Toolkit). SWT widgets render native Win32 controls, which means they expose accessibility nodes through the Windows UI Automation (UIA) tree. This is the critical insight that makes coordinate-independent automation possible.

**Rejected alternatives:**
- **Fixed pixel coordinates** — Brittle; breaks with resolution/DPI changes, window resizing, or any UI update.
- **Template matching / OpenCV** — Requires maintaining a library of reference screenshots for each control; fragile across themes, fonts, and localizations.
- **Direct database manipulation** — Faster but bypasses business logic (validation, auto-numbering, cascading updates), which defeats the purpose of testing the full UI flow.

### 2.2 Element Discovery Hierarchy

Elements are located using this priority cascade (most reliable first):

1. **AutomationId** — Stable across localizations; ideal when Fakturama assigns them.
2. **Name** property — The accessible label (e.g., "Save", "Cust.Ref.", "Select the address"). Works well for Fakturama's consistently-labeled fields.
3. **ControlType + hierarchical position** — For controls without unique names, we navigate the tree (e.g., "the second EditControl inside the TabItem named 'Addresses'").
4. **ClassName** — SWT class names like "SWT_Window0" provide process-level anchoring.

All locator strings are centralized in a single `locators.py` module, so any label change in a Fakturama update requires editing exactly one file.

### 2.3 Interaction Patterns

| Pattern | Primary Method | Fallback |
|---|---|---|
| Click buttons | `InvokePattern.Invoke()` | `element.Click()` at center |
| Set text fields | `ValuePattern.SetValue()` | Focus + `SendKeys` |
| Select combos | `ExpandCollapsePattern` + `SelectionItemPattern` | Expand + name search + click |
| Select table rows | Walk children, substring match | Scroll + re-search |

### 2.4 Stabilization and Timing

SWT applications can lag behind UIA tree updates. Our wrapper addresses this with:

- **Smart waits:** All `find_*` methods poll with exponential backoff up to a configurable timeout (default 15s).
- **Table stabilization:** `wait_for_stable_list()` polls the row count until it remains constant for 3 consecutive checks.
- **Post-action delay:** A configurable 300ms pause after every UI action gives SWT time to process events.

---

## 3. Image-Extraction Strategy

### 3.1 Dual-Engine Architecture

The extraction subsystem supports two production engines through a common `BaseExtractor` interface:

| Engine | Use Case | Requirements |
|---|---|---|
| **Gemini Multimodal Vision** | Primary — high-accuracy semantic and visual data extraction | `GOOGLE_API_KEY` |
| **Tesseract OCR + Regex** | Offline / air-gapped environments without external API calls | Local Tesseract OCR binary |

### 3.2 LLM Prompt Engineering

The LLM receives:
1. The raw image bytes with correct MIME type
2. A strict JSON schema prompt with explicit formatting rules (dates as YYYY-MM-DD, decimals with period separator, payment method enum values)
3. Temperature = 0.1 for deterministic output

Key prompt design decisions:
- **Explicit enum constraints** for payment methods prevent hallucinated values
- **No markdown fences** instruction prevents formatting wrapper issues
- **Example values** in the schema help the model understand expected precision

### 3.3 Mathematical Reconciliation

Post-extraction, every line item and order total is cross-checked:

```
Line Total = Qty × Net Price × (1 - Discount/100)
Gross Price = Net Price × (1 + VAT/100)
Order Total Net = Σ Line Totals
Order Total Gross = Net + VAT
```

Mismatches beyond ±$0.05 are flagged as warnings. This catches OCR digit errors (e.g., "1" read as "7") that would otherwise propagate silently.

---

## 4. Tradeoffs and Design Decisions

### 4.1 Order-First vs. Master-Data-First

We open the Order **before** resolving master data. This means:

✅ The Order's built-in selectors serve as existence checks (no duplicate lookups)  
✅ The Order tab stays open throughout, preserving context  
⚠️ Multiple tab switching is required when creating new Debtors/Products

### 4.2 Full UI Flow vs. Direct DB Access

We chose full UI automation over HSQLDB direct writes because:

✅ Exercises the same path a human user would take  
✅ Validates Fakturama's auto-numbering, cascading saves, and follow-up document linkage  
✅ Screenshots provide visual audit trail  
⚠️ Slower (~2-5 minutes per order vs. <1 second for DB writes)  
⚠️ More fragile to unexpected dialogs or UI state

### 4.3 Stop-for-Review Safety

When ambiguous data is detected (multiple Debtor matches, conflicting VAT definitions), the system raises `StopForReview` rather than guessing. This is a deliberate safety valve — wrong master data creation would cascade through all future documents.

---

## 5. If I Had 3 More Hours

1. **Accessibility tree mapping tool** — Build a quick utility that dumps Fakturama's full UIA tree as JSON/HTML for every editor state. This dramatically accelerates locator development and debugging.

2. **Retry and recovery middleware** — Add an automatic retry layer that captures screenshots on failure, attempts to close unexpected dialogs (confirmation popups, error windows), and resumes from the last successful checkpoint.

3. **Multi-order batch mode** — Accept a directory of PO images and process them sequentially, accumulating results into a summary report. Handle the case where Products/Debtors created during one order are reused in subsequent orders.

4. **Visual regression testing** — Compare milestone screenshots against golden baselines using structural similarity (SSIM) to detect unexpected UI changes.

5. **End-to-end integration test** — Run the full flow against a fresh Fakturama workspace with known-empty master data, verifying that all created records are queryable in `Data > Documents` with exact field matching.

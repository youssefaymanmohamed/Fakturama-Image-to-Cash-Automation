# Implementation Checklist

Status meanings:

- **Live verified:** observed in the successful `PO000035` → `INV000020` run.
- **Implemented:** code and automated checks exist, but the final live run did not take that conditional branch.
- **Partial:** only part of the stated requirement is currently proved.

## 1. Extract the image and open a New Order

| Requirement | Status | Evidence or note |
|---|---|---|
| 1.1 Extract and normalize one order image | Live verified | Gemini fast-path data appeared in the dashboard and passed model validation. |
| 1.2 Extract header, Debtor, addresses, payment, every item, and totals | Live verified | Sample produced one complete line plus reference, customer, totals, payment method, paid state, and dates. |
| 1.3 Open New Order | Live verified | Fakturama opened and verified the selected New Order editor. |
| 1.4 Preserve proposed No. | Live verified | Save retained the proposed number and produced `PO000035`. |
| 1.5 Set extracted Date | Live verified | `15.03.2025` was written and read back. |
| 1.6 Set Cust.Ref. | Live verified | `PO-2025-0042` was written and later verified in Documents. |
| 1.7 Set Net and keep VAT enabled | Live verified | Net was selected through the SWT event path and rechecked before Save. |
| 1.8 Keep Order open while resolving master data | Live verified for existing records | Creation branches retain the Order editor but need a fresh-workspace live run. |

## 2. Select or create the Debtor

| Requirement | Status | Evidence or note |
|---|---|---|
| 2.1–2.4 Search from the Order, select one exact Debtor, verify populated addresses | Live verified | Existing Acme Corporation Debtor was selected from the Order. Ambiguity stops the run. |
| 2.5–2.9 Create missing Debtor, address roles, alias, discount, and Net preference | Implemented | Conditional UIA branch exists; not exercised by the final regression. |
| 2.10 Select exact payment method | Live verified | Bank Transfer was selected for the Invoice; Debtor creation path also assigns it. |
| 2.10.1–2.10.6 Resolve or create missing payment method | Implemented | Exact lookup, payment-code mapping, zero-day defaults, Save, and return path exist; not live verified in the final run. |
| 2.11 Save Debtor once | Implemented | Uses the verified active-editor save lifecycle. |
| 2.12–2.13 Return to Order, reselect new Debtor, verify population | Implemented | Reselection branch exists; not live verified in the final run. |

## 3. Select or create each Product

| Requirement | Status | Evidence or note |
|---|---|---|
| 3.1 Repeat in source order | Implemented | Orchestrator loops through `order_data.items` in order. Final live input contained one item. |
| 3.2–3.3 Search exact SKU and select one Product | Live verified | `WIDGET-001` was selected from the open Order. |
| 3.4–3.6 Resolve or create the exact VAT definition | Implemented | VAT lookup and creation branch exists; existing VAT was reused in the final run. |
| 3.7–3.12 Create and reselect a missing Product | Implemented | Gross price, VAT, zero cost/stock, Save, return, and exact SKU reselection exist; not exercised in the final run. |
| 3.13–3.16 Set and verify quantity, unit net, VAT, discount, and line price | Live verified | Line `WIDGET-001 × 10` was checked before Order Save. |
| 3.17 Repeat for remaining items | Implemented | Loop supports multiple rows; a multi-line live regression remains. |

## 4. Complete and save the Order

| Requirement | Status | Evidence or note |
|---|---|---|
| 4.1 Confirm Debtor and every line | Live verified | Debtor selection and line checks are hard gates. |
| 4.2 Keep overall discount/shipping defaults unless supplied | Partial | Sample retained Fakturama defaults. Explicit source-level shipping/discount input is not modeled. |
| 4.3 Confirm net, VAT, and gross totals | Live verified | Extracted totals were reconciled and displayed gross `276.97` was checked immediately before Save. |
| 4.4 Save once | Live verified | Active Order became clean without changing its proposed number. |
| 4.5 Verify exact Order row in Documents | Live verified | `PO000035`, date, Cust.Ref., open state, and total passed exact row read-back. |
| 4.6–4.7 Create linked Invoice from follow-up action | Live verified | Follow-up Invoice editor opened from the saved Order. |

## 5. Complete and verify the linked Invoice

| Requirement | Status | Evidence or note |
|---|---|---|
| 5.1 Preserve proposed Invoice fields and inherited Order data | Live verified | Linked Invoice retained reference, addresses, item, pricing mode, and total. |
| 5.2 Set exact payment method | Live verified | Bank Transfer read back successfully. |
| 5.3 Apply paid state, date, and full value | Live verified | Paid date `20.03.2025` and value `276.97` were verified. |
| 5.4 Save once | Live verified | Invoice saved as `INV000020`. |
| 5.5 Verify Invoice row and source Order | Partial | Exact Invoice row passed. The source Order was verified immediately beforehand, rather than re-read together during the final check. |
| 5.6 Reopen Invoice only if required | Not required | Payment fields were read back before Save and final state was verified in Documents. |
| 5.7 End without other document types | Live verified | The workflow ended after Invoice verification and created no Delivery, Correction, or Dunning record. |

## Deliverables

| Deliverable | Status |
|---|---|
| Structured source repository | Complete |
| Setup and run instructions | Complete in `README.md` |
| Annotated screenshots | Complete in `docs/EVIDENCE.md`; full gallery remains in `artifacts/screenshots` |
| README | Complete |
| Design document | Complete in `docs/DESIGN_DOCUMENT.md` |
| Written three-hour follow-up | Complete in the README and design document |

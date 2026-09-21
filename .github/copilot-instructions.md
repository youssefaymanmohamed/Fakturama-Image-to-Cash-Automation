# Fakturama Image-to-Cash Automation — Copilot Instructions

## PRIMARY OBJECTIVE

This repository automates the Fakturama desktop application using Microsoft UI Automation.

The current priority is to make the ACTUAL Fakturama desktop workflow work reliably through real GUI interaction.

Do NOT optimize for terminal-only testing.

When debugging UI automation, actually launch Fakturama, inspect the real GUI, inspect the UI Automation tree, interact with the application, and capture screenshots when possible.

---

# ABSOLUTE SCOPE RULE

The existing extraction pipeline is OUT OF SCOPE.

DO NOT modify:

* Gemini
* OpenAI
* LLM extraction
* OCR
* PyTesseract
* image preprocessing
* extraction prompts
* extraction schemas
* mock extraction
* fallback extraction
* sample generation
* extraction business logic

Assume structured order extraction is already working.

The automation layer starts at:

`structured extracted order data → Fakturama`

Do not "improve" extraction while debugging UI automation.

---

# UI AUTOMATION PRIORITY

Use the existing Microsoft UI Automation implementation.

Do NOT replace the project with another automation framework.

Prefer semantic UIA interaction using:

1. AutomationId
2. ControlType
3. Name
4. Parent/child relationship
5. Window/dialog context

Avoid coordinate-based interaction.

Do not assume a control works merely because a Python call returns successfully.

Every important interaction must be verified through the resulting UI state.

---

# REAL GUI TESTING

When debugging UI automation, test the actual installed Fakturama application.

Do not rely only on:

* static code inspection
* terminal output
* unit tests
* mocked UI objects
* assumptions based on screenshots
* assumptions based on the assignment document

The real GUI is the source of truth.

When possible:

1. Launch Fakturama.
2. Bring it to the foreground.
3. Inspect the actual window.
4. Inspect the UIA tree.
5. Perform the action.
6. Capture a screenshot.
7. Verify the resulting UI state.
8. Continue.

If an operation fails, capture the failure state before modifying code.

---

# WINDOW STATE

Fakturama must remain in NORMAL / RESTORED window state.

DO NOT:

* maximize Fakturama
* fullscreen Fakturama
* call Win32 maximize APIs
* use `SW_MAXIMIZE`
* aggressively resize the application
* change the internal Fakturama layout

If Fakturama starts maximized, restore it before automation.

Do not hardcode screen dimensions just to make the automation work.

---

# VERIFICATION RULE

Never treat "no exception" as proof that an interaction succeeded.

Use:

`ACTION → WAIT → READ BACK → VERIFY → CONTINUE`

Examples:

### Text input

Bad:

```text
set_text("Cairo")
→ no exception
→ continue
```

Good:

```text
set_text("Cairo")
→ read UIA value
→ verify value == "Cairo"
→ continue
```

### Save

Bad:

```text
click Save
→ no exception
→ assume saved
```

Good:

```text
click Save
→ wait for UI transition
→ verify saved state/document
→ continue
```

---

# UIA TREE DEBUGGING

When a selector fails, inspect the LIVE UIA tree.

Check:

* Name
* AutomationId
* ControlType
* ClassName
* FrameworkId
* IsEnabled
* IsOffscreen
* BoundingRectangle
* Supported patterns
* Parent
* Children
* Siblings

Do not invent selectors.

Do not blindly try random selectors.

Adapt the selector to the actual currently installed Fakturama UI.

---

# TEXT FIELDS

For important fields:

1. Locate the actual control.
2. Focus it if necessary.
3. Enter the value.
4. Read the value back.
5. Compare expected vs actual.
6. Only continue if verified.

This applies to:

* Company
* First Name
* Last Name
* Street
* ZIP
* City
* Country
* Email
* Telephone
* Alias
* Customer Reference
* SKU
* Product Description
* Quantity
* Unit Price
* Discount

---

# COMBOBOXES / SELECTIONS

For Debtor, Product, VAT, Payment Method, Country, and Payment Status:

1. Locate the correct control.
2. Open it.
3. Wait for results.
4. Select the intended item.
5. Read back the selected value.
6. Verify it.
7. Continue.

Do not assume selection succeeded.

---

# BUTTONS

Do not use "first matching button".

Context matters.

In particular, Fakturama contains different actions for:

* selecting an existing Debtor/Product
* creating a new Debtor/Product

Do not accidentally invoke the green "+" creation button when the workflow requires the upper existing-record selector.

Verify the button using UIA properties and surrounding context.

---

# TIMING

Do not solve synchronization problems with large arbitrary sleeps.

Avoid patterns such as:

```python
sleep(10)
sleep(20)
```

Prefer condition-based waits for:

* Window existence
* Dialog

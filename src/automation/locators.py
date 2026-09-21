"""
Semantic locator definitions for Fakturama 2.2.

Centralizes all UI element identifiers (Names, AutomationIds, ClassNames)
so that the automation code never uses hardcoded strings. Confirmed against
the live installed Fakturama 2.2 application.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolbarLocators:
    """Top-level toolbar buttons in Fakturama 2.2."""
    SAVE = "Save the current contents"
    ORDER_NEW = "Create: New Order"
    INVOICE_NEW = "Create: New Invoice"
    NEW_CONTACT = "Create a new contact"
    NEW_PRODUCT = "Create a new product"

    # Fallback lists for robust discovery across UI states
    SAVE_NAMES = ("Save the current contents", "Save", "Speichern")
    ORDER_NEW_NAMES = ("Create: New Order", "New Order", "Order")
    INVOICE_NEW_NAMES = ("Create: New Invoice", "New Invoice", "Invoice")
    NEW_CONTACT_NAMES = ("Create a new contact", "New Contact", "Contact")
    NEW_PRODUCT_NAMES = ("Create a new product", "New product", "Product")


@dataclass(frozen=True)
class NavigationLocators:
    """Left-panel navigation tree items."""
    DATA = "Data"
    DOCUMENTS = "Documents"
    CONTACTS = "Contacts"
    DEBTORS = "Debtors"
    CREDITORS = "Creditors"
    PRODUCTS = "Products"
    VATS = "VATs"
    TERMS_OF_PAYMENT = "terms of payment"
    NEW_PANEL = "New"
    NEW_PRODUCT = "New product"
    NEW_CONTACT = "New Contact"


@dataclass(frozen=True)
class OrderEditorLocators:
    """Fields and controls within the Order editor tab."""
    TAB_PREFIX = "New Order"
    ORDER_TAB_PREFIX = "Order:"

    # Header fields
    ORDER_NUMBER = "No."
    ORDER_DATE = "Date"
    CUST_REF = "Cust.Ref."
    PRICE_MODE_NET = "Net"
    PRICE_MODE_GROSS = "Gross"
    VAT_MODE = "VAT"
    VAT_WITH = "With VAT"

    # Address section
    ADDRESSES_LABEL = "Addresses"
    INVOICE_ADDRESS_TAB = "Invoice address"
    PICK_ADDRESS_TOOLTIP = "Pick an address from the list of all contacts"

    # Items section
    ITEMS_LABEL = "Items"
    PICK_PRODUCT_TOOLTIP = "Pick an item from the list of all products"

    # Item line fields (within the selected line)
    ITEM_QTY = "Qty."
    ITEM_UPRICE = "U.Price"
    ITEM_VAT = "VAT"
    ITEM_DISCOUNT = "Discount"
    ITEM_PRICE = "Price"
    ITEM_NUMBER = "Item No."
    ITEM_NAME = "Name"

    # Totals
    DISCOUNT_OVERALL = "Discount"
    SHIPPING = "Shipping"
    TOTAL_NET = "Total Net"
    TOTAL_VAT = "VAT"
    TOTAL_GROSS = "Total"

    # Follow-up
    FOLLOWUP_GROUP = "Create a follow-up document"
    FOLLOWUP_INVOICE = "Invoice"


@dataclass(frozen=True)
class ContactEditorLocators:
    """Fields within the New Contact / Debtor editor."""
    CUSTOMER_ID = "Customer ID"
    COMPANY = "Company"
    FIRST_NAME = "First Name"
    LAST_NAME = "Name"  # Fakturama labels it "Name"
    FIRST_LAST_NAME = "First Name Last Name"
    SALUTATION = "Salutation"

    # Address tab
    ADDRESSES_TAB = "Addresses"
    MAIN_ADDRESS = "Main address"
    STREET = "Street"
    ZIP_CITY = "ZIP - City"
    ZIP_CODE = "ZIP"
    CITY = "City"
    COUNTRY = "Country"
    EMAIL = "E-Mail"
    TELEPHONE = "Telephone"
    INVOICE_ADDRESS_ROLE = "Invoice address"
    DELIVERY_ADDRESS_ROLE = "Delivery address"

    # Miscellaneous tab
    MISCELLANEOUS_TAB = "Miscellaneous"
    ALIAS_NAME = "Alias name"
    DISCOUNT = "Discount"
    NET_OR_GROSS = "Net or Gross"

    # Payment tab
    PAYMENT_TAB = "Payment"
    PAYMENT_METHOD = "Payment Method"


@dataclass(frozen=True)
class PaymentEditorLocators:
    """Fields in the Payment Method editor (Data > terms of payment)."""
    NAME = "Name"
    DESCRIPTION = "Description"
    ACCOUNT = "Account"
    PAYMENT_CODE = "Payment code"  # Dropdown
    CASH_DISCOUNT = "Cash discount"
    DISCOUNT_DAYS = "Discount Days"
    NET_DAYS = "Net Days"
    SET_AS_STANDARD = "Set as standard"


@dataclass(frozen=True)
class VATEditorLocators:
    """Fields in the VAT editor (Data > VATs)."""
    NAME = "Name"
    DESCRIPTION = "Description"
    VAT_CODE = "VAT code (E-Invoice)"
    STANDARD_RATE = "S (Standard rate)"
    VALUE = "Value"


@dataclass(frozen=True)
class ProductEditorLocators:
    """Fields in the New Product editor."""
    ITEM_NUMBER = "Item Number"
    NAME = "Name"
    DESCRIPTION = "Description"
    PRICE_GROSS = "Price (gross)"
    COST_PRICE_NET = "cost price (net)"
    VAT = "VAT"
    STOCK = "Stock"


@dataclass(frozen=True)
class InvoiceEditorLocators:
    """Fields within the Invoice editor (follow-up from Order)."""
    INVOICE_NUMBER = "Invoice No."
    INVOICE_DATE = "Invoice Date"
    SERVICE_DATE = "Service date"
    CUST_REF = "Cust.Ref."
    PAYMENT_METHOD = "Payment Method"
    PAID_CHECKBOX = "paid"
    PAYMENT_DATE = "Payment date"
    PAYMENT_VALUE = "Value"


@dataclass(frozen=True)
class DialogLocators:
    """Common dialog buttons and elements."""
    OK = "OK"
    CANCEL = "Cancel"
    SEARCH_LABEL = "Search:"
    SEARCH_FIELD = "Search"
    SELECT_ADDRESS_DIALOG = "Select the address"
    SELECT_PRODUCT_DIALOG = "Select a product"
    GREEN_PLUS = "+"


@dataclass(frozen=True)
class DocumentListLocators:
    """Columns in Data > Documents list."""
    DOC_TYPE = "Type"
    DOC_NUMBER = "Number"
    DOC_DATE = "Date"
    CUST_REF = "Cust.Ref."
    STATE = "State"
    TOTAL = "Total"


# ---------------------------------------------------------------------------
# Singleton instances for convenient import
# ---------------------------------------------------------------------------

TOOLBAR = ToolbarLocators()
NAV = NavigationLocators()
ORDER = OrderEditorLocators()
CONTACT = ContactEditorLocators()
PAYMENT = PaymentEditorLocators()
VAT = VATEditorLocators()
PRODUCT = ProductEditorLocators()
INVOICE = InvoiceEditorLocators()
DIALOG = DialogLocators()
DOC_LIST = DocumentListLocators()

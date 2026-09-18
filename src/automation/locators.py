"""
Semantic locator definitions for Fakturama 2.2.

Centralizes all UI element identifiers (Names, AutomationIds, ClassNames)
so that the automation code never uses hardcoded strings. If Fakturama
changes its UI labels, only this file needs updating.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolbarLocators:
    """Top-level toolbar buttons."""
    SAVE = "Save"
    ORDER_NEW = "Order"
    INVOICE_NEW = "Invoice"
    NEW_CONTACT = "New Contact"
    NEW_PRODUCT = "New product"


@dataclass(frozen=True)
class NavigationLocators:
    """Left-panel navigation tree items."""
    DATA = "Data"
    DOCUMENTS = "Documents"
    CONTACTS = "Contacts"
    PRODUCTS = "Products"
    VATS = "VATs"
    TERMS_OF_PAYMENT = "terms of payment"
    NEW_PANEL = "New"


@dataclass(frozen=True)
class OrderEditorLocators:
    """Fields and controls within the Order editor tab."""
    # Header fields
    ORDER_NUMBER = "No."
    ORDER_DATE = "Date"
    CUST_REF = "Cust.Ref."
    PRICE_MODE_NET = "Net"
    VAT_WITH = "With VAT"

    # Address section
    ADDRESSES_LABEL = "Addresses"
    SELECT_CONTACT_ICON = "Select the address"  # Upper existing-contact icon
    NEW_CONTACT_ICON = "New contact"  # Lower green + icon (DO NOT USE for selection)

    # Items section
    ITEMS_TABLE = "Items"
    SELECT_PRODUCT_ICON = "Select a product"  # Upper product-selection icon

    # Item line fields (within the selected line)
    ITEM_QTY = "Qty."
    ITEM_UPRICE = "U.Price"
    ITEM_VAT = "VAT"
    ITEM_DISCOUNT = "Discount"
    ITEM_PRICE = "Price"

    # Totals
    DISCOUNT_OVERALL = "Discount"
    SHIPPING = "Shipping"
    TOTAL_NET = "Total Net"
    TOTAL_VAT = "VAT"
    TOTAL_GROSS = "Total"

    # Follow-up
    FOLLOWUP_INVOICE = "Invoice"


@dataclass(frozen=True)
class ContactEditorLocators:
    """Fields within the New Contact / Debtor editor."""
    CUSTOMER_ID = "Customer ID"
    COMPANY = "Company"
    FIRST_NAME = "First Name"
    LAST_NAME = "Name"  # Note: Fakturama labels it "Name" not "Last Name"
    SALUTATION = "Salutation"

    # Address tab
    ADDRESSES_TAB = "Addresses"
    MAIN_ADDRESS = "Main address"
    STREET = "Street"
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
    SEARCH_FIELD = "Search"
    SELECT_ADDRESS_DIALOG = "Select the address"
    SELECT_PRODUCT_DIALOG = "Select a product"
    GREEN_PLUS = "+"  # Green + button for adding new items


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

"""
Microsoft UI Automation wrapper for Fakturama SWT/Eclipse RCP.

Provides coordinate-independent element discovery, pattern invocation,
smart waits, window management, and screenshot capture. Works with
SWT accessibility nodes exposed through the Windows UIA bridge.
"""

from __future__ import annotations

import ctypes
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Conditionally import Windows-only modules
try:
    import uiautomation as auto
    HAS_UIA = True
except ImportError:
    HAS_UIA = False
    auto = None


class UIAError(Exception):
    """Raised when a UI Automation operation fails."""
    pass


class StopForReview(Exception):
    """
    Raised when ambiguous or conflicting data is found and the flow
    must stop for manual review (as specified in the assignment).
    """
    pass


class UIAWrapper:
    """
    Coordinate-independent wrapper around Microsoft UI Automation 3.0.

    Key design decisions:
    - Elements are found by Name, AutomationId, ClassName, and ControlType
      (never by screen coordinates).
    - All waits use exponential backoff with configurable timeouts.
    - SWT widgets are accessed through their Win32-bridged accessibility nodes.
    - Screenshots are captured via Win32 PrintWindow for reliability.
    """

    # Default timeouts
    FIND_TIMEOUT = 15  # seconds to wait for an element to appear
    STABILIZE_TIMEOUT = 5  # seconds to wait for list/table to stop changing
    ACTION_DELAY = 0.3  # seconds between UI actions for SWT processing

    def __init__(self, screenshot_dir: str | Path = "artifacts/screenshots"):
        if not HAS_UIA:
            raise UIAError(
                "uiautomation package is not available. "
                "Install it with: pip install uiautomation"
            )
        self._screenshot_dir = Path(screenshot_dir)
        self._screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._screenshot_counter = 0
        self._root_window: Optional[auto.WindowControl] = None

    # -----------------------------------------------------------------------
    # Window management
    # -----------------------------------------------------------------------

    def find_fakturama_window(self, timeout: int = 30) -> auto.WindowControl:
        """Find the main Fakturama window by partial title match."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                # Fakturama windows may have various titles
                for win in auto.GetRootControl().GetChildren():
                    if win.ControlTypeName == "WindowControl":
                        name = win.Name or ""
                        class_name = win.ClassName or ""
                        if "fakturama" in name.lower() or "SWT_Window" in class_name:
                            self._root_window = win
                            logger.info(f"Found Fakturama window: '{name}' ({class_name})")
                            return win
            except Exception:
                pass
            time.sleep(1)
        raise UIAError(f"Fakturama window not found within {timeout}s")

    def attach_or_launch(
        self,
        exe_path: str = r"C:\Program Files\Fakturama2\Fakturama.exe",
        timeout: int = 45,
    ) -> auto.WindowControl:
        """Attach to a running Fakturama instance or launch a new one."""
        try:
            return self.find_fakturama_window(timeout=5)
        except UIAError:
            logger.info(f"Launching Fakturama from: {exe_path}")
            os.startfile(exe_path)
            return self.find_fakturama_window(timeout=timeout)

    def get_root(self) -> auto.WindowControl:
        """Return the cached root Fakturama window."""
        if self._root_window is None:
            raise UIAError("Not attached to Fakturama. Call attach_or_launch() first.")
        return self._root_window

    # -----------------------------------------------------------------------
    # Element discovery (coordinate-independent)
    # -----------------------------------------------------------------------

    def find_by_name(
        self,
        name: str,
        control_type: str = "",
        parent=None,
        timeout: float | None = None,
        partial: bool = False,
    ):
        """
        Find a UI element by its accessible Name property.
        Uses substring matching when partial=True.
        """
        timeout = timeout or self.FIND_TIMEOUT
        parent = parent or self.get_root()
        deadline = time.time() + timeout

        while time.time() < deadline:
            try:
                children = self._walk_tree(parent, max_depth=15)
                for el in children:
                    el_name = el.Name or ""
                    if partial:
                        match = name.lower() in el_name.lower()
                    else:
                        match = el_name == name

                    if match:
                        if control_type and el.ControlTypeName != control_type:
                            continue
                        return el
            except Exception as e:
                logger.debug(f"find_by_name retry: {e}")
            time.sleep(0.5)

        raise UIAError(f"Element not found: name='{name}', type='{control_type}'")

    def find_by_automation_id(
        self, auto_id: str, parent=None, timeout: float | None = None
    ):
        """Find element by AutomationId property."""
        timeout = timeout or self.FIND_TIMEOUT
        parent = parent or self.get_root()
        deadline = time.time() + timeout

        while time.time() < deadline:
            try:
                children = self._walk_tree(parent, max_depth=15)
                for el in children:
                    if (el.AutomationId or "") == auto_id:
                        return el
            except Exception:
                pass
            time.sleep(0.5)

        raise UIAError(f"Element not found: AutomationId='{auto_id}'")

    def find_by_class(
        self, class_name: str, parent=None, timeout: float | None = None
    ):
        """Find element by ClassName."""
        timeout = timeout or self.FIND_TIMEOUT
        parent = parent or self.get_root()
        deadline = time.time() + timeout

        while time.time() < deadline:
            try:
                children = self._walk_tree(parent, max_depth=10)
                for el in children:
                    if (el.ClassName or "") == class_name:
                        return el
            except Exception:
                pass
            time.sleep(0.5)

        raise UIAError(f"Element not found: ClassName='{class_name}'")

    def find_all_by_type(
        self, control_type: str, parent=None, max_depth: int = 10
    ) -> list:
        """Find all elements of a given ControlType."""
        parent = parent or self.get_root()
        children = self._walk_tree(parent, max_depth=max_depth)
        return [el for el in children if el.ControlTypeName == control_type]

    def find_toolbar_button(self, name: str, parent=None) -> auto.Control:
        """
        Find a toolbar button by name. Fakturama uses Eclipse RCP toolbars
        where buttons may be ToolBarControl > ButtonControl or ToolItemControl.
        """
        parent = parent or self.get_root()
        toolbars = self.find_all_by_type("ToolBarControl", parent)
        for tb in toolbars:
            items = self._walk_tree(tb, max_depth=3)
            for item in items:
                item_name = item.Name or ""
                if item_name == name or name.lower() in item_name.lower():
                    return item
        raise UIAError(f"Toolbar button not found: '{name}'")

    # -----------------------------------------------------------------------
    # Actions (pattern-based, no coordinates)
    # -----------------------------------------------------------------------

    def click(self, element, delay: float | None = None):
        """
        Click an element using InvokePattern if available, otherwise
        fall back to simulated mouse click at the element center.
        """
        delay = delay or self.ACTION_DELAY
        try:
            invoke = element.GetInvokePattern()
            if invoke:
                invoke.Invoke()
                time.sleep(delay)
                return
        except Exception:
            pass

        # Fallback: click at element center
        try:
            rect = element.BoundingRectangle
            if rect.width() > 0 and rect.height() > 0:
                element.Click()
                time.sleep(delay)
                return
        except Exception:
            pass

        raise UIAError(f"Cannot click element: {element.Name}")

    def set_value(self, element, value: str, delay: float | None = None):
        """
        Set the value of an edit/text field using ValuePattern,
        falling back to keyboard input.
        """
        delay = delay or self.ACTION_DELAY
        try:
            vp = element.GetValuePattern()
            if vp:
                vp.SetValue(value)
                time.sleep(delay)
                return
        except Exception:
            pass

        # Fallback: focus + keyboard
        try:
            element.SetFocus()
            time.sleep(0.1)
            # Select all and type
            auto.SendKeys("{Ctrl}a")
            time.sleep(0.1)
            auto.SendKeys(value, interval=0.02)
            time.sleep(delay)
            return
        except Exception:
            pass

        raise UIAError(f"Cannot set value on element: {element.Name}")

    def get_value(self, element) -> str:
        """Read the current value of an element."""
        try:
            vp = element.GetValuePattern()
            if vp:
                return vp.Value
        except Exception:
            pass
        return element.Name or ""

    def select_combo_item(self, combo_element, item_name: str):
        """
        Select an item in a ComboBox by expanding it and clicking the item.
        """
        try:
            # Try ExpandCollapse pattern
            ecp = combo_element.GetExpandCollapsePattern()
            if ecp:
                ecp.Expand()
                time.sleep(0.3)
        except Exception:
            self.click(combo_element)
            time.sleep(0.3)

        # Find and select the item
        items = self._walk_tree(combo_element, max_depth=5)
        for item in items:
            if (item.Name or "") == item_name:
                try:
                    sp = item.GetSelectionItemPattern()
                    if sp:
                        sp.Select()
                        time.sleep(self.ACTION_DELAY)
                        return
                except Exception:
                    self.click(item)
                    return

        raise UIAError(f"Combo item not found: '{item_name}'")

    def select_table_row(self, table_element, search_text: str) -> bool:
        """
        Find and select a row in a table/list that contains the search text.
        Returns True if found and selected, False if not found.
        """
        rows = self._walk_tree(table_element, max_depth=5)
        for row in rows:
            row_text = self._get_full_text(row)
            if search_text.lower() in row_text.lower():
                try:
                    sp = row.GetSelectionItemPattern()
                    if sp:
                        sp.Select()
                        time.sleep(self.ACTION_DELAY)
                        return True
                except Exception:
                    self.click(row)
                    return True
        return False

    def send_keys(self, keys: str, interval: float = 0.02):
        """Send keyboard input using uiautomation's SendKeys."""
        auto.SendKeys(keys, interval=interval)
        time.sleep(self.ACTION_DELAY)

    # -----------------------------------------------------------------------
    # Wait utilities
    # -----------------------------------------------------------------------

    def wait_for_element(
        self, name: str, control_type: str = "", timeout: float | None = None,
        parent=None, partial: bool = False,
    ):
        """Wait for an element to appear, then return it."""
        return self.find_by_name(
            name, control_type=control_type, parent=parent,
            timeout=timeout, partial=partial,
        )

    def wait_for_window(self, title: str, timeout: float = 15) -> auto.WindowControl:
        """Wait for a window with the given title to appear."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                for win in auto.GetRootControl().GetChildren():
                    win_name = win.Name or ""
                    if title.lower() in win_name.lower():
                        return win
            except Exception:
                pass
            time.sleep(0.5)
        raise UIAError(f"Window not found: '{title}'")

    def wait_for_stable_list(
        self, list_element, timeout: float | None = None
    ) -> int:
        """
        Wait for a list/table to stabilize (stop changing row count).
        Returns the final row count.
        """
        timeout = timeout or self.STABILIZE_TIMEOUT
        deadline = time.time() + timeout
        prev_count = -1
        stable_ticks = 0

        while time.time() < deadline:
            try:
                items = self.find_all_by_type("ListItemControl", list_element)
                count = len(items)
            except Exception:
                count = 0

            if count == prev_count:
                stable_ticks += 1
                if stable_ticks >= 3:
                    return count
            else:
                stable_ticks = 0
                prev_count = count
            time.sleep(0.3)

        return prev_count

    # -----------------------------------------------------------------------
    # Screenshots
    # -----------------------------------------------------------------------

    def capture_screenshot(self, label: str = "") -> Path:
        """
        Capture a screenshot of the entire screen and save it with a label.
        Returns the path to the saved screenshot.
        """
        self._screenshot_counter += 1
        timestamp = datetime.now().strftime("%H%M%S")
        safe_label = label.replace(" ", "_").replace("/", "-")[:50]
        filename = f"{self._screenshot_counter:03d}_{timestamp}_{safe_label}.png"
        filepath = self._screenshot_dir / filename

        try:
            # Use PIL for cross-platform screenshot
            from PIL import ImageGrab
            img = ImageGrab.grab()
            img.save(str(filepath))
            logger.info(f"Screenshot saved: {filepath}")
        except Exception as e:
            logger.warning(f"Screenshot failed: {e}")
            filepath = self._screenshot_dir / f"{filename}.failed"
            filepath.write_text(f"Screenshot failed: {e}")

        return filepath

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _walk_tree(self, root, max_depth: int = 10, _depth: int = 0) -> list:
        """Recursively walk the UIA tree and collect all elements."""
        if _depth >= max_depth:
            return []
        result = []
        try:
            for child in root.GetChildren():
                result.append(child)
                result.extend(self._walk_tree(child, max_depth, _depth + 1))
        except Exception:
            pass
        return result

    def _get_full_text(self, element) -> str:
        """Get the full text content of an element and its children."""
        parts = []
        name = element.Name or ""
        if name:
            parts.append(name)
        try:
            vp = element.GetValuePattern()
            if vp and vp.Value:
                parts.append(vp.Value)
        except Exception:
            pass
        for child in self._walk_tree(element, max_depth=3):
            child_name = child.Name or ""
            if child_name:
                parts.append(child_name)
        return " ".join(parts)

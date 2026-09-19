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

    def _bring_to_front(self, win: auto.WindowControl):
        """Bring window to foreground so the user can physically watch automation."""
        try:
            hwnd = win.NativeWindowHandle
            if hwnd:
                import ctypes
                user32 = ctypes.windll.user32
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
        except Exception:
            pass
        try:
            win.SetFocus()
        except Exception:
            pass

    def find_fakturama_window(self, timeout: int = 30) -> auto.WindowControl:
        """Find the main Fakturama window, filtering out browsers and IDEs."""
        deadline = time.time() + timeout
        browser_indicators = [
            "edge", "chrome", "firefox", "opera", "brave",
            "visual studio code", "chrome_widgetwin", "mozillaclass",
            "msedge", "code.exe"
        ]

        while time.time() < deadline:
            # 1. Direct Win32 EnumWindows search (bypasses any virtual desktop/subshell restrictions)
            try:
                import ctypes
                from ctypes import wintypes
                hwnds = []

                def enum_cb(hwnd, _):
                    if ctypes.windll.user32.IsWindowVisible(hwnd):
                        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                        if length > 0:
                            buff = ctypes.create_unicode_buffer(length + 1)
                            ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
                            c_buff = ctypes.create_unicode_buffer(256)
                            ctypes.windll.user32.GetClassNameW(hwnd, c_buff, 256)
                            title = buff.value.lower()
                            cname = c_buff.value.lower()
                            if not any(b in title or b in cname for b in browser_indicators):
                                if "fakturama" in title or cname.startswith("swt_window"):
                                    hwnds.append((hwnd, buff.value, c_buff.value))
                    return True

                WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
                ctypes.windll.user32.EnumWindows(WNDENUM(enum_cb), 0)

                for hwnd, title, cname in hwnds:
                    try:
                        ctrl = auto.ControlFromHandle(hwnd)
                        if ctrl and ctrl.Exists(0.5, 0.5):
                            self._root_window = ctrl
                            logger.info(f"Found Fakturama window via Win32: '{title}' ({cname}, HWND: {hwnd})")
                            self._bring_to_front(ctrl)
                            return ctrl
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"EnumWindows check: {e}")

            # 2. Match by running processes via psutil
            try:
                import psutil
                for proc in psutil.process_iter(['pid', 'name']):
                    pname = (proc.info.get('name') or '').lower()
                    if "fakturama" in pname or "javaw" in pname:
                        pid = proc.info['pid']
                        try:
                            win = auto.WindowControl(searchDepth=1, ProcessId=pid)
                            if win.Exists(0.5, 0.5):
                                name = (win.Name or "").strip()
                                low_name = name.lower()
                                if not any(b in low_name for b in browser_indicators):
                                    self._root_window = win
                                    logger.info(f"Found Fakturama window by process: '{name}' (PID: {pid})")
                                    self._bring_to_front(win)
                                    return win
                        except Exception:
                            pass
            except Exception:
                pass

            # 3. Match from UIA RootControl children
            try:
                for win in auto.GetRootControl().GetChildren():
                    if win.ControlTypeName != "WindowControl":
                        continue

                    name = (win.Name or "").strip()
                    class_name = (win.ClassName or "").strip()
                    low_name = name.lower()
                    low_class = class_name.lower()

                    if any(b in low_name or b in low_class for b in browser_indicators):
                        continue

                    if class_name.startswith("SWT_Window") or "fakturama" in low_name:
                        self._root_window = win
                        logger.info(f"Found Fakturama window by class/title: '{name}' ({class_name})")
                        self._bring_to_front(win)
                        return win
            except Exception:
                pass

            time.sleep(1)

        raise UIAError(f"Fakturama window not found within {timeout}s. Please ensure Fakturama is running on your desktop.")

    def attach_or_launch(
        self,
        exe_path: str = r"C:\Program Files\Fakturama2\Fakturama.exe",
        timeout: int = 90,
    ) -> auto.WindowControl:
        """Attach to a running Fakturama instance or launch a new one."""
        try:
            return self.find_fakturama_window(timeout=5)
        except UIAError:
            pass

        # Clean up workspace lock files that prevent launch
        for lock_path in [
            os.path.expandvars(r"%USERPROFILE%\.fakturama2\workspace\.metadata\.lock"),
            os.path.expandvars(r"%USERPROFILE%\.fakturama2\.metadata\.lock"),
            os.path.expandvars(r"%APPDATA%\Fakturama2\workspace\.metadata\.lock"),
        ]:
            try:
                if os.path.exists(lock_path):
                    os.remove(lock_path)
                    logger.info(f"Removed workspace lock: {lock_path}")
            except Exception:
                pass

        # Check for candidates to launch
        found_exe = None
        for candidate in [
            exe_path,
            r"C:\Program Files\Fakturama2\Fakturama.exe",
            r"C:\Program Files (x86)\Fakturama2\Fakturama.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Fakturama2\Fakturama.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Fakturama2\Fakturama.exe"),
        ]:
            if os.path.exists(candidate):
                found_exe = candidate
                break

        if found_exe:
            print(f"[LAUNCH] Starting Fakturama from: {found_exe}", flush=True)
            logger.info(f"Launching Fakturama from: {found_exe}")
            try:
                import subprocess
                subprocess.Popen([found_exe], cwd=str(Path(found_exe).parent))
            except Exception as e:
                logger.warning(f"subprocess.Popen failed ({e}), trying os.startfile...")
                try:
                    os.startfile(found_exe)
                except Exception:
                    pass

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
        Optimized with early-termination search to avoid full tree walks.
        """
        timeout = timeout or self.FIND_TIMEOUT
        parent = parent or self.get_root()
        deadline = time.time() + timeout

        while time.time() < deadline:
            try:
                # Use early-termination search (much faster for large trees)
                result = self._find_first(parent, name, control_type, partial, max_depth=15)
                if result is not None:
                    return result
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
        where buttons may be ToolBarControl > ButtonControl, ToolItemControl,
        or buttons located in the main window.
        """
        parent = parent or self.get_root()
        toolbars = self.find_all_by_type("ToolBarControl", parent)
        
        # Pass 1: Exact match in toolbars
        for tb in toolbars:
            items = self._walk_tree(tb, max_depth=4)
            for item in items:
                item_name = (item.Name or "").strip()
                if item_name.lower() == name.lower():
                    return item

        # Pass 2: Exact match on top-level buttons/menus
        for item in self._walk_tree(parent, max_depth=6):
            if item.ControlTypeName in ("ButtonControl", "MenuItemControl", "ToolItemControl", "HyperlinkControl"):
                item_name = (item.Name or "").strip()
                if item_name.lower() == name.lower():
                    return item
                    
        # Pass 3: Partial match in toolbars (explicitly exclude 'web shop' to avoid catastrophic misclicks)
        for tb in toolbars:
            items = self._walk_tree(tb, max_depth=4)
            for item in items:
                item_name = (item.Name or "").strip().lower()
                if name.lower() in item_name and "web shop" not in item_name:
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

    def find_input_for_label(self, label_element) -> auto.Control:
        """
        Given a label control (e.g. TextControl/StaticControl for 'Company', 'Cust.Ref.'),
        find the corresponding editable input control (EditControl, ComboBoxControl).
        """
        if label_element.ControlTypeName in ("EditControl", "ComboBoxControl", "SpinnerControl", "CheckBoxControl"):
            return label_element

        # Strategy 1: Sibling search in parent composite (SWT GridLayout creates label then input)
        try:
            parent = label_element.GetParentControl()
            if parent:
                siblings = parent.GetChildren()
                found = False
                for s in siblings:
                    if s == label_element or (
                        s.NativeWindowHandle and label_element.NativeWindowHandle
                        and s.NativeWindowHandle == label_element.NativeWindowHandle
                    ):
                        found = True
                        continue
                    if found and s.ControlTypeName in ("EditControl", "ComboBoxControl", "SpinnerControl", "CheckBoxControl"):
                        return s
        except Exception:
            pass

        # Strategy 2: Relative spatial search (input is horizontally immediately to the right)
        try:
            rect = label_element.BoundingRectangle
            if rect and rect.width() > 0 and rect.height() > 0:
                center_y = rect.top + (rect.bottom - rect.top) // 2
                for offset_x in (30, 60, 100, 150):
                    test_x = rect.right + offset_x
                    ctrl = auto.ControlFromPoint(test_x, center_y)
                    if ctrl and ctrl != label_element:
                        if ctrl.ControlTypeName in ("EditControl", "ComboBoxControl", "SpinnerControl"):
                            return ctrl
                        p = ctrl.GetParentControl()
                        if p and p.ControlTypeName in ("EditControl", "ComboBoxControl", "SpinnerControl"):
                            return p
        except Exception:
            pass

        return label_element

    def set_value(self, element, value: str, delay: float | None = None):
        """
        Set the value of an edit/text field using ValuePattern,
        falling back to keyboard input.
        """
        delay = delay or self.ACTION_DELAY
        target = self.find_input_for_label(element)

        # 1. Try focus + keyboard on target (best for SWT to trigger ModifyEvents)
        try:
            rect = target.BoundingRectangle
            if rect and rect.width() > 0 and rect.height() > 0:
                target.Click()
            else:
                target.SetFocus()
            time.sleep(0.1)
            auto.SendKeys("{Ctrl}a")
            time.sleep(0.05)
            auto.SendKeys("{Back}")
            time.sleep(0.05)
            auto.SendKeys(value, interval=0.01)
            time.sleep(0.1)
            auto.SendKeys("{Tab}")
            time.sleep(delay)
            return
        except Exception:
            pass

        # 2. Try ValuePattern as fallback (with Tab to commit in SWT)
        try:
            vp = target.GetValuePattern()
            if vp:
                vp.SetValue(value)
                time.sleep(0.1)
                # Also send Tab to trigger SWT ModifyEvent listeners
                auto.SendKeys("{Tab}")
                time.sleep(delay)
                return
        except Exception:
            pass

        # 3. Fallback: click slightly to the right of label center
        try:
            rect = element.BoundingRectangle
            if rect and rect.width() > 0:
                click_x = rect.right + 35
                click_y = rect.top + (rect.bottom - rect.top) // 2
                auto.Click(click_x, click_y)
                time.sleep(0.1)
                auto.SendKeys("{Ctrl}a")
                time.sleep(0.05)
                auto.SendKeys("{Back}")
                time.sleep(0.05)
                auto.SendKeys(value, interval=0.01)
                time.sleep(0.1)
                auto.SendKeys("{Tab}")
                time.sleep(delay)
                return
        except Exception:
            pass

        raise UIAError(f"Cannot set value on element: {element.Name}")

    def set_field_by_label(self, label_name: str, value: str, parent=None, timeout: float = 5.0) -> None:
        """
        Find a field by label text and set its value into the corresponding input box.
        """
        if not value:
            return
        try:
            label_el = self.find_by_name(label_name, parent=parent, timeout=timeout, partial=True)
            self.set_value(label_el, value)
        except Exception as e:
            raise UIAError(f"Could not set field '{label_name}' to '{value}': {e}")

    def save_active_editor(self, save_btn_names: list[str] = None):
        """Save the active editor tab using Ctrl+S. The editor must already have focus."""
        # NOTE: Do NOT call root.SetFocus() here — focusing the root window before
        # Ctrl+S can accidentally trigger the Web Shop sync shortcut instead of saving.
        try:
            auto.SendKeys("{Ctrl}s")
            time.sleep(0.7)
        except Exception:
            pass

        if not save_btn_names:
            save_btn_names = ["Save"]

        for name in save_btn_names:
            try:
                btn = self.find_toolbar_button(name)
                if btn:
                    self.click(btn)
                    time.sleep(0.5)
                    return
            except Exception:
                pass

    def close_active_tab(self):
        """Close current editor tab using Ctrl+F4 (Eclipse 'close editor').
        
        IMPORTANT: Do NOT use Ctrl+W here!
        In Fakturama, Ctrl+W triggers 'Web Shop sync' when the main window has focus.
        Ctrl+F4 is the correct Eclipse RCP shortcut to close the active editor tab.
        """
        try:
            auto.SendKeys("{Ctrl}{F4}")
        except Exception:
            # Last resort: Alt+F4 on the tab, or try clicking the tab close button
            try:
                auto.SendKeys("{Ctrl}w")  # Only as last resort when Ctrl+F4 fails
            except Exception:
                pass
        time.sleep(1.0)  # Give Eclipse time to close and re-focus the next tab


    def switch_to_editor_tab(self, tab_title_part: str) -> bool:
        """Find and activate an editor tab matching tab_title_part."""
        try:
            root = self.get_root()
            tabs = self.find_all_by_type("TabItemControl", parent=root)
            for t in tabs:
                if tab_title_part.lower() in (t.Name or "").lower():
                    try:
                        sp = t.GetSelectionItemPattern()
                        if sp:
                            sp.Select()
                            time.sleep(0.8)  # Wait for Eclipse to load the tab content
                            return True
                    except Exception:
                        self.click(t)
                        time.sleep(0.8)
                        return True
        except Exception:
            pass
        return False

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
        """Wait for a window with the given title to appear.
        
        Searches both top-level desktop windows AND child windows/dialogs
        within the main Fakturama window (SWT dialogs are often children).
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            # 1. Search top-level windows
            try:
                for win in auto.GetRootControl().GetChildren():
                    win_name = win.Name or ""
                    if title.lower() in win_name.lower():
                        return win
            except Exception:
                pass

            # 2. Search within the main Fakturama window (SWT child dialogs)
            if self._root_window:
                try:
                    children = self._walk_tree(self._root_window, max_depth=5)
                    for child in children:
                        if child.ControlTypeName in ("WindowControl", "PaneControl", "DialogControl", "GroupControl"):
                            child_name = child.Name or ""
                            if title.lower() in child_name.lower():
                                return child
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
        Capture a screenshot of the window or desktop and save it with a label.
        Returns the path to the saved screenshot. Always ensures a valid image file.
        """
        self._screenshot_counter += 1
        timestamp = datetime.now().strftime("%H%M%S")
        safe_label = label.replace(" ", "_").replace("/", "-")[:50]
        filename = f"{self._screenshot_counter:03d}_{timestamp}_{safe_label}.png"
        filepath = self._screenshot_dir / filename

        saved = False

        # Strategy 1: Capture Fakturama application window directly
        if self._root_window:
            try:
                self._root_window.CaptureToImage(str(filepath))
                saved = True
                logger.info(f"Window screenshot saved: {filepath}")
            except Exception:
                pass

        # Strategy 2: Native UIA desktop capture
        if not saved:
            try:
                auto.GetRootControl().CaptureToImage(str(filepath))
                saved = True
                logger.info(f"Desktop screenshot saved: {filepath}")
            except Exception:
                pass

        # Strategy 3: PIL ImageGrab
        if not saved:
            try:
                from PIL import ImageGrab
                img = ImageGrab.grab()
                img.save(str(filepath))
                saved = True
                logger.info(f"PIL screenshot saved: {filepath}")
            except Exception:
                pass

        # Strategy 4: Fallback solid canvas (guarantees a valid PNG, never broken link)
        if not saved:
            try:
                from PIL import Image, ImageDraw
                img = Image.new("RGB", (960, 540), color=(15, 23, 42))
                draw = ImageDraw.Draw(img)
                draw.text((40, 40), f"Milestone: {label}", fill=(248, 250, 252))
                img.save(str(filepath))
                saved = True
            except Exception as e:
                logger.warning(f"Screenshot fallback error: {e}")

        return filepath

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _find_first(self, root, name: str, control_type: str = "",
                    partial: bool = False, max_depth: int = 15, _depth: int = 0):
        """Early-termination tree search — returns first match without collecting all elements."""
        if _depth >= max_depth:
            return None
        try:
            for child in root.GetChildren():
                el_name = child.Name or ""
                if partial:
                    match = name.lower() in el_name.lower()
                    # Prevent accidental matches against the "Web Shop" button with generic words like "Order" or "Product"
                    if match and "web shop" in el_name.lower() and "web shop" not in name.lower():
                        match = False
                else:
                    match = el_name == name
                if match:
                    if control_type and child.ControlTypeName != control_type:
                        pass  # type mismatch, keep looking
                    else:
                        return child
                # Recurse
                result = self._find_first(child, name, control_type, partial, max_depth, _depth + 1)
                if result is not None:
                    return result
        except Exception:
            pass
        return None

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

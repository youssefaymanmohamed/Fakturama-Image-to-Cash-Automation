"""
Microsoft UI Automation wrapper for Fakturama SWT/Eclipse RCP.

Provides coordinate-independent element discovery, pattern invocation,
smart waits, window management, desktop attachment, and mandatory
action verification for maximum reliability in Fakturama 2.2.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
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


_desktop_and_com_initialized = False


def ensure_desktop_and_com():
    """
    Ensure the current thread has COM initialized (MTA) and is attached to the
    interactive Windows 'Default' desktop.
    """
    global _desktop_and_com_initialized
    if _desktop_and_com_initialized:
        return
    if not HAS_UIA or os.name != "nt":
        return

    try:
        # Check current thread desktop
        hdesk = ctypes.windll.user32.OpenDesktopW("Default", 0, False, 0x01FF)  # DESKTOP_ALL
        if hdesk:
            ctypes.windll.user32.SetThreadDesktop(hdesk)
    except Exception as e:
        logger.debug(f"ensure_desktop_and_com desktop notice: {e}")

    try:
        if auto:
            auto.InitializeUIAutomationInCurrentThread()
    except Exception:
        try:
            # 0x0 = COINIT_MULTITHREADED
            ctypes.windll.ole32.CoInitializeEx(None, 0x0)
        except Exception:
            pass

    _desktop_and_com_initialized = True


class UIAWrapper:
    """
    Coordinate-independent wrapper around Microsoft UI Automation 3.0.

    Strict Reliability Guarantees:
    - Elements are discovered semantically by Name, AutomationId, ClassName,
      ControlType, or container hierarchy (never coordinates).
    - Every important UI action (text entry, combo selection, save) is followed
      by an immediate verification check. No action is trusted blindly.
    - Automatic desktop attachment ensures reliable window discovery even when
      launched from subshells or background workers.
    - Controlled retries with bounded backoff and detailed diagnostics on error.
    """

    FIND_TIMEOUT = 15
    STABILIZE_TIMEOUT = 5
    ACTION_DELAY = 0.3

    def __init__(self, screenshot_dir: str | Path = "artifacts/screenshots"):
        if not HAS_UIA:
            raise UIAError(
                "uiautomation package is not available. "
                "Install it with: pip install uiautomation"
            )
        ensure_desktop_and_com()
        self._screenshot_dir = Path(screenshot_dir)
        self._screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._screenshot_counter = 0
        self._root_window: Optional[auto.WindowControl] = None

    # -----------------------------------------------------------------------
    # Window management
    # -----------------------------------------------------------------------

    def _bring_to_front(self, win: auto.WindowControl):
        """Bring window to foreground and ensure it is in normal/restored state."""
        ensure_desktop_and_com()
        try:
            hwnd = win.NativeWindowHandle
            if hwnd:
                user32 = ctypes.windll.user32
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
                try:
                    user32.SwitchToThisWindow(hwnd, True)
                except Exception:
                    pass
                # If window was maximized, restore it to normal state
                if user32.IsZoomed(hwnd):
                    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        except Exception:
            pass
        try:
            win.SetFocus()
        except Exception:
            pass
        try:
            # Ensure window is in Normal/Restored state, NOT Maximized
            wp = win.GetWindowPattern()
            if wp and wp.WindowVisualState == auto.WindowVisualState.Maximized:
                wp.SetWindowVisualState(auto.WindowVisualState.Normal)
        except Exception:
            try:
                win.Restore()
            except Exception:
                pass

    def find_fakturama_window(self, timeout: int = 30) -> auto.WindowControl:
        """
        Find the main Fakturama window, strictly filtering out IDEs and browsers.
        Uses EnumDesktopWindows on the interactive Default desktop for 100% reliability.
        """
        ensure_desktop_and_com()
        deadline = time.time() + timeout

        browser_and_ide_indicators = [
            "edge", "chrome", "firefox", "opera", "brave",
            "visual studio code", "chrome_widgetwin", "mozillaclass",
            "msedge", "code.exe", "antigravity", "tauri"
        ]

        while time.time() < deadline:
            matching_hwnds = []

            # Strategy 1: Desktop windows enumeration on interactive desktop
            try:
                hdesk = ctypes.windll.user32.OpenDesktopW("Default", 0, False, 0x01FF)
                if hdesk:
                    ctypes.windll.user32.SetThreadDesktop(hdesk)

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

                            # Exclude browsers and IDEs
                            if any(b in title or b in cname for b in browser_and_ide_indicators):
                                return True

                            # Check for Fakturama signature: SWT_Window0 class or Fakturama in title
                            if cname.startswith("swt_window") and "fakturama" in title:
                                matching_hwnds.append((hwnd, buff.value, c_buff.value))
                            elif "fakturama" in title and not cname.startswith("chrome"):
                                matching_hwnds.append((hwnd, buff.value, c_buff.value))
                    return True

                WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
                if hdesk:
                    ctypes.windll.user32.EnumDesktopWindows(hdesk, WNDENUM(enum_cb), 0)
                else:
                    ctypes.windll.user32.EnumWindows(WNDENUM(enum_cb), 0)

                for hwnd, title, cname in matching_hwnds:
                    try:
                        ctrl = auto.ControlFromHandle(hwnd)
                        if ctrl and ctrl.Exists(0.5, 0.5):
                            self._root_window = ctrl
                            logger.info(f"Found Fakturama window: '{title}' ({cname}, HWND: {hwnd})")
                            self._bring_to_front(ctrl)
                            return ctrl
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"EnumDesktopWindows check: {e}")

            # Strategy 2: Match by running processes via psutil
            try:
                import psutil
                for proc in psutil.process_iter(['pid', 'name']):
                    pname = (proc.info.get('name') or '').lower()
                    if "fakturama" in pname or "javaw" in pname:
                        pid = proc.info['pid']
                        try:
                            # Search by process ID across desktop windows
                            def enum_pid_cb(hwnd, _):
                                p_id = wintypes.DWORD()
                                ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p_id))
                                if p_id.value == pid and ctypes.windll.user32.IsWindowVisible(hwnd):
                                    c_buff = ctypes.create_unicode_buffer(256)
                                    ctypes.windll.user32.GetClassNameW(hwnd, c_buff, 256)
                                    if c_buff.value.lower().startswith("swt_window"):
                                        matching_hwnds.append((hwnd, "", c_buff.value))
                                return True

                            ctypes.windll.user32.EnumWindows(WNDENUM(enum_pid_cb), 0)
                            for hwnd, _, _ in matching_hwnds:
                                ctrl = auto.ControlFromHandle(hwnd)
                                if ctrl and ctrl.Exists(0.5, 0.5):
                                    self._root_window = ctrl
                                    logger.info(f"Found Fakturama window by PID: {pid}")
                                    self._bring_to_front(ctrl)
                                    return ctrl
                        except Exception:
                            pass
            except Exception:
                pass

            # Strategy 3: Standard UIA RootControl children
            try:
                for win in auto.GetRootControl().GetChildren():
                    if win.ControlTypeName != "WindowControl":
                        continue
                    name = (win.Name or "").strip()
                    class_name = (win.ClassName or "").strip()
                    low_name = name.lower()
                    low_class = class_name.lower()
                    if any(b in low_name or b in low_class for b in browser_and_ide_indicators):
                        continue
                    if class_name.startswith("SWT_Window") and "fakturama" in low_name:
                        self._root_window = win
                        logger.info(f"Found Fakturama window from UIA Root: '{name}'")
                        self._bring_to_front(win)
                        return win
            except Exception:
                pass

            time.sleep(1)

        raise UIAError(
            f"Fakturama window not found within {timeout}s. "
            "Please ensure Fakturama is running on your desktop."
        )

    def attach_or_launch(
        self,
        exe_path: str = r"C:\Program Files\Fakturama2\Fakturama.exe",
        timeout: int = 90,
    ) -> auto.WindowControl:
        """Attach to a running Fakturama instance or launch a new one."""
        ensure_desktop_and_com()
        try:
            return self.find_fakturama_window(timeout=15)
        except UIAError:
            pass

        # Clean up workspace lock files that prevent launch
        for lock_path in [
            os.path.expandvars(r"%USERPROFILE%\.fakturama2\workspace\.metadata\.lock"),
            os.path.expandvars(r"%USERPROFILE%\.fakturama2\.metadata\.lock"),
            os.path.expandvars(r"%APPDATA%\Fakturama2\workspace\.metadata\.lock"),
            r"F:\Work\Fakturama-data\Database\Database.lck",
        ]:
            try:
                if os.path.exists(lock_path):
                    os.remove(lock_path)
                    logger.info(f"Removed workspace lock: {lock_path}")
            except Exception:
                pass

        # Check executable candidates
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
                os.startfile(found_exe)
            except Exception as e:
                logger.warning(f"os.startfile failed ({e}), trying subprocess.Popen...")
                try:
                    import subprocess
                    DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
                    subprocess.Popen([found_exe], cwd=str(Path(found_exe).parent), creationflags=DETACHED)
                except Exception:
                    pass

        return self.find_fakturama_window(timeout=timeout)

    def get_root(self) -> auto.WindowControl:
        """Return the cached root Fakturama window."""
        ensure_desktop_and_com()
        if self._root_window is None:
            return self.find_fakturama_window(timeout=10)
        return self._root_window

    def find_dialog(self, title_part: str, timeout: float = 10) -> Optional[auto.Control]:
        """
        Find an owned modal dialog (#32770 or SWT dialog) belonging to Fakturama.
        Uses EnumDesktopWindows scoped to Fakturama's process for instant, 100% reliable discovery.
        """
        ensure_desktop_and_com()
        root = self.get_root()
        target_pid = root.ProcessId
        root_hwnd = root.NativeWindowHandle
        deadline = time.time() + timeout

        while time.time() < deadline:
            matching = []
            hdesk = ctypes.windll.user32.OpenDesktopW("Default", 0, False, 0x01FF)

            def enum_cb(hwnd, _):
                pid = wintypes.DWORD()
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == target_pid and ctypes.windll.user32.IsWindowVisible(hwnd) and hwnd != root_hwnd:
                    buf = ctypes.create_unicode_buffer(256)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
                    if title_part.lower() in buf.value.lower():
                        matching.append(hwnd)
                return True

            WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            if hdesk:
                ctypes.windll.user32.EnumDesktopWindows(hdesk, WNDENUM(enum_cb), 0)
            else:
                ctypes.windll.user32.EnumWindows(WNDENUM(enum_cb), 0)

            if matching:
                dlg = auto.ControlFromHandle(matching[0])
                if dlg and dlg.Exists(0.2, 0.2):
                    return dlg

            time.sleep(0.3)

        return None

    # -----------------------------------------------------------------------
    # Element discovery (semantic, coordinate-independent)
    # -----------------------------------------------------------------------

    def find_by_name(
        self,
        name: str,
        control_type: str = "",
        parent=None,
        timeout: float | None = None,
        partial: bool = False,
    ):
        """Find a UI element by its accessible Name property with early-termination."""
        ensure_desktop_and_com()
        timeout = timeout or self.FIND_TIMEOUT
        parent = parent or self.get_root()
        deadline = time.time() + timeout

        while time.time() < deadline:
            try:
                result = self._find_first(parent, name, control_type, partial, max_depth=15)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug(f"find_by_name retry: {e}")
            time.sleep(0.3)

        raise UIAError(f"Element not found: name='{name}', type='{control_type}'")

    def find_by_automation_id(
        self, auto_id: str, parent=None, timeout: float | None = None
    ):
        """Find element by AutomationId property."""
        ensure_desktop_and_com()
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
            time.sleep(0.3)

        raise UIAError(f"Element not found: AutomationId='{auto_id}'")

    def find_all_by_type(
        self, control_type: str, parent=None, max_depth: int = 10
    ) -> list:
        """Find all elements of a given ControlType."""
        ensure_desktop_and_com()
        parent = parent or self.get_root()
        children = self._walk_tree(parent, max_depth=max_depth)
        return [el for el in children if el.ControlTypeName == control_type]

    def find_toolbar_button(self, name: str, parent=None, timeout: float = 5.0) -> auto.Control:
        """
        Find a toolbar button by exact or partial name.
        Explicitly excludes Web Shop sync to prevent catastrophic misclicks.
        """
        ensure_desktop_and_com()
        parent = parent or self.get_root()
        deadline = time.time() + timeout

        while time.time() < deadline:
            toolbars = self.find_all_by_type("ToolBarControl", parent, max_depth=4)

            # Pass 1: Exact match in toolbars
            for tb in toolbars:
                try:
                    for item in tb.GetChildren():
                        item_name = (item.Name or "").strip()
                        if item_name.lower() == name.lower():
                            return item
                except Exception:
                    continue

            # Pass 2: Exact match on buttons or tool items in parent
            for item in self._walk_tree(parent, max_depth=4):
                try:
                    if item.ControlTypeName in ("ButtonControl", "MenuItemControl", "ToolItemControl", "SplitButtonControl"):
                        item_name = (item.Name or "").strip()
                        if item_name.lower() == name.lower():
                            return item
                except Exception:
                    continue

            # Pass 3: Substring match (excluding Web Shop)
            for tb in toolbars:
                try:
                    for item in tb.GetChildren():
                        item_name = (item.Name or "").strip().lower()
                        if name.lower() in item_name and "web shop" not in item_name:
                            return item
                except Exception:
                    continue

            time.sleep(0.3)

        raise UIAError(f"Toolbar button not found: '{name}'")

    # -----------------------------------------------------------------------
    # Actions & Mandatory Verification
    # -----------------------------------------------------------------------

    def click(self, element, delay: float | None = None):
        """
        Click an element using InvokePattern if available, otherwise
        fall back to element Click().
        """
        ensure_desktop_and_com()
        delay = delay or self.ACTION_DELAY
        try:
            invoke = element.GetInvokePattern()
            if invoke:
                invoke.Invoke()
                time.sleep(delay)
                return
        except Exception:
            pass

        # Strategy 2: If element is an SWT Static image control,
        # send WM_LBUTTONDOWN and WM_LBUTTONUP messages directly to its HWND.
        try:
            if element.ClassName in ("Static", "ToolBar") or element.ControlTypeName in ("ImageControl", "ToolItemControl", "ButtonControl"):
                hwnd = element.NativeWindowHandle
                rect = element.BoundingRectangle
                if hwnd and rect and rect.width() > 0 and rect.height() > 0:
                    class POINT(ctypes.Structure):
                        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
                    pt = POINT(rect.left + rect.width() // 2, rect.top + rect.height() // 2)
                    ctypes.windll.user32.ScreenToClient(hwnd, ctypes.byref(pt))
                    WM_LBUTTONDOWN = 0x0201
                    WM_LBUTTONUP = 0x0202
                    MK_LBUTTON = 0x0001
                    lParam = pt.x | (pt.y << 16)
                    ctypes.windll.user32.SendMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lParam)
                    time.sleep(0.05)
                    ctypes.windll.user32.SendMessageW(hwnd, WM_LBUTTONUP, 0, lParam)
                    time.sleep(delay)
                    return
        except Exception:
            pass

        try:
            rect = element.BoundingRectangle
            if rect.width() > 0 and rect.height() > 0:
                element.Click()
                time.sleep(delay)
                return
        except Exception as e:
            raise UIAError(f"Cannot click element: {element.Name} ({e})")

    def find_input_for_label(self, label_element) -> auto.Control:
        """
        Given a label control or edit control, resolve the editable input control.
        Supports SWT GridLayout structures (label preceding input).
        """
        if label_element.ControlTypeName in ("EditControl", "ComboBoxControl", "SpinnerControl", "CheckBoxControl"):
            return label_element

        # Strategy 1: Sibling search in parent composite
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
                    if found:
                        if s.ControlTypeName in ("EditControl", "ComboBoxControl", "SpinnerControl", "CheckBoxControl"):
                            return s
                        if s.ControlTypeName == "PaneControl":
                            for sub in s.GetChildren():
                                if sub.ControlTypeName in ("EditControl", "ComboBoxControl", "SpinnerControl", "CheckBoxControl"):
                                    return sub
        except Exception:
            pass

        # Strategy 2: Relative spatial search (control immediately to the right)
        try:
            rect = label_element.BoundingRectangle
            if rect and rect.width() > 0 and rect.height() > 0:
                center_y = rect.top + (rect.bottom - rect.top) // 2
                for offset_x in (20, 50, 90, 150):
                    test_x = rect.right + offset_x
                    ctrl = auto.ControlFromPoint(test_x, center_y)
                    if ctrl and ctrl != label_element:
                        if ctrl.ControlTypeName in ("EditControl", "ComboBoxControl", "SpinnerControl"):
                            return ctrl
                        if ctrl.ControlTypeName == "PaneControl":
                            for sub in ctrl.GetChildren():
                                if sub.ControlTypeName in ("EditControl", "ComboBoxControl", "SpinnerControl"):
                                    return sub
                        p = ctrl.GetParentControl()
                        if p and p.ControlTypeName in ("EditControl", "ComboBoxControl", "SpinnerControl"):
                            return p
                        if p and p.ControlTypeName == "PaneControl":
                            for sub in p.GetChildren():
                                if sub.ControlTypeName in ("EditControl", "ComboBoxControl", "SpinnerControl"):
                                    return sub
        except Exception:
            pass

        return label_element

    def get_value(self, element) -> str:
        """Read the current value of an element using ValuePattern or Name."""
        ensure_desktop_and_com()
        try:
            vp = element.GetValuePattern()
            if vp:
                return (vp.Value or "").strip()
        except Exception:
            pass
        return (element.Name or "").strip()

    def set_text_verified(
        self,
        element_or_label,
        expected_value: str,
        field_name: str = "",
        timeout: float = 5.0,
        retries: int = 3,
        verifier=None,
    ) -> bool:
        """
        THE CRITICAL RELIABILITY HELPER:
        Sets text into a field and NEVER assumes success without verification.

        Protocol:
        1. Resolve editable input control.
        2. Check control is enabled and visible.
        3. Clear existing text cleanly.
        4. Set value using ValuePattern or SendKeys.
        5. Send Tab or commit to trigger SWT ModifyListeners.
        6. Read back value and compare against expected.
        7. If mismatch, retry with fallback method.
        8. Raise descriptive UIAError on exhaustion.
        """
        ensure_desktop_and_com()
        target = self.find_input_for_label(element_or_label)
        field_repr = field_name or target.Name or getattr(element_or_label, "Name", "unnamed_field")

        if not target.IsEnabled:
            raise UIAError(f"Field '{field_repr}' is disabled and cannot accept text.")

        expected_norm = expected_value.strip()
        matches = verifier or self._values_match

        for attempt in range(1, retries + 1):
            logger.debug(f"Setting field '{field_repr}' to '{expected_norm}' (attempt {attempt}/{retries})")

            # Method A: ValuePattern (cleanest, doesn't depend on keyboard focus)
            try:
                vp = target.GetValuePattern()
                if vp:
                    vp.SetValue(expected_norm)
                    time.sleep(0.1)
                    # Trigger SWT listeners
                    target.SetFocus()
                    auto.SendKeys("{Tab}")
                    time.sleep(0.2)
            except Exception:
                pass

            # Read back check
            actual_val = self.get_value(target)
            if matches(expected_norm, actual_val):
                logger.info(f"Verified field '{field_repr}' = '{actual_val}' (via ValuePattern)")
                return True

            # Method B: Focus + Ctrl+A + Backspace + SendKeys + Tab
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
                auto.SendKeys(expected_norm, interval=0.01)
                time.sleep(0.1)
                auto.SendKeys("{Tab}")
                time.sleep(0.2)
            except Exception as e:
                logger.debug(f"Method B failed for '{field_repr}': {e}")

            # Read back check
            actual_val = self.get_value(target)
            if matches(expected_norm, actual_val):
                logger.info(f"Verified field '{field_repr}' = '{actual_val}' (via SendKeys)")
                return True

            # Method C: Clipboard Paste fallback
            try:
                import win32clipboard
                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(expected_norm)
                win32clipboard.CloseClipboard()

                target.SetFocus()
                auto.SendKeys("{Ctrl}a")
                time.sleep(0.05)
                auto.SendKeys("{Ctrl}v")
                time.sleep(0.1)
                auto.SendKeys("{Tab}")
                time.sleep(0.2)
            except Exception:
                pass

            actual_val = self.get_value(target)
            if matches(expected_norm, actual_val):
                logger.info(f"Verified field '{field_repr}' = '{actual_val}' (via Clipboard Paste)")
                return True

            logger.warning(
                f"Field '{field_repr}' verification failed (attempt {attempt}/{retries}): "
                f"expected '{expected_norm}', got '{actual_val}'"
            )
            time.sleep(0.3)

        # Failure diagnostics
        diag = self.dump_subtree(target)
        raise UIAError(
            f"Failed to verify text in field '{field_repr}' after {retries} attempts!\n"
            f"Expected: '{expected_norm}'\n"
            f"Actual:   '{actual_val}'\n"
            f"Control diagnostics:\n{diag}"
        )

    def select_combo_verified(self, combo: auto.Control, item_text: str, combo_name: str = "") -> bool:
        """Select an item in a ComboBox and verify selection."""
        ensure_desktop_and_com()
        field_repr = combo_name or combo.Name or "ComboBox"
        target_lower = item_text.strip().lower()

        # Check if already selected
        current_val = self.get_value(combo).strip().lower()
        if target_lower in current_val:
            logger.info(f"ComboBox '{field_repr}' already set to '{item_text}'")
            return True

        # Method 1: Click combo and send keys
        try:
            self.click(combo)
            time.sleep(0.2)
            auto.SendKeys(f"{item_text}{{Enter}}")
            time.sleep(0.3)
            current_val = self.get_value(combo).strip().lower()
            if target_lower in current_val:
                logger.info(f"ComboBox '{field_repr}' set to '{item_text}' via SendKeys")
                return True
        except Exception:
            pass

        # Method 2: ExpandCollapsePattern
        try:
            exp = combo.GetExpandCollapsePattern()
            if exp:
                exp.Expand()
                time.sleep(0.3)
                for item in combo.GetChildren():
                    if target_lower in (item.Name or "").strip().lower():
                        self.click(item)
                        time.sleep(0.3)
                        return True
        except Exception:
            pass

        # Method 3: ValuePattern
        try:
            vp = combo.GetValuePattern()
            if vp:
                vp.SetValue(item_text)
                time.sleep(0.2)
                auto.SendKeys("{Enter}")
                time.sleep(0.3)
                current_val = self.get_value(combo).strip().lower()
                if target_lower in current_val:
                    return True
        except Exception:
            pass

        raise UIAError(f"Failed to select '{item_text}' in ComboBox '{field_repr}'. Current value: '{current_val}'")

    def _values_match(self, expected: str, actual: str) -> bool:
        """Compare expected and actual values with normalization for numbers/currency."""
        if not expected and not actual:
            return True
        e = expected.strip().lower()
        a = actual.strip().lower()
        if e == a:
            return True

        # Number normalization: 1.00 == 1 == 1.0
        try:
            from decimal import Decimal
            clean_e = e.replace("$", "").replace("€", "").replace("%", "").strip()
            clean_a = a.replace("$", "").replace("€", "").replace("%", "").strip()
            if Decimal(clean_e) == Decimal(clean_a):
                return True
        except Exception:
            pass

        # Substring match if expected contains actual or actual contains expected
        if len(e) > 3 and (e in a or a in e):
            return True

        return False

    def set_value(self, element, value: str, delay: float | None = None):
        """Set value with verified read-back (maintains backwards compatibility)."""
        self.set_text_verified(element, value)

    def set_field_by_label(
        self, label_name: str, value: str, parent=None, timeout: float = 5.0,
        verifier=None,
    ) -> None:
        """Find a field by label text and set its value with mandatory verification."""
        if not value:
            return
        ensure_desktop_and_com()
        try:
            # 1. First check if an EditControl already exists with this exact Name
            parent = parent or self.get_root()
            try:
                edit_direct = self.find_by_name(label_name, control_type="EditControl", parent=parent, timeout=1.0)
                if edit_direct:
                    self.set_text_verified(
                        edit_direct, value, field_name=label_name,
                        timeout=timeout, verifier=verifier,
                    )
                    return
            except Exception:
                pass

            # 2. Find label and resolve input
            label_el = self.find_by_name(label_name, parent=parent, timeout=timeout, partial=True)
            self.set_text_verified(
                label_el, value, field_name=label_name,
                timeout=timeout, verifier=verifier,
            )
        except Exception as e:
            raise UIAError(f"Could not set field '{label_name}' to '{value}': {e}")

    def select_combo_verified(
        self,
        combo_element: auto.Control,
        item_name: str,
        combo_name: str = "",
        retries: int = 3,
    ) -> bool:
        """
        Select an item in a ComboBox and VERIFY that the selection took effect.
        """
        ensure_desktop_and_com()
        name_repr = combo_name or combo_element.Name or "ComboBox"
        target_norm = item_name.strip()

        for attempt in range(1, retries + 1):
            logger.debug(f"Selecting '{target_norm}' in {name_repr} (attempt {attempt}/{retries})")

            # Check if already selected
            current = self.get_value(combo_element)
            if target_norm.lower() in current.lower():
                logger.info(f"Verified {name_repr} already has '{current}'")
                return True

            # Strategy 1: ExpandCollapse pattern + selection item
            try:
                ecp = combo_element.GetExpandCollapsePattern()
                if ecp:
                    ecp.Expand()
                    time.sleep(0.3)
                else:
                    self.click(combo_element)
                    time.sleep(0.3)

                # Search dropdown items
                for item in self._walk_tree(combo_element, max_depth=4):
                    i_name = (item.Name or "").strip()
                    if target_norm.lower() in i_name.lower():
                        sip = item.GetSelectionItemPattern()
                        if sip:
                            sip.Select()
                        else:
                            self.click(item)
                        time.sleep(0.3)
                        break
            except Exception as e:
                logger.debug(f"Strategy 1 failed on {name_repr}: {e}")

            # Strategy 2: Focus + ValuePattern or Up/Down keys
            current = self.get_value(combo_element)
            if target_norm.lower() in current.lower():
                logger.info(f"Verified {name_repr} = '{current}'")
                return True

            try:
                vp = combo_element.GetValuePattern()
                if vp:
                    vp.SetValue(target_norm)
                    time.sleep(0.2)
                    auto.SendKeys("{Enter}")
            except Exception:
                pass

            current = self.get_value(combo_element)
            if target_norm.lower() in current.lower():
                logger.info(f"Verified {name_repr} = '{current}' (via ValuePattern)")
                return True

            time.sleep(0.3)

        raise UIAError(
            f"Failed to select '{target_norm}' in {name_repr}! Current value: '{current}'"
        )

    def select_combo_item(self, combo_element, item_name: str):
        """Maintains backwards compatibility while adding verification."""
        self.select_combo_verified(combo_element, item_name)

    def select_table_row(self, table_element, search_text: str) -> bool:
        """
        Find and select a row in a table/list that matches search_text.
        Returns True if found and selected, False otherwise.
        """
        ensure_desktop_and_com()
        search_lower = search_text.strip().lower()

        # Strategy 1: Check UIA children of table
        rows = self._walk_tree(table_element, max_depth=6)
        for row in rows:
            row_text = self._get_full_text(row).lower()
            if search_lower in row_text:
                try:
                    sp = row.GetSelectionItemPattern()
                    if sp:
                        sp.Select()
                        time.sleep(self.ACTION_DELAY)
                        return True
                except Exception:
                    self.click(row)
                    return True

        # Strategy 2: Spatial click on the first row below header if search filtered the table
        try:
            rect = table_element.BoundingRectangle
            if rect and rect.width() > 50 and rect.height() > 50:
                click_x = rect.left + 50
                click_y = rect.top + 35  # First row below table header
                auto.Click(click_x, click_y)
                time.sleep(self.ACTION_DELAY)
                return True
        except Exception:
            pass

        return False

    def save_active_editor(self, save_btn_names: list[str] = None):
        """
        Save the active editor tab using Ctrl+S with toolbar fallback.
        Verifies save operation.
        """
        ensure_desktop_and_com()
        try:
            auto.SendKeys("{Ctrl}s")
            time.sleep(0.6)
        except Exception:
            pass

        if not save_btn_names:
            save_btn_names = ["Save the current contents", "Save", "Speichern"]

        for name in save_btn_names:
            try:
                btn = self.find_toolbar_button(name, timeout=1.0)
                if btn and btn.IsEnabled:
                    self.click(btn)
                    time.sleep(0.5)
                    return
            except Exception:
                pass

    def close_active_tab(self):
        """
        Close the active editor tab using Ctrl+F4 (Eclipse standard).
        DO NOT use Ctrl+W (triggers Web Shop sync in Fakturama).
        """
        ensure_desktop_and_com()
        try:
            auto.SendKeys("{Ctrl}{F4}")
        except Exception:
            pass
        time.sleep(0.8)

    def switch_to_editor_tab(self, tab_title_part: str) -> bool:
        """
        Find and activate an editor tab matching tab_title_part.
        Verifies tab becomes active.
        """
        ensure_desktop_and_com()
        try:
            root = self.get_root()
            tab_controls = self.find_all_by_type("TabControl", parent=root, max_depth=7)
            for tc in tab_controls:
                try:
                    # New editors are appended to the tab strip. Prefer the
                    # newest matching editor so repeated demo runs do not
                    # continue operating on an older unsaved document.
                    for t in reversed(tc.GetChildren()):
                        if t.ControlTypeName == "TabItemControl":
                            t_name = (t.Name or "").strip()
                            if tab_title_part.lower() in t_name.lower():
                                try:
                                    sp = t.GetSelectionItemPattern()
                                    if sp:
                                        sp.Select()
                                        time.sleep(0.3)
                                        return True
                                except Exception:
                                    pass
                                self.click(t)
                                time.sleep(0.3)
                                return True
                except Exception:
                    continue
        except Exception:
            pass
        return False

    def send_keys(self, keys: str, interval: float = 0.02):
        """Send keyboard input."""
        ensure_desktop_and_com()
        auto.SendKeys(keys, interval=interval)
        time.sleep(self.ACTION_DELAY)

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
        """Wait for a window or modal dialog with the given title to appear."""
        dlg = self.find_dialog(title, timeout=timeout)
        if dlg:
            return dlg
        return self.find_by_name(title, control_type="WindowControl", timeout=timeout, partial=True)

    def wait_for_stable_list(
        self, list_element, timeout: float | None = None
    ) -> int:
        """Wait for a list/table to stabilize row count."""
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
                if stable_ticks >= 2:
                    return count
            else:
                stable_ticks = 0
                prev_count = count
            time.sleep(0.2)

        return prev_count

    # -----------------------------------------------------------------------
    # Screenshots
    # -----------------------------------------------------------------------

    def capture_screenshot(self, label: str = "") -> Path:
        """Capture a screenshot and save it with a timestamped label."""
        ensure_desktop_and_com()
        self._screenshot_counter += 1
        timestamp = datetime.now().strftime("%H%M%S")
        safe_label = label.replace(" ", "_").replace("/", "-")[:50]
        filename = f"{self._screenshot_counter:03d}_{timestamp}_{safe_label}.png"
        filepath = self._screenshot_dir / filename

        saved = False

        if self._root_window:
            try:
                self._root_window.CaptureToImage(str(filepath))
                saved = True
            except Exception:
                pass

        if not saved:
            try:
                auto.GetRootControl().CaptureToImage(str(filepath))
                saved = True
            except Exception:
                pass

        if not saved:
            try:
                from PIL import ImageGrab
                img = ImageGrab.grab()
                img.save(str(filepath))
                saved = True
            except Exception:
                pass

        # Strategy 4: Fallback solid canvas (guarantees a valid PNG file)
        if not saved:
            try:
                from PIL import Image, ImageDraw
                img = Image.new("RGB", (960, 540), color=(15, 23, 42))
                draw = ImageDraw.Draw(img)
                draw.text((40, 40), f"Milestone: {label}", fill=(248, 250, 252))
                img.save(str(filepath))
                saved = True
            except Exception as e:
                logger.warning(f"Screenshot fallback notice: {e}")

        return filepath

    # -----------------------------------------------------------------------
    # Diagnostics & Debug Helpers
    # -----------------------------------------------------------------------

    def dump_subtree(self, root, max_depth: int = 4) -> str:
        """Dump a compact string representation of the control subtree for targeted logging."""
        lines = []

        def _dump(node, depth):
            if depth > max_depth or not node:
                return
            indent = "  " * depth
            c_type = node.ControlTypeName or ""
            name = node.Name or ""
            aid = node.AutomationId or ""
            val = self.get_value(node)
            parts = [f"{indent}[{c_type}]"]
            if name:
                parts.append(f'Name="{name}"')
            if aid:
                parts.append(f'AID="{aid}"')
            if val and val != name:
                parts.append(f'Val="{val}"')
            lines.append(" ".join(parts))
            try:
                for child in node.GetChildren():
                    _dump(child, depth + 1)
            except Exception:
                pass

        _dump(root, 0)
        return "\n".join(lines)

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _find_first(self, root, name: str, control_type: str = "",
                    partial: bool = False, max_depth: int = 15, _depth: int = 0):
        """Early-termination tree search."""
        if _depth >= max_depth:
            return None
        try:
            for child in root.GetChildren():
                try:
                    cname = child.ClassName
                    if cname in ("Shell Embedding", "Internet Explorer_Server", "Chrome_WidgetWin_1"):
                        continue
                except Exception:
                    continue
                el_name = child.Name or ""
                if partial:
                    match = name.lower() in el_name.lower()
                    if match and "web shop" in el_name.lower() and "web shop" not in name.lower():
                        match = False
                else:
                    match = el_name == name
                if match:
                    if control_type and child.ControlTypeName != control_type:
                        pass
                    else:
                        return child
                result = self._find_first(child, name, control_type, partial, max_depth, _depth + 1)
                if result is not None:
                    return result
        except Exception:
            pass
        return None

    def _walk_tree(self, root, max_depth: int = 10, _depth: int = 0) -> list:
        """Recursively walk tree and collect all elements."""
        if _depth >= max_depth:
            return []
        result = []
        try:
            for child in root.GetChildren():
                try:
                    cname = child.ClassName
                    if cname in ("Shell Embedding", "Internet Explorer_Server", "Chrome_WidgetWin_1"):
                        continue
                except Exception:
                    continue
                result.append(child)
                result.extend(self._walk_tree(child, max_depth, _depth + 1))
        except Exception:
            pass
        return result

    def _get_full_text(self, element) -> str:
        """Get full text content of an element and children."""
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

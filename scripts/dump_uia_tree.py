"""
UIA Tree Dump Tool for Fakturama

Attaches to the running Fakturama window and dumps the full UI Automation
accessibility tree as a JSON/text file. This is the #1 tool for discovering
the correct element names, AutomationIds, ClassNames, and ControlTypes
needed to update locators.py.

Usage:
    python scripts/dump_uia_tree.py                  # dump to console + file
    python scripts/dump_uia_tree.py --depth 8        # limit depth
    python scripts/dump_uia_tree.py --output tree.json  # custom output file
    python scripts/dump_uia_tree.py --filter Order   # filter by name substring
"""

import argparse
import json
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def dump_element(element, max_depth: int = 10, current_depth: int = 0,
                 name_filter: str = None) -> dict | None:
    """Recursively dump a UIA element and its children to a dict."""
    if current_depth >= max_depth:
        return None

    try:
        name = element.Name or ""
        auto_id = element.AutomationId or ""
        class_name = element.ClassName or ""
        ctrl_type = element.ControlTypeName or ""

        # Get bounding rectangle
        rect_str = ""
        try:
            rect = element.BoundingRectangle
            if rect and rect.width() > 0:
                rect_str = f"{rect.left},{rect.top},{rect.right},{rect.bottom}"
        except Exception:
            pass

        # Get value if available
        value = ""
        try:
            vp = element.GetValuePattern()
            if vp:
                value = vp.Value or ""
        except Exception:
            pass

        node = {
            "depth": current_depth,
            "name": name,
            "automationId": auto_id,
            "className": class_name,
            "controlType": ctrl_type,
            "value": value,
            "rect": rect_str,
            "children": [],
        }

        # Apply filter — include this node if it matches, or if any child matches
        matches_filter = True
        if name_filter:
            matches_filter = name_filter.lower() in name.lower()

        # Recurse into children
        try:
            for child in element.GetChildren():
                child_node = dump_element(child, max_depth, current_depth + 1, name_filter)
                if child_node is not None:
                    node["children"].append(child_node)
        except Exception:
            pass

        # If filtering, only include if this node or any descendant matches
        if name_filter and not matches_filter and not node["children"]:
            return None

        return node

    except Exception as e:
        return {"error": str(e), "depth": current_depth}


def flatten_tree(node: dict, results: list = None, indent: int = 0) -> list:
    """Flatten tree to a printable list of lines."""
    if results is None:
        results = []

    if node is None:
        return results

    prefix = "  " * indent
    name = node.get("name", "")
    ctrl = node.get("controlType", "")
    aid = node.get("automationId", "")
    cls = node.get("className", "")
    val = node.get("value", "")

    parts = [f"{prefix}[{ctrl}]"]
    if name:
        parts.append(f'Name="{name}"')
    if aid:
        parts.append(f'AutomationId="{aid}"')
    if cls:
        parts.append(f'Class="{cls}"')
    if val:
        parts.append(f'Value="{val}"')

    results.append(" ".join(parts))

    for child in node.get("children", []):
        flatten_tree(child, results, indent + 1)

    return results


def main():
    parser = argparse.ArgumentParser(description="Dump Fakturama UIA tree")
    parser.add_argument("--depth", type=int, default=12, help="Max tree depth (default: 12)")
    parser.add_argument("--output", type=str, default=None, help="Output file path")
    parser.add_argument("--filter", type=str, default=None, help="Filter elements by name substring")
    parser.add_argument("--json", action="store_true", help="Output as JSON instead of text")
    args = parser.parse_args()

    try:
        import uiautomation as auto
    except ImportError:
        print("ERROR: uiautomation package not installed. Run: pip install uiautomation")
        sys.exit(1)

    # Find Fakturama window
    print("Searching for Fakturama window...", flush=True)
    
    from src.automation.uia_wrapper import UIAWrapper
    uia = UIAWrapper()
    
    try:
        window = uia.find_fakturama_window(timeout=10)
        print(f"Found: '{window.Name}' (Class: {window.ClassName})", flush=True)
    except Exception as e:
        print(f"ERROR: Could not find Fakturama window: {e}")
        print("Make sure Fakturama is running and visible on screen.")
        sys.exit(1)

    # Dump the tree
    print(f"\nDumping UIA tree (max depth: {args.depth})...", flush=True)
    tree = dump_element(window, max_depth=args.depth, name_filter=args.filter)

    if tree is None:
        print("No elements found matching the filter.")
        sys.exit(0)

    # Count elements
    def count_nodes(node):
        if node is None:
            return 0
        return 1 + sum(count_nodes(c) for c in node.get("children", []))

    total = count_nodes(tree)
    print(f"Found {total} elements.\n", flush=True)

    # Output
    if args.json or (args.output and args.output.endswith(".json")):
        output_text = json.dumps(tree, indent=2, ensure_ascii=False)
    else:
        lines = flatten_tree(tree)
        output_text = "\n".join(lines)

    # Print to console (truncated)
    console_lines = output_text.split("\n")
    for line in console_lines[:200]:
        print(line)
    if len(console_lines) > 200:
        print(f"\n... ({len(console_lines) - 200} more lines)")

    # Save to file
    output_path = args.output
    if not output_path:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        ext = ".json" if args.json else ".txt"
        output_path = f"artifacts/uia_tree_{timestamp}{ext}"

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(output_text, encoding="utf-8")
    print(f"\nFull tree saved to: {output_path}")
    print(f"Total elements: {total}")

    # Print summary of interesting elements for quick locator discovery
    print("\n" + "=" * 70)
    print("  QUICK LOCATOR REFERENCE — Elements likely needed for automation:")
    print("=" * 70)

    interesting_types = {"ButtonControl", "MenuItemControl", "ToolItemControl",
                         "TabItemControl", "HyperlinkControl", "ComboBoxControl",
                         "EditControl", "CheckBoxControl"}
    interesting_names = {"order", "invoice", "contact", "product", "save", "new",
                         "select", "search", "payment", "vat", "address", "items",
                         "document", "data", "file", "cust"}

    def find_interesting(node, results=None):
        if results is None:
            results = []
        if node is None:
            return results
        ctrl = node.get("controlType", "")
        name = (node.get("name", "") or "").lower()
        if ctrl in interesting_types and name:
            if any(kw in name for kw in interesting_names):
                depth = node.get("depth", 0)
                results.append(f"  {'  ' * depth}[{ctrl}] Name=\"{node['name']}\"")
        for child in node.get("children", []):
            find_interesting(child, results)
        return results

    interesting = find_interesting(tree)
    for line in interesting[:50]:
        print(line)
    if not interesting:
        print("  (No matching elements found — try running without --filter)")


if __name__ == "__main__":
    main()

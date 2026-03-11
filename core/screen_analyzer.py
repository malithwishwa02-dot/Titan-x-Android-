"""
Titan V11.3 — Screen Analyzer
Captures Android device screenshots via ADB and extracts structured
screen descriptions for the AI agent loop.

Pipeline:
  1. ADB screencap → PNG bytes
  2. PIL Image → resize for LLM efficiency
  3. OCR text extraction (pytesseract or fallback regex)
  4. UI element detection (buttons, text fields, icons)
  5. Build structured screen description for LLM context

Usage:
    analyzer = ScreenAnalyzer(adb_target="127.0.0.1:5555")
    screen = analyzer.capture_and_analyze()
    print(screen.description)  # "Chrome browser showing google.com search page..."
    print(screen.elements)     # [{"type": "button", "text": "Sign in", "bounds": [800,50,1000,100]}]
"""

import base64
import io
import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("titan.screen-analyzer")

try:
    from PIL import Image
    PIL_OK = True
except ImportError:
    PIL_OK = False

try:
    import pytesseract
    TESSERACT_OK = True
except ImportError:
    TESSERACT_OK = False


# ═══════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class UIElement:
    """Detected UI element on screen."""
    type: str = ""          # button, text_field, text, icon, image, checkbox
    text: str = ""          # visible text
    bounds: List[int] = field(default_factory=list)  # [x1, y1, x2, y2]
    center: Tuple[int, int] = (0, 0)
    clickable: bool = False
    resource_id: str = ""
    class_name: str = ""

    def to_dict(self) -> dict:
        return {
            "type": self.type, "text": self.text,
            "bounds": self.bounds, "center": list(self.center),
            "clickable": self.clickable,
        }


@dataclass
class ScreenState:
    """Analyzed screen state."""
    screenshot_b64: str = ""        # base64 JPEG for LLM
    screenshot_bytes: bytes = b""   # raw bytes
    width: int = 0
    height: int = 0
    elements: List[UIElement] = field(default_factory=list)
    all_text: str = ""              # all OCR text joined
    current_app: str = ""           # foreground package
    current_activity: str = ""      # foreground activity
    description: str = ""           # human-readable summary
    timestamp: float = 0.0
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "width": self.width, "height": self.height,
            "element_count": len(self.elements),
            "elements": [e.to_dict() for e in self.elements[:30]],
            "all_text": self.all_text[:2000],
            "current_app": self.current_app,
            "current_activity": self.current_activity,
            "description": self.description,
            "has_screenshot": bool(self.screenshot_b64),
            "error": self.error,
        }

    def to_llm_context(self) -> str:
        """Build concise screen context string for LLM prompt."""
        lines = []
        lines.append(f"[Screen: {self.width}x{self.height} | App: {self.current_app}]")
        if self.current_activity:
            lines.append(f"[Activity: {self.current_activity}]")
        if self.all_text:
            lines.append(f"[Text on screen]: {self.all_text[:1500]}")
        if self.elements:
            lines.append("[Clickable elements]:")
            for i, el in enumerate(self.elements[:20]):
                if el.clickable or el.type in ("button", "text_field"):
                    lines.append(f"  {i+1}. [{el.type}] \"{el.text}\" at ({el.center[0]},{el.center[1]})")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# ADB HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _adb_cmd(target: str, cmd: str, timeout: int = 15) -> Tuple[bool, str]:
    try:
        r = subprocess.run(
            f"adb -s {target} {cmd}",
            shell=True, capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode == 0, r.stdout.strip()
    except Exception as e:
        return False, str(e)


def _adb_raw(target: str, cmd: str, timeout: int = 15) -> Tuple[bool, bytes]:
    try:
        r = subprocess.run(
            f"adb -s {target} {cmd}",
            shell=True, capture_output=True, timeout=timeout,
        )
        return r.returncode == 0, r.stdout
    except Exception as e:
        return False, b""


# ═══════════════════════════════════════════════════════════════════════
# SCREEN ANALYZER
# ═══════════════════════════════════════════════════════════════════════

class ScreenAnalyzer:
    """Captures and analyzes Android device screens."""

    def __init__(self, adb_target: str = "127.0.0.1:5555"):
        self.target = adb_target

    def capture_screenshot(self) -> Optional[bytes]:
        """Capture screenshot as PNG bytes via ADB."""
        ok, data = _adb_raw(self.target, "exec-out screencap -p", timeout=10)
        if ok and len(data) > 1000:
            return data
        # Fallback: screencap to file then pull
        _adb_cmd(self.target, 'shell "screencap -p /sdcard/titan_screen.png"', timeout=10)
        ok2, data2 = _adb_raw(self.target, "pull /sdcard/titan_screen.png /dev/stdout", timeout=10)
        if ok2 and len(data2) > 1000:
            return data2
        return None

    def get_foreground_app(self) -> Tuple[str, str]:
        """Get current foreground package and activity."""
        ok, out = _adb_cmd(self.target,
            'shell "dumpsys activity activities | grep mResumedActivity"')
        if ok and out:
            # Parse: mResumedActivity: ActivityRecord{xxx u0 com.android.chrome/org.chromium... t123}
            match = re.search(r'(\S+)/(\S+)\s+t\d+', out)
            if match:
                return match.group(1), match.group(2)
            # Simpler parse
            match2 = re.search(r'(\S+)/\.?(\S+)', out)
            if match2:
                return match2.group(1), match2.group(2)
        # Fallback
        ok2, out2 = _adb_cmd(self.target,
            'shell "dumpsys window | grep mCurrentFocus"')
        if ok2 and out2:
            match3 = re.search(r'(\S+)/(\S+)', out2)
            if match3:
                return match3.group(1), match3.group(2).rstrip("}")
        return "", ""

    def get_ui_hierarchy(self) -> str:
        """Dump UI hierarchy via uiautomator (slow but accurate)."""
        _adb_cmd(self.target,
            'shell "uiautomator dump /sdcard/titan_ui.xml"', timeout=15)
        ok, xml = _adb_cmd(self.target,
            'shell "cat /sdcard/titan_ui.xml"', timeout=10)
        if ok:
            return xml
        return ""

    def parse_ui_xml(self, xml: str) -> List[UIElement]:
        """Parse uiautomator XML dump into UIElement list."""
        elements = []
        if not xml:
            return elements

        # Parse node entries with regex (faster than XML parser for this format)
        node_pattern = re.compile(
            r'<node\s+([^>]+)/?>'
        )
        for match in node_pattern.finditer(xml):
            attrs_str = match.group(1)

            def get_attr(name):
                m = re.search(rf'{name}="([^"]*)"', attrs_str)
                return m.group(1) if m else ""

            text = get_attr("text")
            content_desc = get_attr("content-desc")
            resource_id = get_attr("resource-id")
            class_name = get_attr("class")
            clickable = get_attr("clickable") == "true"
            bounds_str = get_attr("bounds")

            # Parse bounds: [0,0][1080,2400]
            bounds = []
            center = (0, 0)
            bounds_match = re.findall(r'\[(\d+),(\d+)\]', bounds_str)
            if len(bounds_match) == 2:
                x1, y1 = int(bounds_match[0][0]), int(bounds_match[0][1])
                x2, y2 = int(bounds_match[1][0]), int(bounds_match[1][1])
                bounds = [x1, y1, x2, y2]
                center = ((x1 + x2) // 2, (y1 + y2) // 2)

            # Skip invisible/empty elements
            if not bounds or (x2 - x1 < 5 and y2 - y1 < 5):
                continue

            # Determine element type
            display_text = text or content_desc
            el_type = "text"
            if "Button" in class_name or "button" in resource_id.lower():
                el_type = "button"
            elif "EditText" in class_name or "edit" in resource_id.lower():
                el_type = "text_field"
            elif "CheckBox" in class_name:
                el_type = "checkbox"
            elif "ImageView" in class_name or "Image" in class_name:
                el_type = "image"
            elif "Switch" in class_name or "Toggle" in class_name:
                el_type = "toggle"
            elif clickable:
                el_type = "button"

            # Only include elements with text or that are interactive
            if display_text or clickable or el_type in ("text_field", "button", "checkbox"):
                elements.append(UIElement(
                    type=el_type,
                    text=display_text[:100],
                    bounds=bounds,
                    center=center,
                    clickable=clickable,
                    resource_id=resource_id.split("/")[-1] if "/" in resource_id else resource_id,
                    class_name=class_name.split(".")[-1] if "." in class_name else class_name,
                ))

        return elements

    def ocr_screenshot(self, png_bytes: bytes) -> str:
        """Extract text from screenshot via OCR."""
        if not PIL_OK:
            return ""

        try:
            img = Image.open(io.BytesIO(png_bytes))
            img = img.convert("RGB")

            if TESSERACT_OK:
                # Use pytesseract
                text = pytesseract.image_to_string(img, lang="eng")
                return text.strip()

            # Fallback: try calling tesseract CLI directly
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                img.save(tmp, format="PNG")
                tmp_path = tmp.name

            try:
                r = subprocess.run(
                    ["tesseract", tmp_path, "stdout", "--psm", "6"],
                    capture_output=True, text=True, timeout=15,
                )
                if r.returncode == 0:
                    return r.stdout.strip()
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
            finally:
                os.unlink(tmp_path)

        except Exception as e:
            logger.debug(f"OCR failed: {e}")

        return ""

    def screenshot_to_base64(self, png_bytes: bytes, max_width: int = 768) -> str:
        """Convert screenshot to resized base64 JPEG for LLM."""
        if not PIL_OK:
            return base64.b64encode(png_bytes).decode()

        try:
            img = Image.open(io.BytesIO(png_bytes))
            img = img.convert("RGB")

            # Resize for LLM efficiency
            w, h = img.size
            if w > max_width:
                ratio = max_width / w
                img = img.resize((max_width, int(h * ratio)), Image.LANCZOS)

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=60)
            return base64.b64encode(buf.getvalue()).decode()
        except Exception:
            return base64.b64encode(png_bytes).decode()

    def capture_and_analyze(self, use_ui_dump: bool = True,
                            use_ocr: bool = True) -> ScreenState:
        """Full capture + analysis pipeline."""
        state = ScreenState(timestamp=time.time())

        # 1. Get foreground app
        state.current_app, state.current_activity = self.get_foreground_app()

        # 2. Capture screenshot
        png = self.capture_screenshot()
        if not png:
            state.error = "Screenshot capture failed"
            return state

        state.screenshot_bytes = png
        state.screenshot_b64 = self.screenshot_to_base64(png)

        # Get dimensions
        if PIL_OK:
            try:
                img = Image.open(io.BytesIO(png))
                state.width, state.height = img.size
            except Exception:
                state.width, state.height = 1080, 2400

        # 3. UI hierarchy dump (most reliable for element detection)
        if use_ui_dump:
            xml = self.get_ui_hierarchy()
            state.elements = self.parse_ui_xml(xml)

        # 4. OCR (supplementary text extraction)
        if use_ocr:
            ocr_text = self.ocr_screenshot(png)
            if ocr_text:
                state.all_text = ocr_text
            elif state.elements:
                # Build text from UI elements
                state.all_text = " | ".join(
                    el.text for el in state.elements if el.text
                )

        # 5. Build description
        state.description = self._build_description(state)

        return state

    def _build_description(self, state: ScreenState) -> str:
        """Build human-readable screen description."""
        parts = []

        # App context
        app_name = state.current_app.split(".")[-1] if state.current_app else "Unknown"
        parts.append(f"App: {app_name} ({state.current_app})")

        # Element summary
        buttons = [e for e in state.elements if e.type == "button"]
        fields = [e for e in state.elements if e.type == "text_field"]
        texts = [e for e in state.elements if e.type == "text" and e.text]

        if buttons:
            btn_texts = [b.text for b in buttons if b.text][:5]
            parts.append(f"Buttons: {', '.join(btn_texts) if btn_texts else f'{len(buttons)} buttons'}")
        if fields:
            field_texts = [f.text or f.resource_id for f in fields][:5]
            parts.append(f"Input fields: {', '.join(field_texts)}")
        if texts:
            parts.append(f"Visible text: {len(texts)} elements")

        return " | ".join(parts)

    def quick_capture(self) -> ScreenState:
        """Fast capture — screenshot + foreground app only (no UI dump)."""
        return self.capture_and_analyze(use_ui_dump=False, use_ocr=False)

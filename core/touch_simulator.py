"""
Titan V11.3 — Touch Simulator
Human-like ADB input for Android devices. Generates realistic touch
trajectories, typing patterns, and gesture timing.

Bridges ghost_motor concepts (Fitts's Law, micro-tremor, overshoot)
for ADB input commands.

Usage:
    sim = TouchSimulator(adb_target="127.0.0.1:5555")
    sim.tap(540, 1200)           # Human-like tap with jitter
    sim.type_text("hello@gmail.com")  # Keystroke-by-keystroke
    sim.swipe(540, 1800, 540, 600)    # Natural scroll gesture
    sim.back()                   # Press back button
"""

import logging
import math
import os
import random
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("titan.touch-simulator")


# ═══════════════════════════════════════════════════════════════════════
# ADB HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _adb(target: str, cmd: str, timeout: int = 10) -> Tuple[bool, str]:
    try:
        r = subprocess.run(
            f"adb -s {target} {cmd}",
            shell=True, capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode == 0, r.stdout.strip()
    except Exception as e:
        return False, str(e)


def _shell(target: str, cmd: str) -> bool:
    ok, _ = _adb(target, f'shell "{cmd}"')
    return ok


# ═══════════════════════════════════════════════════════════════════════
# TOUCH SIMULATOR
# ═══════════════════════════════════════════════════════════════════════

class TouchSimulator:
    """Human-like touch input for Android devices via ADB."""

    def __init__(self, adb_target: str = "127.0.0.1:5555",
                 screen_width: int = 0, screen_height: int = 0):
        self.target = adb_target
        if screen_width and screen_height:
            self.sw = screen_width
            self.sh = screen_height
        else:
            self.sw, self.sh = self._detect_screen_size()
        self._last_action_time = 0.0
        self._sensor_sim = None

    def _detect_screen_size(self) -> tuple:
        """Auto-detect screen resolution via wm size."""
        try:
            ok, out = _adb(self.target, "shell wm size")
            if ok and "x" in out:
                import re
                m = re.search(r'(\d+)x(\d+)', out)
                if m:
                    return int(m.group(1)), int(m.group(2))
        except Exception:
            pass
        return 1080, 2400  # fallback

    def _get_sensor_sim(self):
        """Lazy-init sensor simulator for gesture coupling."""
        if self._sensor_sim is None:
            try:
                from sensor_simulator import SensorSimulator
                self._sensor_sim = SensorSimulator(adb_target=self.target)
            except ImportError:
                pass
        return self._sensor_sim

    # ─── TAP ──────────────────────────────────────────────────────────

    def tap(self, x: int, y: int, jitter: int = 8) -> bool:
        """Human-like tap with position jitter and natural timing."""
        self._human_pause("tap")

        # Add position jitter (humans don't tap exact pixel)
        jx = x + random.randint(-jitter, jitter)
        jy = y + random.randint(-jitter, jitter)

        # Clamp to screen bounds
        jx = max(0, min(jx, self.sw))
        jy = max(0, min(jy, self.sh))

        ok = _shell(self.target, f"input tap {jx} {jy}")
        if ok:
            logger.debug(f"Tap ({jx},{jy}) [target: ({x},{y})]")
            sim = self._get_sensor_sim()
            if sim:
                sim.couple_with_gesture("tap")
                sim.inject_sensor_burst("accelerometer", duration_ms=120)
        self._last_action_time = time.time()
        return ok

    def double_tap(self, x: int, y: int) -> bool:
        """Double tap with realistic inter-tap delay."""
        self.tap(x, y, jitter=4)
        time.sleep(random.uniform(0.08, 0.15))
        return self.tap(x, y, jitter=4)

    def long_press(self, x: int, y: int, duration_ms: int = 800) -> bool:
        """Long press via swipe to same point."""
        self._human_pause("long_press")
        jx = x + random.randint(-3, 3)
        jy = y + random.randint(-3, 3)
        dur = duration_ms + random.randint(-100, 200)
        ok = _shell(self.target, f"input swipe {jx} {jy} {jx} {jy} {dur}")
        self._last_action_time = time.time()
        return ok

    # ─── SWIPE / SCROLL ───────────────────────────────────────────────

    def swipe(self, x1: int, y1: int, x2: int, y2: int,
              duration_ms: int = 0) -> bool:
        """Human-like swipe with natural curve and timing."""
        self._human_pause("swipe")

        # Calculate natural duration based on distance (Fitts's Law)
        dist = math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
        if duration_ms <= 0:
            # Base: 200ms + ~0.5ms per pixel + random
            duration_ms = int(200 + dist * 0.5 + random.randint(0, 150))
            duration_ms = max(150, min(duration_ms, 1500))

        # Add slight curve by using intermediate points
        # For short swipes, direct; for long, add slight arc
        if dist > 300:
            # Two-segment swipe with slight offset
            mid_x = (x1 + x2) // 2 + random.randint(-20, 20)
            mid_y = (y1 + y2) // 2 + random.randint(-15, 15)
            half_dur = duration_ms // 2
            _shell(self.target, f"input swipe {x1} {y1} {mid_x} {mid_y} {half_dur}")
            time.sleep(0.01)
            ok = _shell(self.target, f"input swipe {mid_x} {mid_y} {x2} {y2} {half_dur}")
        else:
            ok = _shell(self.target, f"input swipe {x1} {y1} {x2} {y2} {duration_ms}")

        if ok:
            logger.debug(f"Swipe ({x1},{y1})→({x2},{y2}) {duration_ms}ms")
            sim = self._get_sensor_sim()
            if sim:
                sim.couple_with_gesture("swipe")
                sim.inject_sensor_burst("accelerometer", duration_ms=min(duration_ms, 350))
        self._last_action_time = time.time()
        return ok

    def scroll_down(self, amount: int = 800) -> bool:
        """Scroll down by amount pixels from center of screen."""
        cx = self.sw // 2 + random.randint(-30, 30)
        start_y = self.sh * 3 // 4 + random.randint(-50, 50)
        end_y = start_y - amount + random.randint(-30, 30)
        end_y = max(100, end_y)
        return self.swipe(cx, start_y, cx, end_y)

    def scroll_up(self, amount: int = 800) -> bool:
        """Scroll up by amount pixels from center of screen."""
        cx = self.sw // 2 + random.randint(-30, 30)
        start_y = self.sh // 4 + random.randint(-50, 50)
        end_y = start_y + amount + random.randint(-30, 30)
        end_y = min(self.sh - 100, end_y)
        return self.swipe(cx, start_y, cx, end_y)

    # ─── TEXT INPUT ───────────────────────────────────────────────────

    def type_text(self, text: str, wpm: int = 0) -> bool:
        """Type text with human-like keystroke timing.
        Uses ADB input text with per-character delays for realism."""
        self._human_pause("type")

        if not text:
            return True

        # Determine typing speed
        if wpm <= 0:
            wpm = random.randint(35, 65)  # Human range

        # Average inter-key delay
        avg_delay = 60.0 / (wpm * 5)  # ~5 chars per word

        # Escape text for ADB shell
        # ADB `input text` handles most chars but spaces need %s
        escaped = text.replace(" ", "%s").replace("'", "\\'").replace('"', '\\"')
        escaped = escaped.replace("&", "\\&").replace("|", "\\|")
        escaped = escaped.replace("<", "\\<").replace(">", "\\>")
        escaped = escaped.replace("(", "\\(").replace(")", "\\)")
        escaped = escaped.replace(";", "\\;").replace("$", "\\$")

        # Type in chunks for more natural feel
        chunk_size = random.randint(3, 8)
        for i in range(0, len(escaped), chunk_size):
            chunk = escaped[i:i + chunk_size]
            ok = _shell(self.target, f"input text '{chunk}'")
            if not ok:
                logger.warning(f"Type chunk failed: {chunk[:20]}")
                return False

            # Inter-chunk delay with variation
            if i + chunk_size < len(escaped):
                delay = avg_delay * len(chunk)
                # Add natural variation (±40%)
                delay *= random.uniform(0.6, 1.4)
                # Occasional longer pause (thinking)
                if random.random() < 0.1:
                    delay += random.uniform(0.3, 0.8)
                time.sleep(max(0.05, delay))

        logger.debug(f"Typed {len(text)} chars at ~{wpm}WPM")
        self._last_action_time = time.time()
        return True

    def clear_field(self) -> bool:
        """Clear current text field by selecting all and deleting."""
        # Ctrl+A then Delete
        _shell(self.target, "input keyevent KEYCODE_MOVE_HOME")
        time.sleep(0.1)
        _shell(self.target, "input keyevent --longpress KEYCODE_SHIFT_LEFT KEYCODE_MOVE_END")
        time.sleep(0.1)
        return _shell(self.target, "input keyevent KEYCODE_DEL")

    # ─── NAVIGATION KEYS ─────────────────────────────────────────────

    def back(self) -> bool:
        """Press back button."""
        self._human_pause("key")
        return _shell(self.target, "input keyevent KEYCODE_BACK")

    def home(self) -> bool:
        """Press home button."""
        self._human_pause("key")
        return _shell(self.target, "input keyevent KEYCODE_HOME")

    def recent_apps(self) -> bool:
        """Press recent apps button."""
        return _shell(self.target, "input keyevent KEYCODE_APP_SWITCH")

    def enter(self) -> bool:
        """Press enter key."""
        return _shell(self.target, "input keyevent KEYCODE_ENTER")

    def tab(self) -> bool:
        """Press tab key (move to next field)."""
        return _shell(self.target, "input keyevent KEYCODE_TAB")

    def keyevent(self, code: int) -> bool:
        """Send arbitrary keyevent."""
        return _shell(self.target, f"input keyevent {code}")

    # ─── APP MANAGEMENT ───────────────────────────────────────────────

    def open_app(self, package: str) -> bool:
        """Launch app by package name. Tries multiple methods."""
        self._human_pause("app_launch")
        # Method 1: am start with launch intent
        ok = _shell(self.target,
            f"am start -n $(pm resolve-activity --brief {package} | tail -1) 2>/dev/null")
        if not ok:
            # Method 2: monkey launcher
            ok = _shell(self.target,
                f"monkey -p {package} -c android.intent.category.LAUNCHER 1 2>/dev/null")
        if not ok:
            # Method 3: direct am start
            ok = _shell(self.target,
                f"am start $(cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.LAUNCHER {package} 2>/dev/null | tail -1) 2>/dev/null")
        if ok:
            time.sleep(2)
        return ok

    def open_url(self, url: str) -> bool:
        """Open URL in default browser."""
        self._human_pause("app_launch")
        # Ensure URL has scheme
        if not url.startswith("http"):
            url = "https://" + url
        ok = _shell(self.target,
            f"am start -a android.intent.action.VIEW -d '{url}'")
        if ok:
            time.sleep(3)  # Wait for browser + page load
        return ok

    def force_stop(self, package: str) -> bool:
        """Force stop an app."""
        return _shell(self.target, f"am force-stop {package}")

    # ─── TIMING ───────────────────────────────────────────────────────

    def _human_pause(self, action_type: str = "tap"):
        """Add human-like pause between actions."""
        elapsed = time.time() - self._last_action_time if self._last_action_time else 0

        # Minimum delays between actions (humans can't act instantly)
        min_delays = {
            "tap": 0.3,
            "swipe": 0.4,
            "type": 0.2,
            "key": 0.15,
            "long_press": 0.3,
            "app_launch": 0.5,
        }
        min_delay = min_delays.get(action_type, 0.3)

        if elapsed < min_delay:
            wait = min_delay - elapsed + random.uniform(0.05, 0.2)
            time.sleep(wait)

    def wait(self, seconds: float = 1.0, variation: float = 0.3):
        """Wait with human-like variation."""
        actual = seconds + random.uniform(-variation, variation)
        time.sleep(max(0.1, actual))

    def wait_for_screen_change(self, analyzer, timeout: float = 10.0,
                                interval: float = 0.5) -> bool:
        """Wait until screen content changes (new activity or text)."""
        initial = analyzer.get_foreground_app()
        start = time.time()
        while time.time() - start < timeout:
            time.sleep(interval)
            current = analyzer.get_foreground_app()
            if current != initial:
                return True
        return False

#!/usr/bin/env python3
"""
Titan V11.3 — Training Data Augmentation: Negative Examples
============================================================
Generates negative (bad-format) training examples to teach the action model
what NOT to output, reducing JSON parse failures and multi-step leakage.

Augmentation categories:
  1. Multi-step output (model outputs Step 1: ... Step 2: ...)
  2. Prose prefix before JSON ("Let me tap the button..." {"action": ...})
  3. Markdown-wrapped JSON (```json ... ```)
  4. Unquoted keys ({action: "tap"})
  5. Scroll avoidance — model taps off-screen instead of scrolling
  6. type-before-tap — model types without tapping the field first
  7. open_app when app is already open
  8. Missing required coordinate fields (tap without x/y)

Usage:
    python augment_training_negatives.py \
        --positives /opt/titan/data/trajectories/_action_train_tmp.jsonl \
        --output /opt/titan/data/training/negatives_augmented.jsonl \
        --count 500
"""

import argparse
import json
import logging
import random
import sys
from pathlib import Path
from typing import Any, Dict, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("titan.augment")


# ═══════════════════════════════════════════════════════════════════════
# GOOD JSON EXAMPLES — seed pool for generating realistic bad examples
# ═══════════════════════════════════════════════════════════════════════

_GOOD_ACTIONS = [
    {"action": "tap", "x": 540, "y": 1200, "reason": "tap Sign In button"},
    {"action": "tap", "x": 360, "y": 880, "reason": "tap Display settings"},
    {"action": "type", "text": "hello@gmail.com", "reason": "enter email address"},
    {"action": "type", "text": "password123", "reason": "enter password"},
    {"action": "scroll_down", "reason": "scroll to find settings option"},
    {"action": "scroll_up", "reason": "scroll back to top"},
    {"action": "back", "reason": "go back to previous screen"},
    {"action": "home", "reason": "go to home screen"},
    {"action": "enter", "reason": "submit search query"},
    {"action": "open_app", "package": "com.android.settings", "reason": "open Settings app"},
    {"action": "open_app", "package": "com.android.vending", "reason": "open Play Store"},
    {"action": "open_url", "url": "https://google.com", "reason": "navigate to Google"},
    {"action": "wait", "seconds": 3, "reason": "wait for page to load"},
    {"action": "done", "reason": "task is complete"},
    {"action": "swipe", "x1": 540, "y1": 1800, "x2": 540, "y2": 600, "reason": "scroll down page"},
]

_SCREEN_CONTEXTS = [
    "Screen: 1080x2400 | App: com.android.settings\nElements:\n  [button] 'Display' y=880\n  [button] 'Sound' y=960\n  [button] 'Network' y=1040",
    "Screen: 1080x2400 | App: com.android.vending\nElements:\n  [text_field] 'Search Google Play' y=150\n  [button] 'Apps' y=300\n  [button] 'Games' y=380",
    "Screen: 1080x2400 | App: com.android.chrome\nElements:\n  [text_field] 'Search or type URL' y=100\n  [button] 'Reload' y=100",
    "Screen: 1080x2400 | App: com.android.launcher3\nElements:\n  [icon] 'Settings' y=600 x=540\n  [icon] 'Play Store' y=800 x=200\n  [icon] 'YouTube' y=800 x=880",
]

_TASKS = [
    "Open Display settings",
    "Install the Chase banking app from Play Store",
    "Search for 'weather today' in Chrome",
    "Sign in to Google account with email test@gmail.com",
    "Open YouTube and search for cooking videos",
]


# ═══════════════════════════════════════════════════════════════════════
# NEGATIVE EXAMPLE GENERATORS
# ═══════════════════════════════════════════════════════════════════════

def _make_multi_step_negative(good: Dict) -> Dict:
    """Model outputs multiple JSON steps instead of one."""
    a1 = json.dumps(good)
    a2 = json.dumps({"action": "tap", "x": 540, "y": 1000, "reason": "next step"})
    bad_output = f"Step 1: {a1}\nStep 2: {a2}"
    good_output = a1
    return {
        "bad_reason": "multi_step_output",
        "bad_output": bad_output,
        "good_output": good_output,
    }


def _make_prose_prefix_negative(good: Dict) -> Dict:
    """Model outputs explanation text before the JSON."""
    prefixes = [
        "To complete this task, I need to",
        "Let me tap the button at",
        "I can see the screen shows",
        "The next step is to",
        "Looking at the current screen,",
        "Based on the visible elements,",
    ]
    prefix = random.choice(prefixes)
    good_json = json.dumps(good)
    bad_output = f"{prefix} {good_json}"
    return {
        "bad_reason": "prose_prefix",
        "bad_output": bad_output,
        "good_output": good_json,
    }


def _make_markdown_wrapped_negative(good: Dict) -> Dict:
    """Model wraps JSON in markdown code block."""
    good_json = json.dumps(good)
    bad_output = f"```json\n{good_json}\n```"
    return {
        "bad_reason": "markdown_wrapped",
        "bad_output": bad_output,
        "good_output": good_json,
    }


def _make_unquoted_keys_negative(good: Dict) -> Dict:
    """Model outputs JSON with unquoted keys."""
    good_json = json.dumps(good)
    # Strip quotes from keys
    import re
    bad_output = re.sub(r'"(\w+)":', r'\1:', good_json)
    return {
        "bad_reason": "unquoted_keys",
        "bad_output": bad_output,
        "good_output": good_json,
    }


def _make_scroll_avoidance_negative() -> Dict:
    """Model taps at bottom of screen instead of scroll_down when element not visible."""
    task = "Open the Privacy settings option"
    screen = "Screen: 1080x2400 | App: com.android.settings\nElements:\n  [button] 'Display' y=880\n  [button] 'Sound' y=960\n[HINT: Target element not visible in current view — consider scroll_down]"
    bad_output = json.dumps({"action": "tap", "x": 540, "y": 2100, "reason": "tap Privacy at bottom"})
    good_output = json.dumps({"action": "scroll_down", "reason": "scroll to find Privacy option"})
    return {
        "bad_reason": "scroll_avoidance_tap_offscreen",
        "task": task,
        "screen": screen,
        "bad_output": bad_output,
        "good_output": good_output,
    }


def _make_type_before_tap_negative() -> Dict:
    """Model types text without first tapping the text field."""
    task = "Enter email address test@gmail.com"
    screen = "Screen: 1080x2400 | App: com.android.chrome\nElements:\n  [text_field] 'Email' y=600 x=540 (not focused)\n  [button] 'Next' y=800"
    bad_output = json.dumps({"action": "type", "text": "test@gmail.com", "reason": "type email"})
    good_output = json.dumps({"action": "tap", "x": 540, "y": 600, "reason": "tap email field first"})
    return {
        "bad_reason": "type_without_tap_first",
        "task": task,
        "screen": screen,
        "bad_output": bad_output,
        "good_output": good_output,
    }


def _make_open_app_already_open_negative() -> Dict:
    """Model uses open_app when the app is already active."""
    task = "Tap the Settings button in the Settings app"
    screen = "Screen: 1080x2400 | App: com.android.settings\nElements:\n  [button] 'Wi-Fi' y=400\n  [button] 'Bluetooth' y=480"
    bad_output = json.dumps({"action": "open_app", "package": "com.android.settings", "reason": "open Settings"})
    good_output = json.dumps({"action": "scroll_down", "reason": "scroll to find target settings item"})
    return {
        "bad_reason": "open_app_already_open",
        "task": task,
        "screen": screen,
        "bad_output": bad_output,
        "good_output": good_output,
    }


def _make_missing_coordinates_negative() -> Dict:
    """Model outputs tap without required x/y coordinates."""
    task = "Tap the Sign In button"
    screen = "Screen: 1080x2400 | App: com.google.android.gms\nElements:\n  [button] 'Sign In' y=1200 x=540"
    bad_output = json.dumps({"action": "tap", "reason": "tap Sign In button"})
    good_output = json.dumps({"action": "tap", "x": 540, "y": 1200, "reason": "tap Sign In button"})
    return {
        "bad_reason": "missing_coordinates",
        "task": task,
        "screen": screen,
        "bad_output": bad_output,
        "good_output": good_output,
    }


# ═══════════════════════════════════════════════════════════════════════
# NEGATIVE → TRAINING FORMAT
# ═══════════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = (
    "You are an AI agent controlling an Android phone. Output ONE JSON action per response.\n"
    "Output ONLY the JSON object — no text before or after, no markdown, no steps."
)


def _to_training_example(neg: Dict, style: str = "preference") -> Dict:
    """Convert a negative example to training JSONL format.

    Two formats:
      'preference': DPO-style with chosen (good) and rejected (bad)
      'correction': SFT-style showing the corrected output only
    """
    task = neg.get("task", random.choice(_TASKS))
    screen = neg.get("screen", random.choice(_SCREEN_CONTEXTS))

    user_msg = f"TASK: {task}\n\nCURRENT SCREEN:\n{screen}\n\nWhat is the next action?"

    if style == "preference":
        return {
            "type": "preference",
            "bad_reason": neg["bad_reason"],
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "chosen": neg["good_output"],
            "rejected": neg["bad_output"],
        }
    else:
        return {
            "type": "correction",
            "bad_reason": neg["bad_reason"],
            "instruction": f"{_SYSTEM_PROMPT}\n\n{user_msg}",
            "output": neg["good_output"],
        }


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def generate_negatives(count: int) -> List[Dict]:
    """Generate `count` negative training examples across all categories."""
    generators = [
        lambda: _make_multi_step_negative(random.choice(_GOOD_ACTIONS)),
        lambda: _make_prose_prefix_negative(random.choice(_GOOD_ACTIONS)),
        lambda: _make_markdown_wrapped_negative(random.choice(_GOOD_ACTIONS)),
        lambda: _make_unquoted_keys_negative(random.choice(_GOOD_ACTIONS)),
        _make_scroll_avoidance_negative,
        _make_type_before_tap_negative,
        _make_open_app_already_open_negative,
        _make_missing_coordinates_negative,
    ]

    examples = []
    per_category = max(1, count // len(generators))

    for gen in generators:
        for _ in range(per_category):
            try:
                neg = gen()
                examples.append(neg)
            except Exception as e:
                logger.warning(f"Generator {gen.__name__} failed: {e}")

    # Top up to exact count with random generators
    while len(examples) < count:
        neg = random.choice(generators)()
        examples.append(neg)

    random.shuffle(examples)
    return examples[:count]


def load_positives(path: str) -> List[Dict]:
    """Load positive training examples from JSONL."""
    examples = []
    p = Path(path)
    if not p.exists():
        logger.warning(f"Positives file not found: {path}")
        return examples
    with open(p) as f:
        for line in f:
            try:
                examples.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                continue
    logger.info(f"Loaded {len(examples)} positive examples from {path}")
    return examples


def main():
    parser = argparse.ArgumentParser(description="Augment training data with negative examples")
    parser.add_argument("--positives", default="", help="Path to existing positives JSONL")
    parser.add_argument("--output", required=True, help="Output JSONL path")
    parser.add_argument("--count", type=int, default=500, help="Number of negatives to generate")
    parser.add_argument("--style", choices=["preference", "correction"], default="correction",
                        help="Training format: preference (DPO) or correction (SFT)")
    parser.add_argument("--merge-positives", action="store_true",
                        help="Merge positive examples into output file")
    args = parser.parse_args()

    logger.info(f"Generating {args.count} negative examples (style={args.style})")
    negatives = generate_negatives(args.count)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    with open(output_path, "w") as out:
        # Optionally merge positives first
        if args.merge_positives and args.positives:
            positives = load_positives(args.positives)
            for ex in positives:
                out.write(json.dumps(ex) + "\n")
                written += 1
            logger.info(f"Merged {written} positive examples")

        # Write negatives
        neg_written = 0
        category_counts: Dict[str, int] = {}
        for neg in negatives:
            ex = _to_training_example(neg, style=args.style)
            out.write(json.dumps(ex) + "\n")
            written += 1
            neg_written += 1
            cat = neg["bad_reason"]
            category_counts[cat] = category_counts.get(cat, 0) + 1

    logger.info(f"Written {written} total examples to {output_path}")
    logger.info(f"Negative breakdown: {json.dumps(category_counts, indent=2)}")

    # Stats summary
    print(f"\n{'='*60}")
    print(f"Augmentation complete:")
    print(f"  Negatives generated: {neg_written}")
    print(f"  Output: {output_path}")
    print(f"  Categories:")
    for cat, cnt in sorted(category_counts.items()):
        print(f"    {cat}: {cnt}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()

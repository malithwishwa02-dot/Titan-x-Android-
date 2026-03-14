"""
Titan V11.3 — Scenario Runner
===============================
Batch-executes predefined task scenarios across devices to generate
large-scale training trajectories automatically.

Runs task templates from DeviceAgent.TASK_TEMPLATES with various
parameter combinations, retries failures, and filters results.

Usage via API:
    POST /api/training/scenarios/run
    {
        "device_ids": ["vmos-samsung-s24", "vmos-oneplus-ace3"],
        "templates": ["install_app", "warmup_device", "search_google"],
        "params_sets": [
            {"app_name": "Chase"},
            {"app_name": "PayPal"},
        ],
        "max_steps": 40,
        "retries": 1
    }

    GET /api/training/scenarios/status/{batch_id}
"""

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("titan.scenario-runner")


@dataclass
class ScenarioTask:
    """Single scenario task in a batch."""
    task_id: str = ""
    device_id: str = ""
    template: str = ""
    params: Dict[str, str] = field(default_factory=dict)
    status: str = "pending"  # pending | running | completed | failed
    steps_taken: int = 0
    error: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0


@dataclass
class ScenarioBatch:
    """A batch of scenario tasks."""
    batch_id: str = ""
    status: str = "pending"  # pending | running | completed
    tasks: List[ScenarioTask] = field(default_factory=list)
    created_at: float = 0.0
    completed_at: float = 0.0
    config: Dict[str, Any] = field(default_factory=dict)

    @property
    def completed_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == "completed")

    @property
    def failed_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == "failed")

    @property
    def pending_count(self) -> int:
        return sum(1 for t in self.tasks if t.status in ("pending", "running"))

    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "status": self.status,
            "total": len(self.tasks),
            "completed": self.completed_count,
            "failed": self.failed_count,
            "pending": self.pending_count,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "tasks": [asdict(t) for t in self.tasks],
        }


# ═══════════════════════════════════════════════════════════════════════
# PREDEFINED SCENARIO SETS
# ═══════════════════════════════════════════════════════════════════════

SCENARIO_PRESETS = {
    "play_store_installs": {
        "description": "Install popular apps from Play Store",
        "template": "install_app",
        "params_sets": [
            {"app_name": "Bank of America Mobile Banking"},
            {"app_name": "Chase Mobile"},
            {"app_name": "Wells Fargo Mobile"},
            {"app_name": "PayPal"},
            {"app_name": "Venmo"},
            {"app_name": "Cash App"},
            {"app_name": "Instagram"},
            {"app_name": "WhatsApp"},
            {"app_name": "Uber Eats"},
            {"app_name": "DoorDash"},
        ],
        "max_steps": 25,
    },
    "warmup_browse": {
        "description": "Browse various websites for device aging",
        "template": "search_google",
        "params_sets": [
            {"query": "best restaurants near me"},
            {"query": "weather forecast this week"},
            {"query": "latest iPhone review"},
            {"query": "how to make pasta"},
            {"query": "NBA scores today"},
            {"query": "flight deals to Miami"},
            {"query": "Netflix new releases"},
            {"query": "used cars for sale"},
        ],
        "max_steps": 15,
    },
    "warmup_youtube": {
        "description": "Watch YouTube videos for natural usage patterns",
        "template": "warmup_youtube",
        "params_sets": [
            {"query": "cooking tutorial"},
            {"query": "funny cats"},
            {"query": "tech review 2026"},
            {"query": "workout routine"},
            {"query": "travel vlog"},
        ],
        "max_steps": 20,
    },
    "full_aging": {
        "description": "Complete device aging: install + sign-in + wallet + browse + social + YouTube",
        "mixed": True,
        "tasks": [
            {"template": "install_app", "params": {"app_name": "Instagram"}},
            {"template": "install_app", "params": {"app_name": "WhatsApp"}},
            {"template": "install_app", "params": {"app_name": "PayPal"}},
            {"template": "install_app", "params": {"app_name": "Cash App"}},
            {"template": "google_signin", "params": {"email": "{email}", "password": "{password}"}},
            {"template": "chrome_signin", "params": {"email": "{email}", "password": "{password}"}},
            {"template": "instagram_signin", "params": {"email": "{email}", "password": "{password}"}},
            {"template": "paypal_signin", "params": {"email": "{email}", "password": "{password}"}},
            {"template": "wallet_verify", "params": {"card_last4": "{card_last4}"}},
            {"template": "search_google", "params": {"query": "best coffee shops near me"}},
            {"template": "warmup_device", "params": {}},
            {"template": "warmup_youtube", "params": {"query": "music mix 2026"}},
            {"template": "warmup_maps", "params": {"location": "Times Square NYC"}},
            {"template": "warmup_social", "params": {"app_name": "Instagram"}},
            {"template": "gmail_compose", "params": {"to_email": "test@example.com", "subject": "Hello", "body": "Just checking in!"}},
            {"template": "search_google", "params": {"query": "how to invest money"}},
            {"template": "settings_tweak", "params": {}},
            {"template": "handle_permissions", "params": {}},
        ],
        "max_steps": 25,
    },
    "sign_in_all": {
        "description": "Sign into all major app categories for training data",
        "mixed": True,
        "tasks": [
            {"template": "google_signin", "params": {"email": "{email}", "password": "{password}"}},
            {"template": "chrome_signin", "params": {"email": "{email}", "password": "{password}"}},
            {"template": "instagram_signin", "params": {"email": "{email}", "password": "{password}"}},
            {"template": "facebook_signin", "params": {"email": "{email}", "password": "{password}"}},
            {"template": "tiktok_signin", "params": {"email": "{email}", "password": "{password}"}},
            {"template": "twitter_signin", "params": {"email": "{email}", "password": "{password}"}},
            {"template": "snapchat_signin", "params": {"email": "{email}", "password": "{password}"}},
            {"template": "paypal_signin", "params": {"email": "{email}", "password": "{password}"}},
            {"template": "venmo_signin", "params": {"email": "{email}", "password": "{password}"}},
            {"template": "cashapp_signin", "params": {"email": "{email}"}},
            {"template": "bank_app_signin", "params": {"app_name": "Chase", "email": "{email}", "password": "{password}"}},
            {"template": "amazon_signin", "params": {"email": "{email}", "password": "{password}"}},
            {"template": "crypto_signin", "params": {"app_name": "Coinbase", "email": "{email}", "password": "{password}"}},
        ],
        "max_steps": 30,
    },
    "wallet_setup": {
        "description": "Add payment cards via UI flows and verify wallet",
        "mixed": True,
        "tasks": [
            {"template": "wallet_add_card_ui", "params": {}},
            {"template": "play_store_add_payment", "params": {}},
            {"template": "wallet_verify", "params": {"card_last4": "{card_last4}"}},
        ],
        "max_steps": 30,
    },
    "social_warmup": {
        "description": "Scroll and interact with social media feeds",
        "template": "warmup_social",
        "params_sets": [
            {"app_name": "Instagram"},
            {"app_name": "TikTok"},
            {"app_name": "Facebook"},
            {"app_name": "X (Twitter)"},
            {"app_name": "Snapchat"},
        ],
        "max_steps": 20,
    },
    "maps_explore": {
        "description": "Explore Google Maps with multiple location searches",
        "template": "warmup_maps",
        "params_sets": [
            {"location": "Times Square New York"},
            {"location": "Golden Gate Bridge San Francisco"},
            {"location": "Starbucks near me"},
            {"location": "best pizza downtown"},
            {"location": "nearest gas station"},
        ],
        "max_steps": 20,
    },
    "email_activity": {
        "description": "Compose and send multiple emails via Gmail",
        "template": "gmail_compose",
        "params_sets": [
            {"to_email": "friend@example.com", "subject": "Weekend plans", "body": "Hey! Want to grab lunch this Saturday?"},
            {"to_email": "work@example.com", "subject": "Project update", "body": "Just checking in on the project timeline."},
            {"to_email": "family@example.com", "subject": "Happy birthday!", "body": "Hope you have an amazing day! Talk soon."},
        ],
        "max_steps": 20,
    },
}


class ScenarioRunner:
    """Orchestrates batch scenario execution for training data generation."""

    def __init__(self, device_manager=None):
        self.dm = device_manager
        self._batches: Dict[str, ScenarioBatch] = {}
        self._threads: Dict[str, threading.Thread] = {}

    def create_batch(self, device_ids: List[str],
                     templates: List[str] = None,
                     params_sets: List[Dict] = None,
                     preset: str = "",
                     max_steps: int = 30,
                     retries: int = 0,
                     persona: Dict[str, str] = None) -> ScenarioBatch:
        """Create a batch of scenario tasks."""
        batch_id = f"batch-{uuid.uuid4().hex[:8]}"
        batch = ScenarioBatch(
            batch_id=batch_id,
            created_at=time.time(),
            config={
                "device_ids": device_ids,
                "templates": templates,
                "preset": preset,
                "max_steps": max_steps,
                "retries": retries,
            },
        )

        # Build task list from preset or custom params
        if preset and preset in SCENARIO_PRESETS:
            sp = SCENARIO_PRESETS[preset]
            if sp.get("mixed"):
                for device_id in device_ids:
                    for task_def in sp["tasks"]:
                        batch.tasks.append(ScenarioTask(
                            task_id=f"task-{uuid.uuid4().hex[:8]}",
                            device_id=device_id,
                            template=task_def["template"],
                            params=task_def["params"],
                        ))
            else:
                for device_id in device_ids:
                    for ps in sp.get("params_sets", [{}]):
                        batch.tasks.append(ScenarioTask(
                            task_id=f"task-{uuid.uuid4().hex[:8]}",
                            device_id=device_id,
                            template=sp["template"],
                            params=ps,
                        ))
        elif templates and params_sets:
            for device_id in device_ids:
                for tmpl in templates:
                    for ps in params_sets:
                        batch.tasks.append(ScenarioTask(
                            task_id=f"task-{uuid.uuid4().hex[:8]}",
                            device_id=device_id,
                            template=tmpl,
                            params=ps,
                        ))
        elif templates:
            for device_id in device_ids:
                for tmpl in templates:
                    batch.tasks.append(ScenarioTask(
                        task_id=f"task-{uuid.uuid4().hex[:8]}",
                        device_id=device_id,
                        template=tmpl,
                        params={},
                    ))

        self._batches[batch_id] = batch
        logger.info(f"Batch {batch_id} created: {len(batch.tasks)} tasks across {len(device_ids)} devices")
        return batch

    def run_batch(self, batch_id: str, persona: Dict[str, str] = None) -> bool:
        """Start executing a batch in background thread."""
        batch = self._batches.get(batch_id)
        if not batch:
            return False
        if batch.status == "running":
            return False

        batch.status = "running"
        thread = threading.Thread(
            target=self._execute_batch,
            args=(batch_id, persona or {}),
            daemon=True,
        )
        self._threads[batch_id] = thread
        thread.start()
        return True

    def _execute_batch(self, batch_id: str, persona: Dict[str, str]):
        """Execute all tasks in a batch sequentially per device."""
        batch = self._batches[batch_id]

        # Group tasks by device for sequential execution
        by_device: Dict[str, List[ScenarioTask]] = {}
        for task in batch.tasks:
            by_device.setdefault(task.device_id, []).append(task)

        # Run each device's tasks (could parallelize later)
        for device_id, tasks in by_device.items():
            for task in tasks:
                if batch.status != "running":
                    break
                self._execute_single(task, persona)
                time.sleep(2)  # brief pause between tasks

        batch.status = "completed"
        batch.completed_at = time.time()
        logger.info(f"Batch {batch_id} complete: {batch.completed_count}/{len(batch.tasks)} succeeded")

    def _execute_single(self, task: ScenarioTask, persona: Dict[str, str]):
        """Execute a single scenario task via DeviceAgent."""
        task.status = "running"
        task.started_at = time.time()

        try:
            from device_agent import DeviceAgent, TASK_TEMPLATES

            # Resolve template
            tmpl = TASK_TEMPLATES.get(task.template)
            if not tmpl:
                task.status = "failed"
                task.error = f"Unknown template: {task.template}"
                return

            prompt = tmpl["prompt"].format(**task.params)
            max_steps = self._batches.get("", ScenarioBatch()).config.get("max_steps", 30)

            # Get or create agent for this device
            agent = self._get_agent(task.device_id)
            if not agent:
                task.status = "failed"
                task.error = "Could not create agent for device"
                return

            agent_task_id = agent.start_task(
                prompt=prompt,
                persona=persona,
                max_steps=max_steps,
            )
            task.task_id = agent_task_id

            # Poll for completion
            while True:
                agent_task = agent.get_task(agent_task_id)
                if not agent_task:
                    task.status = "failed"
                    task.error = "Task vanished"
                    break
                if agent_task.status in ("completed", "failed", "stopped"):
                    task.status = "completed" if agent_task.status == "completed" else "failed"
                    task.steps_taken = agent_task.steps_taken
                    task.error = agent_task.error
                    break
                time.sleep(5)

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            logger.warning(f"Scenario task failed: {e}")

        task.completed_at = time.time()

    def _get_agent(self, device_id: str):
        """Create a DeviceAgent for the given device."""
        if not self.dm:
            return None
        dev = self.dm.get_device(device_id)
        if not dev:
            return None

        from device_agent import DeviceAgent
        return DeviceAgent(adb_target=dev.adb_target)

    def get_batch(self, batch_id: str) -> Optional[ScenarioBatch]:
        return self._batches.get(batch_id)

    def list_batches(self) -> List[Dict]:
        return [b.to_dict() for b in self._batches.values()]

    def list_presets(self) -> Dict[str, Any]:
        return {
            k: {"description": v.get("description", ""), "task_count": len(v.get("params_sets", v.get("tasks", [])))}
            for k, v in SCENARIO_PRESETS.items()
        }

"""
Titan V11.3 — KYC Controller
Handles KYC (Know Your Customer) verification flows including
document capture, liveness detection, and identity verification.

Provides minimal implementation for automated KYC bypass workflows.

Usage:
    from kyc_core import KYCController
    ctrl = KYCController(adb_target="127.0.0.1:5555")
    result = ctrl.run_flow(provider="auto", face_image="/path/to/face.jpg")
"""

import base64
import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("titan.kyc-core")


@dataclass
class KYCResult:
    """KYC flow result."""
    success: bool
    provider: str
    steps_completed: List[str]
    steps_failed: List[str]
    session_id: str
    duration_seconds: float
    errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "provider": self.provider,
            "steps_completed": self.steps_completed,
            "steps_failed": self.steps_failed,
            "session_id": self.session_id,
            "duration_seconds": self.duration_seconds,
            "errors": self.errors,
        }


# Known KYC provider detection patterns
KYC_PROVIDERS = {
    "onfido": {
        "package": "com.onfido.android.sdk",
        "detection_strings": ["onfido", "identity verification"],
        "steps": ["document_front", "document_back", "selfie", "liveness"],
    },
    "jumio": {
        "package": "com.jumio.sdk",
        "detection_strings": ["jumio", "netverify"],
        "steps": ["document_front", "document_back", "face_match"],
    },
    "veriff": {
        "package": "com.veriff.sdk",
        "detection_strings": ["veriff", "identity verification"],
        "steps": ["document", "selfie", "liveness_video"],
    },
    "sumsub": {
        "package": "com.sumsub.sns",
        "detection_strings": ["sumsub", "sum&substance"],
        "steps": ["document_front", "document_back", "selfie", "liveness"],
    },
    "stripe_identity": {
        "package": "com.stripe.android.identity",
        "detection_strings": ["stripe identity", "verify your identity"],
        "steps": ["document_front", "document_back", "selfie"],
    },
    "plaid": {
        "package": "com.plaid.link",
        "detection_strings": ["plaid", "verify identity"],
        "steps": ["document_select", "document_capture", "selfie"],
    },
}


class KYCController:
    """KYC verification flow controller."""
    
    def __init__(self, adb_target: Optional[str] = None, data_dir: Optional[str] = None):
        self.adb_target = adb_target
        self.data_dir = Path(data_dir) if data_dir else Path(os.environ.get("TITAN_DATA", "/opt/titan/data"))
        self.assets_dir = self.data_dir / "kyc_assets"
        self.assets_dir.mkdir(parents=True, exist_ok=True)
    
    def _adb_shell(self, cmd: str, timeout: int = 10) -> Tuple[bool, str]:
        """Run ADB shell command."""
        if not self.adb_target:
            return False, "no_adb_target"
        try:
            result = subprocess.run(
                ["adb", "-s", self.adb_target, "shell", cmd],
                capture_output=True, text=True, timeout=timeout
            )
            return result.returncode == 0, result.stdout + result.stderr
        except Exception as e:
            return False, str(e)
    
    def _adb_push(self, local: str, remote: str) -> bool:
        """Push file to device."""
        if not self.adb_target:
            return False
        try:
            result = subprocess.run(
                ["adb", "-s", self.adb_target, "push", local, remote],
                capture_output=True, timeout=30
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def get_available_cameras(self) -> List[Dict[str, Any]]:
        """Get list of available cameras on device."""
        cameras = []
        
        ok, output = self._adb_shell("dumpsys media.camera | grep -E 'Camera.*facing'")
        if ok:
            for line in output.split("\n"):
                if "facing" in line.lower():
                    camera_id = "0" if "back" in line.lower() else "1"
                    facing = "back" if "back" in line.lower() else "front"
                    cameras.append({"id": camera_id, "facing": facing})
        
        # Fallback to standard front/back
        if not cameras:
            cameras = [
                {"id": "0", "facing": "back"},
                {"id": "1", "facing": "front"},
            ]
        
        return cameras
    
    def detect_kyc_provider(self) -> Optional[str]:
        """Detect active KYC provider from screen content."""
        # Get current activity
        ok, output = self._adb_shell("dumpsys activity activities | grep mResumedActivity")
        if not ok:
            return None
        
        output_lower = output.lower()
        
        # Check for known provider packages
        for provider, info in KYC_PROVIDERS.items():
            if info["package"].lower() in output_lower:
                logger.info(f"Detected KYC provider: {provider}")
                return provider
        
        # Check screen content for detection strings
        ok, ui_dump = self._adb_shell("uiautomator dump /dev/tty 2>/dev/null")
        if ok:
            ui_lower = ui_dump.lower()
            for provider, info in KYC_PROVIDERS.items():
                for pattern in info["detection_strings"]:
                    if pattern in ui_lower:
                        logger.info(f"Detected KYC provider from UI: {provider}")
                        return provider
        
        return None
    
    def inject_camera_image(self, image_path: str, camera_id: str = "1") -> bool:
        """
        Inject image into device camera feed.
        
        Note: Requires virtual camera setup (scrcpy camera or similar).
        This is a placeholder for the actual camera injection logic.
        """
        if not os.path.exists(image_path):
            logger.error(f"Image not found: {image_path}")
            return False
        
        # Push image to device
        remote_path = f"/sdcard/DCIM/kyc_inject_{int(time.time())}.jpg"
        if not self._adb_push(image_path, remote_path):
            logger.error("Failed to push image to device")
            return False
        
        logger.info(f"Image pushed to {remote_path}")
        return True
    
    def capture_screen(self) -> Optional[bytes]:
        """Capture current screen."""
        try:
            result = subprocess.run(
                ["adb", "-s", self.adb_target, "exec-out", "screencap", "-p"],
                capture_output=True, timeout=10
            )
            if result.returncode == 0:
                return result.stdout
        except Exception as e:
            logger.error(f"Screen capture failed: {e}")
        return None
    
    def tap_element(self, x: int, y: int) -> bool:
        """Tap screen coordinates."""
        ok, _ = self._adb_shell(f"input tap {x} {y}")
        return ok
    
    def wait_for_element(self, text: str, timeout: int = 30) -> bool:
        """Wait for element with text to appear."""
        start = time.time()
        while time.time() - start < timeout:
            ok, output = self._adb_shell("uiautomator dump /dev/tty 2>/dev/null")
            if ok and text.lower() in output.lower():
                return True
            time.sleep(1)
        return False
    
    def _run_document_step(self, step: str, document_image: Optional[str] = None) -> bool:
        """Execute document capture step."""
        logger.info(f"Running document step: {step}")
        
        # If document image provided, inject it
        if document_image and os.path.exists(document_image):
            self.inject_camera_image(document_image)
        
        # Wait for camera view
        time.sleep(2)
        
        # Tap center (simulate capture button)
        self.tap_element(540, 1800)  # Common capture button location
        
        time.sleep(2)
        return True
    
    def _run_selfie_step(self, face_image: Optional[str] = None) -> bool:
        """Execute selfie capture step."""
        logger.info("Running selfie step")
        
        if face_image and os.path.exists(face_image):
            self.inject_camera_image(face_image, camera_id="1")  # Front camera
        
        time.sleep(2)
        self.tap_element(540, 1800)
        time.sleep(2)
        return True
    
    def _run_liveness_step(self) -> bool:
        """Execute liveness detection step."""
        logger.info("Running liveness step")
        
        # Liveness typically requires head movement - simulate with swipes
        time.sleep(2)
        
        # Look left
        self._adb_shell("input swipe 600 500 400 500 500")
        time.sleep(1)
        
        # Look right
        self._adb_shell("input swipe 400 500 600 500 500")
        time.sleep(1)
        
        # Look up
        self._adb_shell("input swipe 500 600 500 400 500")
        time.sleep(1)
        
        return True
    
    def run_flow(self, provider: str = "auto", face_image: str = "",
                 document_front: str = "", document_back: str = "") -> Dict[str, Any]:
        """
        Run KYC verification flow.
        
        Args:
            provider: KYC provider name or "auto" for detection
            face_image: Path to face/selfie image
            document_front: Path to document front image
            document_back: Path to document back image
            
        Returns:
            KYC result with completion status
        """
        import uuid
        
        start_time = time.time()
        session_id = str(uuid.uuid4())[:8]
        steps_completed = []
        steps_failed = []
        errors = []
        
        logger.info(f"Starting KYC flow - session {session_id}")
        
        # Detect provider
        if provider == "auto":
            detected = self.detect_kyc_provider()
            if detected:
                provider = detected
            else:
                provider = "generic"
                logger.warning("Could not detect KYC provider, using generic flow")
        
        # Get expected steps
        provider_info = KYC_PROVIDERS.get(provider, {})
        expected_steps = provider_info.get("steps", ["document_front", "selfie"])
        
        # Execute steps
        for step in expected_steps:
            try:
                if "document_front" in step:
                    if self._run_document_step(step, document_front):
                        steps_completed.append(step)
                    else:
                        steps_failed.append(step)
                
                elif "document_back" in step:
                    if self._run_document_step(step, document_back):
                        steps_completed.append(step)
                    else:
                        steps_failed.append(step)
                
                elif "selfie" in step or "face" in step:
                    if self._run_selfie_step(face_image):
                        steps_completed.append(step)
                    else:
                        steps_failed.append(step)
                
                elif "liveness" in step:
                    if self._run_liveness_step():
                        steps_completed.append(step)
                    else:
                        steps_failed.append(step)
                
                else:
                    logger.warning(f"Unknown step type: {step}")
                    steps_failed.append(step)
            
            except Exception as e:
                logger.error(f"Step {step} failed: {e}")
                steps_failed.append(step)
                errors.append(f"{step}: {str(e)}")
        
        duration = time.time() - start_time
        success = len(steps_failed) == 0 and len(steps_completed) > 0
        
        result = KYCResult(
            success=success,
            provider=provider,
            steps_completed=steps_completed,
            steps_failed=steps_failed,
            session_id=session_id,
            duration_seconds=round(duration, 2),
            errors=errors,
        )
        
        logger.info(f"KYC flow complete: {'SUCCESS' if success else 'FAILED'} - {len(steps_completed)}/{len(expected_steps)} steps")
        
        return result.to_dict()
    
    def get_provider_info(self, provider: str) -> Dict[str, Any]:
        """Get information about a KYC provider."""
        if provider in KYC_PROVIDERS:
            info = KYC_PROVIDERS[provider]
            return {
                "provider": provider,
                "package": info["package"],
                "expected_steps": info["steps"],
                "supported": True,
            }
        return {"provider": provider, "supported": False}
    
    def list_providers(self) -> List[str]:
        """List supported KYC providers."""
        return list(KYC_PROVIDERS.keys())

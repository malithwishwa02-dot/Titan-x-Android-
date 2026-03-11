"""
Titan V11.3 — CPU Governor
Monitors CPU usage to prevent Hostinger's 180-min throttle policy.
Hostinger triggers 25%/hr CPU reduction after sustained high usage.
"""

import asyncio
import logging
import os
import time

logger = logging.getLogger("titan.cpu-governor")

# Thresholds
CPU_WARN_PERCENT = 75
CPU_CRITICAL_PERCENT = 85
CHECK_INTERVAL = 30  # seconds


class CPUGovernor:
    """Background monitor that tracks CPU usage and provides throttle warnings."""

    def __init__(self):
        self.cpu_history: list = []  # (timestamp, percent)
        self.is_throttled = False
        self._task = None

    async def start(self):
        """Start the background CPU monitoring loop."""
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("CPU governor started")

    async def stop(self):
        if self._task:
            self._task.cancel()

    async def _monitor_loop(self):
        while True:
            try:
                cpu = await self._get_cpu_percent()
                now = time.time()
                self.cpu_history.append((now, cpu))

                # Keep last 60 minutes of history
                cutoff = now - 3600
                self.cpu_history = [(t, c) for t, c in self.cpu_history if t > cutoff]

                # Check 15-min average
                avg_15m = self._avg_last_n_minutes(15)
                if avg_15m > CPU_CRITICAL_PERCENT:
                    logger.warning(f"CPU CRITICAL: 15-min avg={avg_15m:.1f}% — risk of Hostinger throttle")
                    self.is_throttled = True
                elif avg_15m > CPU_WARN_PERCENT:
                    logger.info(f"CPU WARNING: 15-min avg={avg_15m:.1f}%")
                    self.is_throttled = False
                else:
                    self.is_throttled = False

            except Exception as e:
                logger.debug(f"CPU governor error: {e}")

            await asyncio.sleep(CHECK_INTERVAL)

    async def _get_cpu_percent(self) -> float:
        """Read CPU usage from /proc/stat."""
        try:
            with open("/proc/stat") as f:
                line1 = f.readline()
            vals1 = [int(x) for x in line1.split()[1:]]

            await asyncio.sleep(1)

            with open("/proc/stat") as f:
                line2 = f.readline()
            vals2 = [int(x) for x in line2.split()[1:]]

            d_idle = vals2[3] - vals1[3]
            d_total = sum(vals2) - sum(vals1)
            if d_total == 0:
                return 0.0
            return (1 - d_idle / d_total) * 100
        except Exception:
            return 0.0

    def _avg_last_n_minutes(self, minutes: int) -> float:
        cutoff = time.time() - (minutes * 60)
        recent = [c for t, c in self.cpu_history if t > cutoff]
        return sum(recent) / len(recent) if recent else 0.0

    def get_status(self) -> dict:
        return {
            "current": self.cpu_history[-1][1] if self.cpu_history else 0,
            "avg_5m": round(self._avg_last_n_minutes(5), 1),
            "avg_15m": round(self._avg_last_n_minutes(15), 1),
            "avg_60m": round(self._avg_last_n_minutes(60), 1),
            "is_throttled": self.is_throttled,
            "samples": len(self.cpu_history),
        }


# Singleton
cpu_governor = CPUGovernor()

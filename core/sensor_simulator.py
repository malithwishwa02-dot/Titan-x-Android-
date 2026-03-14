"""
Titan V11.3 — Sensor Simulator
OADEV-based noise model for accelerometer, gyroscope, and magnetometer.
Generates realistic IMU readings with bias instability and random walk.

Couples sensor bursts with touch gestures so accelerometer/gyroscope
readings correlate with user interactions (tap → micro-shake,
swipe → wrist rotation).

Usage:
    sim = SensorSimulator(adb_target="127.0.0.1:5555")
    frame = sim.generate_accelerometer_frame()
    sim.couple_with_gesture("tap", magnitude=0.3)
    sim.inject_sensor_burst("accelerometer", duration_ms=200)
"""

import logging
import math
import os
import random
import subprocess
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("titan.sensor-simulator")

# ═══════════════════════════════════════════════════════════════════════
# OADEV NOISE PROFILES (real MEMS sensor specifications)
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class SensorNoiseProfile:
    """Allan deviation-based noise parameters for a MEMS sensor axis."""
    bias_instability: float   # Long-term drift (mg for accel, °/s for gyro)
    random_walk: float        # White noise integration (mg/√Hz or °/s/√Hz)
    quantization: float       # ADC quantization noise floor


# Real device profiles — values from datasheets (Bosch, InvenSense, STMicro)
SENSOR_PROFILES = {
    "samsung": {
        "accelerometer": SensorNoiseProfile(
            bias_instability=0.04,   # LSM6DSO: 40 µg
            random_walk=0.12,        # 120 µg/√Hz
            quantization=0.061,      # 16-bit @ ±4g
        ),
        "gyroscope": SensorNoiseProfile(
            bias_instability=0.8,    # 0.8 °/s
            random_walk=0.004,       # 4 m°/s/√Hz
            quantization=0.0038,     # 16-bit @ ±125°/s
        ),
        "magnetometer": SensorNoiseProfile(
            bias_instability=0.3,    # 300 nT → 0.3 µT
            random_walk=0.15,
            quantization=0.1,
        ),
    },
    "google": {
        "accelerometer": SensorNoiseProfile(
            bias_instability=0.05,
            random_walk=0.15,
            quantization=0.061,
        ),
        "gyroscope": SensorNoiseProfile(
            bias_instability=1.0,
            random_walk=0.005,
            quantization=0.004,
        ),
        "magnetometer": SensorNoiseProfile(
            bias_instability=0.25,
            random_walk=0.12,
            quantization=0.1,
        ),
    },
    "default": {
        "accelerometer": SensorNoiseProfile(
            bias_instability=0.06,
            random_walk=0.18,
            quantization=0.07,
        ),
        "gyroscope": SensorNoiseProfile(
            bias_instability=1.2,
            random_walk=0.006,
            quantization=0.005,
        ),
        "magnetometer": SensorNoiseProfile(
            bias_instability=0.35,
            random_walk=0.18,
            quantization=0.12,
        ),
    },
}

# Earth gravity constant
EARTH_G = 9.80665

# Gesture coupling profiles: (accel_magnitude_g, gyro_magnitude_dps, duration_ms)
GESTURE_COUPLING = {
    "tap":       {"accel_peak": 0.08, "gyro_peak": 0.5,  "duration_ms": 120, "decay": 0.85},
    "double_tap": {"accel_peak": 0.12, "gyro_peak": 0.8,  "duration_ms": 200, "decay": 0.80},
    "swipe":     {"accel_peak": 0.15, "gyro_peak": 2.0,  "duration_ms": 350, "decay": 0.75},
    "scroll":    {"accel_peak": 0.05, "gyro_peak": 0.3,  "duration_ms": 500, "decay": 0.90},
    "long_press": {"accel_peak": 0.02, "gyro_peak": 0.1,  "duration_ms": 800, "decay": 0.95},
    "type":      {"accel_peak": 0.03, "gyro_peak": 0.2,  "duration_ms": 80,  "decay": 0.88},
}


class SensorNoiseModel:
    """Generates realistic sensor noise using OADEV parameters.

    Models three noise components:
    1. Bias instability — slow 1/f drift (Markov process)
    2. Velocity/angle random walk — white noise integration
    3. Quantization noise — ADC floor
    """

    def __init__(self, profile: SensorNoiseProfile):
        self.profile = profile
        self._bias_state = 0.0    # Current bias drift state
        self._rw_state = 0.0      # Random walk accumulator
        self._last_time = time.time()

    def sample(self) -> float:
        """Generate one noise sample incorporating all three components."""
        now = time.time()
        dt = max(now - self._last_time, 0.001)
        self._last_time = now

        # 1. Bias instability: first-order Gauss-Markov process
        # τ ≈ 100s correlation time for typical MEMS
        tau = 100.0
        alpha = math.exp(-dt / tau)
        self._bias_state = (alpha * self._bias_state +
                            (1 - alpha) * random.gauss(0, self.profile.bias_instability))

        # 2. Random walk: integrated white noise
        self._rw_state += random.gauss(0, self.profile.random_walk * math.sqrt(dt))
        # Clamp random walk to prevent unbounded drift
        rw_limit = self.profile.random_walk * 10
        self._rw_state = max(-rw_limit, min(rw_limit, self._rw_state))

        # 3. Quantization noise
        quant_noise = random.uniform(-0.5, 0.5) * self.profile.quantization

        return self._bias_state + self._rw_state + quant_noise

    def reset(self):
        """Reset noise state (e.g. on device reboot simulation)."""
        self._bias_state = 0.0
        self._rw_state = 0.0
        self._last_time = time.time()


class SensorSimulator:
    """Full sensor simulation for a Cuttlefish Android VM.

    Creates three-axis noise models for accelerometer, gyroscope,
    and magnetometer, with gesture coupling for correlated readings.
    """

    def __init__(self, adb_target: str = "127.0.0.1:5555",
                 brand: str = "samsung"):
        self.target = adb_target
        self.brand = brand.lower()
        profiles = SENSOR_PROFILES.get(self.brand, SENSOR_PROFILES["default"])

        # Three-axis noise models
        self._accel = [SensorNoiseModel(profiles["accelerometer"]) for _ in range(3)]
        self._gyro = [SensorNoiseModel(profiles["gyroscope"]) for _ in range(3)]
        self._mag = [SensorNoiseModel(profiles["magnetometer"]) for _ in range(3)]

        # Gesture coupling state
        self._gesture_impulse = [0.0, 0.0, 0.0]  # [x, y, z] impulse
        self._gesture_decay = 0.0
        self._gesture_start = 0.0

    def _sh(self, cmd: str, timeout: int = 10) -> Tuple[bool, str]:
        try:
            r = subprocess.run(
                ["adb", "-s", self.target, "shell", cmd],
                capture_output=True, text=True, timeout=timeout,
            )
            return r.returncode == 0, r.stdout.strip()
        except Exception as e:
            return False, str(e)

    # ─── FRAME GENERATORS ─────────────────────────────────────────────

    def generate_accelerometer_frame(self) -> List[float]:
        """Generate a realistic [x, y, z] accelerometer reading in m/s².

        At rest, a phone lying face-up reads approximately [0, 0, 9.81].
        Small perturbations from hand holding add ~0.02-0.1g noise.
        """
        # Base: phone held upright with slight tilt
        base_x = random.gauss(0.15, 0.05)   # Slight lateral tilt
        base_y = random.gauss(0.3, 0.1)     # Forward tilt from holding
        base_z = EARTH_G                      # Gravity axis

        # Add OADEV noise
        noise = [m.sample() * EARTH_G / 1000.0 for m in self._accel]  # mg → m/s²

        # Add gesture coupling if active
        gesture = self._get_gesture_contribution()

        return [
            base_x + noise[0] + gesture[0],
            base_y + noise[1] + gesture[1],
            base_z + noise[2] + gesture[2],
        ]

    def generate_gyroscope_frame(self) -> List[float]:
        """Generate a realistic [x, y, z] gyroscope reading in rad/s.

        At rest: near-zero with MEMS drift noise.
        During gestures: correlated rotation from wrist movement.
        """
        noise = [m.sample() * math.pi / 180.0 for m in self._gyro]  # °/s → rad/s
        gesture = self._get_gesture_contribution()
        # Gyro gesture coupling is rotational
        gyro_scale = 0.3  # Gesture → rotation coupling factor
        return [
            noise[0] + gesture[1] * gyro_scale,  # Cross-coupled
            noise[1] + gesture[0] * gyro_scale,
            noise[2] + gesture[2] * gyro_scale * 0.1,
        ]

    def generate_magnetometer_frame(self) -> List[float]:
        """Generate a realistic [x, y, z] magnetometer reading in µT.

        Earth's field: ~25-65 µT total magnitude depending on location.
        """
        # Typical indoor values (partially shielded by building)
        base_x = random.gauss(20.0, 2.0)
        base_y = random.gauss(-5.0, 1.5)
        base_z = random.gauss(-40.0, 3.0)

        noise = [m.sample() for m in self._mag]

        return [base_x + noise[0], base_y + noise[1], base_z + noise[2]]

    # ─── GESTURE COUPLING ─────────────────────────────────────────────

    def couple_with_gesture(self, gesture_type: str, magnitude: float = 1.0):
        """Inject a correlated sensor burst for a touch gesture.

        Args:
            gesture_type: One of "tap", "swipe", "scroll", "long_press", "type"
            magnitude: Scale factor (0.5 = gentle, 1.5 = aggressive)
        """
        params = GESTURE_COUPLING.get(gesture_type, GESTURE_COUPLING["tap"])
        peak = params["accel_peak"] * magnitude

        # Random impulse direction (primarily Z for taps, X/Y for swipes)
        if gesture_type in ("tap", "double_tap", "long_press", "type"):
            self._gesture_impulse = [
                random.gauss(0, peak * 0.3),
                random.gauss(0, peak * 0.3),
                random.gauss(-peak, peak * 0.2),  # Mostly -Z (push into screen)
            ]
        else:  # swipe, scroll
            self._gesture_impulse = [
                random.gauss(peak * 0.7, peak * 0.2),
                random.gauss(peak * 0.3, peak * 0.1),
                random.gauss(0, peak * 0.1),
            ]

        self._gesture_decay = params["decay"]
        self._gesture_start = time.time()
        self._gesture_duration = params["duration_ms"] / 1000.0

    def _get_gesture_contribution(self) -> List[float]:
        """Get current gesture impulse contribution (decaying over time)."""
        if self._gesture_start == 0:
            return [0.0, 0.0, 0.0]

        elapsed = time.time() - self._gesture_start
        if elapsed > self._gesture_duration:
            self._gesture_start = 0
            return [0.0, 0.0, 0.0]

        # Exponential decay
        progress = elapsed / self._gesture_duration
        decay = self._gesture_decay ** (progress * 10)
        return [imp * decay for imp in self._gesture_impulse]

    # ─── DEVICE INJECTION ─────────────────────────────────────────────

    def inject_sensor_burst(self, sensor_type: str = "accelerometer",
                            duration_ms: int = 200, sample_rate_hz: int = 50):
        """Inject a burst of sensor readings into device via setprop.

        Writes sensor frames to persist props that a companion Android
        service can read and feed to SensorManager.
        """
        num_samples = max(1, (duration_ms * sample_rate_hz) // 1000)
        interval = 1.0 / sample_rate_hz

        generators = {
            "accelerometer": self.generate_accelerometer_frame,
            "gyroscope": self.generate_gyroscope_frame,
            "magnetometer": self.generate_magnetometer_frame,
        }
        gen = generators.get(sensor_type, self.generate_accelerometer_frame)

        # Batch sensor data into a single prop write for efficiency
        frames = []
        for _ in range(num_samples):
            frame = gen()
            frames.append(f"{frame[0]:.6f},{frame[1]:.6f},{frame[2]:.6f}")
            time.sleep(interval)

        # Write latest frame to prop (Android service polls this)
        if frames:
            latest = frames[-1]
            self._sh(
                f"setprop persist.titan.sensor.{sensor_type}.data '{latest}'; "
                f"setprop persist.titan.sensor.{sensor_type}.ts '{int(time.time() * 1000)}'"
            )
            logger.debug(f"Sensor burst: {sensor_type} {num_samples} samples, last={latest}")

    # ─── GPS-IMU SENSOR FUSION SYNCHRONIZATION ───────────────────────

    def synchronize_gps_imu(self, lat: float, lon: float,
                             prev_lat: float = 0.0, prev_lon: float = 0.0,
                             dt_seconds: float = 1.0):
        """Synchronize IMU sensor data with GPS position changes.

        Modern RASP and anti-spoofing systems use Extended Kalman Filters (EKF)
        to cross-validate GNSS data against IMU readings. If the GPS coordinates
        change while the accelerometer/gyroscope report zero movement, the
        sensor fusion algorithm instantly detects the anomaly.

        This method calculates the required velocity and directional vectors
        from GPS displacement and translates them into corresponding
        acceleration and angular velocity data, satisfying EKF consistency.

        Args:
            lat, lon: Current GPS coordinates
            prev_lat, prev_lon: Previous GPS coordinates (0 = stationary)
            dt_seconds: Time delta between position updates
        """
        if prev_lat == 0.0 and prev_lon == 0.0:
            # Stationary — just inject idle noise (hand micro-tremor)
            self._inject_stationary_imu()
            return

        # Calculate displacement in meters (Haversine approximation for short distances)
        dlat = (lat - prev_lat) * 111320.0  # ~111.32 km per degree latitude
        dlon = (lon - prev_lon) * 111320.0 * math.cos(math.radians(lat))
        distance_m = math.sqrt(dlat**2 + dlon**2)

        if distance_m < 0.5:
            # Sub-meter movement — treat as stationary with micro-drift
            self._inject_stationary_imu()
            return

        # Calculate velocity and bearing
        velocity_ms = distance_m / max(dt_seconds, 0.1)
        bearing_rad = math.atan2(dlon, dlat)

        # Decompose acceleration into device-frame axes
        # Assume phone held upright: X=lateral, Y=forward, Z=gravity
        accel_forward = velocity_ms / max(dt_seconds, 0.1)  # dv/dt
        # Clamp to realistic range (walking ~1.5 m/s², driving ~3 m/s²)
        accel_forward = max(-5.0, min(5.0, accel_forward))

        # Add realistic noise on top of the kinematic signal
        accel_x = accel_forward * math.sin(bearing_rad) + random.gauss(0, 0.05)
        accel_y = accel_forward * math.cos(bearing_rad) + random.gauss(0, 0.05)
        accel_z = EARTH_G + random.gauss(0, 0.02)  # Gravity + noise

        # Gyroscope: angular velocity from bearing change
        # If bearing changes, there's a corresponding yaw rotation
        gyro_yaw = random.gauss(0, 0.01)  # Base noise
        if velocity_ms > 0.5:
            # Walking/driving induces periodic body sway
            sway_freq = 1.8 if velocity_ms < 2.0 else 0.5  # Walking vs driving
            t = time.time()
            gyro_x = 0.02 * math.sin(2 * math.pi * sway_freq * t) + random.gauss(0, 0.005)
            gyro_y = 0.01 * math.sin(2 * math.pi * sway_freq * t + 1.2) + random.gauss(0, 0.005)
        else:
            gyro_x = random.gauss(0, 0.005)
            gyro_y = random.gauss(0, 0.005)

        # Inject synchronized IMU data
        accel_str = f"{accel_x:.6f},{accel_y:.6f},{accel_z:.6f}"
        gyro_str = f"{gyro_x:.6f},{gyro_y:.6f},{gyro_yaw:.6f}"

        self._sh(
            f"setprop persist.titan.sensor.accelerometer.data '{accel_str}'; "
            f"setprop persist.titan.sensor.accelerometer.ts '{int(time.time() * 1000)}'; "
            f"setprop persist.titan.sensor.gyroscope.data '{gyro_str}'; "
            f"setprop persist.titan.sensor.gyroscope.ts '{int(time.time() * 1000)}'"
        )

        logger.debug(f"GPS-IMU sync: dist={distance_m:.1f}m, v={velocity_ms:.2f}m/s, "
                      f"accel=[{accel_x:.3f},{accel_y:.3f},{accel_z:.3f}]")

    def _inject_stationary_imu(self):
        """Inject realistic stationary IMU data (hand micro-tremor + OADEV noise)."""
        accel = self.generate_accelerometer_frame()
        gyro = self.generate_gyroscope_frame()
        accel_str = f"{accel[0]:.6f},{accel[1]:.6f},{accel[2]:.6f}"
        gyro_str = f"{gyro[0]:.6f},{gyro[1]:.6f},{gyro[2]:.6f}"
        self._sh(
            f"setprop persist.titan.sensor.accelerometer.data '{accel_str}'; "
            f"setprop persist.titan.sensor.accelerometer.ts '{int(time.time() * 1000)}'; "
            f"setprop persist.titan.sensor.gyroscope.data '{gyro_str}'; "
            f"setprop persist.titan.sensor.gyroscope.ts '{int(time.time() * 1000)}'"
        )

    # ─── BACKGROUND NOISE ─────────────────────────────────────────────

    def start_background_noise(self, duration_s: float = 0.0):
        """Set initial background sensor readings on the device.

        If duration_s=0, just sets one batch of current readings.
        """
        for sensor, gen in [
            ("accelerometer", self.generate_accelerometer_frame),
            ("gyroscope", self.generate_gyroscope_frame),
            ("magnetometer", self.generate_magnetometer_frame),
        ]:
            frame = gen()
            data_str = f"{frame[0]:.6f},{frame[1]:.6f},{frame[2]:.6f}"
            self._sh(
                f"setprop persist.titan.sensor.{sensor}.data '{data_str}'; "
                f"setprop persist.titan.sensor.{sensor}.ts '{int(time.time() * 1000)}'"
            )
        logger.info("Background sensor noise initialized")


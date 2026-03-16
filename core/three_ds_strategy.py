"""
Titan V11.3 — 3DS Strategy Engine
Provides intelligent recommendations for handling 3D Secure challenges
based on BIN, merchant, amount, and historical success patterns.

Maps BIN ranges to expected 3DS behavior and suggests optimal approaches.

Usage:
    from three_ds_strategy import ThreeDSStrategy
    strategy = ThreeDSStrategy()
    result = strategy.get_recommendations(bin_prefix="453201", merchant="amazon.com", amount=150.00)
"""

import json
import logging
import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("titan.3ds-strategy")


@dataclass
class ThreeDSRecommendation:
    """3DS handling recommendation."""
    bin_prefix: str
    merchant: str
    amount: float
    expected_challenge: str  # frictionless, challenge, exemption, decline
    confidence: float
    risk_score: int  # 0-100
    recommendations: List[str]
    timing_advice: str
    fallback_strategies: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "bin_prefix": self.bin_prefix,
            "merchant": self.merchant,
            "amount": self.amount,
            "expected_challenge": self.expected_challenge,
            "confidence": self.confidence,
            "risk_score": self.risk_score,
            "recommendations": self.recommendations,
            "timing_advice": self.timing_advice,
            "fallback_strategies": self.fallback_strategies,
        }


# BIN-based 3DS behavior patterns (based on issuer tendencies)
BIN_3DS_PATTERNS = {
    # Chase - Generally strict, high challenge rate
    "4532": {"issuer": "Chase", "challenge_rate": 0.7, "frictionless_rate": 0.2, "exemption_support": True},
    "4147": {"issuer": "Chase", "challenge_rate": 0.6, "frictionless_rate": 0.3, "exemption_support": True},
    
    # Capital One - Moderate, uses risk-based auth
    "4024": {"issuer": "Capital One", "challenge_rate": 0.4, "frictionless_rate": 0.5, "exemption_support": True},
    "4275": {"issuer": "Capital One", "challenge_rate": 0.4, "frictionless_rate": 0.5, "exemption_support": True},
    
    # Bank of America - High challenge rate
    "4000": {"issuer": "Bank of America", "challenge_rate": 0.65, "frictionless_rate": 0.25, "exemption_support": True},
    "4217": {"issuer": "Bank of America", "challenge_rate": 0.6, "frictionless_rate": 0.3, "exemption_support": True},
    
    # Citi - Moderate with good exemption handling
    "4462": {"issuer": "Citibank", "challenge_rate": 0.5, "frictionless_rate": 0.35, "exemption_support": True},
    "4532": {"issuer": "Citibank", "challenge_rate": 0.5, "frictionless_rate": 0.4, "exemption_support": True},
    
    # Wells Fargo - Strict
    "4761": {"issuer": "Wells Fargo", "challenge_rate": 0.7, "frictionless_rate": 0.2, "exemption_support": False},
    "4852": {"issuer": "Wells Fargo", "challenge_rate": 0.65, "frictionless_rate": 0.25, "exemption_support": False},
    
    # Mastercard issuers
    "5100": {"issuer": "Citi MC", "challenge_rate": 0.5, "frictionless_rate": 0.4, "exemption_support": True},
    "5200": {"issuer": "BofA MC", "challenge_rate": 0.6, "frictionless_rate": 0.3, "exemption_support": True},
    "5400": {"issuer": "Chase MC", "challenge_rate": 0.65, "frictionless_rate": 0.25, "exemption_support": True},
    "5500": {"issuer": "HSBC MC", "challenge_rate": 0.55, "frictionless_rate": 0.35, "exemption_support": True},
    
    # Amex - Generally lenient for good standing
    "3400": {"issuer": "Amex", "challenge_rate": 0.3, "frictionless_rate": 0.6, "exemption_support": True},
    "3700": {"issuer": "Amex", "challenge_rate": 0.35, "frictionless_rate": 0.55, "exemption_support": True},
    
    # Discover - Moderate
    "6011": {"issuer": "Discover", "challenge_rate": 0.45, "frictionless_rate": 0.45, "exemption_support": True},
    "6500": {"issuer": "Discover", "challenge_rate": 0.4, "frictionless_rate": 0.5, "exemption_support": True},
    
    # Prepaid/Virtual - High scrutiny
    "4040": {"issuer": "Privacy.com", "challenge_rate": 0.8, "frictionless_rate": 0.1, "exemption_support": False},
    "5319": {"issuer": "Cash App", "challenge_rate": 0.75, "frictionless_rate": 0.15, "exemption_support": False},
}

# Merchant 3DS implementation patterns
MERCHANT_PATTERNS = {
    # E-commerce giants - Sophisticated 3DS
    "amazon.com": {"3ds_version": "2.2", "exemption_usage": "high", "challenge_rate": 0.15, "tra_enabled": True},
    "amazon.co.uk": {"3ds_version": "2.2", "exemption_usage": "high", "challenge_rate": 0.2, "tra_enabled": True},
    "walmart.com": {"3ds_version": "2.1", "exemption_usage": "medium", "challenge_rate": 0.25, "tra_enabled": True},
    "target.com": {"3ds_version": "2.1", "exemption_usage": "medium", "challenge_rate": 0.3, "tra_enabled": True},
    "bestbuy.com": {"3ds_version": "2.1", "exemption_usage": "medium", "challenge_rate": 0.35, "tra_enabled": True},
    
    # Payment platforms
    "paypal.com": {"3ds_version": "2.2", "exemption_usage": "high", "challenge_rate": 0.2, "tra_enabled": True},
    "stripe.com": {"3ds_version": "2.2", "exemption_usage": "high", "challenge_rate": 0.15, "tra_enabled": True},
    
    # Subscriptions - Often exempt small amounts
    "netflix.com": {"3ds_version": "2.1", "exemption_usage": "high", "challenge_rate": 0.1, "tra_enabled": True},
    "spotify.com": {"3ds_version": "2.1", "exemption_usage": "high", "challenge_rate": 0.1, "tra_enabled": True},
    "apple.com": {"3ds_version": "2.2", "exemption_usage": "medium", "challenge_rate": 0.2, "tra_enabled": True},
    
    # Travel - High scrutiny
    "booking.com": {"3ds_version": "2.1", "exemption_usage": "low", "challenge_rate": 0.6, "tra_enabled": False},
    "expedia.com": {"3ds_version": "2.1", "exemption_usage": "low", "challenge_rate": 0.55, "tra_enabled": False},
    "airbnb.com": {"3ds_version": "2.2", "exemption_usage": "medium", "challenge_rate": 0.4, "tra_enabled": True},
    
    # Gaming/Digital - Mixed
    "steam.com": {"3ds_version": "2.1", "exemption_usage": "medium", "challenge_rate": 0.3, "tra_enabled": True},
    "playstation.com": {"3ds_version": "2.1", "exemption_usage": "medium", "challenge_rate": 0.35, "tra_enabled": True},
}

# Amount thresholds (EUR equivalent)
EXEMPTION_THRESHOLDS = {
    "low_value": 30.0,  # Low Value Exemption (LVE) - under €30
    "tra_low": 100.0,   # TRA low risk - under €100
    "tra_medium": 250.0,  # TRA medium - under €250
    "tra_high": 500.0,  # TRA high - under €500
}


class ThreeDSStrategy:
    """3DS strategy recommendation engine."""
    
    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = Path(data_dir) if data_dir else Path(os.environ.get("TITAN_DATA", "/opt/titan/data"))
        self._load_custom_patterns()
    
    def _load_custom_patterns(self):
        """Load custom patterns from data directory."""
        patterns_file = self.data_dir / "3ds_patterns.json"
        if patterns_file.exists():
            try:
                with open(patterns_file) as f:
                    custom = json.load(f)
                BIN_3DS_PATTERNS.update(custom.get("bins", {}))
                MERCHANT_PATTERNS.update(custom.get("merchants", {}))
                logger.info(f"Loaded custom 3DS patterns from {patterns_file}")
            except Exception as e:
                logger.warning(f"Failed to load custom 3DS patterns: {e}")
    
    def _get_bin_pattern(self, bin_prefix: str) -> Dict[str, Any]:
        """Get BIN pattern, trying decreasing prefix lengths."""
        for length in [6, 4]:
            prefix = bin_prefix[:length]
            if prefix in BIN_3DS_PATTERNS:
                return BIN_3DS_PATTERNS[prefix]
        # Default pattern for unknown BINs
        return {
            "issuer": "Unknown",
            "challenge_rate": 0.5,
            "frictionless_rate": 0.35,
            "exemption_support": True,
        }
    
    def _get_merchant_pattern(self, merchant: str) -> Dict[str, Any]:
        """Get merchant pattern."""
        # Normalize merchant domain
        merchant_clean = merchant.lower().replace("www.", "")
        
        if merchant_clean in MERCHANT_PATTERNS:
            return MERCHANT_PATTERNS[merchant_clean]
        
        # Check partial matches
        for pattern, data in MERCHANT_PATTERNS.items():
            if pattern in merchant_clean or merchant_clean in pattern:
                return data
        
        # Default pattern
        return {
            "3ds_version": "2.1",
            "exemption_usage": "medium",
            "challenge_rate": 0.4,
            "tra_enabled": True,
        }
    
    def _calculate_expected_outcome(self, bin_pattern: Dict, merchant_pattern: Dict,
                                    amount: float) -> Tuple[str, float]:
        """Calculate expected 3DS outcome."""
        # Combined challenge probability
        bin_challenge = bin_pattern["challenge_rate"]
        merchant_challenge = merchant_pattern["challenge_rate"]
        
        # Weight merchant more heavily (they control the request)
        combined_challenge = merchant_challenge * 0.6 + bin_challenge * 0.4
        
        # Adjust for amount
        if amount < EXEMPTION_THRESHOLDS["low_value"]:
            combined_challenge *= 0.3  # Very likely exempt
        elif amount < EXEMPTION_THRESHOLDS["tra_low"]:
            combined_challenge *= 0.6
        elif amount < EXEMPTION_THRESHOLDS["tra_medium"]:
            combined_challenge *= 0.8
        elif amount > EXEMPTION_THRESHOLDS["tra_high"]:
            combined_challenge *= 1.2
        
        # Clamp
        combined_challenge = min(0.95, max(0.05, combined_challenge))
        
        # Determine expected outcome
        if combined_challenge < 0.2:
            return "frictionless", 1.0 - combined_challenge
        elif combined_challenge < 0.5:
            return "frictionless", 0.6
        elif combined_challenge < 0.7:
            return "challenge", 0.7
        else:
            return "challenge", 0.8
    
    def _generate_recommendations(self, bin_pattern: Dict, merchant_pattern: Dict,
                                  amount: float, expected: str) -> List[str]:
        """Generate specific recommendations."""
        recs = []
        
        # Timing
        recs.append("Execute during business hours (9AM-5PM local) for best success rates")
        
        # Amount-based
        if amount < EXEMPTION_THRESHOLDS["low_value"]:
            recs.append(f"Amount ${amount:.2f} qualifies for Low Value Exemption (LVE)")
        elif amount < EXEMPTION_THRESHOLDS["tra_low"] and merchant_pattern.get("tra_enabled"):
            recs.append("Amount qualifies for TRA (Transaction Risk Analysis) exemption")
        
        # BIN-specific
        if bin_pattern.get("challenge_rate", 0.5) > 0.6:
            recs.append(f"High-scrutiny issuer ({bin_pattern.get('issuer', 'Unknown')}) - expect OTP challenge")
        
        # Merchant-specific
        if merchant_pattern.get("exemption_usage") == "high":
            recs.append("Merchant frequently uses exemptions - likely frictionless")
        elif merchant_pattern.get("exemption_usage") == "low":
            recs.append("Merchant rarely exempts - prepare for full authentication")
        
        # 3DS version
        if merchant_pattern.get("3ds_version") == "2.2":
            recs.append("Merchant uses 3DS 2.2 - supports biometric/app-based auth")
        
        return recs
    
    def _generate_fallbacks(self, expected: str, bin_pattern: Dict) -> List[str]:
        """Generate fallback strategies."""
        fallbacks = []
        
        if expected == "challenge":
            fallbacks.append("If OTP fails, request resend after 30 seconds")
            fallbacks.append("Consider splitting into smaller transactions")
            if bin_pattern.get("exemption_support"):
                fallbacks.append("Try different merchant that uses more exemptions")
        
        fallbacks.append("If hard decline, wait 24 hours before retry")
        fallbacks.append("Ensure device fingerprint matches card billing address region")
        
        return fallbacks
    
    def get_recommendations(self, bin_prefix: str, merchant_domain: str = "",
                           amount: float = 0.0) -> Dict[str, Any]:
        """
        Get 3DS handling recommendations.
        
        Args:
            bin_prefix: First 6 digits of card number
            merchant_domain: Target merchant domain
            amount: Transaction amount in USD
            
        Returns:
            Recommendation with expected outcome and strategies
        """
        bin_prefix = bin_prefix.replace(" ", "").replace("-", "")[:6]
        
        bin_pattern = self._get_bin_pattern(bin_prefix)
        merchant_pattern = self._get_merchant_pattern(merchant_domain)
        
        expected, confidence = self._calculate_expected_outcome(
            bin_pattern, merchant_pattern, amount
        )
        
        # Risk score (higher = more likely to be challenged)
        risk_score = int(bin_pattern["challenge_rate"] * 50 + 
                        merchant_pattern["challenge_rate"] * 30 +
                        min(amount / 20, 20))
        
        recommendations = self._generate_recommendations(
            bin_pattern, merchant_pattern, amount, expected
        )
        fallbacks = self._generate_fallbacks(expected, bin_pattern)
        
        # Timing advice
        if expected == "frictionless":
            timing = "Any time - transaction likely exempt from challenge"
        else:
            timing = "Weekday 10AM-3PM local time for fastest OTP delivery"
        
        result = ThreeDSRecommendation(
            bin_prefix=bin_prefix,
            merchant=merchant_domain,
            amount=amount,
            expected_challenge=expected,
            confidence=confidence,
            risk_score=risk_score,
            recommendations=recommendations,
            timing_advice=timing,
            fallback_strategies=fallbacks,
        )
        
        logger.info(f"3DS strategy for BIN {bin_prefix[:4]}** @ {merchant_domain}: {expected} (conf={confidence:.2f})")
        
        return result.to_dict()
    
    def analyze_batch(self, cards: List[Dict[str, Any]], merchant: str) -> List[Dict[str, Any]]:
        """Analyze multiple cards for a merchant."""
        results = []
        for card in cards:
            bin_prefix = card.get("bin", card.get("number", "")[:6])
            amount = card.get("amount", 100.0)
            result = self.get_recommendations(bin_prefix, merchant, amount)
            result["card_ref"] = card.get("ref", bin_prefix)
            results.append(result)
        return results

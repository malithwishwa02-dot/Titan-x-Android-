"""
Titan V11.3 — BIN Database
Provides BIN (Bank Identification Number) lookup for card validation,
issuer detection, and network identification.

Contains static BIN data for common issuers plus dynamic lookup support.

Usage:
    from bin_database import BINDatabase
    db = BINDatabase.get()
    info = db.lookup("453201")
    print(info.bank, info.network, info.country)
"""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("titan.bin-database")


@dataclass
class BINRecord:
    """BIN lookup result."""
    bin: str
    network: str  # visa, mastercard, amex, discover
    bank: str
    country: str
    country_code: str
    card_type: str  # credit, debit, prepaid
    card_level: str  # classic, gold, platinum, business, corporate
    is_prepaid: bool = False
    is_commercial: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "bin": self.bin,
            "network": self.network,
            "bank": self.bank,
            "country": self.country,
            "country_code": self.country_code,
            "card_type": self.card_type,
            "card_level": self.card_level,
            "is_prepaid": self.is_prepaid,
            "is_commercial": self.is_commercial,
        }


# Static BIN database - common US/EU issuers
STATIC_BIN_DATA: Dict[str, Dict[str, Any]] = {
    # Visa - Major US Banks
    "453201": {"network": "visa", "bank": "Chase", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "platinum"},
    "453265": {"network": "visa", "bank": "Chase", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "sapphire"},
    "414720": {"network": "visa", "bank": "Chase", "country": "United States", "country_code": "US", "card_type": "debit", "card_level": "classic"},
    "491653": {"network": "visa", "bank": "US Bank", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "platinum"},
    "402400": {"network": "visa", "bank": "Capital One", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "venture"},
    "427533": {"network": "visa", "bank": "Capital One", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "quicksilver"},
    "400011": {"network": "visa", "bank": "Bank of America", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "classic"},
    "421783": {"network": "visa", "bank": "Bank of America", "country": "United States", "country_code": "US", "card_type": "debit", "card_level": "classic"},
    "446291": {"network": "visa", "bank": "Citibank", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "gold"},
    "453275": {"network": "visa", "bank": "Citibank", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "costco"},
    "476173": {"network": "visa", "bank": "Wells Fargo", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "platinum"},
    "485246": {"network": "visa", "bank": "Wells Fargo", "country": "United States", "country_code": "US", "card_type": "debit", "card_level": "classic"},
    "459825": {"network": "visa", "bank": "American Express (Visa)", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "platinum"},
    "411111": {"network": "visa", "bank": "Test Bank", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "classic"},
    "400000": {"network": "visa", "bank": "Visa Inc.", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "classic"},
    "455600": {"network": "visa", "bank": "Stripe Test", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "classic"},
    
    # Mastercard - Major US Banks
    "510000": {"network": "mastercard", "bank": "Citibank", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "classic"},
    "512345": {"network": "mastercard", "bank": "Capital One", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "classic"},
    "520000": {"network": "mastercard", "bank": "Bank of America", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "classic"},
    "525412": {"network": "mastercard", "bank": "HSBC", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "gold"},
    "530000": {"network": "mastercard", "bank": "US Bank", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "classic"},
    "540000": {"network": "mastercard", "bank": "Chase", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "world"},
    "545454": {"network": "mastercard", "bank": "Barclays", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "classic"},
    "550000": {"network": "mastercard", "bank": "HSBC", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "classic"},
    "555555": {"network": "mastercard", "bank": "Test Bank", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "classic"},
    "222100": {"network": "mastercard", "bank": "Mastercard Inc.", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "classic"},
    
    # American Express
    "340000": {"network": "amex", "bank": "American Express", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "green"},
    "341111": {"network": "amex", "bank": "American Express", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "gold"},
    "370000": {"network": "amex", "bank": "American Express", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "platinum"},
    "371449": {"network": "amex", "bank": "American Express", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "corporate"},
    "378282": {"network": "amex", "bank": "American Express", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "classic"},
    "378734": {"network": "amex", "bank": "American Express", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "centurion"},
    
    # Discover
    "601100": {"network": "discover", "bank": "Discover Financial", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "classic"},
    "601111": {"network": "discover", "bank": "Discover Financial", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "it"},
    "644000": {"network": "discover", "bank": "Discover Financial", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "miles"},
    "650000": {"network": "discover", "bank": "Discover Financial", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "cashback"},
    
    # UK Banks
    "454313": {"network": "visa", "bank": "Barclays", "country": "United Kingdom", "country_code": "GB", "card_type": "debit", "card_level": "classic"},
    "475129": {"network": "visa", "bank": "HSBC UK", "country": "United Kingdom", "country_code": "GB", "card_type": "credit", "card_level": "classic"},
    "492181": {"network": "visa", "bank": "Lloyds Bank", "country": "United Kingdom", "country_code": "GB", "card_type": "debit", "card_level": "classic"},
    "454742": {"network": "visa", "bank": "NatWest", "country": "United Kingdom", "country_code": "GB", "card_type": "debit", "card_level": "classic"},
    "539175": {"network": "mastercard", "bank": "Monzo", "country": "United Kingdom", "country_code": "GB", "card_type": "debit", "card_level": "classic", "is_prepaid": False},
    "535522": {"network": "mastercard", "bank": "Revolut", "country": "United Kingdom", "country_code": "GB", "card_type": "debit", "card_level": "classic", "is_prepaid": True},
    
    # EU Banks
    "404288": {"network": "visa", "bank": "N26", "country": "Germany", "country_code": "DE", "card_type": "debit", "card_level": "classic"},
    "532421": {"network": "mastercard", "bank": "Bunq", "country": "Netherlands", "country_code": "NL", "card_type": "debit", "card_level": "classic"},
    "426684": {"network": "visa", "bank": "ING", "country": "Netherlands", "country_code": "NL", "card_type": "debit", "card_level": "classic"},
    
    # Prepaid/Virtual
    "404038": {"network": "visa", "bank": "Privacy.com", "country": "United States", "country_code": "US", "card_type": "debit", "card_level": "virtual", "is_prepaid": True},
    "486208": {"network": "visa", "bank": "PayPal", "country": "United States", "country_code": "US", "card_type": "debit", "card_level": "classic", "is_prepaid": True},
    "531993": {"network": "mastercard", "bank": "Cash App", "country": "United States", "country_code": "US", "card_type": "debit", "card_level": "classic", "is_prepaid": True},
    "559666": {"network": "mastercard", "bank": "Venmo", "country": "United States", "country_code": "US", "card_type": "debit", "card_level": "classic", "is_prepaid": True},
    
    # Corporate/Business
    "453245": {"network": "visa", "bank": "Chase", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "business", "is_commercial": True},
    "555456": {"network": "mastercard", "bank": "Capital One", "country": "United States", "country_code": "US", "card_type": "credit", "card_level": "spark", "is_commercial": True},
}

# Network detection by prefix
NETWORK_PREFIXES = {
    "visa": ["4"],
    "mastercard": ["51", "52", "53", "54", "55", "2221", "2222", "2223", "2224", "2225", "2226", "2227", "2228", "2229", "223", "224", "225", "226", "227", "228", "229", "23", "24", "25", "26", "270", "271", "2720"],
    "amex": ["34", "37"],
    "discover": ["6011", "622126", "622127", "622128", "622129", "62213", "62214", "62215", "62216", "62217", "62218", "62219", "6222", "6223", "6224", "6225", "6226", "6227", "6228", "62290", "62291", "622920", "622921", "622922", "622923", "622924", "622925", "644", "645", "646", "647", "648", "649", "65"],
    "diners": ["300", "301", "302", "303", "304", "305", "36", "38"],
    "jcb": ["3528", "3529", "353", "354", "355", "356", "357", "358"],
    "unionpay": ["62"],
}


class BINDatabase:
    """BIN Database with static data and optional external lookup."""
    
    _instance: Optional["BINDatabase"] = None
    
    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = Path(data_dir) if data_dir else Path(os.environ.get("TITAN_DATA", "/opt/titan/data"))
        self._cache: Dict[str, BINRecord] = {}
        self._load_static_data()
        self._load_external_data()
    
    @classmethod
    def get(cls) -> "BINDatabase":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = BINDatabase()
        return cls._instance
    
    def _load_static_data(self):
        """Load built-in static BIN data."""
        for bin_prefix, data in STATIC_BIN_DATA.items():
            self._cache[bin_prefix] = BINRecord(
                bin=bin_prefix,
                network=data.get("network", "unknown"),
                bank=data.get("bank", "Unknown"),
                country=data.get("country", "Unknown"),
                country_code=data.get("country_code", "XX"),
                card_type=data.get("card_type", "credit"),
                card_level=data.get("card_level", "classic"),
                is_prepaid=data.get("is_prepaid", False),
                is_commercial=data.get("is_commercial", False),
            )
        logger.info(f"Loaded {len(self._cache)} static BIN records")
    
    def _load_external_data(self):
        """Load additional BIN data from external file if available."""
        external_path = self.data_dir / "bin_data.json"
        if external_path.exists():
            try:
                with open(external_path) as f:
                    data = json.load(f)
                for bin_prefix, info in data.items():
                    if bin_prefix not in self._cache:
                        self._cache[bin_prefix] = BINRecord(
                            bin=bin_prefix,
                            network=info.get("network", "unknown"),
                            bank=info.get("bank", "Unknown"),
                            country=info.get("country", "Unknown"),
                            country_code=info.get("country_code", "XX"),
                            card_type=info.get("card_type", "credit"),
                            card_level=info.get("card_level", "classic"),
                            is_prepaid=info.get("is_prepaid", False),
                            is_commercial=info.get("is_commercial", False),
                        )
                logger.info(f"Loaded {len(data)} external BIN records")
            except Exception as e:
                logger.warning(f"Failed to load external BIN data: {e}")
    
    def lookup(self, bin_prefix: str) -> Optional[BINRecord]:
        """
        Look up BIN information.
        
        Args:
            bin_prefix: First 6-8 digits of card number
            
        Returns:
            BINRecord if found, None otherwise
        """
        # Normalize input
        bin_clean = bin_prefix.replace(" ", "").replace("-", "")[:8]
        
        # Try exact match first (8, 6 digits)
        for length in [8, 6]:
            prefix = bin_clean[:length]
            if prefix in self._cache:
                return self._cache[prefix]
        
        # Try partial matches (decreasing length)
        for length in range(min(6, len(bin_clean)), 3, -1):
            prefix = bin_clean[:length]
            if prefix in self._cache:
                return self._cache[prefix]
        
        # Fall back to network detection
        network = self._detect_network(bin_clean)
        if network:
            return BINRecord(
                bin=bin_clean[:6],
                network=network,
                bank="Unknown",
                country="Unknown",
                country_code="XX",
                card_type="credit",
                card_level="classic",
            )
        
        return None
    
    def _detect_network(self, card_number: str) -> Optional[str]:
        """Detect card network from number prefix."""
        for network, prefixes in NETWORK_PREFIXES.items():
            for prefix in prefixes:
                if card_number.startswith(prefix):
                    return network
        return None
    
    def get_network(self, card_number: str) -> str:
        """Get network name for card number."""
        record = self.lookup(card_number[:6])
        if record:
            return record.network
        return self._detect_network(card_number) or "unknown"
    
    def is_prepaid(self, card_number: str) -> bool:
        """Check if card is prepaid."""
        record = self.lookup(card_number[:6])
        return record.is_prepaid if record else False
    
    def is_commercial(self, card_number: str) -> bool:
        """Check if card is commercial/business."""
        record = self.lookup(card_number[:6])
        return record.is_commercial if record else False
    
    def get_issuer(self, card_number: str) -> str:
        """Get issuer bank name."""
        record = self.lookup(card_number[:6])
        return record.bank if record else "Unknown"
    
    def get_country(self, card_number: str) -> str:
        """Get issuing country."""
        record = self.lookup(card_number[:6])
        return record.country if record else "Unknown"
    
    def validate_luhn(self, card_number: str) -> bool:
        """Validate card number using Luhn algorithm."""
        num = card_number.replace(" ", "").replace("-", "")
        if not num.isdigit():
            return False
        
        digits = [int(d) for d in num]
        odd_digits = digits[-1::-2]
        even_digits = digits[-2::-2]
        
        checksum = sum(odd_digits)
        for d in even_digits:
            checksum += sum(divmod(d * 2, 10))
        
        return checksum % 10 == 0
    
    def full_lookup(self, card_number: str) -> Dict[str, Any]:
        """
        Comprehensive card lookup with all available information.
        
        Returns dict with BIN info, network, validation status, etc.
        """
        num = card_number.replace(" ", "").replace("-", "")
        record = self.lookup(num[:6])
        
        result = {
            "card_number_masked": f"{num[:4]}****{num[-4:]}" if len(num) >= 8 else "****",
            "bin": num[:6] if len(num) >= 6 else num,
            "luhn_valid": self.validate_luhn(num),
            "length_valid": len(num) in [13, 14, 15, 16, 19],
        }
        
        if record:
            result.update(record.to_dict())
        else:
            result["network"] = self._detect_network(num) or "unknown"
            result["bank"] = "Unknown"
            result["country"] = "Unknown"
        
        return result


# Convenience function for direct import
def lookup_bin(bin_prefix: str) -> Optional[BINRecord]:
    """Quick BIN lookup."""
    return BINDatabase.get().lookup(bin_prefix)

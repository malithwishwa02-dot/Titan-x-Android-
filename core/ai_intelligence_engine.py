"""
Titan V11.3 — AI Intelligence Engine
Provides AI-powered copilot functionality for operation intelligence,
target analysis, and strategic recommendations using Ollama LLM backend.

Wires to GPU Ollama (Vast.ai) or local CPU Ollama for inference.

Usage:
    from ai_intelligence_engine import AIIntelligenceEngine
    engine = AIIntelligenceEngine()
    result = engine.orchestrate_operation_intel("Analyze target domain example.com")
    print(result)
"""

import json
import logging
import os
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger("titan.ai-intelligence")

# Ollama endpoints
GPU_OLLAMA_URL = os.environ.get("TITAN_GPU_OLLAMA", "http://127.0.0.1:11435")
CPU_OLLAMA_URL = os.environ.get("TITAN_CPU_OLLAMA", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("TITAN_SPECIALIST_MODEL", "titan-specialist:7b")


@dataclass
class IntelResult:
    """Intelligence analysis result."""
    query: str
    response: str
    model: str
    confidence: float
    categories: List[str]
    recommendations: List[str]
    risk_factors: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "response": self.response,
            "model": self.model,
            "confidence": self.confidence,
            "categories": self.categories,
            "recommendations": self.recommendations,
            "risk_factors": self.risk_factors,
        }


class AIIntelligenceEngine:
    """AI-powered intelligence analysis engine."""
    
    SYSTEM_PROMPT = """You are Titan Intelligence, an expert AI analyst specializing in:
- Target domain analysis and reconnaissance
- Security posture assessment
- Payment system analysis (3DS, fraud detection)
- OSINT and digital footprint analysis
- Risk assessment and strategic recommendations

Provide concise, actionable intelligence. Structure responses with:
1. Summary (2-3 sentences)
2. Key Findings (bullet points)
3. Risk Factors (if applicable)
4. Recommendations (actionable steps)

Be direct and technical. Avoid unnecessary disclaimers."""

    def __init__(self, model: Optional[str] = None):
        self.model = model or DEFAULT_MODEL
        self.ollama_url = self._detect_ollama()
        logger.info(f"AIIntelligenceEngine initialized: {self.model} @ {self.ollama_url}")
    
    def _detect_ollama(self) -> str:
        """Detect available Ollama endpoint."""
        for url in [GPU_OLLAMA_URL, CPU_OLLAMA_URL]:
            try:
                req = urllib.request.Request(f"{url}/api/tags", method="GET")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    data = json.loads(resp.read().decode())
                    models = [m["name"] for m in data.get("models", [])]
                    if models:
                        logger.info(f"Ollama available at {url} with {len(models)} models")
                        return url
            except Exception:
                continue
        logger.warning("No Ollama endpoint available, using GPU URL as fallback")
        return GPU_OLLAMA_URL
    
    def _call_ollama(self, prompt: str, system: Optional[str] = None,
                     temperature: float = 0.7, max_tokens: int = 2048) -> Optional[str]:
        """Call Ollama API for completion."""
        try:
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                }
            }
            if system:
                payload["system"] = system
            
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{self.ollama_url}/api/generate",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode())
                return result.get("response", "")
        
        except urllib.error.URLError as e:
            logger.error(f"Ollama connection error: {e}")
            return None
        except Exception as e:
            logger.error(f"Ollama API error: {e}")
            return None
    
    def _extract_categories(self, text: str) -> List[str]:
        """Extract intelligence categories from response."""
        categories = []
        category_keywords = {
            "domain": ["domain", "dns", "website", "web"],
            "security": ["security", "vulnerability", "risk", "threat"],
            "payment": ["payment", "card", "3ds", "fraud", "transaction"],
            "identity": ["identity", "kyc", "verification", "account"],
            "infrastructure": ["server", "infrastructure", "hosting", "cloud"],
            "social": ["social", "osint", "profile", "account"],
        }
        
        text_lower = text.lower()
        for cat, keywords in category_keywords.items():
            if any(kw in text_lower for kw in keywords):
                categories.append(cat)
        
        return categories or ["general"]
    
    def _extract_recommendations(self, text: str) -> List[str]:
        """Extract recommendations from response."""
        recommendations = []
        lines = text.split("\n")
        in_recommendations = False
        
        for line in lines:
            line = line.strip()
            if "recommendation" in line.lower() or "suggest" in line.lower():
                in_recommendations = True
                continue
            if in_recommendations and line.startswith(("-", "*", "•", "1", "2", "3")):
                rec = line.lstrip("-*•0123456789. ")
                if len(rec) > 10:
                    recommendations.append(rec)
            elif in_recommendations and line and not line.startswith(("-", "*", "•")):
                in_recommendations = False
        
        return recommendations[:5]  # Max 5 recommendations
    
    def _extract_risks(self, text: str) -> List[str]:
        """Extract risk factors from response."""
        risks = []
        lines = text.split("\n")
        in_risks = False
        
        for line in lines:
            line = line.strip()
            if "risk" in line.lower() and ("factor" in line.lower() or ":" in line):
                in_risks = True
                continue
            if in_risks and line.startswith(("-", "*", "•", "1", "2", "3")):
                risk = line.lstrip("-*•0123456789. ")
                if len(risk) > 10:
                    risks.append(risk)
            elif in_risks and line and not line.startswith(("-", "*", "•")):
                in_risks = False
        
        return risks[:5]  # Max 5 risks
    
    def orchestrate_operation_intel(self, query: str) -> Dict[str, Any]:
        """
        Main intelligence orchestration - analyzes query and provides intel.
        
        Args:
            query: Natural language query about target, domain, or operation
            
        Returns:
            Intelligence result with analysis, recommendations, and risks
        """
        logger.info(f"Processing intel query: {query[:100]}...")
        
        response = self._call_ollama(query, system=self.SYSTEM_PROMPT)
        
        if not response:
            return {
                "query": query,
                "response": "Intelligence engine unavailable. Check Ollama connection.",
                "model": self.model,
                "confidence": 0.0,
                "categories": [],
                "recommendations": [],
                "risk_factors": [],
                "error": "ollama_unavailable",
            }
        
        result = IntelResult(
            query=query,
            response=response,
            model=self.model,
            confidence=0.85,  # Base confidence
            categories=self._extract_categories(response),
            recommendations=self._extract_recommendations(response),
            risk_factors=self._extract_risks(response),
        )
        
        return result.to_dict()
    
    def analyze_domain(self, domain: str) -> Dict[str, Any]:
        """Analyze a target domain for security and infrastructure intel."""
        prompt = f"""Analyze the domain: {domain}

Provide intelligence on:
1. Likely technology stack and hosting
2. Security posture indicators
3. Payment/e-commerce capabilities if applicable
4. Risk factors for operations targeting this domain
5. Recommended approach and tactics"""
        
        return self.orchestrate_operation_intel(prompt)
    
    def analyze_bin(self, bin_prefix: str) -> Dict[str, Any]:
        """Analyze a BIN for payment intelligence."""
        prompt = f"""Analyze BIN (Bank Identification Number): {bin_prefix}

Provide intelligence on:
1. Likely issuing bank and country
2. Card type (credit/debit/prepaid)
3. 3DS implementation likelihood
4. Fraud detection sensitivity
5. Recommended transaction approach"""
        
        return self.orchestrate_operation_intel(prompt)
    
    def get_3ds_strategy(self, bin_prefix: str, merchant: str,
                         amount: float) -> Dict[str, Any]:
        """Get 3DS bypass/handling strategy."""
        prompt = f"""3DS Strategy Request:
- BIN: {bin_prefix}
- Merchant: {merchant}
- Amount: ${amount:.2f}

Analyze and provide:
1. Expected 3DS challenge type (frictionless, challenge, exemption)
2. Risk factors that may trigger step-up
3. Recommended timing and approach
4. Fallback strategies if challenged"""
        
        return self.orchestrate_operation_intel(prompt)
    
    def assess_target(self, target_info: Dict[str, Any]) -> Dict[str, Any]:
        """Comprehensive target assessment."""
        prompt = f"""Target Assessment Request:
{json.dumps(target_info, indent=2)}

Provide comprehensive analysis:
1. Target profile summary
2. Vulnerability assessment
3. Operational risk factors
4. Strategic recommendations
5. Timeline and resource estimates"""
        
        return self.orchestrate_operation_intel(prompt)
    
    def health_check(self) -> Dict[str, Any]:
        """Check engine health and connectivity."""
        try:
            req = urllib.request.Request(f"{self.ollama_url}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                models = [m["name"] for m in data.get("models", [])]
                return {
                    "status": "healthy",
                    "ollama_url": self.ollama_url,
                    "model": self.model,
                    "available_models": models,
                    "model_loaded": self.model in models or any(
                        m.startswith(self.model.split(":")[0]) for m in models
                    ),
                }
        except Exception as e:
            return {
                "status": "unhealthy",
                "ollama_url": self.ollama_url,
                "error": str(e),
            }

"""Input checks for sensitive data and prohibited investment requests."""

from __future__ import annotations

from enum import Enum
import re


class RequestIntent(str, Enum):
    FACTUAL = "factual"
    ADVICE = "advice"
    PERFORMANCE = "performance"


_PII_PATTERNS = (
    re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b", re.IGNORECASE),
    re.compile(r"(?<!\d)(?:\d[ -]?){11}\d(?!\d)"),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    re.compile(
        r"\b(?:bank\s+)?account\s*(?:number|no\.?|#)?\s*[:=-]?\s*\d{5,20}\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:a/c|acct)\s*(?:number|no\.?|#)?\s*[:=-]?\s*\d{5,20}\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:otp|one[- ]time password)\D{0,16}\d{4,8}\b", re.IGNORECASE
    ),
    re.compile(r"(?<!\d)(?:\+?91[\s.-]?)?[6-9]\d{9}(?!\d)"),
    re.compile(r"(?<!\d)\+?\d[\d().\s-]{8,}\d(?!\d)"),
)

_PERFORMANCE_TERMS = re.compile(
    r"\b(?:performance|returns?|cagr|xirr)\b", re.IGNORECASE
)
_PERFORMANCE_PATTERNS = (
    re.compile(
        r"\b(?:will|would|can|could|might)\b.{0,60}\b(?:perform|outperform|return|grow|gain|earn|appreciate|make money)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bhow\s+(?:did|has|have)\b.{0,50}\b(?:fund|scheme|investment|it)\b.{0,40}\b(?:perform|do|grow|return)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bhow much\b.{0,40}\b(?:earn|gain|grow|make)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:returned|generated|delivered|gained|grew|earned|appreciated|declined|fell|rose)\b.{0,40}\b\d+(?:\.\d+)?\s*(?:%|percent)",
        re.IGNORECASE,
    ),
)
_ADVICE_PATTERNS = (
    re.compile(r"\bshould\s+i\b", re.IGNORECASE),
    re.compile(r"\b(?:recommend|recommendation|advise|advice|opinion)\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+do\s+you\s+think\b", re.IGNORECASE),
    re.compile(
        r"\b(?:right|suitable|appropriate|good\s+fit|fit)\b.{0,50}\b(?:for\s+(?:me|you|my\s+(?:goals|needs|risk|portfolio|horizon)|your\s+(?:goals|needs|risk|portfolio|horizon))|my\s+(?:goals|needs|risk\s+profile|portfolio|horizon)|your\s+(?:goals|needs|risk\s+profile|portfolio|horizon))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:does|do|will|would|could|might|is)\b.{0,60}\b(?:match|fit|suit|align\s+with)\b.{0,40}\b(?:me|you|my\s+(?:goals|needs|risk|portfolio|horizon)|your\s+(?:goals|needs|risk|portfolio|horizon))\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:good|bad)\s+investment\b", re.IGNORECASE),
    re.compile(
        r"\bwhich\s+(?:fund|scheme|portfolio)\b.{0,60}\b(?:choose|select|invest|recommend|best|better)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:can|would|should)\s+i\s+(?:buy|sell|hold|switch|invest)\b", re.IGNORECASE),
    re.compile(r"\b(?:buy|sell|hold|switch)\s+(?:this|the|a|that)\s+(?:fund|scheme)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:my|personal|own)\s+portfolio\s+(?:allocation|mix|construction)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:allocate|rebalance|diversify|split)\b.{0,60}\b(?:my|portfolio|fund|scheme|investment|money)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:my|portfolio)\b.{0,60}\b(?:allocate|rebalance|diversify|split)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:how(?:\s+much)?|where)\s+should\s+i\b.{0,60}\b(?:invest|allocate|put|split|divide)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:what|how much|how many)\b.{0,60}\b(?:of|in)\s+(?:my|your)\s+portfolio\b.{0,50}\b(?:should|would|could|ought to)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:put|allocate|invest|move|shift|split)\b.{0,60}\b(?:my|your)\s+portfolio\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:best|better)\s+(?:fund|scheme|option)\s+for\s+me\b", re.IGNORECASE),
    re.compile(r"\bwhich\s+is\s+better\s+for\s+me\b", re.IGNORECASE),
)


def contains_pii(text: str) -> bool:
    """Return whether text includes common Indian identifiers or contact data."""
    return any(pattern.search(text) for pattern in _PII_PATTERNS)


def classify_request(text: str) -> RequestIntent:
    """Classify advice/performance questions before factual retrieval or generation."""
    if _PERFORMANCE_TERMS.search(text):
        return RequestIntent.PERFORMANCE
    if any(pattern.search(text) for pattern in _PERFORMANCE_PATTERNS):
        return RequestIntent.PERFORMANCE
    if any(pattern.search(text) for pattern in _ADVICE_PATTERNS):
        return RequestIntent.ADVICE
    return RequestIntent.FACTUAL
"""Deterministic Care response composer (Step 3: select-then-enhance).

The composer owns facts, structure, and decisions. It selects the
immutable fact block per topic from already-assembled backend context,
decides whether AI phrasing is allowed, and validates any model output
before it may reach the user. It never calls an LLM and never invents
values: missing data stays missing (rendered as named absence).
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.care_topics import (
    LOG_LOOKUP,
    MOOD,
    SYMPTOM,
    THERAPY,
    WELLNESS_GENERAL,
)

TIER_INFO = "info"
# Voice-hygiene denylist: population generalizations and clinical overreach
# that must never appear in model prose (deterministic fallback is used).
BANNED_PHRASES = [
    "many users",
    "many people",
    "diagnos",
    "prescrib",
    "ibuprofen",
    "paracetamol",
    "acetaminophen",
    "aspirin",
    "naproxen",
    "dosage",
    "antibiotic",
]

# Banned follow-up closers: filler questions that keep the chat going
# without resolving anything.
BANNED_FOLLOWUPS = [
    "know more",
    "anything else",
    "else can i",
    "else i can",
    "how else can i help",
]

_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_MONTHS = {
    "01": ("Jan", "January"), "02": ("Feb", "February"), "03": ("Mar", "March"),
    "04": ("Apr", "April"), "05": ("May", "May"), "06": ("Jun", "June"),
    "07": ("Jul", "July"), "08": ("Aug", "August"), "09": ("Sep", "September"),
    "10": ("Oct", "October"), "11": ("Nov", "November"), "12": ("Dec", "December"),
}

MAX_FOLLOWUP_CHARS = 160
MAX_LOG_ROWS_QUOTED = 3


@dataclass(frozen=True)
class ComposedReply:
    topic: str
    facts: Dict[str, Any] = field(default_factory=dict)
    enhance: bool = False
    followup_allowed: bool = False
    base_text: Optional[str] = None


def _str_list(values: Any, limit: int = 5) -> List[str]:
    if not isinstance(values, list):
        return []
    return [str(v) for v in values[:limit]]


def _symptom_facts(context: Dict[str, Any]) -> Dict[str, Any]:
    logs = context.get("recent_logs", []) or []
    recent_symptoms: List[str] = []
    for log in logs:
        for symptom in (log.get("symptoms") or []):
            if symptom not in recent_symptoms:
                recent_symptoms.append(str(symptom))
    return {
        "cycle_day": context.get("cycle_day"),
        "phase": context.get("phase"),
        "today_pain": _today_pain_from_logs(logs),
        "recent_pain_avg": context.get("recent_pain_avg"),
        "recent_symptoms": recent_symptoms[:5],
        "frequent_symptoms": _str_list(context.get("frequent_symptoms")),
        "logs_count": len(logs),
    }


def _today_pain_from_logs(logs: List[Dict[str, Any]]) -> Optional[Any]:
    if not logs:
        return None
    # recent_logs arrive newest-first (desc log_date).
    pain = logs[0].get("pain")
    return pain


def _mood_facts(context: Dict[str, Any]) -> Dict[str, Any]:
    logs = context.get("recent_logs", []) or []
    recent_mood = None
    for log in logs:
        if log.get("mood"):
            recent_mood = log.get("mood")
            break
    return {
        "cycle_day": context.get("cycle_day"),
        "phase": context.get("phase"),
        "recent_mood": recent_mood,
        "today_pain": _today_pain_from_logs(logs),
    }


def _wellness_facts(context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "cycle_day": context.get("cycle_day"),
        "phase": context.get("phase"),
        "is_bleeding": context.get("is_bleeding"),
        "predicted_next_period": context.get("predicted_next_period"),
        "prediction_confidence": context.get("prediction_confidence"),
    }


# Deterministic mention scan: symptom words in the user's own message, so
# fallback frames can acknowledge what was actually said without echoing
# free text. Labels are fixed display words, never raw input.
_MENTION_LABELS = [
    (re.compile(r"\bcramps?\b"), "cramps"),
    (re.compile(r"\bheadaches?\b|\bmigraine\b"), "headaches"),
    (re.compile(r"\bnausea\b"), "nausea"),
    (re.compile(r"\bbloat\w*\b"), "bloating"),
    (re.compile(r"\btired\b|\bfatigu\w*\b|\bexhaust\w*\b"), "low energy"),
    (re.compile(r"\bdizz\w*\b"), "dizziness"),
    (re.compile(r"\bback\b.*\bpain\b|\bpain\b.*\bback\b"), "back pain"),
]


def _mentioned_symptoms(message: Optional[str]) -> List[str]:
    msg = (message or "").lower()
    return [label for pattern, label in _MENTION_LABELS if pattern.search(msg)]


def _therapy_facts(context: Dict[str, Any]) -> Dict[str, Any]:
    pattern = context.get("recent_pattern", {}) or {}
    evidence = {}
    for band, val in pattern.items():
        if isinstance(val, dict) and (val.get("total_sessions") or 0) > 0:
            evidence[band] = {
                "preferred_profile": val.get("preferred_profile"),
                "successful_sessions": val.get("successful_sessions"),
                "total_sessions": val.get("total_sessions"),
            }
    return {
        "cycle_day": context.get("cycle_day"),
        "phase": context.get("phase"),
        "current_pain": context.get("current_pain"),
        "recent_pain_avg": context.get("recent_pain_avg"),
        "has_history": bool(context.get("has_history")),
        "band_evidence": evidence,
        "sensitivity_index": context.get("sensitivity_index"),
        # Deterministic /recommend subset (profile label + pain only).
        "recommendation": context.get("recommendation"),
    }


def build_log_lookup_text(context: Dict[str, Any]) -> str:
    """Deterministic exact read-out of stored logs (no AI)."""
    logs = context.get("recent_logs", []) or []
    if not logs:
        return (
            "I don't see any logs in the last 7 days, so there's nothing to read back yet. "
            "Log today to start building your history."
        )
    parts = []
    for log in logs[:MAX_LOG_ROWS_QUOTED]:
        bits = [f"pain {log.get('pain')}"]
        if log.get("mood"):
            bits.append(f"mood {log.get('mood')}")
        symptoms = _str_list(log.get("symptoms"))
        if symptoms:
            bits.append(", ".join(symptoms))
        if log.get("flow"):
            bits.append(f"flow {log.get('flow')}")
        parts.append(f"on {log.get('date')}: " + "; ".join(bits))
    return "Here's what you logged — " + ". ".join(parts) + "."


def compose_ai_reply(
    topic: str, context: Dict[str, Any], message: Optional[str] = None
) -> ComposedReply:
    """Select facts and enhancement policy for AI-path topics."""
    mentioned = _mentioned_symptoms(message)
    if topic == SYMPTOM:
        facts = _symptom_facts(context)
        facts["mentioned"] = mentioned
        return ComposedReply(
            topic=topic, facts=facts,
            enhance=True, followup_allowed=True,
        )
    if topic == MOOD:
        return ComposedReply(
            topic=topic, facts=_mood_facts(context),
            enhance=True, followup_allowed=True,
        )
    if topic == THERAPY:
        return ComposedReply(
            topic=topic, facts=_therapy_facts(context),
            enhance=True, followup_allowed=True,
        )
    if topic == LOG_LOOKUP:
        return ComposedReply(
            topic=topic,
            facts={"cycle_day": context.get("cycle_day"), "phase": context.get("phase")},
            enhance=False, followup_allowed=False,
            base_text=build_log_lookup_text(context),
        )
    # wellness_general and anything unexpected: minimal facts, AI explains.
    return ComposedReply(
        topic=topic, facts=_wellness_facts(context),
        enhance=True, followup_allowed=False,
    )


def _allowed_tokens(facts: Dict[str, Any]) -> set:
    """Every number/date the model may use: those present in facts."""
    allowed: set = set()
    stack: List[Any] = [facts]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            stack.extend(node.values())
        elif isinstance(node, (list, tuple)):
            stack.extend(node)
        elif node is None:
            continue
        else:
            text = str(node)
            for match in _NUMBER_RE.findall(text):
                allowed.add(match.lstrip("0") or "0")
                allowed.add(match)
            for iso in _ISO_DATE_RE.findall(text):
                allowed.add(iso)
                year, mon, day = iso.split("-")
                day_naked = day.lstrip("0") or "0"
                for name in _MONTHS.get(mon, ()):
                    allowed.add(f"{name} {day}")
                    allowed.add(f"{name} {day_naked}")
    return allowed


def _text_tokens(text: str) -> set:
    tokens = set()
    for match in _NUMBER_RE.findall(text):
        tokens.add(match.lstrip("0") or "0")
        tokens.add(match)
    for iso in _ISO_DATE_RE.findall(text):
        tokens.add(iso)
    return tokens


def validate_explained_text(text: str, facts: Dict[str, Any]) -> bool:
    """True iff model prose uses only fact-backed numbers/dates and no
    banned clinical/population phrasing."""
    if not text or not text.strip():
        return False
    lowered = text.lower()
    if any(phrase in lowered for phrase in BANNED_PHRASES):
        return False
    allowed = _allowed_tokens(facts)
    return _text_tokens(text) <= allowed


def validate_followup(followup: Optional[str]) -> bool:
    if followup is None:
        return True
    text = followup.strip()
    if not text or len(text) > MAX_FOLLOWUP_CHARS:
        return False
    if text.count("?") != 1 or not text.endswith("?"):
        return False
    lowered = text.lower()
    return not any(banned in lowered for banned in BANNED_FOLLOWUPS)


def cross_check_therapy_profile(
    profile: Optional[str], facts: Dict[str, Any]
) -> Optional[str]:
    """Null a model-suggested profile that contradicts deterministic facts.

    Accepts on absence of evidence (no history is not a contradiction);
    rejects only genuine conflicts: no pain, or verified band evidence
    (2+ sessions) pointing at a different profile.
    """
    if profile is None:
        return None
    current_pain = facts.get("current_pain")
    if current_pain == 0:
        return None
    # Deterministic /recommend output wins over the model label: a
    # differing suggestion is nulled, never executed.
    recommended = (facts.get("recommendation") or {}).get("profile")
    if recommended and profile != recommended:
        return None
    band = None
    if isinstance(current_pain, (int, float)):
        band = (
            "mild_pain" if current_pain <= 4
            else ("moderate_pain" if current_pain <= 7 else "severe_pain")
        )
    evidence = (facts.get("band_evidence") or {}).get(band, {}) if band else {}
    total = evidence.get("total_sessions") or 0
    preferred = evidence.get("preferred_profile")
    if total >= 2 and preferred and preferred != profile:
        return None
    return profile


def _day_phase_line(facts: Dict[str, Any]) -> str:
    """Honest day/phase anchor that never renders 'None'."""
    day = facts.get("cycle_day")
    phase = facts.get("phase")
    if day is not None and phase:
        return f"day {day}, {phase} phase"
    if phase:
        return f"{phase} phase"
    if day is not None:
        return f"day {day} of your cycle"
    return "your cycle"


def _join_words(words: List[str]) -> str:
    words = [str(w) for w in words if w]
    if not words:
        return ""
    if len(words) == 1:
        return words[0]
    return ", ".join(words[:-1]) + f" and {words[-1]}"


def render_deterministic_reply(composed: ComposedReply) -> str:
    """Shared deterministic frames over composer facts (Step 4).

    Used by the Mock fallback so keyless replies carry the same decisions
    and context as the enhanced path — plainer sentences, same structure.
    Never invents values; names absence instead.
    """
    facts = composed.facts
    anchor = _day_phase_line(facts)

    if composed.topic == LOG_LOOKUP and composed.base_text:
        return composed.base_text

    if composed.topic == SYMPTOM:
        recent = _join_words(facts.get("recent_symptoms") or [])
        mentioned = _join_words(facts.get("mentioned") or [])
        pain = facts.get("today_pain")
        pain_line = f" Today's logged pain is {pain}." if pain is not None else ""
        if recent:
            return (
                f"Your recent logs show {recent} (around {anchor}).{pain_line} "
                "Gentle warmth, light movement, or rest can help with cramp-like "
                "discomfort. If pain feels unusually sharp or severe, consider "
                "speaking with a healthcare professional."
            )
        if mentioned:
            return (
                f"You mentioned {mentioned} — nothing like that is logged in the "
                f"last 7 days, so I'm going by what you told me (around {anchor})."
                f"{pain_line} Gentle warmth, light movement, or rest can help with "
                "cramp-like discomfort. If pain feels unusually sharp or severe, "
                "consider speaking with a healthcare professional."
            )
        return (
            f"Nothing logged in the last 7 days (around {anchor}).{pain_line} "
            "If cramps or other symptoms come up, log them and I can factor them in. "
            "If pain feels unusually sharp or severe, consider speaking with a "
            "healthcare professional."
        )

    if composed.topic == MOOD:
        mood = facts.get("recent_mood")
        if mood:
            return (
                f"You logged feeling {mood} recently (around {anchor}). Quiet moments "
                "for yourself, gentle walks, and steady sleep can help you feel more "
                "grounded. If mood changes feel unmanageable, a professional can "
                "offer personalized support."
            )
        return (
            f"No mood logged recently (around {anchor}). Quiet moments for yourself, "
            "gentle walks, and steady sleep can help you feel more grounded. If mood "
            "changes feel unmanageable, a professional can offer personalized support."
        )

    if composed.topic == THERAPY:
        pain = facts.get("current_pain")
        if pain == 0:
            return "No pain reported, so no therapy is needed right now."
        evidence = facts.get("band_evidence") or {}
        band = None
        if isinstance(pain, (int, float)):
            band = (
                "mild_pain" if pain <= 4
                else ("moderate_pain" if pain <= 7 else "severe_pain")
            )
        band_info = evidence.get(band, {}) if band else {}
        total = band_info.get("total_sessions") or 0
        preferred = band_info.get("preferred_profile")
        if total >= 1 and preferred:
            successes = band_info.get("successful_sessions") or 0
            return (
                f"{preferred.capitalize()} has helped in {successes} of {total} similar "
                f"sessions (current pain {pain}). I'd suggest sticking with what worked, "
                "within the wearable's safe settings."
            )
        recommended = (facts.get("recommendation") or {}).get("profile")
        if recommended:
            return (
                f"For your current pain ({pain}), the approved {recommended.capitalize()} "
                "setup applies — log the session and I'll learn what helps you."
            )
        return (
            "No prior therapy sessions recorded, so I can't personalize from history yet. "
            "A gentle setting is a calm place to start — log the session and I'll learn "
            "what helps you."
        )

    # wellness_general and any other topic: day/phase anchor + prediction
    # line where available.
    prediction = facts.get("predicted_next_period")
    if prediction:
        conf = facts.get("prediction_confidence")
        conf_line = f" ({conf} confidence)" if conf else ""
        return (
            f"Around {anchor}, tracking symptoms helps build a clearer picture of your "
            f"rhythms. Your next period is estimated around {prediction}{conf_line}."
        )
    return (
        f"Around {anchor}, tracking symptoms helps build a clearer picture of your "
        "rhythms. If health concerns come up, a healthcare provider is best suited "
        "to guide you."
    )

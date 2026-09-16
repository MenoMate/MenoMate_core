"""Deterministic Care topic classification (Step 2).

Maps (client intent hint + user message + recent session turns) to one of
the conceptual topics. The client-sent intent is a HINT only: the same
semantic question must reach the same topic whether it came from a quick
chip, free text, or another entry point.

Topic is authoritative routing input; it never invents facts and never
touches safety logic (red-flag triage in care.py always runs first).
"""

import re
from typing import Any, Dict, List, Optional

CYCLE_STATUS = "cycle_status"
PREDICTION = "prediction"
SYMPTOM = "symptom"
MOOD = "mood"
LOG_LOOKUP = "log_lookup"
THERAPY = "therapy"
DEVICE = "device"
WELLNESS_GENERAL = "wellness_general"
OUT_OF_SCOPE = "out_of_scope"

CARE_TOPICS = (
    CYCLE_STATUS,
    PREDICTION,
    SYMPTOM,
    MOOD,
    LOG_LOOKUP,
    THERAPY,
    DEVICE,
    WELLNESS_GENERAL,
    OUT_OF_SCOPE,
)

# Client intent is a hint, not the router. Explicit intents with a direct
# topic map straight through; everything else is classified from text.
# None means "decide from the message".
INTENT_TOPIC_HINT: Dict[str, Optional[str]] = {
    "cycle_insight": CYCLE_STATUS,  # refined to PREDICTION by timing words
    "pain_help": None,  # symptom vs therapy decided by relief-seeking words
    "symptom_insight": SYMPTOM,
    "wellness_help": None,
    "device_help": DEVICE,
    "pattern_summary": SYMPTOM,
    "therapy_recommendation": THERAPY,
    "therapy": THERAPY,
    "feature_help": WELLNESS_GENERAL,
    "general_inquiry": None,
    "other": None,
}

OUT_OF_SCOPE_PATTERNS = [
    r"\b(python|javascript|typescript|java\b|programming|code (this|that|a)|write (me )?(a |some )?code)\b",
    r"\b(sort numbers|football|soccer|basketball|cricket|politics|election|homework|trivia|recipe|movies?|song lyrics)\b",
]

DEVICE_PATTERNS = [
    r"\b(device|esp32|bluetooth|ble|wearable|pair(ing|ed)?)\b",
    r"\bconnect (my |the )?wearable\b",
]

PREDICTION_PATTERNS = [
    r"\bnext period\b",
    r"\bwhen is my period\b",
    r"\bperiod date\b",
    r"\bpredic\w*\b",
    r"\bforecast\b",
    r"\bovulat\w*\b",
    r"\bperiod\b.*\b(due|late|expected|coming)\b",
    r"\b(due|late|expected)\b.*\bperiod\b",
]

CYCLE_STATUS_PATTERNS = [
    r"\bcycle day\b",
    r"\bwhat day\b.*\b(cycle|am i)\b",
    r"\bam i on\b",
    r"\bphase\b",
    r"\bbleeding\b",
    r"\bam i bleeding\b",
    r"\bperiod (started|today|now)\b",
    r"\bwhat'?s happening\b",
    r"\btoday\b.*\bcycle\b",
]

LOG_LOOKUP_PATTERNS = [
    r"\bdid i log\b",
    r"\bwhat did i log\b",
    r"\bshow\b.*\blog\b",
    r"\bmy log\b",
    r"\bi logged\b",
    r"\bpain on \w+\b",
    r"\b(yesterday|today|last night)\b.*\b(log|logged|pain|cramps?)\b",
    # Bare time fragments ("yesterday?", "what about today?") read as
    # log lookups only when the whole message is the fragment — never
    # when the timeword trails a longer sentence ("moody today").
    r"^(what about )?(yesterday|today|last night)\??$",
]

THERAPY_PATTERNS = [
    r"\bwhat setting\b",
    r"\bthermal\b",
    r"\brelief\b",
    r"\bwhat help\w*\b",
    r"\bhelps?\b.*\b(cramps?|pain)\b",
    r"\b(cramps?|pain)\b.*\bhelps?\b",
    r"\bsooth\w*\b",
    r"\bwarmth\b",
]

SYMPTOM_PATTERNS = [
    r"\bcramps?\b",
    r"\bpain\b",
    r"\bach(e|ing|y)\b",
    r"\bnausea\b",
    r"\bheadache\b",
    r"\bmigraine\b",
    r"\bbloat\w*\b",
    r"\btired\b",
    r"\bfatigu\w*\b",
    r"\bexhaust\w*\b",
    r"\bdizz\w*\b",
    r"\bspotting\b",
    r"\bdischarge\b",
    r"\bflow\b",
    r"\bbreast\b",
    r"\bsore\b",
    r"\bsymptom\w*\b",
]

MOOD_PATTERNS = [
    r"\bmood\b",
    r"\banxi\w*\b",
    r"\bdepress\w*\b",
    r"\bsad\b",
    r"\birritab\w*\b",
    r"\bemotion\w*\b",
    r"\bstress\w*\b",
    r"\bsleep\b",
    r"\binsomnia\b",
    r"\bcry\w*\b",
    r"\boverwhelm\w*\b",
    r"\bmental health\b",
]

# Follow-up shorthand that refers to the ongoing conversation rather than
# starting a new question. When matched and session turns exist, the topic
# is inherited from the most recent topical turn (Step 1 memory in use).
FOLLOWUP_PATTERNS = [
    r"^what about\b",
    r"^and \b",
    r"^how about\b",
    r"\bthat symptom\b",
    r"\bthose symptoms\b",
    r"\bwhat about it\b",
    r"\bsame (thing|as before)\b",
    r"^(why|and\?)\??$",
]

RISK_NONE = "none"
RISK_DIAGNOSIS = "diagnosis"
RISK_MEDICATION = "medication"
RISK_ADVISORY = "advisory"

# Step 5 — deterministic soft-risk classification. Runs after red-flag
# triage, before topic routing. High-precision ask patterns only: everyday
# intensity adjectives ("terrible cramps") must NOT trip these.
DIAGNOSIS_PATTERNS = [
    r"\bdo i have\b",
    r"\bcould i have\b",
    r"\bdo you think i have\b",
    r"\bdiagnos\w* me\b",
    r"\bwhat('s| is) wrong with me\b",
    r"\bwhat condition\b",
    r"\bwhich disease\b",
    r"\bam i pregnant\b",
    r"\bcould i be pregnant\b",
    r"\bpregnancy test\b",
]

MEDICATION_PATTERNS = [
    r"\bibuprofen\b",
    r"\bparacetamol\b",
    r"\bacetaminophen\b",
    r"\baspirin\b",
    r"\bnaproxen\b",
    r"\bpainkillers?\b",
    r"\bpain killers?\b",
    r"\bdosage\b",
    r"\bdose\b",
    r"\bhow many (mg|pills|tablets)\b",
    r"\bwhat (medicine|medication|pill|tablet) should i take\b",
    r"\bshould i take\b.*\b(medicine|medication|pill|tablet|supplement|vitamin)\b",
    r"\bantibiotic\w*\b",
    r"\bbirth control\b",
    r"\bcontracepti\w*\b",
]

# Escalation language below the red-flag threshold: worsening course,
# functional impact, or failed relief — not plain intensity adjectives.
ADVISORY_PATTERNS = [
    r"\bgetting worse\b",
    r"\bworse than usual\b",
    r"\bworse every\b",
    r"\bcan'?t cope\b",
    r"\bcan'?t function\b",
    r"\bmissed work\b",
    r"\bmissed school\b",
    r"\bpainkillers? (don'?t|doesn'?t|not) work\w*\b",
    r"\bnothing helps\b",
    r"\bnot working\b.*\b(pain|cramps?)\b",
    r"\b(pain|cramps?)\b.*\bnot working\b",
]


def classify_soft_risk(message: Optional[str]) -> str:
    """Return the soft-risk class for a message (Step 5).

    Advisory escalation is checked before bare drug mentions so that
    failed-relief reports ("painkillers don't work") read as escalation,
    not as dosage questions. Pure dosage questions carry no advisory
    words and still route to medication.
    """
    msg = (message or "").strip().lower()
    if _matches(DIAGNOSIS_PATTERNS, msg):
        return RISK_DIAGNOSIS
    if _matches(ADVISORY_PATTERNS, msg):
        return RISK_ADVISORY
    if _matches(MEDICATION_PATTERNS, msg):
        return RISK_MEDICATION
    return RISK_NONE


def _matches(patterns: List[str], msg: str) -> bool:
    return any(re.search(p, msg) for p in patterns)


# Topic -> build_care_context intent: the context branch carrying the
# fields the topic's composer needs. Client intent is NOT used here;
# topic is authoritative (Step 3).
TOPIC_CONTEXT_INTENT = {
    SYMPTOM: "symptom_insight",
    MOOD: "symptom_insight",
    THERAPY: "pain_help",
    LOG_LOOKUP: "symptom_insight",
}


def classify_care_topic(
    message: Optional[str],
    intent_hint: Optional[str] = None,
    recent_turns: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Deterministically classify a Care message into a topic.

    Precedence: follow-up inheritance (when session context exists) >
    out-of-scope > device > prediction > cycle_status > log_lookup >
    therapy > symptom > mood > explicit-hint/intent default >
    wellness_general.
    """
    msg = (message or "").strip().lower()
    turns = list(recent_turns or [])

    # Follow-up shorthand inherits the conversation topic.
    if turns and _matches(FOLLOWUP_PATTERNS, msg):
        for turn in reversed(turns):
            topic = (turn or {}).get("topic")
            if topic in CARE_TOPICS:
                return topic

    if _matches(OUT_OF_SCOPE_PATTERNS, msg):
        return OUT_OF_SCOPE
    if _matches(DEVICE_PATTERNS, msg):
        return DEVICE
    if _matches(PREDICTION_PATTERNS, msg):
        return PREDICTION
    if _matches(CYCLE_STATUS_PATTERNS, msg):
        return CYCLE_STATUS
    if _matches(LOG_LOOKUP_PATTERNS, msg):
        return LOG_LOOKUP
    if _matches(THERAPY_PATTERNS, msg):
        return THERAPY
    if _matches(SYMPTOM_PATTERNS, msg):
        return SYMPTOM
    if _matches(MOOD_PATTERNS, msg):
        return MOOD

    hinted = INTENT_TOPIC_HINT.get(intent_hint or "")
    if hinted is not None:
        # cycle_insight refines to prediction on timing words (already
        # checked above, so reaching here means plain cycle status).
        return hinted
    return WELLNESS_GENERAL

import re
import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device
from app.services.ai_context import build_care_context
from app.services.ai_provider import MockAIProvider, get_ai_provider
from app.services.care_composer import (
    compose_ai_reply,
    cross_check_therapy_profile,
    validate_explained_text,
    validate_followup,
)
from app.services.care_topics import (
    DEVICE,
    LOG_LOOKUP,
    MOOD,
    OUT_OF_SCOPE,
    PREDICTION,
    CYCLE_STATUS,
    SYMPTOM,
    THERAPY,
    RISK_ADVISORY,
    RISK_DIAGNOSIS,
    RISK_MEDICATION,
    TOPIC_CONTEXT_INTENT,
    classify_care_topic,
    classify_soft_risk,
)
from app.services.summary import get_current_cycle_summary

MEDICAL_DISCLAIMER = (
    "MenoMate provides educational wellness insights and does not provide medical diagnoses "
    "or substitute for professional healthcare. Always seek clinical advice for severe or unexpected symptoms."
)

OUT_OF_SCOPE_RESPONSE = (
    "I'm here to help with your menstrual wellness, cycle data, symptoms, and MenoMate features. "
    "I can't help with unrelated topics."
)

DIAGNOSIS_FRAME = (
    "I can't diagnose conditions or tell you what a specific symptom means as an illness — "
    "that needs a clinician who can evaluate you directly. What I can do is help you track "
    "what you've logged so you have clear patterns to discuss with them."
)

MEDICATION_FRAME = (
    "I can't recommend medications, doses, or supplements — those decisions need a clinician "
    "or pharmacist. For general comfort, gentle warmth, rest, or light movement are safe options, "
    "and logging what you try helps track what works for you."
)

ADVISORY_LEAD = (
    "That sounds really tough, and worth taking seriously. "
)

# Step 6 — semantic action vocabulary. The backend chooses action IDs
# deterministically per topic/tier/state; the model never chooses actions.
# Labels are user-facing chip text; the UI routes on `id` only.
ACTION_OPEN_LOGGER = "open_logger"
ACTION_OPEN_CALENDAR = "open_calendar"
ACTION_OPEN_HISTORY = "open_history"
ACTION_CONNECT_WEARABLE = "connect_wearable"
ACTION_LOG_PERIOD_START = "log_period_start"
ACTION_VIEW_THERAPY = "view_therapy"
ACTION_SEEK_EMERGENCY = "seek_emergency_care"
ACTION_CALL_DOCTOR = "call_doctor"

ACTION_LABELS = {
    ACTION_OPEN_LOGGER: "Log Symptoms",
    ACTION_OPEN_CALENDAR: "View Calendar",
    ACTION_OPEN_HISTORY: "History",
    ACTION_CONNECT_WEARABLE: "Connect Wearable",
    ACTION_LOG_PERIOD_START: "Log Period Start",
    ACTION_VIEW_THERAPY: "Therapy Controls",
    ACTION_SEEK_EMERGENCY: "Seek Emergency Care",
    ACTION_CALL_DOCTOR: "Call Doctor / Urgent Care",
}

TIER_INFO = "info"
TIER_ADVISORY = "advisory"
TIER_URGENT = "urgent"


def _actions(*ids: str, labels: Optional[Dict[str, str]] = None) -> List[Dict[str, str]]:
    """Build action objects, capped at 3. Per-call `labels` override the
    default chip text for an id (used for the profile-specific therapy
    chip) without changing routing."""
    seen: List[Dict[str, str]] = []
    for action_id in ids:
        if action_id in [a["id"] for a in seen]:
            continue
        label = (labels or {}).get(action_id, ACTION_LABELS[action_id])
        seen.append({"id": action_id, "label": label})
        if len(seen) >= 3:
            break
    return seen

RED_FLAG_PATTERNS = [
    r"\b(unbearable pain|excruciating|can't walk|cannot walk|cant walk|worst pain)\b",
    r"\b(fainted|fainting|passed out|blacked out|loss of consciousness)\b",
    r"\b(chest pain|shortness of breath|trouble breathing|difficulty breathing)\b",
    r"\b(heavy bleeding|soaking a pad|soaking through|hemorrhage|huge blood clots)\b",
    r"\b(sudden severe pain|one-sided pain|sharp stabbing pain in side)\b",
    r"\b(high fever.*(pain|abdomen|pelvi)|(pain|abdomen|pelvi).*high fever)\b",
]

RED_FLAG_RESPONSE = (
    "URGENT CLINICAL SAFETY ADVISORY: Your message mentions severe or potentially high-risk symptoms "
    "(such as severe/sudden pain, fainting, breathing difficulties, or unusually heavy bleeding). "
    "MenoMate is an educational wellness tool and cannot provide emergency medical care or clinical diagnoses. "
    "Please seek immediate medical attention, contact emergency services, or visit the nearest emergency medical facility right away."
)


async def handle_care_interaction(
    db: AsyncSession,
    user_id: uuid.UUID,
    intent: Any,
    user_message: Optional[str] = None,
    recent_turns: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Care interaction router:
    1. Deterministic red-flag triage: intercepts medical emergencies before any other processing.
    2. Deterministic topic classification (Step 2): the same semantic
       question reaches the same topic whether it came from a chip or
       free text. Client intent is a hint only. Cycle-fact topics and
       device topics are answered deterministically; out-of-scope gets a
       fixed refusal without invoking AI.
    3. Context-tailored guidance queried through AI provider.
    4. Guarantees truthful is_ai_generated flag and safety disclaimers.

    recent_turns (Step 1) is transient active-session context: it is
    forwarded to the AI provider inside the prompt payload only and is
    never stored anywhere.
    """
    intent_str = intent.value if hasattr(intent, "value") else str(intent)
    msg = (user_message or "").strip().lower()
    # Defensive bound on transient conversation context (client keeps 4).
    turns = list(recent_turns or [])[-10:]

    # --- 1. Red-Flag Safety Triage (Deterministic Priority) ---
    for pattern in RED_FLAG_PATTERNS:
        if re.search(pattern, msg):
            return {
                "intent": intent_str,
                "response_text": RED_FLAG_RESPONSE,
                "is_ai_generated": False,
                "tier": TIER_URGENT,
                "actions": _actions(ACTION_SEEK_EMERGENCY, ACTION_CALL_DOCTOR),
                "disclaimer": MEDICAL_DISCLAIMER,
            }

    # --- 2. Deterministic Topic + Soft-Risk Routing (Steps 2 & 5) ---
    # Safety (step 1 red flags) already ran above and always takes precedence.
    # Soft-risk interception runs before normal generation: diagnosis and
    # medication asks get fixed frames with no AI; advisory escalation gets
    # a fixed caution lead plus validated educational context.
    topic = classify_care_topic(msg, intent_hint=intent_str, recent_turns=turns)
    risk = classify_soft_risk(user_message)

    if risk == RISK_DIAGNOSIS:
        return {
            "intent": intent_str,
            "response_text": DIAGNOSIS_FRAME,
            "is_ai_generated": False,
            "tier": TIER_ADVISORY,
            "actions": _actions(ACTION_OPEN_LOGGER),
            "disclaimer": MEDICAL_DISCLAIMER,
        }

    if risk == RISK_MEDICATION:
        return {
            "intent": intent_str,
            "response_text": MEDICATION_FRAME,
            "is_ai_generated": False,
            "tier": TIER_ADVISORY,
            "actions": _actions(ACTION_OPEN_LOGGER),
            "disclaimer": MEDICAL_DISCLAIMER,
        }

    advisory = risk == RISK_ADVISORY

    if topic == OUT_OF_SCOPE:
        return {
            "intent": intent_str,
            "response_text": OUT_OF_SCOPE_RESPONSE,
            "is_ai_generated": False,
            "tier": TIER_INFO,
            "actions": [],
            "disclaimer": MEDICAL_DISCLAIMER,
        }

    if topic in (CYCLE_STATUS, PREDICTION):
        summary = await get_current_cycle_summary(db, user_id)
        if not summary.get("has_data"):
            return {
                "intent": intent_str,
                "response_text": "You have not logged a period yet. Complete onboarding or log a period start to see cycle projections.",
                "is_ai_generated": False,
                "tier": TIER_INFO,
                "actions": _actions(ACTION_LOG_PERIOD_START),
                "disclaimer": MEDICAL_DISCLAIMER,
            }

        cycle_day = summary["current_cycle_day"]
        phase = summary["phase"]
        next_p = summary["predicted_next_period"]
        days_left = summary["days_until_next_period"]
        conf = summary["prediction_confidence"]
        pred_status = summary.get("prediction_status")

        if next_p:
            if pred_status == "awaiting_next_start":
                # Rule F: neutral phrasing, no negative countdown.
                timeline_str = f"(expected around {next_p}, confidence: {conf})"
                reply = (
                    f"You are currently on Day {cycle_day} of your cycle, in the {phase.capitalize()} phase. "
                    f"Your next estimated period was expected around {next_p} {timeline_str}. "
                    "Log your next period when it starts."
                )
            elif days_left is None:
                timeline_str = f"(predicted: {next_p}, confidence: {conf})"
                reply = (
                    f"You are currently on Day {cycle_day} of your cycle, in the {phase.capitalize()} phase. "
                    f"Your next estimated period is around {next_p} {timeline_str}."
                )
            elif days_left == 0:
                timeline_str = f"(predicted for today, confidence: {conf})"
                reply = (
                    f"You are currently on Day {cycle_day} of your cycle, in the {phase.capitalize()} phase. "
                    f"Your next estimated period is around {next_p} {timeline_str}."
                )
            else:
                timeline_str = f"(in approximately {days_left} days, confidence: {conf})"
                reply = (
                    f"You are currently on Day {cycle_day} of your cycle, in the {phase.capitalize()} phase. "
                    f"Your next estimated period is around {next_p} {timeline_str}."
                )
        else:
            reply = (
                f"You are currently on Day {cycle_day} of your cycle, in the {phase.capitalize()} phase. "
                "More cycle logs are needed before a reliable next-period prediction can be estimated."
            )

        return {
            "intent": intent_str,
            "response_text": reply,
            "is_ai_generated": False,
            "tier": TIER_INFO,
            "actions": _actions(
                ACTION_OPEN_CALENDAR,
                ACTION_OPEN_HISTORY,
                *(
                    [ACTION_LOG_PERIOD_START]
                    if pred_status == "awaiting_next_start"
                    else []
                ),
            ),
            "disclaimer": MEDICAL_DISCLAIMER,
        }

    if topic == DEVICE:
        dev_stmt = select(Device).where(Device.user_id == user_id)
        dev_res = await db.execute(dev_stmt)
        devices: List[Device] = list(dev_res.scalars().all())

        if devices:
            dev_names = ", ".join([d.name or d.device_identifier for d in devices])
            reply = (
                f"You have {len(devices)} device(s) linked: {dev_names}. "
                "Ensure Bluetooth is enabled on your mobile device to establish a direct BLE link for thermal and vibration therapy."
            )
        else:
            reply = (
                "You do not have any MenoMate wearable devices paired yet. "
                "Go to Settings > Devices in the mobile app to pair your wearable via Bluetooth."
            )
        return {
            "intent": intent_str,
            "response_text": reply,
            "is_ai_generated": False,
            "tier": TIER_INFO,
            "actions": _actions(ACTION_CONNECT_WEARABLE, ACTION_VIEW_THERAPY),
            "disclaimer": MEDICAL_DISCLAIMER,
        }

    # --- 3. Composed AI Path (Step 3: select-then-enhance) ---
    # Topic selects the context branch and the immutable fact block.
    # The model may phrase/explain; facts, tier, and actions stay
    # deterministic, and model output is validated before use.
    context = await build_care_context(
        db, user_id, intent=TOPIC_CONTEXT_INTENT.get(topic, intent_str)
    )
    # Transient session context only: part of this prompt payload, never stored.
    context["recent_turns"] = turns
    # Deterministic routing outcome travels with the context.
    context["topic"] = topic
    # Minimality (Steps 7/16): the model gets profile labels and aggregates,
    # never raw hardware numbers from session telemetry.
    context["recent_therapy_sessions"] = [
        {
            "profile": s.get("profile"),
            "pain_before": s.get("pain_before"),
            "pain_after": s.get("pain_after"),
            "feedback": s.get("feedback"),
        }
        for s in (context.get("recent_therapy_sessions") or [])
        if isinstance(s, dict)
    ]
    composed = compose_ai_reply(topic, context)
    prompt_text = user_message or f"Intent: {intent_str}"

    if not composed.enhance:
        # Deterministic read-out (log_lookup): exact stored values, no AI.
        return {
            "intent": intent_str,
            "response_text": composed.base_text or "",
            "is_ai_generated": False,
            "tier": TIER_INFO,
            "actions": _actions(ACTION_OPEN_LOGGER),
            "disclaimer": MEDICAL_DISCLAIMER,
        }

    provider = get_ai_provider()

    care_res = await provider.generate_care_response(
        context=context,
        user_message=prompt_text,
        intent=intent_str,
        facts=composed.facts,
        topic=topic,
        recent_turns=turns,
    )
    ai_reply = care_res.get("response_text", "")
    followup = care_res.get("followup")
    therapy_profile = cross_check_therapy_profile(
        care_res.get("therapy_profile"), composed.facts
    )
    is_ai = care_res.get("is_ai_generated", False)

    # Validation gates MODEL output only: deterministic providers (Mock)
    # render composer frames that are fact-built by construction.
    if is_ai and not validate_explained_text(ai_reply, composed.facts):
        # Reject invented numbers/dates/clinical overreach: fall back to
        # the deterministic Mock reply. Never expose validation internals.
        mock = MockAIProvider()
        ai_reply = await mock.generate_reply(context, prompt_text, intent_str)
        followup = None
        therapy_profile = None
        is_ai = False

    if (
        is_ai
        and followup
        and composed.followup_allowed
        and validate_followup(followup)
    ):
        ai_reply = f"{ai_reply.rstrip()}\n\n{followup.strip()}"

    if advisory:
        # Advisory tier (Step 5): fixed caution lead stays even when the
        # educational body below is model-phrased or Mock-framed. The
        # dedicated tier field reaches the contract in Step 6.
        ai_reply = f"{ADVISORY_LEAD}{ai_reply.lstrip()}"


    action_ids: List[str] = []
    action_labels: Dict[str, str] = {}
    if therapy_profile:
        action_ids.append(ACTION_VIEW_THERAPY)
        action_labels[ACTION_VIEW_THERAPY] = (
            f"Start {therapy_profile.capitalize()} Thermal Therapy"
        )
    elif topic == THERAPY:
        # Therapy topic without a confirmed profile: offer the
        # non-executable path, never a fake start chip.
        action_ids.append(ACTION_CONNECT_WEARABLE)
    if topic in (SYMPTOM, MOOD, LOG_LOOKUP) or advisory:
        action_ids.append(ACTION_OPEN_LOGGER)
    if topic == THERAPY and ACTION_OPEN_LOGGER not in action_ids:
        action_ids.append(ACTION_OPEN_LOGGER)

    return {
        "intent": intent_str,
        "response_text": ai_reply,
        "is_ai_generated": is_ai,
        "tier": TIER_ADVISORY if advisory else TIER_INFO,
        "actions": _actions(*action_ids, labels=action_labels),
        "disclaimer": MEDICAL_DISCLAIMER,
        "therapy_profile": therapy_profile,
    }

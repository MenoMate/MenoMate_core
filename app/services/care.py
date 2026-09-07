import re
import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device
from app.schemas.care import CareIntentEnum
from app.services.ai_context import build_care_context
from app.services.ai_provider import get_ai_provider
from app.services.summary import get_current_cycle_summary

MEDICAL_DISCLAIMER = (
    "MenoMate provides educational wellness insights and does not provide medical diagnoses "
    "or substitute for professional healthcare. Always seek clinical advice for severe or unexpected symptoms."
)

RED_FLAG_PATTERNS = [
    r"\b(unbearable pain|excruciating|can't walk|cannot walk|worst pain)\b",
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
) -> Dict[str, Any]:
    """
    Care interaction router:
    1. Deterministic red-flag triage: intercepts medical emergencies before any other processing.
    2. Explicit structured intent priority: handles cycle_insight and device_help deterministically.
       Keyword inference is used only as fallback when intent is 'other'.
    3. Context-tailored guidance queried through AI provider.
    4. Guarantees truthful is_ai_generated flag and safety disclaimers.
    """
    intent_str = intent.value if hasattr(intent, "value") else str(intent)
    msg = (user_message or "").strip().lower()

    # --- 1. Red-Flag Safety Triage (Deterministic Priority) ---
    for pattern in RED_FLAG_PATTERNS:
        if re.search(pattern, msg):
            return {
                "intent": intent_str,
                "response_text": RED_FLAG_RESPONSE,
                "is_ai_generated": False,
                "suggested_actions": ["Seek Emergency Care", "Call Doctor / Urgent Care"],
                "disclaimer": MEDICAL_DISCLAIMER,
            }

    # --- 2. Deterministic Structured Inquiries vs Fallback ---
    is_cycle_inquiry = (intent_str == "cycle_insight") or (
        intent_str == "other"
        and bool(re.search(r"\b(next period|cycle day|phase|when is my period|period date)\b", msg))
    )
    if is_cycle_inquiry:
        summary = await get_current_cycle_summary(db, user_id)
        if not summary.get("has_data"):
            return {
                "intent": intent_str,
                "response_text": "You have not logged a period yet. Complete onboarding or log a period start to see cycle projections.",
                "is_ai_generated": False,
                "suggested_actions": ["Log Period Start"],
                "disclaimer": MEDICAL_DISCLAIMER,
            }

        cycle_day = summary["current_cycle_day"]
        phase = summary["phase"]
        next_p = summary["predicted_next_period"]
        days_left = summary["days_until_next_period"]
        conf = summary["prediction_confidence"]

        if next_p:
            if days_left is not None and days_left < 0:
                timeline_str = f"({abs(days_left)} days overdue, predicted: {next_p}, confidence: {conf})"
            elif days_left == 0:
                timeline_str = f"(predicted for today, confidence: {conf})"
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
            "suggested_actions": ["View Calendar", "Log Symptoms"],
            "disclaimer": MEDICAL_DISCLAIMER,
        }

    is_device_inquiry = (intent_str == "device_help") or (
        intent_str == "other"
        and bool(re.search(r"\b(device|esp32|bluetooth|pair|ble|wearable)\b", msg))
    )
    if is_device_inquiry:
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
            "suggested_actions": ["Pair Device", "Therapy Controls"],
            "disclaimer": MEDICAL_DISCLAIMER,
        }

    # --- 3. Personalized Inquiries -> AI Provider with Compact Context ---
    context = await build_care_context(db, user_id, intent=intent_str)
    provider = get_ai_provider()
    prompt_text = user_message or f"Intent: {intent_str}"

    care_res = await provider.generate_care_response(
        context=context,
        user_message=prompt_text,
        intent=intent_str,
    )
    ai_reply = care_res.get("response_text", "")
    therapy_profile = care_res.get("therapy_profile")
    is_ai = care_res.get("is_ai_generated", False)

    suggested = []
    if therapy_profile:
        suggested.append(f"Start {therapy_profile.capitalize()} Thermal Therapy")
    elif "cramp" in prompt_text.lower() or intent_str in ("pain_help", "therapy", "therapy_recommendation"):
        suggested.append("Start Thermal Therapy")
    suggested.append("Log Daily Symptoms")

    return {
        "intent": intent_str,
        "response_text": ai_reply,
        "is_ai_generated": is_ai,
        "suggested_actions": suggested,
        "disclaimer": MEDICAL_DISCLAIMER,
        "therapy_profile": therapy_profile,
    }

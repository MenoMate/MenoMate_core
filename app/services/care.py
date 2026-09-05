import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device
from app.services.ai_context import build_care_context
from app.services.ai_provider import get_ai_provider
from app.services.summary import get_current_cycle_summary

MEDICAL_DISCLAIMER = (
    "MenoMate provides educational wellness insights and does not provide medical diagnoses "
    "or substitute for professional healthcare. Always seek clinical advice for severe or unexpected symptoms."
)


async def handle_care_interaction(
    db: AsyncSession,
    user_id: uuid.UUID,
    intent: str,
    user_message: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Care interaction router:
    1. Resolves simple questions deterministically using backend calculations.
    2. Builds compact intent-specific context and queries the AI provider for personalized guidance.
    3. Guarantees non-diagnostic safety guardrails and medical disclaimers.
    """
    msg = (user_message or "").strip().lower()

    # --- 1. Deterministic Question Resolution ---
    import re
    
    is_cycle_inquiry = intent == "cycle_insight" or bool(
        re.search(r"\b(next period|cycle day|phase|when is my period|period date)\b", msg)
    )
    if is_cycle_inquiry:
        summary = await get_current_cycle_summary(db, user_id)
        if not summary.get("has_data"):
            return {
                "intent": intent,
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
            reply = (
                f"You are currently on Day {cycle_day} of your cycle, in the {phase.capitalize()} phase. "
                f"Your next estimated period is around {next_p} (in approximately {days_left} days, confidence: {conf})."
            )
        else:
            reply = (
                f"You are currently on Day {cycle_day} of your cycle, in the {phase.capitalize()} phase. "
                "More cycle logs are needed before a reliable next-period prediction can be estimated."
            )

        return {
            "intent": intent,
            "response_text": reply,
            "is_ai_generated": False,
            "suggested_actions": ["View Calendar", "Log Symptoms"],
            "disclaimer": MEDICAL_DISCLAIMER,
        }

    is_device_inquiry = intent == "device_help" or bool(
        re.search(r"\b(device|esp32|bluetooth|pair|ble|wearable)\b", msg)
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
            "intent": intent,
            "response_text": reply,
            "is_ai_generated": False,
            "suggested_actions": ["Pair Device", "Therapy Controls"],
            "disclaimer": MEDICAL_DISCLAIMER,
        }

    # --- 2. Personalized Inquiries -> AI Provider with Compact Intent-Tailored Context ---
    context = await build_care_context(db, user_id, intent=intent)
    provider = get_ai_provider()
    prompt_text = user_message or f"Intent: {intent}"
    
    ai_reply = await provider.generate_reply(
        context=context,
        user_message=prompt_text,
        intent=intent,
    )

    suggested = []
    if "cramp" in prompt_text.lower() or intent in ("pain_help", "therapy"):
        suggested.append("Start Thermal Therapy")
    suggested.append("Log Daily Symptoms")

    return {
        "intent": intent,
        "response_text": ai_reply,
        "is_ai_generated": True,
        "suggested_actions": suggested,
        "disclaimer": MEDICAL_DISCLAIMER,
    }

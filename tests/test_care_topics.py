"""Step 2 — deterministic topic classification (pure unit tests, no DB)."""

from app.services.care_topics import (
    CYCLE_STATUS,
    DEVICE,
    LOG_LOOKUP,
    MOOD,
    OUT_OF_SCOPE,
    PREDICTION,
    SYMPTOM,
    THERAPY,
    WELLNESS_GENERAL,
    classify_care_topic,
)


def test_chip_vs_freetext_same_topic():
    # The same semantic question classifies identically whether it came
    # from the cycle_insight chip or free text (wellness_help default).
    assert (
        classify_care_topic("What's happening today?", intent_hint="cycle_insight")
        == classify_care_topic("What's happening today?", intent_hint="wellness_help")
        == CYCLE_STATUS
    )


def test_cycle_fact_questions_route_regardless_of_hint():
    for hint in ("wellness_help", "other", "symptom_insight", "general_inquiry", None):
        assert (
            classify_care_topic("What day of my cycle am I on?", intent_hint=hint)
            == CYCLE_STATUS
        ), hint
        assert (
            classify_care_topic("When is my next period?", intent_hint=hint)
            == PREDICTION
        ), hint
        assert (
            classify_care_topic("Am I bleeding today?", intent_hint=hint)
            == CYCLE_STATUS
        ), hint
        assert (
            classify_care_topic("What's happening in my cycle?", intent_hint=hint)
            == CYCLE_STATUS
        ), hint


def test_device_topic():
    assert classify_care_topic("How do I pair my wearable?", intent_hint="wellness_help") == DEVICE
    assert classify_care_topic("bluetooth wont connect", intent_hint="other") == DEVICE
    assert classify_care_topic("hello", intent_hint="device_help") == DEVICE


def test_therapy_vs_symptom_split():
    assert (
        classify_care_topic("What setting usually helps with my cramps?", intent_hint="pain_help")
        == THERAPY
    )
    assert (
        classify_care_topic("I'm having terrible cramps and lower back pain", intent_hint="pain_help")
        == SYMPTOM
    )
    assert classify_care_topic("Why am I having bloating and headaches?") == SYMPTOM
    assert classify_care_topic("I feel anxious and moody today") == MOOD


def test_log_lookup_topic():
    assert classify_care_topic("did I log pain yesterday") == LOG_LOOKUP
    assert classify_care_topic("What did I log on Tuesday?") == LOG_LOOKUP


def test_out_of_scope_topic():
    assert (
        classify_care_topic("Write me a Python program to sort numbers", intent_hint="other")
        == OUT_OF_SCOPE
    )
    assert classify_care_topic("Who won the football match?", intent_hint="wellness_help") == OUT_OF_SCOPE


def test_unrecognized_defaults_to_wellness_general():
    assert classify_care_topic("Hello", intent_hint="wellness_help") == WELLNESS_GENERAL
    assert classify_care_topic("", intent_hint="wellness_help") == WELLNESS_GENERAL
    assert classify_care_topic(None, intent_hint="other") == WELLNESS_GENERAL


def test_hint_only_used_when_text_is_ambiguous():
    assert classify_care_topic("hello", intent_hint="cycle_insight") == CYCLE_STATUS
    assert classify_care_topic("hello", intent_hint="therapy_recommendation") == THERAPY
    assert classify_care_topic("hello", intent_hint="pain_help") == WELLNESS_GENERAL


def test_followup_inherits_topic_from_recent_turns():
    turns = [
        {"role": "user", "text": "My cramps are worse today.", "topic": "symptom"},
        {"role": "care", "text": "Sorry to hear that.", "topic": "symptom"},
    ]
    assert classify_care_topic("What about yesterday?", recent_turns=turns) == SYMPTOM
    assert classify_care_topic("that symptom is worse", recent_turns=turns) == SYMPTOM


def test_followup_without_turns_falls_through():
    assert classify_care_topic("What about yesterday?") == LOG_LOOKUP
    assert classify_care_topic("What about it?") == WELLNESS_GENERAL

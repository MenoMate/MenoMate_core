"""Explainable longitudinal pattern and insights engine for MenoMate Care.

Computes user-specific symptom, cycle-day, pain-trend, mood/pain co-occurrence,
and device-session patterns strictly from authenticated user records.

Product-level evidence heuristics (not clinical validation thresholds):
- Minimum 3 logged days before reporting frequent-symptom patterns.
- Minimum 2 observed cycles and 2 cycle occurrences before reporting cycle-day
  symptom clustering.
- Minimum 2 pain-logged days in both comparison windows before reporting a
  pain severity change.
- Minimum 2 therapy sessions before reporting device setting or comfort trends.

Strict epistemic rules:
- Missing logs or null pain values are NEVER imputed as 0 or symptom-free.
- Incomplete cycles (period_end is None or open-ended) are never treated as
  completed cycle intervals.
- Never claims causation, never infers hormones, and never labels repeated
  symptoms as harmless or clinically normal.
"""

from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.models.cycle import Cycle
from app.models.daily_log import DailyLog
from app.models.therapy_session import TherapySession
from app.schemas.daily_log import decode_moods
from app.schemas.insights import (
    InsightRecord,
    PatternAnalysisResult,
    TrackingCompleteness,
)

# Conservative product-level evidence thresholds (configurable)
MIN_LOGS_FOR_SYMPTOM_FREQUENCY = 3
MIN_CYCLES_FOR_CYCLE_PATTERN = 2
MIN_OCCURRENCES_FOR_CYCLE_DAY_PATTERN = 2
MIN_PAIN_LOGS_PER_WINDOW_FOR_TREND = 2
MIN_COOCCURRENCE_FOR_MOOD_PAIN = 2
MIN_SESSIONS_FOR_DEVICE_PATTERN = 2
PAIN_TREND_DELTA_THRESHOLD = 1.0


def _confidence_from_count(count: int, high_at: int = 5, mod_at: int = 3) -> str:
    if count >= high_at:
        return "high"
    if count >= mod_at:
        return "moderate"
    return "low"


def map_date_to_cycle(
    log_date: date,
    cycles_asc: Sequence[Cycle],
    today: date,
) -> Optional[Tuple[int, int]]:
    """Map a log_date to (cycle_index, cycle_day_1_based) using observed period_starts.

    Only considers cycles with period_start <= today (never future periods).
    Returns None if log_date precedes the user's earliest observed period_start.
    """
    valid = [c for c in cycles_asc if c.period_start <= today]
    if not valid:
        return None
    matched_idx: Optional[int] = None
    for idx, c in enumerate(valid):
        if c.period_start <= log_date:
            matched_idx = idx
        else:
            break
    if matched_idx is None:
        return None
    cycle_day = (log_date - valid[matched_idx].period_start).days + 1
    return matched_idx, cycle_day


def _cycle_day_bucket(cycle_day: int) -> str:
    if cycle_day <= 2:
        return "days 1-2"
    if cycle_day <= 5:
        return "days 3-5"
    if cycle_day <= 12:
        return "days 6-12"
    if cycle_day <= 16:
        return "days 13-16"
    return f"day {cycle_day}"


def analyze_user_patterns(
    *,
    cycles: Sequence[Cycle],
    logs: Sequence[DailyLog],
    sessions: Sequence[TherapySession],
    today: date,
    window_days: int = 90,
) -> PatternAnalysisResult:
    """Analyze longitudinal patterns from user records without inventing missing data."""
    cycles_asc = sorted(
        [c for c in cycles if c.period_start <= today],
        key=lambda c: c.period_start,
    )
    complete_cycles = [c for c in cycles_asc if c.period_end is not None]
    incomplete_cycles = [c for c in cycles_asc if c.period_end is None]

    cutoff = today - timedelta(days=window_days - 1)
    window_logs = [l for l in logs if cutoff <= l.log_date <= today]
    pain_logs = [l for l in window_logs if l.pain is not None]

    missing_notes: List[str] = []
    if len(window_logs) == 0:
        missing_notes.append(f"No daily logs recorded in the last {window_days} days.")
    elif len(window_logs) < MIN_LOGS_FOR_SYMPTOM_FREQUENCY:
        missing_notes.append(
            f"Only {len(window_logs)} daily log(s) recorded in the last {window_days} days."
        )
    if incomplete_cycles:
        missing_notes.append(
            f"{len(incomplete_cycles)} cycle(s) do not have a recorded end date and are treated as incomplete."
        )

    coverage_ratio = round(len(window_logs) / max(window_days, 1), 2)
    completeness = TrackingCompleteness(
        logged_days=len(window_logs),
        window_days=window_days,
        coverage_ratio=coverage_ratio,
        complete_cycles=len(complete_cycles),
        incomplete_cycles=len(incomplete_cycles),
        pain_logged_days=len(pain_logs),
        missing_data_notes=missing_notes,
    )
    comp_dict = completeness.model_dump()

    insights: List[InsightRecord] = []
    insufficient_reasons: List[str] = []

    # 1. Frequent symptoms (only from explicitly logged DailyLog + SymptomLog rows)
    sym_counts: Counter[str] = Counter()
    sym_severities: Dict[str, List[int]] = defaultdict(list)
    sym_log_ids: Dict[str, List[str]] = defaultdict(list)
    for l in window_logs:
        for s in l.symptoms or []:
            sym_counts[s.symptom_type] += 1
            sym_log_ids[s.symptom_type].append(f"log:{l.id}")
            if s.severity is not None:
                sym_severities[s.symptom_type].append(s.severity)

    frequent_symptoms_list: List[Dict[str, Any]] = []
    for sym_type, cnt in sym_counts.most_common(5):
        sevs = sym_severities.get(sym_type, [])
        avg_sev = round(sum(sevs) / len(sevs), 1) if sevs else None
        frequent_symptoms_list.append(
            {
                "symptom": sym_type,
                "count": cnt,
                "avg_severity": avg_sev,
            }
        )

    if len(window_logs) >= MIN_LOGS_FOR_SYMPTOM_FREQUENCY and frequent_symptoms_list:
        top = frequent_symptoms_list[0]
        if top["count"] >= 2:
            sev_note = (
                f" with average severity {top['avg_severity']}/5"
                if top["avg_severity"] is not None
                else ""
            )
            insights.append(
                InsightRecord(
                    insight_id=f"freq_symptom_{top['symptom']}",
                    insight_type="frequent_symptom",
                    title=f"Most frequently logged symptom: {top['symptom']}",
                    explanation=(
                        f"You logged {top['symptom']} on {top['count']} of {len(window_logs)} "
                        f"logged days in the last {window_days} days{sev_note}."
                    ),
                    time_period=f"last {window_days} days",
                    supporting_counts={
                        "occurrences": top["count"],
                        "logged_days": len(window_logs),
                        "avg_severity": top["avg_severity"],
                    },
                    data_completeness=comp_dict,
                    confidence=_confidence_from_count(top["count"]),
                    source_record_ids=sym_log_ids[top["symptom"]][:10],
                    caveat=(
                        f"Based only on {len(window_logs)} logged days; unlogged days are not assumed symptom-free."
                    ),
                )
            )
    else:
        insufficient_reasons.append(
            f"Need at least {MIN_LOGS_FOR_SYMPTOM_FREQUENCY} logged days to summarize symptom frequency."
        )

    # 2. Cycle-day symptom clustering across observed cycles
    cycle_day_patterns: List[Dict[str, Any]] = []
    if len(cycles_asc) >= MIN_CYCLES_FOR_CYCLE_PATTERN:
        # Map (symptom, bucket) -> set of cycle indices
        bucket_cycles: Dict[Tuple[str, str], set[int]] = defaultdict(set)
        bucket_log_ids: Dict[Tuple[str, str], List[str]] = defaultdict(list)
        for l in logs:
            mapped = map_date_to_cycle(l.log_date, cycles_asc, today)
            if mapped is None:
                continue
            c_idx, c_day = mapped
            bucket = _cycle_day_bucket(c_day)
            for s in l.symptoms or []:
                bucket_cycles[(s.symptom_type, bucket)].add(c_idx)
                bucket_log_ids[(s.symptom_type, bucket)].append(f"log:{l.id}")

        sorted_buckets = sorted(
            bucket_cycles.items(),
            key=lambda kv: len(kv[1]),
            reverse=True,
        )
        for (sym_type, bucket), c_indices in sorted_buckets[:3]:
            if len(c_indices) >= MIN_OCCURRENCES_FOR_CYCLE_DAY_PATTERN:
                total_c = len(cycles_asc)
                cycle_day_patterns.append(
                    {
                        "symptom": sym_type,
                        "cycle_day_window": bucket,
                        "cycles_with_symptom": len(c_indices),
                        "observed_cycles": total_c,
                    }
                )
                insights.append(
                    InsightRecord(
                        insight_id=f"cycle_day_{sym_type}_{bucket.replace(' ', '_')}",
                        insight_type="cycle_day_pattern",
                        title=f"{sym_type.capitalize()} around {bucket}",
                        explanation=(
                            f"{sym_type.capitalize()} was recorded during {bucket} in "
                            f"{len(c_indices)} of your {total_c} observed cycles."
                        ),
                        time_period=f"{total_c} observed cycles",
                        supporting_counts={
                            "cycles_with_symptom": len(c_indices),
                            "observed_cycles": total_c,
                        },
                        data_completeness=comp_dict,
                        confidence=_confidence_from_count(len(c_indices), high_at=4, mod_at=3),
                        source_record_ids=bucket_log_ids[(sym_type, bucket)][:10],
                        caveat="Reflects logged observations only; unlogged cycles or days are excluded.",
                    )
                )
    else:
        insufficient_reasons.append(
            f"Need at least {MIN_CYCLES_FOR_CYCLE_PATTERN} observed cycles to detect cycle-day symptom patterns."
        )

    # 3. Pain severity trend (most recent cycle vs prior cycles, or recent 30d vs prior 30d)
    pain_trend_dict: Optional[Dict[str, Any]] = None
    if len(cycles_asc) >= 2:
        latest_start = cycles_asc[-1].period_start
        prev_start = cycles_asc[-2].period_start
        recent_pains = [
            l.pain for l in logs if l.pain is not None and l.log_date >= latest_start and l.log_date <= today
        ]
        prev_pains = [
            l.pain for l in logs if l.pain is not None and prev_start <= l.log_date < latest_start
        ]
        if (
            len(recent_pains) >= MIN_PAIN_LOGS_PER_WINDOW_FOR_TREND
            and len(prev_pains) >= MIN_PAIN_LOGS_PER_WINDOW_FOR_TREND
        ):
            rec_avg = round(sum(recent_pains) / len(recent_pains), 1)
            prev_avg = round(sum(prev_pains) / len(prev_pains), 1)
            delta = round(rec_avg - prev_avg, 1)
            direction = (
                "higher"
                if delta >= PAIN_TREND_DELTA_THRESHOLD
                else ("lower" if delta <= -PAIN_TREND_DELTA_THRESHOLD else "similar")
            )
            pain_trend_dict = {
                "recent_avg_pain": rec_avg,
                "previous_avg_pain": prev_avg,
                "delta": delta,
                "direction": direction,
                "recent_count": len(recent_pains),
                "previous_count": len(prev_pains),
            }
            insights.append(
                InsightRecord(
                    insight_id="pain_trend_cycle_compare",
                    insight_type="pain_trend",
                    title="Pain severity compared with previous cycle",
                    explanation=(
                        f"Your average logged pain in the current cycle is {rec_avg}/10 "
                        f"({len(recent_pains)} logs), which is {direction} compared with "
                        f"{prev_avg}/10 ({len(prev_pains)} logs) in your previous cycle."
                    ),
                    time_period="current vs previous cycle",
                    supporting_counts=pain_trend_dict,
                    data_completeness=comp_dict,
                    confidence=_confidence_from_count(min(len(recent_pains), len(prev_pains)), high_at=5, mod_at=3),
                    source_record_ids=[],
                    caveat="Only days with an explicit pain score are averaged; missing pain values are not treated as 0.",
                )
            )
        else:
            insufficient_reasons.append(
                "Insufficient pain logs across both recent and previous cycles to compare pain severity."
            )

    # 4. Mood & pain co-occurrence (descriptive only, never causal)
    mood_pain_patterns: List[Dict[str, Any]] = []
    mood_pains: Dict[str, List[int]] = defaultdict(list)
    for l in window_logs:
        if l.pain is None:
            continue
        for m in (decode_moods(l.mood) or []):
            mood_pains[m].append(l.pain)
    for mood_label, pains in sorted(mood_pains.items(), key=lambda kv: len(kv[1]), reverse=True)[:3]:
        if len(pains) >= MIN_COOCCURRENCE_FOR_MOOD_PAIN:
            avg_p = round(sum(pains) / len(pains), 1)
            mood_pain_patterns.append(
                {
                    "mood": mood_label,
                    "cooccurring_days": len(pains),
                    "avg_pain": avg_p,
                }
            )
    if mood_pain_patterns:
        top_mp = mood_pain_patterns[0]
        insights.append(
            InsightRecord(
                insight_id=f"mood_pain_{top_mp['mood']}",
                insight_type="mood_pain_cooccurrence",
                title=f"Mood & pain logged together: {top_mp['mood']}",
                explanation=(
                    f"You logged mood '{top_mp['mood']}' alongside pain ratings on "
                    f"{top_mp['cooccurring_days']} days (average pain {top_mp['avg_pain']}/10). "
                    "These were recorded on the same days, which does not show cause."
                ),
                time_period=f"last {window_days} days",
                supporting_counts=top_mp,
                data_completeness=comp_dict,
                confidence=_confidence_from_count(top_mp["cooccurring_days"]),
                source_record_ids=[],
                caveat="Co-occurrence in logs does not imply one caused the other.",
            )
        )

    # 5. Device settings & post-session feedback patterns
    device_pref_summary: Optional[Dict[str, Any]] = None
    if len(sessions) >= MIN_SESSIONS_FOR_DEVICE_PATTERN:
        mode_counts: Counter[str] = Counter(s.mode for s in sessions if s.mode)
        heat_counts: Counter[int] = Counter(
            s.requested_heat_level for s in sessions if s.requested_heat_level is not None
        )
        comfortable_modes: Counter[str] = Counter()
        improved_count = 0
        feedback_count = 0
        confirmed_completed = 0
        for s in sessions:
            if s.session_status == "completed":
                confirmed_completed += 1
            if s.feedback or s.comfort_rating or s.noticed_improvement is not None:
                feedback_count += 1
            is_helpful = (
                s.feedback == "just_right"
                or s.comfort_rating == "comfortable"
                or s.noticed_improvement is True
                or (
                    s.pain_before is not None
                    and s.pain_after is not None
                    and s.pain_after < s.pain_before
                )
            )
            if is_helpful and s.mode:
                comfortable_modes[s.mode] += 1
                improved_count += 1

        top_mode = mode_counts.most_common(1)[0][0] if mode_counts else None
        top_heat = heat_counts.most_common(1)[0][0] if heat_counts else None
        top_comfortable = comfortable_modes.most_common(1)[0][0] if comfortable_modes else None

        device_pref_summary = {
            "total_sessions": len(sessions),
            "confirmed_completed_sessions": confirmed_completed,
            "most_selected_mode": top_mode,
            "most_selected_heat_level": top_heat,
            "most_comfortable_mode": top_comfortable,
            "sessions_with_feedback": feedback_count,
            "helpful_sessions": improved_count,
        }

        if top_mode:
            insights.append(
                InsightRecord(
                    insight_id="device_selected_settings",
                    insight_type="device_preference",
                    title="Most selected wearable setting",
                    explanation=(
                        f"Across {len(sessions)} recorded sessions ({confirmed_completed} confirmed completed), "
                        f"you most frequently selected '{top_mode}' mode."
                    ),
                    time_period="recorded device history",
                    supporting_counts={
                        "total_sessions": len(sessions),
                        "confirmed_completed": confirmed_completed,
                        "mode_selections": mode_counts[top_mode],
                    },
                    data_completeness=comp_dict,
                    confidence=_confidence_from_count(len(sessions), high_at=5, mod_at=3),
                    source_record_ids=[f"session:{s.id}" for s in sessions[:5]],
                    caveat="Selected settings reflect user/app requests; physical execution depends on device confirmation.",
                )
            )
        if feedback_count >= MIN_SESSIONS_FOR_DEVICE_PATTERN:
            insights.append(
                InsightRecord(
                    insight_id="device_feedback_pattern",
                    insight_type="session_feedback_pattern",
                    title="Post-session comfort feedback",
                    explanation=(
                        f"You reported comfort or symptom improvement in {improved_count} of "
                        f"{feedback_count} sessions with feedback"
                        + (f" (most often with '{top_comfortable}')." if top_comfortable else ".")
                    ),
                    time_period="recorded feedback history",
                    supporting_counts={
                        "helpful_sessions": improved_count,
                        "sessions_with_feedback": feedback_count,
                    },
                    data_completeness=comp_dict,
                    confidence=_confidence_from_count(feedback_count, high_at=5, mod_at=3),
                    source_record_ids=[f"session:{s.id}" for s in sessions[:5]],
                )
            )
    elif len(sessions) == 0:
        insufficient_reasons.append("No wearable sessions recorded yet.")

    return PatternAnalysisResult(
        insights=insights,
        frequent_symptoms=frequent_symptoms_list,
        cycle_day_symptom_patterns=cycle_day_patterns,
        pain_trend=pain_trend_dict,
        mood_pain_patterns=mood_pain_patterns,
        device_preference_summary=device_pref_summary,
        tracking_completeness=completeness,
        insufficient_data_reasons=insufficient_reasons,
    )

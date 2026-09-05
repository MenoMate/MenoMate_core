from datetime import date, timedelta
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_summary_endpoints(async_client: AsyncClient, auth_headers: dict):
    # 1. Check summary before logging any periods
    init_res = await async_client.get("/api/v1/summary/current", headers=auth_headers)
    assert init_res.status_code == 200
    assert init_res.json()["has_data"] is False

    # 2. Log two periods (e.g. 28 days apart)
    p1_start = date.today() - timedelta(days=32)
    p1_end = date.today() - timedelta(days=28)
    p2_start = date.today() - timedelta(days=4)
    p2_end = date.today() - timedelta(days=1)

    await async_client.post(
        "/api/v1/cycles",
        headers=auth_headers,
        json={"period_start": str(p1_start), "period_end": str(p1_end)},
    )
    await async_client.post(
        "/api/v1/cycles",
        headers=auth_headers,
        json={"period_start": str(p2_start), "period_end": str(p2_end)},
    )

    # Log symptoms for recent days
    await async_client.post(
        "/api/v1/logs",
        headers=auth_headers,
        json={
            "log_date": str(date.today()),
            "pain": 5,
            "symptoms": [{"symptom_type": "cramps", "severity": 6}],
        },
    )

    # 3. Test /summary/current
    curr_res = await async_client.get("/api/v1/summary/current", headers=auth_headers)
    assert curr_res.status_code == 200
    curr_data = curr_res.json()
    assert curr_data["has_data"] is True
    assert curr_data["current_cycle_day"] == 5
    assert curr_data["phase"] in ["menstrual", "follicular"]
    assert curr_data["average_cycle_length"] == 28
    assert "cramps" in curr_data["frequent_symptoms"]

    # 4. Test /summary/history
    hist_res = await async_client.get("/api/v1/summary/history", headers=auth_headers)
    assert hist_res.status_code == 200
    hist_data = hist_res.json()
    assert hist_data["total_periods_logged"] == 2
    assert len(hist_data["history"]) == 2
    assert "cramps" in hist_data["symptom_frequencies"]

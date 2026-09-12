"""Acceptance test against the running local demo; leaves it in the baseline scenario."""

import argparse
import json
from decimal import Decimal
from urllib.parse import urlsplit

import httpx


def verify(base_url):
    # This tool mutates demo incident state. Restrict it to a local test deployment.
    if urlsplit(base_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Acceptance tests require a local demo URL")
    results = []
    with httpx.Client(base_url=base_url, timeout=55, trust_env=False) as client:

        def get(path):
            response = client.get(path)
            response.raise_for_status()
            return response.json()

        def run(scenario, status):
            response = client.post("/api/demo/run", json={"scenario": scenario, "transport": "http"})
            response.raise_for_status()
            data = response.json()
            assert data["status"] == status, (scenario, data)
            checks = get(f"/api/integrations/{data['integration_id']}/checks?limit=1")
            check = checks[0]
            assert check["id"] == data["run_id"] and check["transport"] == "http"
            assert check["diagnostics"]["source"]["pages"] == 2
            assert check["diagnostics"]["source"]["complete"] is True
            if scenario == "outage":
                assert check["diagnostics"]["target"]["retries"] == 2
                assert check["diagnostics"]["lookup_complete"] is False
            else:
                assert check["diagnostics"]["target"]["complete"] is True
                assert len(check["observations"]) == 3
            results.append(
                {"scenario": scenario, "status": status, "run_id": data["run_id"], "diagnostics": check["diagnostics"]}
            )
            return data

        run("baseline", "BROKEN")
        original = {row["type"]: row["id"] for row in get("/api/incidents") if row["status"] != "RESOLVED"}
        assert set(original) == {"missing_target", "wrong_amount"}
        assert run("baseline", "BROKEN")["incidents_created"] == 0
        run("healthy", "HEALTHY")
        assert get("/api/dashboard")["open_incidents"] == 0
        assert run("baseline", "BROKEN")["incidents_created"] == 0
        current = {row["type"]: row["id"] for row in get("/api/incidents") if row["status"] != "RESOLVED"}
        assert current == original
        detail = get(f"/api/incidents/{original['missing_target']}")
        assert detail["timeline"][-1]["status"] == "REOPENED"
        assert detail["evidence"][0]["target_lookup_result"]["match_count"] == 0
        run("outage", "UNKNOWN")
        dashboard = get("/api/dashboard")
        assert dashboard["open_incidents"] == 2
        assert Decimal(dashboard["business_value_at_risk"]) == Decimal("194000")
        run("duplicate", "BROKEN")
        run("wrong_amount", "DELAYED")
        assert Decimal(get("/api/dashboard")["business_value_at_risk"]) == Decimal("10000")
        run("delay", "DELAYED")
        assert Decimal(get("/api/dashboard")["business_value_at_risk"]) == 0
        run("healthy", "HEALTHY")
        run("pending", "DELAYED")
        assert get("/api/dashboard")["open_incidents"] == 0
        run("baseline", "BROKEN")
    return {
        "passed": True,
        "transport": "actual HTTP sockets",
        "scope": "synthetic Bitrix24 / 1C contracts",
        "checks": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:3000")
    args = parser.parse_args()
    print(json.dumps(verify(args.base_url), ensure_ascii=False, indent=2))

"""Exercise the opt-in M9 demo through the running Next.js proxy and FastAPI."""

import os

import httpx


def main() -> None:
    base_url = os.getenv("PATHFINDER_WEB_URL", "http://127.0.0.1:3000")
    with httpx.Client(base_url=base_url, timeout=30) as client:
        page = client.get("/")
        assert page.status_code == 200 and "Build a better week." in page.text
        reset = client.post("/api/backend/demo/reset")
        assert reset.status_code == 200, reset.text
        bootstrap = reset.json()
        assert bootstrap["mode"] == "offline_fixture"
        assert bootstrap["catalog_sessions"] > 8

        discovery = client.post(
            "/api/backend/sessions/recommend",
            json={
                "query": "serverless",
                "profile": bootstrap["profile"],
                "filters": {},
                "limit": 10,
            },
        )
        assert discovery.status_code == 200 and discovery.json()["total"] > 0

        conversation = "m9-http-smoke"

        def message(text: str, **fields: object) -> dict:
            response = client.post(
                "/api/backend/agent/message",
                json={"conversation_id": conversation, "message": text, **fields},
            )
            assert response.status_code == 200, response.text
            return response.json()

        assert message("Do it.")["status"] == "needs_context"
        optimized = message(
            "Build my week around serverless security observability.",
            profile=bootstrap["profile"],
            current_schedule=bootstrap["existing_schedule"],
        )
        assert optimized["status"] == "ok"
        assert optimized["data"]["schedule"]["selected_sessions"]
        assert optimized["data"]["explanation"]["sessions"]
        assert optimized["data"]["explanation"]["goal_coverage"]
        assert message("Make Wednesday less busy.")["status"] == "ok"
        replacement_text = (
            "Replace my Wednesday 2 PM session with something more "
            "advanced about containers."
        )
        replacement = message(replacement_text)
        assert replacement["status"] == "confirmation_required"
        assert replacement["data"]["plan"]["replacements"]
        assert message("Confirm plan wrong-id")["status"] == "needs_context"
        assert message("Discard plan.")["status"] == "ok"
        assert message("Do it.")["status"] == "needs_context"

        message(
            "Build my week around serverless security observability.",
            profile=bootstrap["profile"],
            current_schedule=bootstrap["existing_schedule"],
        )
        message("Make Wednesday less busy.")
        replacement = message(replacement_text)
        confirmed = message(f"Confirm plan {replacement['pending_plan_id']}")
        assert confirmed["data"]["status"] in {"completed", "partially_completed"}
        verified = confirmed["data"]["verified_schedule"]
        assert "con410" in verified["reserved_session_ids"]
        assert "sec340" not in verified["reserved_session_ids"]

        restored = client.post("/api/backend/demo/reset")
        assert restored.status_code == 200
        original_ids = restored.json()["existing_schedule"]["reserved_session_ids"]
        assert "sec340" in original_ids and "con410" not in original_ids
        print(
            "M9 HTTP demo passed: discover, optimize, explain, refine, plan, "
            "reject wrong ID, discard, confirm, verify, reset"
        )


if __name__ == "__main__":
    main()

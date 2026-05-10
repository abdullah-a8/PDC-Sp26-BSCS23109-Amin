"""Lost-Update test suite.

Drives the same race scenario through both endpoints:

1. test_naive_endpoint_loses_update            — proves the bug exists on /naive.
2. test_versioned_endpoint_rejects_stale_write — proves the fix on the main PUT.
3. test_versioned_endpoint_retry_after_conflict_succeeds — proves the recovery path.

Real ThreadPoolExecutor + real SQLite + real TestClient. No mocks; the race is
genuine.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient


def _create_doc(client: TestClient, title: str, content: str) -> dict:
    r = client.post("/documents", json={"title": title, "content": content})
    assert r.status_code == 201
    return r.json()


def test_x_student_id_header_present_on_every_response(client):
    """Every response — success or error — must carry the header."""
    r = client.get("/")
    assert r.headers.get("X-Student-ID") == "BSCS23109"

    r = client.get("/documents/999999")  # 404
    assert r.status_code == 404
    assert r.headers.get("X-Student-ID") == "BSCS23109"


def test_naive_endpoint_loses_update(client):
    """Without optimistic locking, the second writer silently clobbers the first."""
    doc = _create_doc(client, "Shared Notes", "Original content.")
    doc_id = doc["id"]

    alice_text = "Alice's careful edit — paragraph A.\nParagraph B.\nParagraph C."
    bob_text = "Bob's careful edit — section 1.\nSection 2.\nSection 3."

    # Both writers READ the same baseline, then both WRITE — classic lost-update race.
    barrier = threading.Barrier(2)

    def write(text: str):
        barrier.wait()
        return client.put(f"/documents/{doc_id}/naive", json={"content": text})

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_alice = ex.submit(write, alice_text)
        f_bob = ex.submit(write, bob_text)
        r_alice = f_alice.result()
        r_bob = f_bob.result()

    # Both succeeded — no signal that anything went wrong.
    assert r_alice.status_code == 200
    assert r_bob.status_code == 200

    final = client.get(f"/documents/{doc_id}").json()
    # Exactly one of the two edits survives. The other is silently lost.
    assert final["content"] in {alice_text, bob_text}
    lost = bob_text if final["content"] == alice_text else alice_text
    assert lost not in final["content"], "expected lost update, but both writes survived"


def test_versioned_endpoint_rejects_stale_write(client):
    """With optimistic locking, the second writer gets HTTP 409 instead of overwriting."""
    doc = _create_doc(client, "Shared Notes", "Original content.")
    doc_id = doc["id"]

    base = client.get(f"/documents/{doc_id}").json()
    base_version = base["version"]
    assert base_version == 1

    alice_text = "Alice's careful edit — paragraph A.\nParagraph B."
    bob_text = "Bob's careful edit — section 1.\nSection 2."

    barrier = threading.Barrier(2)

    def write(text: str):
        barrier.wait()
        return client.put(
            f"/documents/{doc_id}",
            json={"content": text, "version": base_version},
        )

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_alice = ex.submit(write, alice_text)
        f_bob = ex.submit(write, bob_text)
        r_alice = f_alice.result()
        r_bob = f_bob.result()

    statuses = sorted([r_alice.status_code, r_bob.status_code])
    assert statuses == [200, 409], (
        f"expected exactly one 200 and one 409, got {statuses}"
    )

    winner = r_alice if r_alice.status_code == 200 else r_bob
    loser = r_bob if winner is r_alice else r_alice

    final = client.get(f"/documents/{doc_id}").json()
    assert final["content"] == winner.json()["content"]
    assert final["version"] == 2

    body = loser.json()["detail"]
    assert body["error"] == "version_conflict"
    assert body["your_version"] == base_version
    assert body["current_version"] == 2


def test_versioned_endpoint_retry_after_conflict_succeeds(client):
    """A well-behaved client re-fetches and retries with the new version — and wins."""
    doc = _create_doc(client, "Shared Notes", "Original")
    doc_id = doc["id"]

    r1 = client.put(
        f"/documents/{doc_id}",
        json={"content": "first edit", "version": 1},
    )
    assert r1.status_code == 200
    assert r1.json()["version"] == 2

    r2_stale = client.put(
        f"/documents/{doc_id}",
        json={"content": "second edit (stale)", "version": 1},
    )
    assert r2_stale.status_code == 409

    fresh = client.get(f"/documents/{doc_id}").json()
    r2_retry = client.put(
        f"/documents/{doc_id}",
        json={"content": "second edit (retry)", "version": fresh["version"]},
    )
    assert r2_retry.status_code == 200
    assert r2_retry.json()["version"] == 3
    assert r2_retry.json()["content"] == "second edit (retry)"

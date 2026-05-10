"""Live demo — fire two concurrent edits at a running uvicorn server.

Designed for the 2-minute screen-recording. Run it twice:

    # Side A — the bug
    python tests/concurrent_demo.py --naive

    # Side B — the fix
    python tests/concurrent_demo.py

Prereq: `uvicorn app.main:app --reload` running in another terminal.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

BASE_URL = "http://127.0.0.1:8000"


def _print(label: str, msg: str) -> None:
    color = {
        "alice": "\033[36m",  # cyan
        "bob": "\033[35m",  # magenta
        "info": "\033[33m",  # yellow
        "ok": "\033[32m",  # green
        "bad": "\033[31m",  # red
    }.get(label, "")
    print(f"{color}[{label:5}]\033[0m {msg}")


def _seed() -> int:
    r = httpx.post(
        f"{BASE_URL}/documents",
        json={"title": "Race-condition demo doc", "content": "ORIGINAL CONTENT"},
        timeout=5,
    )
    r.raise_for_status()
    doc = r.json()
    _print("info", f"created doc id={doc['id']} version={doc['version']}")
    _print("info", f"X-Student-ID header from server: {r.headers.get('X-Student-ID')}")
    return doc["id"]


def _race_naive(doc_id: int) -> None:
    _print("info", "Both writers read v1, then both PUT to /naive simultaneously...")
    barrier = threading.Barrier(2)

    def writer(name: str, content: str):
        barrier.wait()
        t0 = time.perf_counter()
        r = httpx.put(
            f"{BASE_URL}/documents/{doc_id}/naive",
            json={"content": content},
            timeout=5,
        )
        dt = (time.perf_counter() - t0) * 1000
        _print(name, f"PUT /naive  -> HTTP {r.status_code}  ({dt:.0f} ms)")

    with ThreadPoolExecutor(max_workers=2) as ex:
        ex.submit(writer, "alice", "ALICE wrote her chapter outline here.")
        ex.submit(writer, "bob", "BOB wrote his completely different notes here.")

    final = httpx.get(f"{BASE_URL}/documents/{doc_id}").json()
    _print("bad", f"FINAL CONTENT  : {final['content']!r}")
    _print("bad", "ONE EDIT WAS SILENTLY LOST. The bug is real.")


def _race_versioned(doc_id: int) -> None:
    base = httpx.get(f"{BASE_URL}/documents/{doc_id}").json()
    v = base["version"]
    _print("info", f"Both writers read v{v}, then both PUT with version={v}...")

    barrier = threading.Barrier(2)
    results: dict[str, httpx.Response] = {}

    def writer(name: str, content: str):
        barrier.wait()
        t0 = time.perf_counter()
        r = httpx.put(
            f"{BASE_URL}/documents/{doc_id}",
            json={"content": content, "version": v},
            timeout=5,
        )
        dt = (time.perf_counter() - t0) * 1000
        results[name] = r
        _print(name, f"PUT /documents -> HTTP {r.status_code}  ({dt:.0f} ms)")

    with ThreadPoolExecutor(max_workers=2) as ex:
        ex.submit(writer, "alice", "ALICE wrote her chapter outline here.")
        ex.submit(writer, "bob", "BOB wrote his completely different notes here.")

    statuses = sorted(r.status_code for r in results.values())
    if statuses != [200, 409]:
        _print("bad", f"unexpected status pair {statuses}")
        sys.exit(1)

    loser_name, loser = next(
        (n, r) for n, r in results.items() if r.status_code == 409
    )
    _print(loser_name, f"got 409 body: {loser.json()['detail']}")

    final = httpx.get(f"{BASE_URL}/documents/{doc_id}").json()
    _print("ok", f"FINAL CONTENT  : {final['content']!r}")
    _print("ok", f"FINAL VERSION  : {final['version']}")
    _print("ok", "NO LOST UPDATE. Loser was told to retry. Bug is fixed.")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--naive",
        action="store_true",
        help="Hit the broken /naive endpoint to demonstrate the bug",
    )
    args = p.parse_args()

    try:
        httpx.get(f"{BASE_URL}/", timeout=2).raise_for_status()
    except Exception as e:  # noqa: BLE001
        print(f"Server not reachable at {BASE_URL}: {e}")
        print("Start it first:  uvicorn app.main:app --reload")
        return 1

    doc_id = _seed()
    print()
    if args.naive:
        _print("info", "=== Mode: NAIVE (Lost-Update bug) ===")
        _race_naive(doc_id)
    else:
        _print("info", "=== Mode: VERSIONED (Optimistic Locking fix) ===")
        _race_versioned(doc_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())

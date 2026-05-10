Muhammad Abdullah Amin, BSCS23109

# PDC Assignment 2

This is my submission for Problem 1 of the assignment, the Lost Update bug.
I picked this one because it is the easiest of the three to set up a clean
before-and-after demo for, and the fix is a well known pattern (optimistic
concurrency control with row versioning).

The written report (Parts 1 and 2) is submitted separately on the classroom.
This README is just for running the code.

## What the service does

There is a small FastAPI app with a `documents` table. You can create a
document, read it, and update it. There are two update endpoints on
purpose so I can demo the bug and the fix side by side:

| Method and path                     | What it does                                                         |
| ----------------------------------- | -------------------------------------------------------------------- |
| `POST   /documents`                 | Create a document. Returns `id` and `version` (starts at 1).         |
| `GET    /documents/{id}`            | Read the current content and version.                                |
| `PUT    /documents/{id}/naive`      | The broken version. No version check. Last write silently wins.      |
| `PUT    /documents/{id}`            | The fixed version. Checks the version column, returns 409 if stale.  |

A FastAPI middleware adds an `X-Student-ID: BSCS23109` header to every
response (success or error). The assignment requires this and says it is a
zero on Part 3 if it is missing, so I have a test specifically for it.

The fix is just one SQL statement. The version column is part of the WHERE
clause, so the database itself decides who wins the race:

```sql
UPDATE documents
   SET content = :new_content, version = version + 1
 WHERE id = :id
   AND version = :client_version;
```

If the affected row count is 0 it means somebody else already updated the
row since this client read it. The endpoint returns 409 with the current
version in the body so the client can refetch and retry.

## How to run it

You need [`uv`](https://docs.astral.sh/uv/) and Python 3.11 or newer. I am
using uv as the package manager.

```bash
# install dependencies into a project local venv
uv sync

# start the API
uv run uvicorn app.main:app --reload
```

It runs on `http://127.0.0.1:8000`. Swagger UI is at `/docs`.

To check the required header is there:

```bash
curl -i http://127.0.0.1:8000/ | grep -i x-student-id
# X-Student-ID: BSCS23109
```

## How to run the tests

```bash
uv run pytest
```

There are four tests in `tests/test_lost_update.py`:

1. `test_x_student_id_header_present_on_every_response` checks the header
   is on both a 200 and a 404 response.
2. `test_naive_endpoint_loses_update` fires two writes at the same time
   against the broken endpoint using a `ThreadPoolExecutor` and a
   `threading.Barrier` so both threads start writing at the same instant.
   It then asserts that exactly one of the two edits is gone. This is the
   bug.
3. `test_versioned_endpoint_rejects_stale_write` does the same race against
   the fixed endpoint and asserts that one writer gets 200 and the other
   gets 409 with a structured error body. This is the fix.
4. `test_versioned_endpoint_retry_after_conflict_succeeds` is the recovery
   path. The loser refetches, retries with the new version, and succeeds.

Each test uses its own SQLite file (handled by the fixture in
`tests/conftest.py`) so the tests do not interfere with each other.

## How to run the live demo

This is what I use for the screen recording.

In one terminal start the server:

```bash
uv run uvicorn app.main:app --reload
```

In another terminal run the demo script. It creates a document, then fires
two concurrent PUTs (one as Alice, one as Bob) and prints what happened:

```bash
# Side A: the bug. Both writes succeed, one is silently lost.
uv run python tests/concurrent_demo.py --naive

# Side B: the fix. One write returns 200, the other returns 409 with the
# current version in the body.
uv run python tests/concurrent_demo.py
```

## Folder layout

```
PDC-Sp26-BSCS23109-Amin/
|-- app/
|   |-- main.py          FastAPI app, middleware, routes (naive and versioned)
|   |-- database.py      SQLAlchemy engine and session factory
|   |-- models.py        Document table with a version column
|   `-- schemas.py       Pydantic request and response models
|-- tests/
|   |-- conftest.py            per test SQLite isolation
|   |-- test_lost_update.py    pytest cases for the bug and the fix
|   `-- concurrent_demo.py     CLI demo for the screen recording
|-- pyproject.toml
`-- README.md
```

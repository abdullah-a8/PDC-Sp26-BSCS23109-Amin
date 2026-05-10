"""StudySync — Optimistic Locking demo (Problem 1: Lost Update).

Two endpoints update the same document:

* PUT /documents/{id}/naive — the broken baseline. Last writer wins, silently.
* PUT /documents/{id}      — the fix. Caller must echo the version they read;
                              stale writes are rejected with HTTP 409.

Every response carries the X-Student-ID header (required by the assignment).
"""

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from app import models, schemas
from app.database import Base, engine, get_db

STUDENT_ID = "BSCS23109"

Base.metadata.create_all(bind=engine)

app = FastAPI(title="StudySync — Optimistic Locking Demo")


class StudentIDMiddleware(BaseHTTPMiddleware):
    """Attach X-Student-ID to every response, including error responses."""

    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception:
            # Even on unhandled exceptions, the assignment requires the header.
            response = JSONResponse(
                {"detail": "Internal server error"},
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        response.headers["X-Student-ID"] = STUDENT_ID
        return response


app.add_middleware(StudentIDMiddleware)


@app.get("/", tags=["meta"])
def root():
    return {
        "service": "StudySync optimistic-locking demo",
        "student_id": STUDENT_ID,
        "endpoints": {
            "create": "POST /documents",
            "read": "GET /documents/{id}",
            "naive_update_BROKEN": "PUT /documents/{id}/naive",
            "versioned_update_FIXED": "PUT /documents/{id}",
        },
    }


@app.post(
    "/documents",
    response_model=schemas.DocumentRead,
    status_code=status.HTTP_201_CREATED,
    tags=["documents"],
)
def create_document(payload: schemas.DocumentCreate, db: Session = Depends(get_db)):
    doc = models.Document(title=payload.title, content=payload.content, version=1)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@app.get(
    "/documents/{doc_id}",
    response_model=schemas.DocumentRead,
    tags=["documents"],
)
def read_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.get(models.Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@app.put(
    "/documents/{doc_id}/naive",
    response_model=schemas.DocumentRead,
    tags=["documents"],
    summary="BROKEN baseline — silently overwrites concurrent edits (Lost Update)",
)
def update_document_naive(
    doc_id: int,
    payload: schemas.DocumentNaiveUpdate,
    db: Session = Depends(get_db),
):
    doc = db.get(models.Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    doc.content = payload.content
    db.commit()
    db.refresh(doc)
    return doc


@app.put(
    "/documents/{doc_id}",
    response_model=schemas.DocumentRead,
    tags=["documents"],
    summary="FIXED — optimistic lock; rejects stale writes with 409",
)
def update_document_versioned(
    doc_id: int,
    payload: schemas.DocumentUpdate,
    db: Session = Depends(get_db),
):
    # The atomic compare-and-swap: UPDATE ... WHERE id = ? AND version = ?
    # SQLAlchemy emits exactly that SQL, so the database (not Python) decides
    # the winner of a race. rowcount == 0 means another writer already moved
    # the version forward, and we reject this request as stale.
    result = db.execute(
        models.Document.__table__.update()
        .where(models.Document.id == doc_id)
        .where(models.Document.version == payload.version)
        .values(content=payload.content, version=models.Document.version + 1)
    )
    db.commit()

    if result.rowcount == 0:
        existing = db.get(models.Document, doc_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Document not found")
        raise HTTPException(
            status_code=409,
            detail={
                "error": "version_conflict",
                "message": (
                    "Document was modified by another user. "
                    "Re-fetch and retry."
                ),
                "your_version": payload.version,
                "current_version": existing.version,
            },
        )

    refreshed = db.get(models.Document, doc_id)
    return refreshed

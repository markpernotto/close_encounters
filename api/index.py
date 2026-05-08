"""FastAPI app for close_encounters / neo_citation.

Local dev:
    make api       # uvicorn at :8000

Production:
    Vercel routes /api/* and /docs and /openapi.json here via vercel.json.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(
    title="neo_citation",
    description="Public near-Earth object close-approach + citation warehouse.",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

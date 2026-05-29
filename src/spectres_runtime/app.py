"""FastAPI application entry point for the Spectres Runtime.

v0.1 ships only a health-check endpoint; AgentOS / agent wiring lands in a
later release. The shape (module-level ``app`` variable, ``main`` callable) is
chosen so both ``uvicorn spectres_runtime.app:app`` and a future
``[project.scripts]`` entry point can target it.
"""

from __future__ import annotations

from typing import Final

from fastapi import FastAPI

app: Final[FastAPI] = FastAPI(
    title="Spectres Runtime",
    version="0.1.0",
    description="Runtime tier of the Spectres personal assistant.",
)


@app.get("/healthz", tags=["meta"], summary="Liveness probe")
async def healthz() -> dict[str, str]:
    """Return a static OK payload.

    Intended for container / CI liveness checks. Has no side effects and
    performs no I/O, so it is safe to poll at high frequency.
    """
    return {"status": "ok"}


def main() -> None:  # pragma: no cover - thin uvicorn wrapper, exercised manually
    """Run the app with uvicorn for local development.

    Production deployments should invoke ``uvicorn spectres_runtime.app:app``
    directly with the desired worker / binding flags.
    """
    import uvicorn

    uvicorn.run(
        "spectres_runtime.app:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )

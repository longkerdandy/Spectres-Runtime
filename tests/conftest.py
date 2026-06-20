"""Shared pytest configuration for the Spectres Runtime test suite."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Point the settings loader at the committed test environment file.
os.environ.setdefault("SPECTRES_ENV_FILE", ".env.test")

# Load optional local test secrets (gitignored) so integration tests can call
# real LLM APIs such as GitHub Models without committing credentials.
_local_env = Path(__file__).parent.parent / ".env.test.local"
if _local_env.exists():
    load_dotenv(_local_env, override=False)

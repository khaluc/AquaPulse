"""AquaPulse backend package."""

from pathlib import Path

from dotenv import load_dotenv

# Settings live in the repository's .env (see .env.example). Variables already set in
# the environment win, so deployments and tests can override any of them.
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

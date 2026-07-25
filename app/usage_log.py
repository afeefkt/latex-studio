# ── Phase 5: LLM usage logger ──

import csv
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).parent.parent / "workspace"
LOG_PATH = WORKSPACE / "llm_usage.csv"


def log_usage(
    provider: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    endpoint: str = "chat",
) -> None:
    """Append a row to workspace/llm_usage.csv."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    exists = LOG_PATH.exists()
    with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow([
                "timestamp", "provider", "model", "tokens_in",
                "tokens_out", "endpoint",
            ])
        writer.writerow([
            datetime.now(timezone.utc).isoformat(),
            provider,
            model,
            tokens_in,
            tokens_out,
            endpoint,
        ])

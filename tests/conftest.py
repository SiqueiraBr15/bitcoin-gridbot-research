from __future__ import annotations

import os

import pytest
from hypothesis import HealthCheck, settings

settings.register_profile("default", max_examples=200, deadline=None)
settings.register_profile(
    "ci",
    max_examples=300,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))


@pytest.fixture(autouse=True)
def _isolate_gridbot_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nenhum teste herda variáveis GRIDBOT_* do ambiente real."""
    for key in list(os.environ):
        if key.upper().startswith("GRIDBOT_"):
            monkeypatch.delenv(key)

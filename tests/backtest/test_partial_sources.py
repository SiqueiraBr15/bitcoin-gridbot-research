"""Recovery from encoded source recipes rederives every financial effect."""

import json
from dataclasses import replace

import pytest

from gridbot.backtest.partial_sources import encode_partial_sources, replay_partial_sources
from gridbot.domain.errors import DomainError
from gridbot.storage.paper_codec import encode_command
from tests.paper.test_two_generation import plan, prepared


def encoded() -> tuple[str, object]:
    sim = prepared(active_sell=True)
    sim.publish(sim.revision, plan(sim))
    return encode_partial_sources(sim.source_log()), sim.snapshot()


def test_source_roundtrip_preserves_owned_identity_and_both_states() -> None:
    source, snap = encoded()
    recovered = replay_partial_sources(source, max_events=1000)
    assert recovered.snapshot() == snap
    assert encode_partial_sources(recovered.source_log()) == source


@pytest.mark.parametrize(
    "damage",
    [
        "schema",
        "revision",
        "omit",
        "duplicate",
        "generation",
        "digest",
        "kind",
        "recipe",
        "unknown_field",
        "truncated",
        "duplicate_key",
        "budget",
    ],
)
def test_corrupt_sources_are_rejected_without_partial_authority(damage: str) -> None:
    source, _ = encoded()
    data = json.loads(source)
    limit = 1000
    if damage == "schema":
        data["schema"] = "UNKNOWN"
    elif damage == "revision":
        data["revision"] += 1
    elif damage == "omit":
        data["events"] = []
    elif damage == "duplicate":
        data["events"].append(data["events"][0])
        data["revision"] += 1
    elif damage == "generation":
        data["events"][0]["generation"] = "PAPER:FOREIGN:GEN:1"
    elif damage == "digest":
        data["events"][0]["allocation_sha256"] = "0" * 64
    elif damage == "kind":
        data["events"][0]["kind"] = "CREDIT"
    elif damage == "recipe":
        data["events"][0]["payload"] = "{}"
    elif damage == "unknown_field":
        data["available_usdt"] = "1000000"
    elif damage == "budget":
        limit = 1
    source = json.dumps(data)
    if damage == "truncated":
        source = source[:-1]
    if damage == "duplicate_key":
        source = '{"schema":"OTHER",' + source[1:]
    with pytest.raises(DomainError):
        replay_partial_sources(source, max_events=limit)


def test_durable_paper_codec_cannot_serialize_new_authority_or_publish_recipe() -> None:
    from typing import cast

    from gridbot.paper.accounting import PaperCommand

    sim = prepared()
    with pytest.raises((DomainError, TypeError)):
        encode_command(cast(PaperCommand, plan(sim)))
    with pytest.raises((DomainError, TypeError)):
        encode_partial_sources(replace(sim.source_log(), version=2))


def test_encoder_rejects_boolean_revision_instead_of_producing_unreadable_sources() -> None:
    from gridbot.paper.two_generation import TwoGenerationPaper
    from tests.backtest.test_safe_recenter import runtime

    sim = TwoGenerationPaper(runtime().source_log(), max_events=1000)
    sim.publish(0, plan(sim))
    with pytest.raises(DomainError):
        encode_partial_sources(replace(sim.source_log(), revision=True))

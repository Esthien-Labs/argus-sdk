"""Public tests for the wedge containment benchmark."""

from __future__ import annotations

import pytest

from argus.regression.wedge import (
    DeclaredLinearController,
    WedgeFault,
    build_wedge_fault_corpus,
    run_wedge_benchmark,
    write_wedge_report,
)


def test_controller_is_confident_on_a_dead_sensor() -> None:
    """The documented failure mode: a dead sensor still yields a motion intent."""
    import numpy as np

    controller = DeclaredLinearController()
    dead = np.zeros((16, 4))
    provenance = controller.propose.__defaults__
    from argus.safety import ActionProvenance

    proposal = controller.propose(dead, ActionProvenance("m", "1", "p", "local", 0.0))
    assert proposal.intent != "rest"
    assert proposal.confidence >= 0.6


def test_controller_is_deterministic() -> None:
    import numpy as np
    from argus.safety import ActionProvenance

    controller = DeclaredLinearController()
    window = np.random.default_rng(1).normal(size=(16, 4))
    provenance = ActionProvenance("m", "1", "p", "local", 0.0)
    first = controller.propose(window, provenance)
    second = controller.propose(window, provenance)
    assert (first.intent, first.confidence) == (second.intent, second.confidence)


def test_corpus_covers_the_declared_fault_classes() -> None:
    names = {fault.name for fault in build_wedge_fault_corpus()}
    kinds = {fault.kind for fault in build_wedge_fault_corpus()}
    assert {"flatline_single_channel", "flatline_all_channels", "saturation", "mean_shift", "slow_drift"} == names
    assert kinds == {"flatline", "saturation", "shift", "drift"}


def test_wedge_rejects_unknown_fault_kind() -> None:
    with pytest.raises(ValueError):
        WedgeFault("bad", "explosion", onset=0, duration=1)


def test_wedge_rejects_bad_fault_span() -> None:
    with pytest.raises(ValueError):
        WedgeFault("bad", "flatline", onset=-1, duration=1)
    with pytest.raises(ValueError):
        WedgeFault("bad", "flatline", onset=0, duration=0)


def test_benchmark_contains_unsafe_commands() -> None:
    result = run_wedge_benchmark()
    assert result["evidence_class"] == "digital_source_verification"
    assert result["aggregate"]["baseline_unsafe_commands"] > 0


def test_benchmark_shows_containment_on_flatline_all_channels() -> None:
    result = run_wedge_benchmark()
    by_name = {row["fault"]: row for row in result["results"]}
    row = by_name["flatline_all_channels"]
    assert row["baseline_unsafe_commands"] > 0
    assert row["argus_unsafe_commands"] < row["baseline_unsafe_commands"]
    assert row["first_safe_halt_window"] is not None
    # A dead sensor halts within the declared persistence window after onset.
    assert row["first_safe_halt_window"] <= row["detail"]["fault_onset"] + row["detail"]["persistence_windows"] + 1


def test_benchmark_has_a_low_false_stop_rate() -> None:
    result = run_wedge_benchmark()
    for row in result["results"]:
        assert row["argus_false_stops"] <= row["windows"] // 10


def test_benchmark_is_deterministic() -> None:
    first = run_wedge_benchmark()
    second = run_wedge_benchmark()
    assert first["aggregate"] == second["aggregate"]
    assert first["results"] == second["results"]


def test_benchmark_declares_its_boundary(tmp_path) -> None:
    result = run_wedge_benchmark()
    assert "No hardware" in result["boundary"]
    paths = write_wedge_report(result, tmp_path)
    assert paths["json"].is_file()
    assert paths["md"].is_file()
    text = paths["md"].read_text(encoding="utf-8")
    assert "digital_source_verification" in text
    assert "Aggregate containment" in text

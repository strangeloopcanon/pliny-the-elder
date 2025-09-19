from __future__ import annotations

import json
from pathlib import Path

import typer.testing

from vei.cli.vei_state import app as state_app
from vei.world.state import Event, StateStore


def _seed_state(base: Path) -> None:
    store = StateStore(base_dir=base, branch="main")

    def reducer(state: dict[str, object], event: Event) -> None:
        state["count"] = state.get("count", 0) + 1

    store.register_reducer("touch", reducer)
    store.append("touch", {"value": 1})
    store.take_snapshot()

    store.append("touch", {"value": 1})
    store.take_snapshot()


def test_vei_state_cli_list_and_show(tmp_path: Path) -> None:
    runner = typer.testing.CliRunner()
    base = tmp_path / "state"
    _seed_state(base)

    result = runner.invoke(state_app, ["list", "--state-dir", str(base)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["branch"] == "main"
    assert len(payload["snapshots"]) == 2

    result_show = runner.invoke(
        state_app,
        [
            "show",
            "--state-dir",
            str(base),
            "--snapshot",
            "000000",
            "--include-state",
        ],
    )
    assert result_show.exit_code == 0, result_show.output
    show_payload = json.loads(result_show.stdout)
    assert show_payload["index"] == 0
    assert show_payload["data"]["count"] == 1


def test_vei_state_cli_diff(tmp_path: Path) -> None:
    runner = typer.testing.CliRunner()
    base = tmp_path / "state"
    _seed_state(base)

    result = runner.invoke(
        state_app,
        [
            "diff",
            "--state-dir",
            str(base),
            "--snapshot-from",
            "0",
            "--snapshot-to",
            "1",
        ],
    )
    assert result.exit_code == 0, result.output
    diff_payload = json.loads(result.stdout)
    assert diff_payload["diff"]["changed"]["count"]["from"] == 1
    assert diff_payload["diff"]["changed"]["count"]["to"] == 2

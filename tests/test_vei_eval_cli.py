from __future__ import annotations

import json
from pathlib import Path

from vei.cli.vei_eval import scripted, bc as eval_bc
from vei.cli.vei_train import bc as train_bc
from vei.data.rollout import rollout_procurement


def test_vei_eval_scripted_creates_score(tmp_path: Path) -> None:
    artifacts = tmp_path / "eval"
    scripted(seed=101, dataset=Path("-"), artifacts=artifacts)
    score_path = artifacts / "score.json"
    assert score_path.exists()
    data = json.loads(score_path.read_text(encoding="utf-8"))
    assert "success" in data


def test_vei_eval_bc(tmp_path: Path) -> None:
    dataset = rollout_procurement(episodes=1, seed=555)
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(json.dumps(dataset.model_dump()), encoding="utf-8")

    model_path = tmp_path / "policy.json"
    train_bc(dataset=[str(dataset_path)], output=model_path)

    artifacts = tmp_path / "eval_bc"
    eval_bc(model=model_path, seed=555, dataset=dataset_path, artifacts=artifacts, max_steps=10)
    score_path = artifacts / "score.json"
    assert score_path.exists()

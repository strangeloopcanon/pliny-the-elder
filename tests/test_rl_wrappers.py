from __future__ import annotations

from vei.rl.arg_helpers import default_args_for
from vei.rl.env import VEIEnv
from vei.rl.wrappers import ActionMaskWrapper, MenuIndexWrapper, SimpleVectorEnv


def _make_env() -> MenuIndexWrapper:
    env = VEIEnv(seed=123)
    env = MenuIndexWrapper(env)
    env = ActionMaskWrapper(env)
    return env


def test_action_mask_wrapper_provides_mask() -> None:
    env = _make_env()
    obs, info = env.reset()
    assert info["action_mask"], "expected action mask"

    action = 0
    obs, reward, terminated, truncated, info = env.step(action)
    assert isinstance(info["action_mask"], list)


def test_menu_index_wrapper_translates_actions() -> None:
    env = _make_env()
    obs, _ = env.reset()
    menu = obs.get("action_menu")
    assert menu
    obs, reward, terminated, truncated, info = env.step(0)
    assert isinstance(obs, dict)


def test_simple_vector_env_runs_multiple_envs() -> None:
    vec = SimpleVectorEnv([lambda: _make_env(), lambda: _make_env()])
    obs_list, infos = vec.reset()
    assert len(obs_list) == 2
    assert len(infos) == 2
    actions = [0, 0]
    obs_list, rewards, terms, truncs, infos = vec.step(actions)
    assert len(rewards) == 2
    vec.close()


def test_default_args_helper_handles_schema() -> None:
    entry = {"tool": "calendar.create_event", "args_schema": {"title": "str", "start_ms": "int", "attendees": "[str]?"}}
    args = default_args_for(entry)
    assert "title" in args and args["attendees"] == []

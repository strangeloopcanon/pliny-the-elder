"""Run the scripted procurement policy for a single episode."""

from vei.behavior import ScriptedProcurementPolicy
from vei.router.core import Router


def main() -> None:
    router = Router(seed=123, artifacts_dir=None)
    runner = ScriptedProcurementPolicy(router)
    transcript = runner.run()
    for entry in transcript:
        print(entry)


if __name__ == "__main__":
    main()

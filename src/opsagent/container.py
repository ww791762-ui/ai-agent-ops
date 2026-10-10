from dataclasses import dataclass

from opsagent.runner.runner import Runner
from opsagent.storage.repo import DbRecorder, RunRepo


@dataclass
class Container:
    runner: Runner
    runs: RunRepo
    recorder: DbRecorder

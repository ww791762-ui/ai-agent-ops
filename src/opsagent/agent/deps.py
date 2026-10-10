from dataclasses import dataclass

from opsagent.gateway.gateway import Gateway
from opsagent.nacos.store import ConfigStore
from opsagent.topology.model import Topology

from .llm import LLM


@dataclass
class Deps:
    llm: LLM
    store: ConfigStore
    gateway: Gateway
    topo: Topology

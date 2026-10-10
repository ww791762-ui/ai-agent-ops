from pathlib import Path

import pytest

from opsagent.topology.model import Topology, load_topology_yaml

TEXT = Path("fixtures/topology.yaml").read_text(encoding="utf-8")


@pytest.fixture
def topo() -> Topology:
    return load_topology_yaml(TEXT)


def ids(nodes):
    return sorted(n.id for n in nodes)


def test_find_by_name_alias_and_id(topo):
    assert ids(topo.find("b 服务")) == ["svc-b"]
    assert ids(topo.find("支付接口")) == ["svc-b-pay"]
    assert ids(topo.find("ocr proxy")) == ["ocr-proxy"]
    assert ids(topo.find("OCR")) == ["ocr"]
    assert ids(topo.find("/login")) == ["svc-a-login"]


def test_find_ambiguous_and_unknown(topo):
    assert ids(topo.find("支付服务")) == ["svc-b", "svc-paycb"]
    assert topo.find("不存在的服务") == []


def test_trace_service_returns_all_paths(topo):
    paths = topo.trace("svc-c")
    assert sorted(p.path_id for p in paths) == ["c-ocr-direct", "c-ocr-via-proxy"]
    direct = next(p for p in paths if p.path_id == "c-ocr-direct")
    assert [h.node_id for h in direct.hops] == ["svc-c", "ocr-thirdparty"]
    assert direct.hops[0].next_timeout == "3s"
    assert direct.hops[1].tools == []  # 三方系统按黑盒处理，没有工具


def test_trace_parent_service_finds_endpoint_path(topo):
    paths = topo.trace("svc-b")
    assert [p.path_id for p in paths] == ["public-b-pay"]
    kong = paths[0].hops[2]
    assert kong.node_id == "kong" and "kong.upstream_health" in kong.tools


def test_invalid_path_without_edge_raises():
    bad = TEXT.replace("  - {from: ocr-proxy, to: ocr, protocol: http}\n", "")
    assert bad != TEXT
    with pytest.raises(ValueError, match="ocr-proxy"):
        load_topology_yaml(bad)


def test_unknown_node_in_edge_raises():
    bad = TEXT.replace("edges:\n", "edges:\n  - {from: svc-c, to: ghost}\n")
    with pytest.raises(ValueError, match="ghost"):
        load_topology_yaml(bad)

---
name: http_5xx
description: HTTP 接口 5xx、超时、变慢问题的逐跳排查
---
# HTTP 接口错误 / 变慢排查

1. 用 topology_trace 展开目标接口或服务所在的链路。
2. 从入口开始逐跳检查，优先拆分耗时和状态码：
   - proxy：用 logs_search 查看状态码分布和 upstream 耗时。
   - Kong：用 kong_upstream_health 查看 upstream 健康状态；用 metrics_query 对比 Kong 自身延迟（latency_p99）和 upstream 延迟（upstream_latency_p99）。自身延迟正常而 upstream 延迟升高，说明问题在 Kong 之后。
   - 服务：用 metrics_query 查询 latency_p99、error_rate、qps、conn_pool_wait；用 logs_search 查看 error 日志；用 changes_list 查看变更。
3. 找到第一个异常的节点后，在该节点上找原因，同时考虑替代解释：流量突增（qps）、下游依赖变慢、资源问题。
4. 有变更时，比较变更时间和异常开始时间，并在变更内容中寻找能解释现象的直接证据。
5. 调用方到 external 三方系统的问题，只能依据调用方的指标和日志判断；有多条路径时对比各路径的指标。

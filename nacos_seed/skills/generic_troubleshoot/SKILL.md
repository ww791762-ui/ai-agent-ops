---
name: generic_troubleshoot
description: 没有专用 Skill 时的通用只读排查
---
# 通用排查

1. 用 topology_trace 了解目标所在的链路。
2. 对目标节点查询核心指标（qps、error_rate、latency_p99）、错误日志和近期变更。
3. 发现异常后沿链路向上下游扩展检查，找出第一个异常的节点。
4. 证据不足以下结论时，明确说明还需要哪些信息，并建议人工接管。

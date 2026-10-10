from ..deps import Deps

FALLBACK = {"troubleshoot": "generic_troubleshoot", "topology_query": "topology_qa"}


def make_route_skill(deps: Deps):
    async def route_skill(state: dict) -> dict:
        intent = state["intent"]["intent"]
        text = f"{state['question']} {state['intent'].get('symptom') or ''}".lower()
        candidates = [s for s in deps.store.skills() if intent in s.meta.intents]
        hit = next((s for s in candidates if any(k.lower() in text for k in s.meta.keywords)), None)
        skill = hit or deps.store.skill(FALLBACK[intent])
        return {"skill": {"id": skill.meta.id, "version": skill.meta.version, "md5": skill.md5}}

    return route_skill

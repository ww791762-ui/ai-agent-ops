def render(template: str, **values: str) -> str:
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def format_history(history: list[dict]) -> str:
    if not history:
        return "（无）"
    return "\n".join(f"- 问：{t['question']}\n  答：{t['answer']}" for t in history)

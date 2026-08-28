"""Camada de provedores de LLM — resiliência por failover.

Formato interno neutro de histórico:
  {"role": "user"|"assistant", "content": str}
  {"role": "assistant", "content": str|None, "tool_calls": [{id, name, input}]}
  {"role": "tool", "tool_call_id": str, "name": str, "content": str}

Dois adaptadores cobrem o mercado:
  • AnthropicProvider — API nativa da Anthropic
  • OpenAICompatProvider — OpenAI, DeepSeek, Groq, Ollama, etc. (mesmo formato
    /chat/completions; muda só base_url + modelo + chave)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import httpx


@dataclass
class Reply:
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)  # [{id, name, input}]

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class ProviderError(RuntimeError):
    pass


class AnthropicProvider:
    def __init__(self, api_key: str, model: str):
        self.name = f"anthropic:{model}"
        self.model = model
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)

    def chat(self, system: str, history: list[dict], tools: list[dict]) -> Reply:
        msgs = []
        for h in history:
            if h["role"] == "tool":
                msgs.append({"role": "user", "content": [{
                    "type": "tool_result", "tool_use_id": h["tool_call_id"],
                    "content": h["content"]}]})
            elif h["role"] == "assistant" and h.get("tool_calls"):
                blocks = []
                if h.get("content"):
                    blocks.append({"type": "text", "text": h["content"]})
                for tc in h["tool_calls"]:
                    blocks.append({"type": "tool_use", "id": tc["id"],
                                   "name": tc["name"], "input": tc["input"]})
                msgs.append({"role": "assistant", "content": blocks})
            else:
                msgs.append({"role": h["role"], "content": h["content"]})
        try:
            resp = self.client.messages.create(
                model=self.model, max_tokens=1500, system=system,
                tools=tools, messages=msgs)
        except Exception as e:  # noqa: BLE001 — qualquer falha dispara failover
            raise ProviderError(f"{self.name}: {e}") from e
        out = Reply()
        for b in resp.content:
            if b.type == "text":
                out.text += b.text
            elif b.type == "tool_use":
                out.tool_calls.append({"id": b.id, "name": b.name, "input": dict(b.input)})
        return out


class OpenAICompatProvider:
    """OpenAI / DeepSeek / Groq / Ollama — mesmo contrato /chat/completions."""

    def __init__(self, api_key: str, model: str, base_url: str, label: str):
        self.name = f"{label}:{model}"
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _tools_openai(self, tools: list[dict]) -> list[dict]:
        return [{"type": "function", "function": {
            "name": t["name"], "description": t["description"],
            "parameters": t["input_schema"]}} for t in tools]

    def chat(self, system: str, history: list[dict], tools: list[dict]) -> Reply:
        msgs: list[dict] = [{"role": "system", "content": system}]
        for h in history:
            if h["role"] == "tool":
                msgs.append({"role": "tool", "tool_call_id": h["tool_call_id"],
                             "content": h["content"]})
            elif h["role"] == "assistant" and h.get("tool_calls"):
                msgs.append({"role": "assistant", "content": h.get("content") or None,
                             "tool_calls": [{"id": tc["id"], "type": "function",
                                             "function": {"name": tc["name"],
                                                          "arguments": json.dumps(tc["input"], ensure_ascii=False)}}
                                            for tc in h["tool_calls"]]})
            else:
                msgs.append({"role": h["role"], "content": h["content"]})
        try:
            r = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "messages": msgs,
                      "tools": self._tools_openai(tools), "max_tokens": 1500},
                timeout=60.0)
            r.raise_for_status()
            choice = r.json()["choices"][0]["message"]
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"{self.name}: {e}") from e
        out = Reply(text=choice.get("content") or "")
        for tc in choice.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            out.tool_calls.append({"id": tc["id"], "name": tc["function"]["name"],
                                   "input": args})
        return out


def montar_cadeia(settings) -> list:
    """Lê TESOUREIRO_PROVIDERS (ex.: 'anthropic,deepseek,openai,ollama')
    e monta a cadeia de failover na ordem declarada. Ignora provedor sem chave."""
    cadeia = []
    for nome in [p.strip().lower() for p in settings.providers.split(",") if p.strip()]:
        if nome == "anthropic" and settings.anthropic_api_key:
            cadeia.append(AnthropicProvider(settings.anthropic_api_key,
                                            settings.anthropic_model))
        elif nome == "deepseek" and settings.deepseek_api_key:
            cadeia.append(OpenAICompatProvider(settings.deepseek_api_key,
                                               settings.deepseek_model,
                                               "https://api.deepseek.com/v1", "deepseek"))
        elif nome == "openai" and settings.openai_api_key:
            cadeia.append(OpenAICompatProvider(settings.openai_api_key,
                                               settings.openai_model,
                                               "https://api.openai.com/v1", "openai"))
        elif nome == "ollama":
            cadeia.append(OpenAICompatProvider("ollama", settings.ollama_model,
                                               settings.ollama_base_url, "ollama"))
    return cadeia

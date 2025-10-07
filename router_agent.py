from typing import Dict, Any, Tuple
from logging_config import get_guardrails_logger,setup_logging
setup_logging()
log = get_guardrails_logger()
MODELS = {
    "llama-3.2": "ws://localhost:8765/llama3.2",
    "claude-2": "ws://localhost:8765/claude2",
    "gpt-4": "ws://localhost:8765/gpt4",
    "vllm": "ws://localhost:8765/vllm"
}


OLLAMA_TEMPLATE = {
    "model": "",
    "messages":[
        {"role": "user", "content": ""}
        ],  
    "stream": True
}


CLAUDE_TEMPLATE = {
    "model": "claude-2",
    "system": "you are an assistant",
    "messages": [
        {"role": "user", "content": ""}
    ],
    "stream": True,
    "max_tokens": 4096
}


GPT4_TEMPLATE = {
    "model": "gpt-4",
    "system": "you are an assistant",
    "messages": [
        {"role": "user", "content": ""}
    ],
    "stream": True,
    "temperature": 0.7
}

VLLM_TEMPLATE={
    "model": "NousResearch/Meta-Llama-3-8B-Instruct",
    "system":"you are an assistant",
    "messages":[
        {"role": "user", "content": ""}
    ],
    "stream": True
}

def router(data: dict) -> Tuple[str, Dict[str, Any]]:
    prompt = data.get("prompt", "").strip()
    model_name = data.get("model", "").strip().lower()
    if not prompt:
        log.error("User with username %s sent empty prompt with ip %s", data.get("username"),data.get("ip"))
        return "error", {"error": "Prompt is required"}

    if not model_name:
        model_name = "llama-3.2"

    model_key = model_name.lower()
    if model_key not in MODELS:
        log.error("User with username %s sent unknown model %s with ip %s", data.get("username"),model_name,data.get("ip"))
        return "error", {"error": "Unknown model"}

    model_url = MODELS[model_key]

    if model_key == "llama-3.2":
        payload = OLLAMA_TEMPLATE.copy()
        payload["messages"][0]["content"] = prompt
        payload["model"] = "llama3.2"

    elif model_key == "claude-2":
        payload = CLAUDE_TEMPLATE.copy()
        payload["messages"][0]["content"] = prompt

    elif model_key == "gpt-4":
        payload = GPT4_TEMPLATE.copy()
        payload["messages"][0]["content"] = prompt

    elif model_key == "vllm":
        payload = VLLM_TEMPLATE.copy()
        payload["messages"][0]["content"] = prompt
    else:
        log.error("User with username %s sent unknown model %s with ip %s", data.get("username"),model_name,data.get("ip"))
        return "error", {"error": "Unknown model"}

    return model_url, payload
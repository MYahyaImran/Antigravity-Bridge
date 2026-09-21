import json
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple
import uuid

from bridge.antigravity_client import clean_schema_for_gemini, normalize_antigravity_contents
from bridge.config import KNOWN_MODELS, get_all_known_models, resolve_model
from bridge.quota_router import QuotaRouter

logger = logging.getLogger("antigravity-bridge.openai_adapter")


def convert_openai_tools(raw_tools: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
    """Convert OpenAI tool specifications to Gemini Antigravity format with schema cleaning."""
    if not isinstance(raw_tools, list) or not raw_tools:
        return None
    fn_decls = []
    for t in raw_tools:
        if not isinstance(t, dict):
            continue
        fn = t.get("function", {}) if t.get("type") == "function" else t
        name = fn.get("name")
        if not name:
            continue
        schema = clean_schema_for_gemini(fn.get("parameters", {"type": "object", "properties": {}}), is_root=True)
        fn_decls.append({
            "name": name,
            "description": (fn.get("description") or "")[:1024],
            "parameters": schema,
        })
    return [{"functionDeclarations": fn_decls}] if fn_decls else None


def convert_openai_to_antigravity(
    openai_req: Dict[str, Any]
) -> Tuple[str, List[Dict[str, Any]], Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    Convert an OpenAI Chat Completion request body to Antigravity format:
    Returns (model, contents, system_instruction, generation_config).
    """
    raw_model = openai_req.get("model", "gemini-3.8-flash-high")
    model = resolve_model(raw_model)

    messages = openai_req.get("messages", [])
    contents: List[Dict[str, Any]] = []
    system_parts: List[Dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        # Extract text
        text_content = ""
        if isinstance(content, str):
            text_content = content
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_content += part.get("text", "")
                elif isinstance(part, str):
                    text_content += part

        if role == "system":
            if text_content:
                system_parts.append({"text": text_content})
        elif role in ("user", "human"):
            contents.append({
                "role": "user",
                "parts": [{"text": text_content}]
            })
        elif role in ("assistant", "model"):
            model_parts = []
            if text_content:
                model_parts.append({"text": text_content})
            for tc in msg.get("tool_calls", []):
                if isinstance(tc, dict):
                    fn = tc.get("function", {})
                    fn_name = fn.get("name", "tool")
                    raw_args = fn.get("arguments", {})
                    if isinstance(raw_args, str):
                        try:
                            fn_args = json.loads(raw_args)
                        except Exception:
                            fn_args = {}
                    else:
                        fn_args = raw_args or {}
                    fn_id = tc.get("id") or f"call_{uuid.uuid4().hex[:16]}"
                    model_parts.append({
                        "functionCall": {
                            "name": fn_name,
                            "args": fn_args,
                            "id": fn_id,
                        },
                        "thoughtSignature": "skip_thought_signature_validator",
                    })
            if model_parts:
                contents.append({
                    "role": "model",
                    "parts": model_parts
                })
        elif role == "tool":
            # Function/tool response
            tool_call_id = msg.get("tool_call_id") or msg.get("id") or "call_default"
            tool_name = msg.get("name") or "tool"
            contents.append({
                "role": "user",
                "parts": [{
                    "functionResponse": {
                        "name": tool_name,
                        "response": {"result": text_content},
                        "id": tool_call_id,
                    }
                }]
            })

    # Ensure at least one content part exists
    if not contents:
        contents.append({"role": "user", "parts": [{"text": "Hello"}]})

    system_instruction = None
    if system_parts:
        system_instruction = {"parts": system_parts}

    generation_config: Dict[str, Any] = {}
    if "temperature" in openai_req:
        generation_config["temperature"] = float(openai_req["temperature"])
    if "top_p" in openai_req:
        generation_config["topP"] = float(openai_req["top_p"])
    
    max_allowed = 32768 if "pro" in model.lower() else 65536
    max_toks = None
    if "max_tokens" in openai_req:
        max_toks = int(openai_req["max_tokens"])
    elif "max_completion_tokens" in openai_req:
        max_toks = int(openai_req["max_completion_tokens"])
        
    if max_toks is not None:
        # Give at least 2048 tokens so reasoning/thinking doesn't starve the response
        generation_config["maxOutputTokens"] = min(max(max_toks, 2048), max_allowed)
    else:
        generation_config["maxOutputTokens"] = 8192

    contents = normalize_antigravity_contents(contents)
    return model, contents, system_instruction, generation_config


async def stream_openai_response(
    quota_router: QuotaRouter,
    openai_req: Dict[str, Any]
) -> AsyncGenerator[str, None]:
    """Stream OpenAI-compatible Server-Sent Events (SSE)."""
    model, contents, system_inst, gen_config = convert_openai_to_antigravity(openai_req)
    tools_param = convert_openai_tools(openai_req.get("tools"))
    req_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    stream = quota_router.stream_with_failover(
        model=model,
        contents=contents,
        system_instruction=system_inst,
        generation_config=gen_config,
        tools=tools_param,
    )

    # Initial chunk with role
    init_chunk = {
        "id": req_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": ""},
                "finish_reason": None,
            }
        ],
    }
    yield f"data: {json.dumps(init_chunk)}\n\n"

    async for chunk in stream:
        response_obj = chunk.get("response", {})
        candidates = response_obj.get("candidates", [])
        for cand in candidates:
            cand_content = cand.get("content", {})
            parts = cand_content.get("parts", [])
            for p in parts:
                text = p.get("text")
                delta: Dict[str, Any] = {}

                # Check reasoning / thought: in Gemini, thought is True and text contains the thought
                if p.get("thought") is True:
                    if text:
                        delta["reasoning_content"] = text
                else:
                    if text:
                        delta["content"] = text
                    reasoning = p.get("reasoning") or (p.get("thought") if isinstance(p.get("thought"), str) else None)
                    if reasoning:
                        delta["reasoning_content"] = reasoning

                if delta:
                    chunk_data = {
                        "id": req_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": delta,
                                "finish_reason": None,
                            }
                        ],
                    }
                    yield f"data: {json.dumps(chunk_data)}\n\n"

    # Final stopping chunk
    final_chunk = {
        "id": req_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }
        ],
    }
    yield f"data: {json.dumps(final_chunk)}\n\n"
    yield "data: [DONE]\n\n"


async def generate_openai_response(
    quota_router: QuotaRouter,
    openai_req: Dict[str, Any]
) -> Dict[str, Any]:
    """Generate a non-streaming OpenAI-compatible Chat Completion response."""
    model, contents, system_inst, gen_config = convert_openai_to_antigravity(openai_req)
    tools_param = convert_openai_tools(openai_req.get("tools"))
    req_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    full_text = ""
    stream = quota_router.stream_with_failover(
        model=model,
        contents=contents,
        system_instruction=system_inst,
        generation_config=gen_config,
        tools=tools_param,
    )

    async for chunk in stream:
        response_obj = chunk.get("response", {})
        candidates = response_obj.get("candidates", [])
        for cand in candidates:
            parts = cand.get("content", {}).get("parts", [])
            for p in parts:
                text = p.get("text")
                if text:
                    full_text += text

    return {
        "id": req_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": full_text,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": len(str(contents)) // 4,
            "completion_tokens": len(full_text) // 4,
            "total_tokens": (len(str(contents)) + len(full_text)) // 4,
        },
    }


def get_openai_models_list() -> Dict[str, Any]:
    """Return list of models in OpenAI format, including dynamically discovered models."""
    data = []
    created = 1720000000
    seen = set()
    
    # All dynamic and static models
    for m in get_all_known_models():
        m_id = m["id"]
        if m_id in seen:
            continue
        seen.add(m_id)
        data.append({
            "id": m_id,
            "object": "model",
            "created": created,
            "owned_by": m.get("provider", "antigravity"),
            "permission": [],
            "root": m_id,
            "parent": None,
        })
        
    # Also expose standard aliases (e.g. gpt-4o, claude-3-5-sonnet, etc.)
    from bridge.config import MODEL_ALIASES, _DYNAMIC_ALIASES
    combined_aliases = {**MODEL_ALIASES, **_DYNAMIC_ALIASES}
    for alias in combined_aliases:
        if alias not in seen:
            seen.add(alias)
            data.append({
                "id": alias,
                "object": "model",
                "created": created,
                "owned_by": "antigravity-alias",
                "permission": [],
                "root": combined_aliases[alias],
                "parent": None,
            })

    return {"object": "list", "data": data}

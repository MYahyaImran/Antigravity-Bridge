import json
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple
import uuid

from bridge.antigravity_client import clean_schema_for_gemini, normalize_antigravity_contents
from bridge.config import resolve_model
from bridge.quota_router import QuotaRouter

logger = logging.getLogger("antigravity-bridge.anthropic_adapter")

# Cache to store thoughtSignature for tool calls across turns
# Keyed by tool_id, stores the opaque thoughtSignature returned by Gemini
_THOUGHT_SIGNATURE_CACHE: Dict[str, str] = {}
_MAX_SIGNATURE_CACHE_SIZE = 1000


def _cache_thought_signature(tool_id: str, sig: str):
    """Cache thoughtSignature with LRU-style eviction."""
    if not tool_id or not sig:
        return
    if len(_THOUGHT_SIGNATURE_CACHE) >= _MAX_SIGNATURE_CACHE_SIZE:
        # Remove oldest 100 entries
        keys_to_remove = list(_THOUGHT_SIGNATURE_CACHE.keys())[:100]
        for k in keys_to_remove:
            _THOUGHT_SIGNATURE_CACHE.pop(k, None)
    _THOUGHT_SIGNATURE_CACHE[tool_id] = sig


def convert_anthropic_to_antigravity(
    anthropic_req: Dict[str, Any]
) -> Tuple[str, List[Dict[str, Any]], Optional[Dict[str, Any]], Dict[str, Any], Optional[List[Dict[str, Any]]]]:
    """
    Convert an Anthropic /v1/messages request body to Antigravity format.
    Returns (model, contents, system_instruction, generation_config, tools).
    """
    raw_model = anthropic_req.get("model", "claude-sonnet-4-6")
    model = resolve_model(raw_model)

    # 1. Convert tools if provided
    tools_param: Optional[List[Dict[str, Any]]] = None
    raw_tools = anthropic_req.get("tools")
    if isinstance(raw_tools, list) and raw_tools:
        fn_decls = []
        for t in raw_tools:
            if not isinstance(t, dict):
                continue
            name = t.get("name")
            if not name:
                continue
            schema = clean_schema_for_gemini(t.get("input_schema", {"type": "object", "properties": {}}), is_root=True)
            fn_decls.append({
                "name": name,
                "description": (t.get("description") or "")[:1024],
                "parameters": schema,
            })
        if fn_decls:
            tools_param = [{"functionDeclarations": fn_decls}]

    # 2. Build mapping of tool_use ID to tool name across message history
    tool_id_to_name: Dict[str, str] = {}
    messages = anthropic_req.get("messages", [])
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    t_id = block.get("id")
                    t_name = block.get("name")
                    if t_id and t_name:
                        tool_id_to_name[t_id] = t_name

    # 3. Convert message turns
    contents: List[Dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        text_parts: List[Dict[str, Any]] = []
        fn_call_parts: List[Dict[str, Any]] = []
        fn_response_parts: List[Dict[str, Any]] = []

        if isinstance(content, str):
            if content.strip():
                text_parts.append({"text": content})
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, str):
                    if block.strip():
                        text_parts.append({"text": block})
                elif isinstance(block, dict):
                    b_type = block.get("type")
                    if b_type == "text":
                        txt = block.get("text", "")
                        if txt:
                            text_parts.append({"text": txt})
                    elif b_type == "thinking":
                        th = block.get("thinking", "")
                        if th:
                            # In Gemini protobuf, thought is a boolean (TYPE_BOOL), and text holds the reasoning
                            text_parts.append({"text": th, "thought": True})
                    elif b_type == "tool_use":
                        # Assistant requested a tool call
                        name = block.get("name", "tool")
                        tool_id = block.get("id") or f"toolu_{uuid.uuid4().hex[:16]}"
                        inp = block.get("input", {})
                        tool_id_to_name[tool_id] = name
                        sig = _THOUGHT_SIGNATURE_CACHE.get(tool_id) or "skip_thought_signature_validator"
                        fn_call_parts.append({
                            "functionCall": {
                                "name": name,
                                "args": inp if isinstance(inp, dict) else {},
                                "id": tool_id,
                            },
                            "thoughtSignature": sig,
                        })
                    elif b_type == "tool_result":
                        # Tool output returned to model
                        tool_id = block.get("tool_use_id", "") or f"toolu_{uuid.uuid4().hex[:16]}"
                        name = tool_id_to_name.get(tool_id, "tool")
                        raw_content = block.get("content", "")
                        if isinstance(raw_content, list):
                            text_items = []
                            for b in raw_content:
                                if isinstance(b, dict):
                                    if b.get("type") == "text":
                                        text_items.append(b.get("text", ""))
                                elif isinstance(b, str):
                                    text_items.append(b)
                            content_str = "\n".join(text_items)
                        elif isinstance(raw_content, str):
                            content_str = raw_content
                        else:
                            content_str = json.dumps(raw_content)

                        if block.get("is_error"):
                            content_str = f"Error: {content_str}"

                        fn_resp: Dict[str, Any] = {
                            "name": name,
                            "response": {"result": content_str},
                            "id": tool_id,
                        }
                        fn_response_parts.append({"functionResponse": fn_resp})

        antigravity_role = "user" if role in ("user", "human") else "model"

        # IMPORTANT Ordering for Vertex AI Claude and Gemini:
        # 1. In model turns: text/thought parts MUST come first, followed by function call parts.
        #    (Vertex AI Claude rejects tool_use followed by text in an assistant message).
        # 2. In user turns: functionResponse parts MUST come first, followed by any text parts.
        if antigravity_role == "model":
            all_parts = text_parts + fn_call_parts
        else:
            all_parts = fn_response_parts + text_parts

        if all_parts:
            contents.append({
                "role": antigravity_role,
                "parts": all_parts,
            })
        elif antigravity_role == "user":
            contents.append({
                "role": "user",
                "parts": [{"text": "Hello"}],
            })

    # Normalize conversation: alternating roles, never ending with model turn
    contents = normalize_antigravity_contents(contents)

    # Extract system instruction
    system_val = anthropic_req.get("system")
    system_instruction = None
    if system_val:
        if isinstance(system_val, str) and system_val.strip():
            system_instruction = {"parts": [{"text": system_val.strip()}]}
        elif isinstance(system_val, list):
            sys_texts = []
            for item in system_val:
                if isinstance(item, dict) and item.get("type") == "text":
                    sys_texts.append(item.get("text", ""))
                elif isinstance(item, str):
                    sys_texts.append(item)
            if sys_texts:
                system_instruction = {"parts": [{"text": "\n".join(sys_texts)}]}

    generation_config: Dict[str, Any] = {}
    if "temperature" in anthropic_req:
        generation_config["temperature"] = float(anthropic_req["temperature"])
    if "top_p" in anthropic_req:
        generation_config["topP"] = float(anthropic_req["top_p"])
    max_allowed = 32768 if "pro" in model.lower() else 65536
    if "max_tokens" in anthropic_req:
        max_toks = int(anthropic_req["max_tokens"])
        generation_config["maxOutputTokens"] = min(max(max_toks, 2048), max_allowed)
    else:
        generation_config["maxOutputTokens"] = 8192

    return model, contents, system_instruction, generation_config, tools_param


async def stream_anthropic_response(
    quota_router: QuotaRouter,
    anthropic_req: Dict[str, Any]
) -> AsyncGenerator[str, None]:
    """Stream Anthropic-compatible Server-Sent Events (SSE)."""
    raw_model = anthropic_req.get("model", "claude-sonnet-4-6")
    model, contents, system_inst, gen_config, tools_param = convert_anthropic_to_antigravity(anthropic_req)
    msg_id = f"msg_{uuid.uuid4().hex[:16]}"

    stream = quota_router.stream_with_failover(
        model=model,
        contents=contents,
        system_instruction=system_inst,
        generation_config=gen_config,
        tools=tools_param,
    )

    # 1. message_start (echoing the model requested by client)
    start_payload = {
        "type": "message_start",
        "message": {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": raw_model,
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": len(str(contents)) // 4, "output_tokens": 1},
        },
    }
    yield f"event: message_start\ndata: {json.dumps(start_payload)}\n\n"

    current_block_index = -1
    current_block_type: Optional[str] = None
    has_tool_call = False
    total_output_chars = 0

    try:
        async for chunk in stream:
            response_obj = chunk.get("response", {})
            candidates = response_obj.get("candidates", [])
            for cand in candidates:
                parts = cand.get("content", {}).get("parts", [])
                for p in parts:
                    # 1. Check reasoning / thought
                    is_thought = False
                    thought_content = ""
                    if p.get("thought") is True:
                        is_thought = True
                        thought_content = p.get("text", "")
                    elif isinstance(p.get("thought"), str) and p.get("thought"):
                        is_thought = True
                        thought_content = p.get("thought")
                    elif isinstance(p.get("reasoning"), str) and p.get("reasoning"):
                        is_thought = True
                        thought_content = p.get("reasoning")

                    if is_thought and thought_content:
                        total_output_chars += len(thought_content)
                        if current_block_type != "thinking":
                            if current_block_type is not None:
                                yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': current_block_index})}\n\n"
                            current_block_index += 1
                            current_block_type = "thinking"
                            start_blk = {
                                "type": "content_block_start",
                                "index": current_block_index,
                                "content_block": {"type": "thinking", "thinking": ""},
                            }
                            yield f"event: content_block_start\ndata: {json.dumps(start_blk)}\n\n"

                        delta_payload = {
                            "type": "content_block_delta",
                            "index": current_block_index,
                            "delta": {"type": "thinking_delta", "thinking": thought_content},
                        }
                        yield f"event: content_block_delta\ndata: {json.dumps(delta_payload)}\n\n"

                    elif not is_thought:
                        # 2. Check regular text
                        text = p.get("text")
                        if text:
                            total_output_chars += len(text)
                            if current_block_type != "text":
                                if current_block_type is not None:
                                    yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': current_block_index})}\n\n"
                                current_block_index += 1
                                current_block_type = "text"
                                start_blk = {
                                    "type": "content_block_start",
                                    "index": current_block_index,
                                    "content_block": {"type": "text", "text": ""},
                                }
                                yield f"event: content_block_start\ndata: {json.dumps(start_blk)}\n\n"

                            delta_payload = {
                                "type": "content_block_delta",
                                "index": current_block_index,
                                "delta": {"type": "text_delta", "text": text},
                            }
                            yield f"event: content_block_delta\ndata: {json.dumps(delta_payload)}\n\n"

                    # 3. Check functionCall
                    fn_call = p.get("functionCall")
                    if fn_call:
                        has_tool_call = True
                        if current_block_type is not None:
                            yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': current_block_index})}\n\n"
                            current_block_type = None

                        fn_name = fn_call.get("name", "tool")
                        fn_args = fn_call.get("args", {})
                        fn_id = fn_call.get("id") or f"toolu_{uuid.uuid4().hex[:20]}"

                        # Capture thoughtSignature for multi-turn tool calling
                        sig = p.get("thoughtSignature") or p.get("thought_signature") or fn_call.get("thoughtSignature")
                        if sig:
                            _cache_thought_signature(fn_id, sig)

                        current_block_index += 1
                        tool_start = {
                            "type": "content_block_start",
                            "index": current_block_index,
                            "content_block": {
                                "type": "tool_use",
                                "id": fn_id,
                                "name": fn_name,
                                "input": {},
                            },
                        }
                        yield f"event: content_block_start\ndata: {json.dumps(tool_start)}\n\n"

                        args_json = json.dumps(fn_args) if isinstance(fn_args, dict) else str(fn_args)
                        total_output_chars += len(args_json)
                        tool_delta = {
                            "type": "content_block_delta",
                            "index": current_block_index,
                            "delta": {
                                "type": "input_json_delta",
                                "partial_json": args_json,
                            },
                        }
                        yield f"event: content_block_delta\ndata: {json.dumps(tool_delta)}\n\n"

                        yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': current_block_index})}\n\n"

        # Close any open content block
        if current_block_type is not None:
            yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': current_block_index})}\n\n"
            current_block_type = None

        # If nothing was emitted at all, emit empty text block
        if current_block_index == -1:
            yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}})}\n\n"
            yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': 0})}\n\n"

        # message_delta
        stop_reason = "tool_use" if has_tool_call else "end_turn"
        msg_delta_payload = {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": {"output_tokens": max(1, total_output_chars // 4)},
        }
        yield f"event: message_delta\ndata: {json.dumps(msg_delta_payload)}\n\n"

        # message_stop
        yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"

    except Exception as e:
        logger.error("Error streaming Anthropic response: %s", e)
        err_payload = {
            "type": "error",
            "error": {
                "type": "api_error",
                "message": str(e),
            },
        }
        yield f"event: error\ndata: {json.dumps(err_payload)}\n\n"


async def generate_anthropic_response(
    quota_router: QuotaRouter,
    anthropic_req: Dict[str, Any]
) -> Dict[str, Any]:
    """Generate a non-streaming Anthropic-compatible message response."""
    raw_model = anthropic_req.get("model", "claude-sonnet-4-6")
    model, contents, system_inst, gen_config, tools_param = convert_anthropic_to_antigravity(anthropic_req)
    msg_id = f"msg_{uuid.uuid4().hex[:16]}"

    full_text = ""
    full_thought = ""
    tool_calls: List[Dict[str, Any]] = []

    stream = quota_router.stream_with_failover(
        model=model,
        contents=contents,
        system_instruction=system_inst,
        generation_config=gen_config,
        tools=tools_param,
    )

    async for chunk in stream:
        candidates = chunk.get("response", {}).get("candidates", [])
        for cand in candidates:
            parts = cand.get("content", {}).get("parts", [])
            for p in parts:
                if p.get("thought") is True:
                    th = p.get("text", "")
                    if th:
                        full_thought += th
                else:
                    text = p.get("text")
                    if text:
                        full_text += text
                fn_call = p.get("functionCall")
                if fn_call:
                    fn_id = fn_call.get("id") or f"toolu_{uuid.uuid4().hex[:20]}"
                    fn_call["id"] = fn_id
                    tool_calls.append(fn_call)
                    sig = p.get("thoughtSignature") or p.get("thought_signature") or fn_call.get("thoughtSignature")
                    if sig:
                        _cache_thought_signature(fn_id, sig)

    content_blocks: List[Dict[str, Any]] = []
    if full_thought:
        content_blocks.append({"type": "thinking", "thinking": full_thought})
    if full_text:
        content_blocks.append({"type": "text", "text": full_text})
    for tc in tool_calls:
        fn_id = tc.get("id") or f"toolu_{uuid.uuid4().hex[:20]}"
        content_blocks.append({
            "type": "tool_use",
            "id": fn_id,
            "name": tc.get("name", "tool"),
            "input": tc.get("args", {}),
        })
    if not content_blocks:
        content_blocks.append({"type": "text", "text": ""})

    stop_reason = "tool_use" if tool_calls else "end_turn"
    total_len = len(full_text) + sum(len(str(tc)) for tc in tool_calls)

    return {
        "id": msg_id,
        "type": "message",
        "role": "assistant",
        "content": content_blocks,
        "model": raw_model,
        "stop_reason": stop_reason,
        "usage": {
            "input_tokens": len(str(contents)) // 4,
            "output_tokens": max(1, total_len // 4),
        },
    }

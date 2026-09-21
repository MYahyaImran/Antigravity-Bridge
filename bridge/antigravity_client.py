import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional
import uuid
import httpx

from bridge.config import (
    ANTIGRAVITY_BASE_URL,
    ANTIGRAVITY_FALLBACK_BASE_URL,
    DEFAULT_PROJECT,
    USER_AGENT,
    resolve_model,
)

logger = logging.getLogger("antigravity-bridge.client")


class QuotaExceededError(Exception):
    """Raised when an account's quota limit is reached (HTTP 429 / RESOURCE_EXHAUSTED)."""
    def __init__(self, message: str, reset_time: Optional[str] = None):
        super().__init__(message)
        self.reset_time = reset_time


def clean_schema_for_gemini(obj: Any, is_root: bool = False) -> Any:
    """
    Sanitize JSON Schema so Google Antigravity / Gemini Protobuf validators accept it.
    
    Fixes:
    1. Arrays: Gemini strictly requires an 'items' schema object for any type == 'array'.
       If 'items' is missing or empty, defaults to {'type': 'string'}.
       If 'items' is a list (tuple validation in JSON Schema), unwraps to a single schema.
       Ensures nested arrays (e.g. array of arrays) recursively have 'items' at every level.
    2. Objects: Non-root objects without properties get a placeholder to satisfy the validator.
    3. Union types: Lists like ['string', 'null'] or ['string', 'integer'] are resolved to a single type.
    4. Enums: Converts 'const' to 'enum', ensures enum values are strings.
    5. Combinators: Collapses 'anyOf'/'oneOf' to enums if string enums, or picks first valid branch.
       Merges 'allOf' dictionaries.
    6. Keywords: Strips unsupported keywords like $schema, $defs, definitions, propertyNames, $id, title.
    7. Required: Filters 'required' list to only include keys actually present in 'properties'.
    8. Bounds: Converts exclusiveMinimum/exclusiveMaximum to minimum/maximum.
    """
    if isinstance(obj, list):
        return [clean_schema_for_gemini(x, is_root=False) for x in obj]

    if not isinstance(obj, dict):
        return obj

    schema = dict(obj)

    # 1. Strip unsupported meta-keywords
    for drop_key in ("$schema", "$defs", "definitions", "propertyNames", "$id", "id", "title"):
        schema.pop(drop_key, None)

    # 2. Handle type normalization (list -> single type + nullable)
    raw_type = schema.get("type")
    if isinstance(raw_type, list):
        non_null = [str(t) for t in raw_type if str(t).lower() != "null"]
        if len(non_null) < len(raw_type):
            schema["nullable"] = True
        schema["type"] = non_null[0] if non_null else "string"
    elif isinstance(raw_type, str):
        schema["type"] = raw_type.lower()

    # 3. Convert const to enum
    if "const" in schema and "enum" not in schema:
        schema["enum"] = [schema.pop("const")]
        if "type" not in schema:
            schema["type"] = "string"

    # 4. Convert exclusiveMinimum / exclusiveMaximum
    if "exclusiveMinimum" in schema:
        ex_min = schema.pop("exclusiveMinimum")
        if isinstance(ex_min, (int, float)) and "minimum" not in schema:
            schema["minimum"] = ex_min
    if "exclusiveMaximum" in schema:
        ex_max = schema.pop("exclusiveMaximum")
        if isinstance(ex_max, (int, float)) and "maximum" not in schema:
            schema["maximum"] = ex_max

    # 5. Handle anyOf / oneOf / allOf
    for union_key in ("anyOf", "oneOf"):
        if union_key in schema:
            branches = schema.pop(union_key)
            if isinstance(branches, list) and branches:
                all_enums = []
                can_collapse_enum = True
                for b in branches:
                    if isinstance(b, dict) and "enum" in b and isinstance(b["enum"], list):
                        all_enums.extend(b["enum"])
                    elif isinstance(b, dict) and "const" in b:
                        all_enums.append(b["const"])
                    else:
                        can_collapse_enum = False
                        break
                if can_collapse_enum and all_enums:
                    schema["type"] = "string"
                    schema["enum"] = all_enums
                else:
                    selected = None
                    for b in branches:
                        if isinstance(b, dict) and b.get("type") != "null":
                            selected = b
                            break
                    if not selected and isinstance(branches[0], dict):
                        selected = branches[0]
                    if selected:
                        for k, v in selected.items():
                            if k not in schema:
                                schema[k] = v

    if "allOf" in schema:
        all_of_list = schema.pop("allOf")
        if isinstance(all_of_list, list):
            for item in all_of_list:
                if isinstance(item, dict):
                    if "properties" in item and isinstance(item["properties"], dict):
                        schema.setdefault("properties", {}).update(item["properties"])
                    if "required" in item and isinstance(item["required"], list):
                        schema.setdefault("required", []).extend(item["required"])
                    for k, v in item.items():
                        if k not in ("properties", "required") and k not in schema:
                            schema[k] = v

    # 6. Normalize enum values to strings
    if "enum" in schema and isinstance(schema["enum"], list):
        schema["enum"] = [str(x) for x in schema["enum"]]
        if "type" not in schema:
            schema["type"] = "string"

    # 7. Infer type if missing
    if "type" not in schema:
        if "properties" in schema:
            schema["type"] = "object"
        elif "items" in schema:
            schema["type"] = "array"
        elif "enum" in schema:
            schema["type"] = "string"

    # 8. CRITICAL: Handle Array types and items
    type_val = schema.get("type")
    is_array = (isinstance(type_val, str) and type_val == "array") or ("items" in schema)
    if is_array:
        schema["type"] = "array"
        items = schema.get("items")
        if items is None:
            schema["items"] = {"type": "string"}
        elif isinstance(items, list):
            if items and isinstance(items[0], dict):
                schema["items"] = clean_schema_for_gemini(items[0], is_root=False)
            else:
                schema["items"] = {"type": "string"}
        elif isinstance(items, dict):
            if not items:
                schema["items"] = {"type": "string"}
            else:
                schema["items"] = clean_schema_for_gemini(items, is_root=False)
        else:
            schema["items"] = {"type": "string"}

    # 9. Handle Object types and properties
    if schema.get("type") == "object":
        if "properties" in schema and isinstance(schema["properties"], dict):
            cleaned_props = {}
            for pk, pv in schema["properties"].items():
                cleaned_props[pk] = clean_schema_for_gemini(pv, is_root=False)
            schema["properties"] = cleaned_props
        elif not is_root:
            schema["properties"] = {
                "_empty": {
                    "type": "string",
                    "description": "Arbitrary or empty object payload"
                }
            }
        else:
            schema.setdefault("properties", {})

    # 10. Clean 'required' array
    if "required" in schema and isinstance(schema["required"], list):
        if "properties" in schema and isinstance(schema["properties"], dict):
            schema["required"] = [r for r in schema["required"] if r in schema["properties"]]
        else:
            schema.pop("required", None)

    # 11. Recursively clean any remaining dictionary values (except already cleaned items/properties)
    for k, v in list(schema.items()):
        if k not in ("properties", "items"):
            if isinstance(v, (dict, list)):
                schema[k] = clean_schema_for_gemini(v, is_root=False)

    return schema


def normalize_antigravity_tools(tools: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
    """Sanitize and normalize tools list for Google Antigravity/Gemini backend."""
    if not tools or not isinstance(tools, list):
        return None

    normalized_tools = []
    for tool_group in tools:
        if not isinstance(tool_group, dict):
            continue
        new_group = dict(tool_group)
        for decls_key in ("functionDeclarations", "function_declarations"):
            if decls_key in new_group and isinstance(new_group[decls_key], list):
                cleaned_decls = []
                for decl in new_group[decls_key]:
                    if not isinstance(decl, dict):
                        continue
                    new_decl = dict(decl)
                    if "parameters" in new_decl and isinstance(new_decl["parameters"], dict):
                        new_decl["parameters"] = clean_schema_for_gemini(new_decl["parameters"], is_root=True)
                    cleaned_decls.append(new_decl)
                new_group[decls_key] = cleaned_decls
        normalized_tools.append(new_group)
    return normalized_tools or None


def normalize_antigravity_contents(contents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Ensure contents conforms to Google Antigravity / Gemini internal requirements:
    1. Must not be empty.
    2. Must start with a 'user' turn.
    3. Consecutive turns with the same role are merged into one.
    4. Must NEVER end with a 'model' turn:
       - If trailing model turn has non-empty text (e.g. assistant prefill), append a user turn with 'Continue'.
       - If trailing model turn has no text or is whitespace, pop it.
    5. Strips empty parts so Gemini does not receive invalid empty turns.
    """
    if not contents:
        return [{"role": "user", "parts": [{"text": "Hello"}]}]

    valid_turns: List[Dict[str, Any]] = []
    for turn in contents:
        role = turn.get("role", "user")
        parts = turn.get("parts", [])
        clean_parts: List[Dict[str, Any]] = []
        for p in parts:
            if isinstance(p, dict):
                if "text" in p:
                    txt = p.get("text", "")
                    if txt is not None and str(txt).strip():
                        part_entry: Dict[str, Any] = {"text": str(txt)}
                        if "thought" in p:
                            part_entry["thought"] = bool(p["thought"])
                        clean_parts.append(part_entry)
                elif "thought" in p:
                    # If thought was passed as string, move content to text and set thought=True
                    th = p.get("thought")
                    if isinstance(th, str) and th.strip():
                        clean_parts.append({"text": th, "thought": True})
                    elif th is True and p.get("text"):
                        clean_parts.append({"text": str(p["text"]), "thought": True})
                elif "functionCall" in p:
                    fc = dict(p.get("functionCall", {}))
                    if not fc.get("id"):
                        fc["id"] = f"call_{uuid.uuid4().hex[:16]}"
                    p_copy = dict(p)
                    p_copy["functionCall"] = fc
                    if "thoughtSignature" not in p_copy and "thought_signature" not in p_copy:
                        p_copy["thoughtSignature"] = "skip_thought_signature_validator"
                    clean_parts.append(p_copy)
                elif "functionResponse" in p:
                    fr = dict(p.get("functionResponse", {}))
                    if not fr.get("id"):
                        fr["id"] = f"call_{uuid.uuid4().hex[:16]}"
                    p_copy = dict(p)
                    p_copy["functionResponse"] = fr
                    clean_parts.append(p_copy)
                elif "inlineData" in p:
                    clean_parts.append(p)
            elif isinstance(p, str):
                if p.strip():
                    clean_parts.append({"text": p})

        if clean_parts:
            valid_turns.append({"role": role, "parts": clean_parts})

    if not valid_turns:
        return [{"role": "user", "parts": [{"text": "Hello"}]}]

    # 1. Must start with 'user'
    if valid_turns[0]["role"] == "model":
        valid_turns.insert(0, {"role": "user", "parts": [{"text": "Hello"}]})

    # 2. Merge consecutive turns of the same role
    merged: List[Dict[str, Any]] = []
    for turn in valid_turns:
        if merged and merged[-1]["role"] == turn["role"]:
            merged[-1]["parts"].extend(turn["parts"])
        else:
            merged.append(turn)

    # 3. Must NEVER end with a 'model' turn (Vertex AI and Gemini reject trailing model turns)
    if merged and merged[-1]["role"] == "model":
        last_parts = merged[-1]["parts"]
        has_fn_call = any("functionCall" in p for p in last_parts)
        if has_fn_call:
            # If the model turn ends with a functionCall, Vertex Claude requires a matching tool_result
            fn_resps = []
            for p in last_parts:
                if "functionCall" in p:
                    fc = p["functionCall"]
                    fn_resps.append({
                        "functionResponse": {
                            "name": fc.get("name", "tool"),
                            "response": {"result": "Done"},
                            "id": fc.get("id", "call_default"),
                        }
                    })
            merged.append({"role": "user", "parts": fn_resps})
        else:
            merged.append({"role": "user", "parts": [{"text": "Continue"}]})

    # 4. Enforce strict part ordering per turn:
    # - In model turns: text/thought parts must come first, followed by functionCall.
    # - In user turns: functionResponse parts must come first, followed by text.
    ordered_turns: List[Dict[str, Any]] = []
    for turn in merged:
        role = turn["role"]
        parts = turn["parts"]
        if role == "model":
            text_p = [p for p in parts if "text" in p or "thought" in p]
            fn_p = [p for p in parts if "functionCall" in p]
            other_p = [p for p in parts if p not in text_p and p not in fn_p]
            ordered_turns.append({"role": "model", "parts": text_p + other_p + fn_p})
        else:
            fn_resp_p = [p for p in parts if "functionResponse" in p]
            text_p = [p for p in parts if "text" in p]
            other_p = [p for p in parts if p not in fn_resp_p and p not in text_p]
            ordered_turns.append({"role": "user", "parts": fn_resp_p + other_p + text_p})

    return ordered_turns


class AntigravityClient:
    def __init__(
        self,
        base_url: str = ANTIGRAVITY_BASE_URL,
        fallback_url: str = ANTIGRAVITY_FALLBACK_BASE_URL,
        timeout: float = 120.0,
    ):
        self.base_url = base_url
        self.fallback_url = fallback_url
        self.timeout = timeout

    def _headers(self, access_token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }

    async def fetch_models(self, access_token: str) -> Dict[str, Any]:
        """Fetch available models for this account."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.base_url}:fetchAvailableModels",
                headers=self._headers(access_token),
                json={},
            )
            if resp.status_code == 200:
                return resp.json()
            # Try fallback
            fallback_resp = await client.post(
                f"{self.fallback_url}:fetchAvailableModels",
                headers=self._headers(access_token),
                json={},
            )
            if fallback_resp.status_code == 200:
                return fallback_resp.json()
            raise RuntimeError(f"fetchAvailableModels failed: {resp.status_code} {resp.text}")

    async def fetch_quota_summary(self, access_token: str) -> Dict[str, Any]:
        """Fetch real-time quota status and remaining fractions for all model buckets."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.base_url}:retrieveUserQuotaSummary",
                headers=self._headers(access_token),
                json={},
            )
            if resp.status_code == 200:
                return resp.json()
            # Try fallback
            fallback_resp = await client.post(
                f"{self.fallback_url}:retrieveUserQuotaSummary",
                headers=self._headers(access_token),
                json={},
            )
            if fallback_resp.status_code == 200:
                return fallback_resp.json()
            raise RuntimeError(f"retrieveUserQuotaSummary failed: {resp.status_code} {resp.text}")

    async def load_code_assist(self, access_token: str) -> Dict[str, Any]:
        """Load account subscription metadata and tier details."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.base_url}:loadCodeAssist",
                headers=self._headers(access_token),
                json={},
            )
            if resp.status_code == 200:
                return resp.json()
            fallback_resp = await client.post(
                f"{self.fallback_url}:loadCodeAssist",
                headers=self._headers(access_token),
                json={},
            )
            if fallback_resp.status_code == 200:
                return fallback_resp.json()
            raise RuntimeError(f"loadCodeAssist failed: {resp.status_code} {resp.text}")

    async def stream_generate_content(
        self,
        access_token: str,
        model: str,
        contents: List[Dict[str, Any]],
        system_instruction: Optional[Dict[str, Any]] = None,
        generation_config: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        project: str = DEFAULT_PROJECT,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream content generation from Antigravity internal backend."""
        resolved_model = resolve_model(model)
        request_id = str(uuid.uuid4())

        inner_request: Dict[str, Any] = {
            "contents": normalize_antigravity_contents(contents),
        }
        if system_instruction:
            inner_request["systemInstruction"] = system_instruction
        if generation_config:
            inner_request["generationConfig"] = generation_config
        if tools:
            norm_tools = normalize_antigravity_tools(tools)
            if norm_tools:
                inner_request["tools"] = norm_tools

        payload = {
            "project": project,
            "model": resolved_model,
            "requestId": request_id,
            "userAgent": USER_AGENT,
            "request": inner_request,
        }

        url = f"{self.base_url}:streamGenerateContent?alt=sse"

        # Try base_url first, then fallback_url if connection fails
        endpoints_to_try = [url, f"{self.fallback_url}:streamGenerateContent?alt=sse"]

        last_stream_err = None
        for endpoint in endpoints_to_try:
            client = httpx.AsyncClient(timeout=self.timeout)
            try:
                async with client.stream(
                    "POST",
                    endpoint,
                    headers=self._headers(access_token),
                    json=payload,
                ) as response:
                    if response.status_code == 429:
                        error_text = await response.aread()
                        raise QuotaExceededError(
                            f"Quota exceeded (429) for model {resolved_model}: {error_text.decode('utf-8', errors='ignore')}"
                        )
                    elif response.status_code != 200:
                        error_text = await response.aread()
                        err_str = error_text.decode("utf-8", errors="ignore")
                        if "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                            raise QuotaExceededError(f"Quota exhausted: {err_str}")
                        if response.status_code >= 500:
                            logger.warning("Endpoint %s returned HTTP %d (%s). Trying fallback...", endpoint, response.status_code, err_str)
                            last_stream_err = RuntimeError(
                                f"Antigravity upstream error ({endpoint}): HTTP {response.status_code} - {err_str}"
                            )
                            continue
                        raise RuntimeError(
                            f"Antigravity upstream error ({endpoint}): HTTP {response.status_code} - {err_str}"
                        )

                    buffer = ""
                    async for chunk in response.aiter_text():
                        buffer += chunk
                        lines = buffer.split("\n")
                        # Keep uncompleted trailing line in buffer
                        buffer = lines.pop()

                        for line in lines:
                            line = line.strip()
                            if not line:
                                continue
                            if line.startswith("data:"):
                                raw_data = line[5:].strip()
                                if raw_data == "[DONE]":
                                    break
                                try:
                                    parsed = json.loads(raw_data)
                                    yield parsed
                                except json.JSONDecodeError:
                                    logger.debug("Non-json SSE chunk: %s", raw_data)

                    # Process any remaining buffer
                    if buffer.strip().startswith("data:"):
                        raw_data = buffer.strip()[5:].strip()
                        if raw_data and raw_data != "[DONE]":
                            try:
                                parsed = json.loads(raw_data)
                                yield parsed
                            except json.JSONDecodeError:
                                pass
                # If stream succeeded, exit retry loop
                return
            except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadTimeout) as conn_err:
                logger.warning("Connection error on %s: %s. Retrying on next endpoint...", endpoint, conn_err)
                last_stream_err = conn_err
                await asyncio.sleep(0.5)
            finally:
                await client.aclose()

        if last_stream_err:
            err_msg = str(last_stream_err)
            if "CAPACITY_EXHAUSTED" in err_msg or "RESOURCE_EXHAUSTED" in err_msg or "503" in err_msg:
                raise QuotaExceededError(f"Quota / Capacity exhausted on all endpoints: {err_msg}")
            raise last_stream_err

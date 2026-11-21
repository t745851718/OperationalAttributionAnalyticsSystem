import json
import logging
import os
import re

import httpx

from backend.config import LLM_BASE_URL


logger = logging.getLogger(__name__)


def object_schema(properties, required=None):
    return {"type": "object", "properties": properties, "additionalProperties": False,
            "required": list(properties) if required is None else required}


class ModelError(RuntimeError):
    pass


class MessagesModel:
    async def json_request(self, instructions, payload, max_tokens=1800, *, schema=None):
        key, model = os.getenv("LLM_API_KEY"), os.getenv("LLM_MODEL")
        if not key or not model:
            raise ModelError("请在根目录 .env 中配置 LLM_API_KEY 和 LLM_MODEL")
        request = {"model": model, "max_tokens": max_tokens, "system": instructions,
                   "thinking": {"type": "disabled"},
                   "messages": [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]}
        if schema:
            request["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
        stop_reason, block_types = None, []
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(65, connect=10)) as client:
                response = await client.post(
                    f"{LLM_BASE_URL}/v1/messages",
                    headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                    json=request,
                )
                response.raise_for_status()
            body = response.json()
            blocks = body.get("content", [])
            stop_reason = body.get("stop_reason")
            block_types = [item.get("type") for item in blocks]
            content = "".join(item.get("text", "") for item in blocks if item.get("type") == "text").strip()
            content = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", content)
            decoded = json.loads(content)
            if not isinstance(decoded, dict):
                raise ValueError
            return decoded
        except httpx.HTTPStatusError as exc:
            raise ModelError(f"模型服务返回 HTTP {exc.response.status_code}") from None
        except httpx.RequestError:
            raise ModelError("模型服务连接失败或响应超时") from None
        except (ValueError, KeyError, AttributeError, TypeError):
            logger.warning("Invalid Messages response, stop=%s blocks=%s", stop_reason, block_types)
            raise ModelError("模型服务返回了无效的分析结构") from None

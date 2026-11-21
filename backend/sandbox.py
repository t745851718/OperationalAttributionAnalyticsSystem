import asyncio
import contextlib
import json
import os
from pathlib import Path
from uuid import uuid4

from backend.config import RUNTIME
from backend.sandbox_worker import get_query

MAX_OUTPUT = 1_048_576


def evidence_code(request):
    return {
        "language": "sql",
        "source": get_query(request["domain"], request["template"], request["filters"]),
        "parameters": {key: [*request[key], *request["filters"].values()]
                       for key in ("baseline", "current", "history")},
        "executor": "backend.sandbox_worker.evaluate",
    }


async def remove_container(name):
    process = await asyncio.create_subprocess_exec(
        "docker", "rm", "-f", name,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except TimeoutError:
        process.kill()
        await process.wait()


async def verify(version, request, timeout=20, memory_mb=512):
    database = RUNTIME / f"{version}.duckdb"
    if not database.is_file():
        return {"status": "error", "reasons": ["未找到数仓验证副本"]}
    name = f"attribution-verify-{uuid4().hex}"
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            "docker", "run", "--pull=never", "--rm", "--name", name, "--network=none",
            "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
            f"--memory={memory_mb}m", f"--memory-swap={memory_mb}m", "--pids-limit=24", "--cpus=1",
            "--mount", f"type=bind,source={database},target=/warehouse/demo.duckdb,readonly",
            "-i", os.getenv("SANDBOX_IMAGE", "attribution-sandbox:local"),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        async with asyncio.timeout(timeout):
            process.stdin.write(json.dumps(request, ensure_ascii=False).encode())
            await process.stdin.drain()
            process.stdin.close()
            output = bytearray()
            async for chunk in _read_chunks(process.stdout):
                output.extend(chunk)
                if len(output) > MAX_OUTPUT:
                    return {"status": "error", "reasons": ["验证输出超出 1 MB"]}
            if await process.wait():
                return {"status": "error", "reasons": ["验证容器未成功结束，请检查镜像、挂载和配额"]}
            return json.loads(output)
    except TimeoutError:
        return {"status": "timeout", "reasons": ["验证已终止，结果可能不完整"]}
    except (OSError, ValueError):
        return {"status": "error", "reasons": ["统计验证环境不可用或返回无效结果"]}
    finally:
        if process is not None and process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
            with contextlib.suppress(OSError):
                await remove_container(name)


async def _read_chunks(reader):
    while chunk := await reader.read(65536):
        yield chunk

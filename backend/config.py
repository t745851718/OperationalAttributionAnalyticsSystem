import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
RUNTIME = Path(os.getenv("ATTRIBUTION_RUNTIME", str(ROOT / ".runtime"))).resolve()

LLM_BASE_URL = "https://ws-a0x5jc6dusvyqin7.cn-beijing.maas.aliyuncs.com/apps/anthropic"

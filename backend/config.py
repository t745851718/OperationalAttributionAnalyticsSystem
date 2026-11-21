import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
RUNTIME = Path(os.getenv("ATTRIBUTION_RUNTIME", str(ROOT / ".runtime"))).resolve()

LLM_BASE_URL = "https://ws-a0x5jc6dusvyqin7.cn-beijing.maas.aliyuncs.com/apps/anthropic"


def postgres_dsn():
    from psycopg.conninfo import make_conninfo

    return os.getenv("DATABASE_URL") or make_conninfo(
        host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "attribution"),
        user=os.getenv("POSTGRES_USER", "attribution"),
        password=os.getenv("POSTGRES_PASSWORD", "attribution-local"),
    )

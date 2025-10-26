import httpx
from typing import Any, Dict

class BackendClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def health(self) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{self.base_url}/health")
            r.raise_for_status()
            return r.json()

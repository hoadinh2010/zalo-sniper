import base64
import logging
from typing import Optional, Tuple
import aiohttp

logger = logging.getLogger(__name__)


class OpenProjectClient:
    def __init__(self, url: str, api_key: str) -> None:
        self._base = url.rstrip("/")
        self._headers = {
            "Authorization": f"Basic {_encode_api_key(api_key)}",
            "Content-Type": "application/json",
        }

    async def create_work_package(
        self,
        project_id: str,
        title: str,
        description: str,
        status: str = "new",
    ) -> Tuple[Optional[int], Optional[str]]:
        payload = {
            "subject": title,
            "description": {"format": "markdown", "raw": description},
            "_links": {
                "project": {"href": f"/api/v3/projects/{project_id}"},
                "status": {"href": f"/api/v3/statuses/{status}"},
            },
        }
        url = f"{self._base}/api/v3/work_packages"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=self._headers) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json()
                        wp_id = data.get("id")
                        wp_url = f"{self._base}/work_packages/{wp_id}"
                        logger.info(f"Work package created: {wp_url}")
                        return wp_id, wp_url
                    else:
                        body = await resp.text()
                        logger.error(f"OpenProject error {resp.status}: {body}")
                        return None, None
        except Exception as e:
            logger.error(f"OpenProject request failed: {e}")
            return None, None


def _encode_api_key(api_key: str) -> str:
    return base64.b64encode(f"apikey:{api_key}".encode()).decode()

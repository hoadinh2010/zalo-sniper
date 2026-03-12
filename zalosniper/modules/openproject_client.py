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
    ) -> Tuple[Optional[int], Optional[str]]:
        """Create a work package using the project-scoped endpoint.

        Uses POST /api/v3/projects/{project_id}/work_packages which lets
        OpenProject resolve the project from the URL and apply the project's
        default type automatically.
        """
        payload = {
            "subject": title,
            "description": {"format": "markdown", "raw": description},
        }
        url = f"{self._base}/api/v3/projects/{project_id}/work_packages"
        logger.info(f"Creating work package: POST {url} subject={title!r}")
        try:
            async with aiohttp.ClientSession() as session:
                # First verify the project exists
                proj_url = f"{self._base}/api/v3/projects/{project_id}"
                async with session.get(proj_url, headers=self._headers) as proj_resp:
                    if proj_resp.status != 200:
                        body = await proj_resp.text()
                        logger.error(f"OpenProject project '{project_id}' not found ({proj_resp.status}): {body}")
                        return None, None

                # Get the project's default type
                types_url = f"{self._base}/api/v3/projects/{project_id}/types"
                async with session.get(types_url, headers=self._headers) as types_resp:
                    if types_resp.status == 200:
                        types_data = await types_resp.json()
                        elements = types_data.get("_embedded", {}).get("elements", [])
                        if elements:
                            type_href = elements[0].get("_links", {}).get("self", {}).get("href")
                            if type_href:
                                payload["_links"] = {"type": {"href": type_href}}
                                logger.info(f"Using type: {type_href}")

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


    async def upload_attachment(
        self,
        work_package_id: int,
        file_path: str,
    ) -> Optional[str]:
        """Upload a file attachment to a work package. Returns the attachment download URL."""
        import os
        if not os.path.exists(file_path):
            logger.warning(f"Attachment file not found: {file_path}")
            return None
        filename = os.path.basename(file_path)
        url = f"{self._base}/api/v3/work_packages/{work_package_id}/attachments"
        # OP API requires multipart: metadata (JSON) + file
        headers = {k: v for k, v in self._headers.items() if k != "Content-Type"}
        try:
            import aiohttp
            data = aiohttp.FormData()
            data.add_field(
                "metadata",
                '{"fileName": "' + filename + '"}',
                content_type="application/json",
            )
            data.add_field(
                "file",
                open(file_path, "rb"),
                filename=filename,
            )
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=data, headers=headers) as resp:
                    if resp.status in (200, 201):
                        result = await resp.json()
                        dl_url = result.get("_links", {}).get("downloadLocation", {}).get("href", "")
                        logger.info(f"Attachment uploaded to WP #{work_package_id}: {filename}")
                        return dl_url
                    else:
                        body = await resp.text()
                        logger.error(f"OP attachment upload error {resp.status}: {body}")
                        return None
        except Exception as e:
            logger.error(f"OP attachment upload failed: {e}")
            return None

    async def update_work_package(
        self,
        work_package_id: int,
        description: str,
    ) -> bool:
        """Update an existing work package's description."""
        payload = {
            "description": {"format": "markdown", "raw": description},
        }
        url = f"{self._base}/api/v3/work_packages/{work_package_id}"
        logger.info(f"Updating work package #{work_package_id}")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.patch(url, json=payload, headers=self._headers) as resp:
                    if resp.status in (200, 201):
                        logger.info(f"Work package #{work_package_id} updated")
                        return True
                    else:
                        body = await resp.text()
                        logger.error(f"OpenProject update error {resp.status}: {body}")
                        return False
        except Exception as e:
            logger.error(f"OpenProject update failed: {e}")
            return False


    async def assign_work_package(self, work_package_id: int, assignee_id: int) -> bool:
        payload = {
            "_links": {
                "assignee": {"href": f"/api/v3/users/{assignee_id}"}
            }
        }
        url = f"{self._base}/api/v3/work_packages/{work_package_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.patch(url, json=payload, headers=self._headers) as resp:
                    if resp.status in (200, 201):
                        return True
                    else:
                        body = await resp.text()
                        logger.error(f"OP assign error {resp.status}: {body}")
                        return False
        except Exception as e:
            logger.error(f"OP assign failed: {e}")
            return False


def _encode_api_key(api_key: str) -> str:
    return base64.b64encode(f"apikey:{api_key}".encode()).decode()

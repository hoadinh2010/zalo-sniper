import logging
from typing import Optional

from fastapi import APIRouter, Cookie, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

SECRET_SETTINGS = {"gemini_api_key", "zai_api_key", "ai_api_key", "github_token",
                   "telegram_bot_token", "openproject_api_key", "dashboard_password"}


def _mask(key: str, value: str) -> str:
    if key in SECRET_SETTINGS and len(value) > 4:
        return f"****{value[-4:]}"
    return value


def _require_auth(request: Request) -> Optional[str]:
    token = request.cookies.get("session")
    if not token or not request.app.state.auth.validate_session(token):
        return None
    return token


def create_api_router() -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.post("/auth/login")
    async def login(request: Request):
        body = await request.json()
        password = body.get("password", "")
        pw_hash = request.app.state.password_hash
        if not pw_hash or not request.app.state.auth.verify_password(password, pw_hash):
            return JSONResponse({"error": "Invalid password"}, status_code=401)
        token = request.app.state.auth.create_session()
        resp = JSONResponse({"token": token})
        resp.set_cookie("session", token, httponly=True, samesite="strict", max_age=86400)
        return resp

    @router.post("/auth/logout")
    async def logout(request: Request):
        token = request.cookies.get("session")
        if token:
            request.app.state.auth.invalidate_session(token)
        resp = JSONResponse({"ok": True})
        resp.delete_cookie("session")
        return resp

    @router.post("/auth/change-password")
    async def change_password(request: Request):
        if not _require_auth(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        body = await request.json()
        password = body.get("password", "")
        if len(password) < 6:
            return JSONResponse({"error": "Password too short"}, status_code=400)
        new_hash = request.app.state.auth.hash_password(password)
        request.app.state.password_hash = new_hash
        await request.app.state.db.set_setting("dashboard_password", new_hash)
        return {"ok": True}

    @router.get("/status")
    async def status(request: Request):
        if not _require_auth(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        bot_state = request.app.state.bot_state
        stats = await request.app.state.db.get_dashboard_stats()
        settings = await request.app.state.db.get_all_settings()
        return {
            "bot_running": bot_state.get("bot_running", False),
            "zalo_running": bot_state.get("zalo_running", False),
            "ai_provider": settings.get("ai_provider", "gemini"),
            **stats,
        }

    @router.get("/settings")
    async def get_settings(request: Request, reveal: int = 0):
        if not _require_auth(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        settings = await request.app.state.db.get_all_settings()
        if not reveal:
            settings = {k: _mask(k, v) for k, v in settings.items()}
        return settings

    @router.post("/settings")
    async def post_settings(request: Request):
        if not _require_auth(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        body = await request.json()
        # Never allow updating dashboard_password directly here
        body.pop("dashboard_password", None)
        await request.app.state.db.set_many_settings(body)

        # Hot-reload AI config if AI settings changed
        ai_keys = {"ai_provider", "ai_model", "ai_base_url", "gemini_api_key", "zai_api_key", "ai_api_key"}
        if ai_keys & body.keys():
            config = request.app.state.bot_state.get("config")
            if config and hasattr(config, "reload_ai_config"):
                new_ai = await config.reload_ai_config()
                # Re-initialize AI analyzer with new config
                from zalosniper.modules.ai_analyzer import AIAnalyzer
                request.app.state.bot_state["ai"] = AIAnalyzer(new_ai)
                logger.info(f"AI config reloaded: provider={new_ai.provider}, model={new_ai.model}")

        return {"ok": True}

    @router.get("/groups")
    async def get_groups(request: Request):
        if not _require_auth(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await request.app.state.db.get_all_groups()

    @router.post("/groups")
    async def create_group(request: Request):
        if not _require_auth(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        body = await request.json()
        gid = await request.app.state.db.create_group(
            body["group_name"], int(body["telegram_chat_id"])
        )
        return {"id": gid}

    @router.patch("/groups/{group_id}")
    async def update_group(group_id: int, request: Request):
        if not _require_auth(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        body = await request.json()
        ok = await request.app.state.db.update_group(group_id, **body)
        # Reload in-memory config if groups changed
        config = request.app.state.bot_state.get("config")
        if config and hasattr(config, "reload_groups"):
            await config.reload_groups()
        return {"ok": ok}

    @router.delete("/groups/{group_id}")
    async def delete_group(group_id: int, request: Request):
        if not _require_auth(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        ok = await request.app.state.db.delete_group(group_id)
        config = request.app.state.bot_state.get("config")
        if config and hasattr(config, "reload_groups"):
            await config.reload_groups()
        return {"ok": ok}

    @router.get("/groups/{group_id}/repos")
    async def get_repos(group_id: int, request: Request):
        if not _require_auth(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await request.app.state.db.get_group_repos(group_id)

    @router.post("/groups/{group_id}/repos")
    async def add_repo(group_id: int, request: Request):
        if not _require_auth(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        body = await request.json()
        rid = await request.app.state.db.add_group_repo(
            group_id, body["owner"], body["repo_name"],
            body.get("branch", "main"), body.get("description", "")
        )
        return {"id": rid}

    @router.put("/groups/{group_id}/repos/{repo_id}")
    async def update_repo(group_id: int, repo_id: int, request: Request):
        if not _require_auth(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        body = await request.json()
        ok = await request.app.state.db.update_group_repo(repo_id, **body)
        return {"ok": ok}

    @router.delete("/groups/{group_id}/repos/{repo_id}")
    async def delete_repo(group_id: int, repo_id: int, request: Request):
        if not _require_auth(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        ok = await request.app.state.db.delete_group_repo(repo_id)
        return {"ok": ok}

    @router.get("/groups/{group_id}/openproject")
    async def get_openproject(group_id: int, request: Request):
        if not _require_auth(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        op = await request.app.state.db.get_group_openproject(group_id)
        return op or {}

    @router.put("/groups/{group_id}/openproject")
    async def set_openproject(group_id: int, request: Request):
        if not _require_auth(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        body = await request.json()
        await request.app.state.db.upsert_group_openproject(
            group_id, body.get("op_url", ""),
            body.get("op_api_key", ""), body.get("op_project_id", "")
        )
        return {"ok": True}

    @router.get("/github/repos")
    async def list_github_repos(request: Request, q: str = "", test_token: str = ""):
        if not _require_auth(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        # Allow testing a token before saving it
        if test_token:
            token = test_token
        else:
            settings = await request.app.state.db.get_all_settings()
            token = settings.get("github_token", "")
        if not token:
            return JSONResponse({"error": "GitHub token not configured"}, status_code=400)
        import aiohttp
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
        repos = []
        try:
            async with aiohttp.ClientSession() as session:
                # Fetch user repos + org repos via /user/repos (includes all accessible)
                url = "https://api.github.com/user/repos?per_page=100&sort=updated&affiliation=owner,collaborator,organization_member"
                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        return JSONResponse({"error": f"GitHub API error {resp.status}: {body}"}, status_code=resp.status)
                    data = await resp.json()
                    repos = [{"full_name": r["full_name"], "owner": r["owner"]["login"],
                               "repo_name": r["name"], "default_branch": r["default_branch"]}
                              for r in data]
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)
        if q:
            q_lower = q.lower()
            repos = [r for r in repos if q_lower in r["full_name"].lower()]
        return repos

    @router.delete("/analyses/{analysis_id}")
    async def delete_analysis(analysis_id: int, request: Request):
        if not _require_auth(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        ok = await request.app.state.db.delete_bug_analysis(analysis_id)
        if not ok:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return {"ok": True}

    @router.post("/analyses/{analysis_id}/status")
    async def update_analysis_status(analysis_id: int, request: Request):
        if not _require_auth(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        body = await request.json()
        new_status = body.get("status", "")
        from zalosniper.models.bug_analysis import BugStatus
        try:
            status = BugStatus(new_status)
        except ValueError:
            return JSONResponse({"error": f"Invalid status: {new_status}"}, status_code=400)
        ok = await request.app.state.db.update_bug_analysis_status(analysis_id, status)
        if not ok:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return {"ok": True}

    @router.post("/analyses/{analysis_id}/create-op-task")
    async def create_op_task(analysis_id: int, request: Request):
        """Create an OpenProject task for a bug analysis from the dashboard."""
        if not _require_auth(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        db = request.app.state.db
        from zalosniper.models.bug_analysis import BugAnalysis, BugStatus
        analysis = await db.get_bug_analysis(analysis_id)
        if not analysis:
            return JSONResponse({"error": "Not found"}, status_code=404)
        if analysis.op_work_package_url:
            return JSONResponse({"error": "Task OP da ton tai", "op_url": analysis.op_work_package_url}, status_code=409)
        # Find group's OP config
        groups = await db.get_all_groups()
        group = next((g for g in groups if g["group_name"] == analysis.group_name), None)
        if not group:
            return JSONResponse({"error": "Group not found"}, status_code=404)
        op_config = await db.get_group_openproject(group["id"])
        if not op_config or not op_config.get("op_url") or not op_config.get("op_project_id"):
            return JSONResponse({"error": "OpenProject chua duoc cau hinh cho group nay"}, status_code=400)
        from zalosniper.modules.openproject_client import OpenProjectClient
        client = OpenProjectClient(url=op_config["op_url"], api_key=op_config["op_api_key"])
        summary = analysis.claude_summary or f"Bug #{analysis_id}"
        # Build rich description with original messages
        desc_parts = [f"**Tóm tắt:** {summary}"]
        if analysis.message_ids:
            msgs = await db.get_recent_messages(analysis.group_name, limit=50, within_hours=24)
            msg_map = {m.id: m for m in msgs}
            relevant = [msg_map[mid] for mid in analysis.message_ids if mid in msg_map]
            if relevant:
                desc_parts.append("\n**Tin nhắn gốc từ Zalo:**")
                for m in relevant:
                    desc_parts.append(f"- **{m.sender}** ({m.timestamp.strftime('%H:%M')}): {m.content}")
        try:
            op_id, op_url = await client.create_work_package(
                project_id=op_config["op_project_id"],
                title=f"Bug: {summary}",
                description="\n".join(desc_parts),
            )
        except Exception as e:
            return JSONResponse({"error": f"OpenProject error: {e}"}, status_code=500)
        if not op_id:
            return JSONResponse({"error": "Khong tao duoc task tren OpenProject"}, status_code=500)
        # Upload images from linked messages
        if relevant:
            for m in relevant:
                if hasattr(m, 'image_path') and m.image_path:
                    try:
                        await client.upload_attachment(op_id, m.image_path)
                    except Exception:
                        pass
        await db.update_bug_analysis_status(
            analysis_id, BugStatus(analysis.status.value),
            op_work_package_id=op_id, op_work_package_url=op_url,
        )
        return {"ok": True, "op_id": op_id, "op_url": op_url}

    @router.get("/analyses/{analysis_id}/op-info")
    async def get_op_info(analysis_id: int, request: Request):
        """Fetch OpenProject work package info for a bug analysis."""
        if not _require_auth(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        db = request.app.state.db
        analysis = await db.get_bug_analysis(analysis_id)
        if not analysis or not analysis.op_work_package_id:
            return JSONResponse({"error": "No OP task"}, status_code=404)
        groups = await db.get_all_groups()
        group = next((g for g in groups if g["group_name"] == analysis.group_name), None)
        if not group:
            return JSONResponse({"error": "Group not found"}, status_code=404)
        op_config = await db.get_group_openproject(group["id"])
        if not op_config or not op_config.get("op_url"):
            return JSONResponse({"error": "OP not configured"}, status_code=400)
        import aiohttp
        import base64
        auth = base64.b64encode(f"apikey:{op_config['op_api_key']}".encode()).decode()
        headers = {"Authorization": f"Basic {auth}", "Content-Type": "application/json"}
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{op_config['op_url'].rstrip('/')}/api/v3/work_packages/{analysis.op_work_package_id}"
                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        return JSONResponse({"error": f"OP API {resp.status}"}, status_code=resp.status)
                    data = await resp.json()
                    return {
                        "id": data.get("id"),
                        "subject": data.get("subject"),
                        "status": data.get("_links", {}).get("status", {}).get("title", ""),
                        "type": data.get("_links", {}).get("type", {}).get("title", ""),
                        "assignee": data.get("_links", {}).get("assignee", {}).get("title", ""),
                        "priority": data.get("_links", {}).get("priority", {}).get("title", ""),
                        "created_at": data.get("createdAt", ""),
                        "updated_at": data.get("updatedAt", ""),
                        "url": analysis.op_work_package_url,
                    }
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @router.get("/chat")
    async def list_chat_groups(request: Request):
        if not _require_auth(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        groups = await request.app.state.db.get_all_groups()
        return groups

    @router.get("/chat/{group_name}")
    async def get_chat_messages(group_name: str, request: Request, days: int = 7, limit: int = 500):
        if not _require_auth(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        messages = await request.app.state.db.get_all_messages(group_name, days=days, limit=limit)
        return [
            {
                "id": m.id,
                "sender": m.sender,
                "content": m.content,
                "timestamp": m.timestamp.strftime("%Y-%m-%d %H:%M:%S") if m.timestamp else None,
                "created_at": m.created_at.strftime("%Y-%m-%d %H:%M:%S") if m.created_at else None,
                "processed": m.processed,
                "image_path": m.image_path,
            }
            for m in reversed(messages)  # oldest first for chat display
        ]

    @router.get("/logs")
    async def get_logs(request: Request, level: str = None, n: int = 100):
        if not _require_auth(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        from zalosniper.web.log_handler import ring_handler
        return ring_handler.get_lines(level=level)[-n:]

    return router

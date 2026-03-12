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
                "processed": m.processed,
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

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse


def create_pages_router() -> APIRouter:
    router = APIRouter()

    def _authed(request: Request) -> bool:
        token = request.cookies.get("session")
        return bool(token and request.app.state.auth.validate_session(token))

    @router.get("/", response_class=HTMLResponse)
    async def root(request: Request):
        if _authed(request):
            return RedirectResponse("/dashboard")
        return request.app.state.templates.TemplateResponse("login.html", {"request": request})

    @router.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(request: Request):
        if not _authed(request):
            return RedirectResponse("/")
        return request.app.state.templates.TemplateResponse("dashboard.html", {"request": request, "page": "dashboard"})

    @router.get("/keys", response_class=HTMLResponse)
    async def keys(request: Request):
        if not _authed(request):
            return RedirectResponse("/")
        return request.app.state.templates.TemplateResponse("keys.html", {"request": request, "page": "keys"})

    @router.get("/groups", response_class=HTMLResponse)
    async def groups(request: Request):
        if not _authed(request):
            return RedirectResponse("/")
        return request.app.state.templates.TemplateResponse("groups.html", {"request": request, "page": "groups"})

    @router.get("/mapping", response_class=HTMLResponse)
    async def mapping(request: Request):
        if not _authed(request):
            return RedirectResponse("/")
        return request.app.state.templates.TemplateResponse("mapping.html", {"request": request, "page": "mapping"})

    @router.get("/logs", response_class=HTMLResponse)
    async def logs(request: Request):
        if not _authed(request):
            return RedirectResponse("/")
        return request.app.state.templates.TemplateResponse("logs.html", {"request": request, "page": "logs"})

    return router

"""Request limits and same-origin CSRF protection."""
from contextvars import ContextVar
import hmac
import re
import secrets
from urllib.parse import urlsplit
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

csrf_token_context = ContextVar("safeorbit_csrf", default="")


def protect_forms(page):
    token = csrf_token_context.get()
    if not token or "</head>" not in page:
        return page
    page = page.replace("</head>", f'<meta name="csrf-token" content="{token}"><script src="/static/v2/csrf.js?v=release1"></script></head>', 1)
    def insert(match):
        tag = match.group()
        if re.search(r'\bmethod\s*=\s*["\']?post\b', tag, re.I):
            return tag + f'<input type="hidden" name="csrf_token" value="{token}">'
        return tag
    return re.sub(r"<form\b[^>]*>", insert, page, flags=re.I)


class RequestSecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        token = request.cookies.get("so_csrf", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            token = secrets.token_urlsafe(32)
        context = csrf_token_context.set(token)
        try:
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                limit = 16 * 1024 * 1024 if request.headers.get("content-type", "").startswith("multipart/form-data") else 1024 * 1024
                try:
                    length = int(request.headers.get("content-length", "0"))
                except ValueError:
                    return JSONResponse({"detail": "Invalid content length"}, status_code=400)
                if length < 0 or length > limit:
                    return JSONResponse({"detail": "Request too large"}, status_code=413)
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > limit:
                        return JSONResponse({"detail": "Request too large"}, status_code=413)
                request._body = bytes(body)
                if (request.cookies.get("session") or request.url.path in {"/login", "/register"}
                        or request.url.path.startswith(("/maistry/", "/proposals/", "/maket/", "/login/", "/register/"))):
                    origin = request.headers.get("origin")
                    if origin:
                        parsed = urlsplit(origin)
                        if parsed.netloc.lower() != request.url.netloc.lower() or parsed.scheme != request.url.scheme:
                            return JSONResponse({"detail": "Cross-origin request rejected"}, status_code=403)
                    provided = request.headers.get("x-csrf-token", "")
                    if not provided and request.headers.get("content-type", "").startswith(("application/x-www-form-urlencoded", "multipart/form-data")):
                        provided = str((await request.form()).get("csrf_token", ""))
                    cookie = request.cookies.get("so_csrf", "")
                    if not cookie or not provided or not hmac.compare_digest(cookie, provided):
                        return JSONResponse({"detail": "CSRF verification failed. Reload the page."}, status_code=403)
            response = await call_next(request)
            if response.headers.get("content-type", "").startswith("text/html"):
                response.set_cookie("so_csrf", token, secure=request.url.scheme == "https",
                                    httponly=False, samesite="strict", path="/")
            return response
        finally:
            csrf_token_context.reset(context)

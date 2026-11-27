from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from config import DATABASE_URL, asyncpg_connect_args, is_sqlite_db

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args=asyncpg_connect_args(DATABASE_URL),
    pool_pre_ping=not is_sqlite_db(),
)

AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)


async def get_db(request: Request):
    """
    Dependency function that yields an async session.
    """
    # Import lazily so offline callers can keep using the standard database.
    from services.demo_workspace import DEMO_SESSION_KEY, READ_ROUTES, WRITE_ROUTES, demo_workspaces
    from services.marketing_funnel import LANDINGS

    demo_key = request.scope.get("session", {}).get(DEMO_SESSION_KEY)
    public_route = request.url.path in LANDINGS or (request.method == "POST" and request.url.path == "/login")
    public_route = public_route or request.url.path.startswith(("/proposals/", "/maistry/", "/signals/", "/books/", "/maket/", "/login/", "/register/")) or request.url.path == "/maistry"
    if demo_key and not public_route:
        routes = READ_ROUTES if request.method == "GET" else WRITE_ROUTES if request.method == "POST" else ()
        route = getattr(request.scope.get("route"), "path", request.url.path)
        if route not in routes:
            raise HTTPException(403, "Ця дія доступна у власному робочому просторі.")
        request.state.demo_workspace = True
        async with demo_workspaces.database(demo_key, touch=route not in {"/admin/api/unread-updates", "/api/check-notifications"}) as session:
            yield session
        return

    async with AsyncSessionLocal() as session:
        yield session

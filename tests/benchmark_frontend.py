"""Reproducible in-process benchmark with in-memory DB and synthetic credentials."""
import os
os.environ["DATABASE_URL"]="sqlite+aiosqlite:///:memory:"
os.environ["SECRET_KEY"]="benchmark-local-secret"
os.environ["GROQ_API_KEY"]="benchmark-not-a-real-key"
os.environ["ENVIRONMENT"]="test"

import asyncio
import gzip
import json
import statistics
import time
from pathlib import Path
from types import SimpleNamespace
import httpx
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.gzip import GZipMiddleware
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from models import Base,GlobalPaymentSettings
from database import get_db
from routers.auth import router
from utils.static import CachedStaticFiles
from utils.templates import login_html
from ui import get_layout

ROOT=Path(__file__).resolve().parents[1]

async def main():
    engine=create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions=async_sessionmaker(engine,expire_on_commit=False)
    async with engine.begin() as connection: await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        db.add(GlobalPaymentSettings(id=1));await db.commit()
    app=FastAPI()
    app.add_middleware(SessionMiddleware,secret_key="benchmark-local-secret")
    app.add_middleware(GZipMiddleware,minimum_size=1024,compresslevel=4)
    app.include_router(router)
    app.mount("/static",CachedStaticFiles(directory=str(ROOT/"static")))
    async def isolated_db():
        async with sessions() as db: yield db
    app.dependency_overrides[get_db]=isolated_db
    result={"method":"100 warm sequential in-process HTTP requests; in-memory SQLite; not internet latency"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
        for path in ("/login","/register","/static/saas/auth.css"):
            response=await client.get(path);assert response.status_code==200
            timings=[]
            for _ in range(100):
                start=time.perf_counter();response=await client.get(path);timings.append((time.perf_counter()-start)*1000)
            result[path]={"html_or_asset_bytes":len(response.content),"gzip_bytes":len(gzip.compress(response.content,compresslevel=4)),
                "p50_ms":round(statistics.median(timings),3),"p95_ms":round(sorted(timings)[94],3)}
    baseline=json.loads((ROOT/"tests"/"baseline_metrics.json").read_text())
    user=SimpleNamespace(role="owner",username="preview",business=SimpleNamespace(type="barbershop",lang="ua",name="Test"))
    page=get_layout("Sample",user,"dash","<script>window.pageScript=true</script>")
    result["workspace_shell"]={"before_html_bytes":baseline["layout_bytes"],"after_html_bytes":len(page.encode()),
        "reduction_percent":round(100*(1-len(page.encode())/baseline["layout_bytes"]),1),
        "script_occurrences":page.count("window.pageScript=true")}
    result["auth_js_bytes"]=(ROOT/"static"/"saas"/"auth.js").stat().st_size
    output=ROOT/"qa";output.mkdir(exist_ok=True)
    (output/"performance.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))
    await engine.dispose()

if __name__=="__main__": asyncio.run(main())

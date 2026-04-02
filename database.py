from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from config import DATABASE_URL, asyncpg_connect_args, is_sqlite_db

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args=asyncpg_connect_args(DATABASE_URL),
    pool_pre_ping=not is_sqlite_db(),
)

AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)


async def get_db():
    """
    Dependency function that yields an async session.
    """
    async with AsyncSessionLocal() as session:
        yield session
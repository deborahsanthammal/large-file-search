import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.file import File
from app.models.job import ProcessingJob


async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ProcessingJob).limit(1)
        )

        job = result.scalar_one_or_none()

        if job is None:
            print("No processing job found")
            return

        job.status = "PROCESSING"
        job.started_at = (
            datetime.now(timezone.utc)
            - timedelta(minutes=20)
        )

        await db.commit()

        print(f"Made job stale: {job.id}")


if __name__ == "__main__":
    asyncio.run(main())

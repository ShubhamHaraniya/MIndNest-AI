"""Small counts for the dashboard."""

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from mindnest_api.deps import AuthUser, UserDbDep

router = APIRouter(tags=["stats"])


class StatsOut(BaseModel):
    subjects: int
    materials: int
    materials_ready: int


@router.get("/stats", response_model=StatsOut)
async def get_stats(_user: AuthUser, db: UserDbDep) -> StatsOut:
    async with db.session() as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                        SELECT
                          (SELECT count(*) FROM subjects WHERE archived_at IS NULL) AS subjects,
                          (SELECT count(*) FROM materials WHERE deleted_at IS NULL) AS materials,
                          (SELECT count(*) FROM materials
                             WHERE deleted_at IS NULL AND status = 'ready') AS materials_ready
                        """
                    )
                )
            )
            .mappings()
            .one()
        )
    return StatsOut(**row)

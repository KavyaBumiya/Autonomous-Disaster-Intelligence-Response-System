"""Action approval endpoint — commander-only."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.core.database import get_db
from app.models.action import Action
from app.services.websocket import emit_action_state_changed

router = APIRouter()


class ActionUpdateRequest(BaseModel):
    status: str  # "approved" | "rejected"
    note: str | None = None


@router.patch("/{action_id}")
async def update_action(
    action_id: str,
    body: ActionUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_role(["commander"])),
):
    """Commander approves or rejects a pending action."""
    result = await db.execute(select(Action).where(Action.id == action_id))
    action = result.scalar_one_or_none()
    if not action:
        raise HTTPException(404, detail="Action not found")

    if action.status != "pending_approval":
        raise HTTPException(400, detail=f"Action is not pending (current status: {action.status})")

    if body.status not in ("approved", "rejected"):
        raise HTTPException(400, detail="Status must be 'approved' or 'rejected'")

    action.status = body.status
    action.approved_by = user["user_id"]
    action.updated_at = datetime.now(timezone.utc)
    await db.commit()

    # Emit WebSocket event
    await emit_action_state_changed(
        action.id,
        action.zone_id,
        body.status,
        user["role"],
    )

    return {
        "action_id": action.id,
        "status": action.status,
        "approved_by": user["user_id"],
        "message": f"Action {body.status} successfully",
    }

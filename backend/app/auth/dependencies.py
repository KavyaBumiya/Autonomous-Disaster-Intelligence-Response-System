"""FastAPI dependencies for role-based access control."""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.auth.jwt import decode_token

bearer_scheme = HTTPBearer(auto_error=False)


def _get_token_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return payload


def get_current_user(payload: dict = Depends(_get_token_payload)) -> dict:
    return {"user_id": payload["sub"], "role": payload["role"]}


def require_role(allowed_roles: list[str]):
    def _checker(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user['role']}' is not permitted for this action.",
            )
        return user
    return _checker

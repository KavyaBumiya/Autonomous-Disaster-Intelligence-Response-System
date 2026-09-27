"""FastAPI auth dependencies — public demo mode.

Sign-in was removed for the public demo (2026-09): every guarded route runs
as a fixed operator identity instead of rejecting anonymous requests with
401/403. The /api/auth/login and /api/auth/me endpoints remain part of the
frozen §41 API contract (login still issues real JWTs for API clients), but
no route requires a bearer token anymore — an Authorization header, valid or
not, is ignored.
"""
from fastapi import Depends

# Fixed demo identity: "commander" passes every historical require_role list.
DEMO_USER: dict[str, str] = {"user_id": "demo-operator", "role": "commander"}


def get_current_user() -> dict:
    """Public demo: every caller is the demo operator (never 401)."""
    return dict(DEMO_USER)


def require_role(allowed_roles: list[str]):
    """Role gate retained for route signatures — open in public demo mode."""
    del allowed_roles  # roles are not enforced without sign-in

    def _checker(user: dict = Depends(get_current_user)) -> dict:
        return user

    return _checker

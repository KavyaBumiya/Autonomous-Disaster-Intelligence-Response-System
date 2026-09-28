"""FastAPI request-identity dependencies.

This deployment runs unauthenticated: there is no sign-in, no session and no
token, so every guarded route accepts anonymous callers instead of returning
401/403. The two dependencies below are kept because the frozen §41 API
contract has every route signature carrying them, and because several routes
record *who* approved or rejected an action.

Because there is no authenticated principal, the identity handed to those
routes is a fixed ``operator`` label. It records that an action was approved
through this deployment's console. It is **not** an account, it grants no
permissions, and it must not be presented to operators as an authenticated
user. Add real authentication before treating ``approved_by`` as an audit
trail: today it records a constant, not a person.
"""
from fastapi import Depends

# Fixed label recorded on approval/audit fields. Not an account.
OPERATOR: dict[str, str] = {"user_id": "operator", "role": "commander"}


def get_current_user() -> dict:
    """Return the fixed operator label for this unauthenticated deployment."""
    return dict(OPERATOR)


def require_role(allowed_roles: list[str]):
    """Role gate retained for route signatures — open, as there is no sign-in.

    `allowed_roles` is not enforced. It is accepted and discarded so the frozen
    contract's decorator shape does not have to change.
    """
    del allowed_roles  # roles are not enforced without sign-in

    def _checker(user: dict = Depends(get_current_user)) -> dict:
        return user

    return _checker

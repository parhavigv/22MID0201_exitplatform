"""
Request dependencies.

This module is the hinge the whole security model turns on. Every request
arrives with a Supabase JWT; this file turns it into an ActorContext carrying a
Supabase client **bound to that user's token**, so PostgREST applies RLS to
every query made through it.

The rule (CLAUDE.md rule 1): handlers and agent tools use `actor.db`. The
service-role client is reachable only through `service_db()`, which exists for
the executor, the sweep job, and audit writes — code paths that act as the
system, not on behalf of a user.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from typing import Annotated, Any, Literal

import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt import PyJWKClient
from supabase import Client, create_client

from app.config import Settings, get_settings

AppRole = Literal["employee", "manager", "hr", "it", "finance"]
"""Mirrors the `app_role` enum. `it` and `finance` were added in migration
0010 — their tasks existed on every case long before they could sign in."""

CLEARANCE_ROLES: frozenset[str] = frozenset({"it", "finance"})
"""Roles that own a clearance stage rather than a person. They see the cases
they have work on and may act only on their own tasks and their own stage —
see migration 0011 for the policies that enforce it."""


@dataclass(frozen=True)
class ActorContext:
    """Who is making this request, and a database handle scoped to them."""

    employee_id: str
    auth_user_id: str
    role: AppRole
    full_name: str
    email: str
    db: Client
    """RLS-bound. Reads and writes only what this person is allowed to touch."""

    @property
    def is_hr(self) -> bool:
        return self.role == "hr"


# ---------------------------------------------------------------------------
# JWT verification
# ---------------------------------------------------------------------------


@lru_cache
def _jwk_client(supabase_url: str) -> PyJWKClient:
    # Cached: the client keeps its own key cache and refreshes on rotation.
    return PyJWKClient(f"{supabase_url}/auth/v1/.well-known/jwks.json")


# Supabase issues tokens by its own clock, which is not this machine's. A token
# whose `iat` is a second or two in the future is not an attack, it is ordinary
# skew — but PyJWT rejects it outright, and `deps` then reports "Not signed in"
# for a perfectly good login.
#
# That was the real cause of sign-in needing several attempts: each click burnt
# a second or so until local time caught up with the timestamp, and one of them
# eventually landed. Thirty seconds is the usual allowance; it applies to `exp`
# as well, which is harmless against a one-hour token.
CLOCK_SKEW_LEEWAY = timedelta(seconds=30)


def _decode_token(token: str, settings: Settings) -> dict[str, Any]:
    """Verify the Supabase access token and return its claims.

    Supports both signing schemes: the legacy shared HS256 secret, and the
    asymmetric keys that current Supabase projects default to.
    """
    options = {"verify_aud": False}

    try:
        if settings.supabase_jwt_secret:
            return jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                options=options,
                leeway=CLOCK_SKEW_LEEWAY,
            )

        signing_key = _jwk_client(settings.supabase_url).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            options=options,
            leeway=CLOCK_SKEW_LEEWAY,
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Your session has expired. Sign in again."
        )
    except jwt.PyJWTError:
        # Deliberately vague: do not tell a caller why their token failed.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in.")


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------


def _user_client(token: str, settings: Settings) -> Client:
    """A Supabase client that acts AS the signed-in user.

    Built per request. The anon key selects the project; the user's token is
    what PostgREST reads to evaluate RLS policies.
    """
    client = create_client(settings.supabase_url, settings.supabase_anon_key)
    client.postgrest.auth(token)
    return client


@lru_cache
def service_db() -> Client:
    """RLS-bypassing client. Not a request dependency on purpose.

    Import it explicitly in the executor, the sweep job, and audit writes so
    every bypass is greppable. Never pass it to an agent tool.
    """
    settings = get_settings()
    if not settings.supabase_service_key:
        raise RuntimeError("SUPABASE_SERVICE_KEY is not set")
    return create_client(settings.supabase_url, settings.supabase_service_key)


# ---------------------------------------------------------------------------
# The dependency
# ---------------------------------------------------------------------------


async def current_actor(
    authorization: Annotated[str | None, Header()] = None,
    settings: Annotated[Settings, Depends(get_settings)] = None,  # type: ignore[assignment]
) -> ActorContext:
    if not settings.configured:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The server has no database configured yet.",
        )

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in.")

    token = authorization.split(" ", 1)[1].strip()
    claims = _decode_token(token, settings)

    auth_user_id = claims.get("sub")
    if not auth_user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in.")

    db = _user_client(token, settings)

    # Read the employee row through the RLS-bound client. The `employees_select`
    # policy always lets someone read their own row, so this doubles as a check
    # that the account is provisioned and active.
    result = (
        db.table("employees")
        .select("id, full_name, work_email, app_role")
        .eq("auth_user_id", auth_user_id)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This account is not linked to an employee record. Contact HR.",
        )

    row = result.data[0]
    return ActorContext(
        employee_id=row["id"],
        auth_user_id=auth_user_id,
        role=row["app_role"],
        full_name=row["full_name"],
        email=row["work_email"],
        db=db,
    )


Actor = Annotated[ActorContext, Depends(current_actor)]


def require_roles(*roles: AppRole):
    """Route guard. Defence in depth only — RLS is what actually protects data.

    A handler without this still returns nothing to an unauthorised caller,
    because their RLS-bound client sees no rows.
    """

    async def guard(actor: Actor) -> ActorContext:
        if actor.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not available for your role.")
        return actor

    return guard

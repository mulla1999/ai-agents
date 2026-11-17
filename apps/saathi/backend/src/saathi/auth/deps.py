"""FastAPI dependencies: database session, current user, role checks."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import Role, User
from .sessions import SESSION_COOKIE, user_for_token


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


DB = Annotated[AsyncSession, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings_dep)]


async def optional_user(request: Request, db: DB) -> User | None:
    return await user_for_token(db, request.cookies.get(SESSION_COOKIE))


async def current_user(user: Annotated[User | None, Depends(optional_user)]) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="sign in required")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
OptionalUser = Annotated[User | None, Depends(optional_user)]


def require_role(*roles: Role) -> Callable[[User], Coroutine[Any, Any, User]]:
    async def dependency(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="not allowed for your role")
        return user

    return dependency


StaffUser = Annotated[User, Depends(require_role(Role.HELPER, Role.ADMIN))]
AdminUser = Annotated[User, Depends(require_role(Role.ADMIN))]

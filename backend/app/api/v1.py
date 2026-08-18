from fastapi import APIRouter

from app.modules.accounts.router import router as accounts_router
from app.modules.transactions.router import router as transactions_router
from app.modules.transfers.router import router as transfers_router
from app.modules.users.router import router as users_router

api_router = APIRouter()

api_router.include_router(accounts_router, prefix="/accounts", tags=["accounts"])
api_router.include_router(transactions_router, prefix="/accounts", tags=["transactions"])
api_router.include_router(transfers_router, prefix="/transfers", tags=["transfers"])
api_router.include_router(users_router, prefix="/users", tags=["users"])

# Not yet mounted: the auth teammate adds modules/auth/router.py (login,
# logout, register) and then, here, adds:
#   from app.modules.auth.router import router as auth_router
#   api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
# See docs/AUTH_HANDOFF.md for the full contract.

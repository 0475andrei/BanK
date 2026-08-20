from fastapi import APIRouter

from app.modules.accounts.router import router as accounts_router
from app.modules.auth.router import router as auth_router
from app.modules.beneficiaries.router import router as beneficiaries_router
from app.modules.card_orders.router import router as card_orders_router
from app.modules.cards.router import router as cards_router
from app.modules.chat.router import router as chat_router
from app.modules.id_ocr.router import router as id_ocr_router
from app.modules.payments.router import router as payments_router
from app.modules.transactions.router import router as transactions_router
from app.modules.transfers.router import router as transfers_router
from app.modules.users.router import router as users_router

api_router = APIRouter()

api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(accounts_router, prefix="/accounts", tags=["accounts"])
api_router.include_router(transactions_router, prefix="/accounts", tags=["transactions"])
api_router.include_router(transfers_router, prefix="/transfers", tags=["transfers"])
api_router.include_router(cards_router, prefix="/cards", tags=["cards"])
api_router.include_router(card_orders_router, prefix="/card-orders", tags=["card-orders"])
api_router.include_router(payments_router, prefix="/payments", tags=["payments"])
api_router.include_router(beneficiaries_router, prefix="/beneficiaries", tags=["beneficiaries"])
api_router.include_router(users_router, prefix="/users", tags=["users"])
api_router.include_router(chat_router, prefix="/chat", tags=["chat"])
api_router.include_router(id_ocr_router, prefix="/id-ocr", tags=["id-ocr"])

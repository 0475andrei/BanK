import uuid

from postgrest.exceptions import APIError
from supabase import AsyncClient

from app.core.audit import record_audit_event
from app.core.exceptions import AccountNotEmptyError, AccountNotFoundError, ValidationError
from app.modules.accounts.iban import generate_iban
from app.modules.accounts.models import AccountStatus
from app.modules.ledger import service as ledger_service
from app.modules.users.schemas import UserRead

UNIQUE_VIOLATION = "23505"
_IBAN_GENERATION_ATTEMPTS = 5

# Every new account starts funded - there's no deposit/funding endpoint
# anywhere else in this app (see design_decisions), so this is a deliberate
# "welcome balance" rather than a real bank giving out free money.
OPENING_BALANCE_MINOR = 50_000


def _validate_currency(currency: str) -> str:
    currency = currency.upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ValidationError(f"Currency must be a 3-letter code, got: {currency!r}")
    return currency


async def _insert_account_with_iban(supabase: AsyncClient, user: UserRead, name: str, currency: str) -> dict:
    """A generated IBAN is practically always unique (36^16 possibilities),
    but "practically" isn't a guarantee - retry a few times on a genuine
    collision rather than letting it surface as a confusing 500."""
    last_error: APIError | None = None
    for _ in range(_IBAN_GENERATION_ATTEMPTS):
        try:
            resp = (
                await supabase.table("accounts")
                .insert(
                    {
                        "user_id": str(user.id),
                        "name": name,
                        "currency": currency,
                        "status": AccountStatus.ACTIVE.value,
                        "iban": generate_iban(),
                    }
                )
                .execute()
            )
            return resp.data[0]
        except APIError as exc:
            if exc.code != UNIQUE_VIOLATION or "iban" not in f"{exc.message} {exc.details or ''}".lower():
                raise
            last_error = exc
    raise last_error  # pragma: no cover - astronomically unlikely


async def open_account(supabase: AsyncClient, user: UserRead, name: str, currency: str) -> dict:
    currency = _validate_currency(currency)

    account = await _insert_account_with_iban(supabase, user, name, currency)

    await record_audit_event(
        supabase,
        user_id=user.id,
        action="accounts.open",
        entity=f"accounts:{account['id']}",
        metadata={"name": name, "currency": currency, "iban": account["iban"]},
    )

    await ledger_service.grant_opening_balance(
        supabase,
        uuid.UUID(account["id"]),
        OPENING_BALANCE_MINOR,
        currency,
        idempotency_key=f"opening-balance:{account['id']}",
        actor_user_id=user.id,
    )
    return account


async def _get_owned_account(supabase: AsyncClient, user: UserRead, account_id: uuid.UUID) -> dict:
    resp = (
        await supabase.table("accounts")
        .select("*")
        .eq("id", str(account_id))
        .eq("user_id", str(user.id))
        .maybe_single()
        .execute()
    )
    account = resp.data if resp is not None else None
    if account is None:
        # Same error whether the account doesn't exist or just isn't the
        # caller's - don't leak which one it is.
        raise AccountNotFoundError()
    return account


async def get_account(supabase: AsyncClient, user: UserRead, account_id: uuid.UUID) -> dict:
    return await _get_owned_account(supabase, user, account_id)


async def list_accounts(supabase: AsyncClient, user: UserRead) -> list[dict]:
    resp = (
        await supabase.table("accounts")
        .select("*")
        .eq("user_id", str(user.id))
        .order("created_at")
        .execute()
    )
    return resp.data


async def get_account_balance(supabase: AsyncClient, user: UserRead, account_id: uuid.UUID) -> int:
    """Ownership-checked balance read. AI read tools (get_balance) and any
    other module should call this rather than reaching into ledger.service
    directly, so ownership is always enforced."""
    account = await _get_owned_account(supabase, user, account_id)
    return await ledger_service.get_balance(supabase, uuid.UUID(account["id"]))


async def close_account(supabase: AsyncClient, user: UserRead, account_id: uuid.UUID) -> dict:
    account = await _get_owned_account(supabase, user, account_id)
    if account["status"] == AccountStatus.CLOSED.value:
        return account

    balance = await ledger_service.get_balance(supabase, uuid.UUID(account["id"]))
    if balance != 0:
        raise AccountNotEmptyError()

    resp = (
        await supabase.table("accounts")
        .update({"status": AccountStatus.CLOSED.value})
        .eq("id", str(account_id))
        .execute()
    )

    await record_audit_event(
        supabase, user_id=user.id, action="accounts.close", entity=f"accounts:{account_id}"
    )
    return resp.data[0]

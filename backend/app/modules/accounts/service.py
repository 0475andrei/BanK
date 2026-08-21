import uuid
from datetime import UTC, datetime

from postgrest.exceptions import APIError
from supabase import AsyncClient

from app.core.audit import record_audit_event
from app.core.exceptions import (
    AccountNotEmptyError,
    AccountNotFoundError,
    IbanNotFoundError,
    ValidationError,
)
from app.modules.accounts.iban import generate_iban
from app.modules.accounts.models import AccountStatus
from app.modules.ledger import service as ledger_service
from app.modules.notifications import service as notifications_service
from app.modules.users.schemas import UserRead

UNIQUE_VIOLATION = "23505"
_IBAN_GENERATION_ATTEMPTS = 5

# Only users who registered with the referral code get a welcome balance
# on every account they open (see auth/service.py::FALLBACK_REFERRAL_CODE) -
# there's no deposit/funding endpoint anywhere else in this app (see
# design_decisions), so this is a deliberate "welcome balance" rather than
# a real bank giving out free money, and it's gated so it isn't unlimited.
OPENING_BALANCE_MINOR = 50_000

# The referrer's side of the same deal (see 0009_referral_rewards.sql): paid
# out in RON specifically, so it can only land on a RON account - if the
# referrer doesn't have one yet when the referred user opens theirs, the
# reward sits `pending` until the referrer opens their own first RON account
# (handled at the bottom of open_account below).
REFERRAL_REWARD_MINOR = 30_000
REFERRAL_REWARD_CURRENCY = "RON"


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


async def _get_first_active_account(supabase: AsyncClient, user_id: str, currency: str) -> dict | None:
    resp = (
        await supabase.table("accounts")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", AccountStatus.ACTIVE.value)
        .eq("currency", currency)
        .order("created_at")
        .limit(1)
        .maybe_single()
        .execute()
    )
    return resp.data if resp is not None else None


async def _pay_referral_reward(supabase: AsyncClient, reward: dict, payout_account: dict) -> None:
    """Grants the reward onto payout_account (a RON account belonging to the
    referrer - either the one the referred user's opening just unlocked an
    immediate payout for, or one the referrer opens later, see the pending
    sweep at the end of open_account) and raises an in-app notification for
    them (see modules/notifications - the bell icon in the header). Unlike
    the password-reset OTP, this happens to an already-logged-in user, so it
    belongs in-app rather than on Teams. grant_opening_balance is idempotent
    on idempotency_key, so this is safe to call again for a reward that's
    already `paid` - it'll just replay the existing journal entry rather
    than double-crediting."""
    await ledger_service.grant_opening_balance(
        supabase,
        uuid.UUID(payout_account["id"]),
        reward["amount_minor"],
        reward["currency"],
        idempotency_key=f"referral-reward:{reward['referred_account_id']}",
        actor_user_id=uuid.UUID(reward["referrer_user_id"]),
    )
    await (
        supabase.table("referral_rewards")
        .update(
            {
                "status": "paid",
                "paid_account_id": payout_account["id"],
                "paid_at": datetime.now(UTC).isoformat(),
            }
        )
        .eq("id", reward["id"])
        .execute()
    )
    amount_major = reward["amount_minor"] / 100
    await notifications_service.create_notification(
        supabase,
        reward["referrer_user_id"],
        title="Bonus de recomandare",
        body=(
            f"Ai primit {amount_major:.2f} {reward['currency']} pentru că cineva "
            f"s-a înregistrat cu codul tău de referral, în contul \"{payout_account['name']}\"."
        ),
    )


async def _record_and_pay_referrer_reward(supabase: AsyncClient, user: UserRead, account: dict) -> None:
    """The other half of `user.referral_bonus_eligible` above: if `user` was
    referred by someone's per-user code (not the fallback), that person is
    owed a reward now that `user` has an account. Records it unconditionally
    (UNIQUE(referred_account_id) makes this a no-op on retry) and pays it
    immediately if the referrer already has a RON account to receive it on -
    otherwise it stays `pending`, see the sweep below."""
    if user.referred_by_user_id is None:
        return

    try:
        resp = (
            await supabase.table("referral_rewards")
            .insert(
                {
                    "referrer_user_id": str(user.referred_by_user_id),
                    "referred_user_id": str(user.id),
                    "referred_account_id": account["id"],
                    "amount_minor": REFERRAL_REWARD_MINOR,
                    "currency": REFERRAL_REWARD_CURRENCY,
                }
            )
            .execute()
        )
    except APIError as exc:
        if exc.code == UNIQUE_VIOLATION:
            return  # already recorded for this account - a retried request
        raise

    reward = resp.data[0]
    referrer_account = await _get_first_active_account(
        supabase, str(user.referred_by_user_id), REFERRAL_REWARD_CURRENCY
    )
    if referrer_account is not None:
        await _pay_referral_reward(supabase, reward, referrer_account)


async def _pay_pending_referral_rewards(supabase: AsyncClient, user: UserRead, account: dict) -> None:
    """The referrer side of the deferred case: `user` just opened a RON
    account, so any reward(s) left `pending` for them (from people they
    referred before they had a RON account of their own) can be paid now."""
    if account["currency"] != REFERRAL_REWARD_CURRENCY:
        return

    resp = (
        await supabase.table("referral_rewards")
        .select("*")
        .eq("referrer_user_id", str(user.id))
        .eq("status", "pending")
        .execute()
    )
    for reward in resp.data or []:
        await _pay_referral_reward(supabase, reward, account)


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

    if user.referral_bonus_eligible:
        await ledger_service.grant_opening_balance(
            supabase,
            uuid.UUID(account["id"]),
            OPENING_BALANCE_MINOR,
            currency,
            idempotency_key=f"opening-balance:{account['id']}",
            actor_user_id=user.id,
        )

    await _record_and_pay_referrer_reward(supabase, user, account)
    await _pay_pending_referral_rewards(supabase, user, account)

    return account


async def get_account_holder_by_iban(supabase: AsyncClient, iban: str) -> dict:
    """Public-within-the-app lookup (no ownership check - the whole point is
    letting the sender see who a not-yet-owned IBAN belongs to before
    paying, same as any real bank's payee-name display). Deliberately
    returns only first/last name, nothing else."""
    iban = iban.replace(" ", "").upper()
    resp = await supabase.table("accounts").select("user_id").eq("iban", iban).maybe_single().execute()
    account = resp.data if resp is not None else None
    if account is None:
        raise IbanNotFoundError()

    user_resp = (
        await supabase.table("users")
        .select("first_name, last_name")
        .eq("id", account["user_id"])
        .maybe_single()
        .execute()
    )
    user_row = user_resp.data if user_resp is not None else None
    if user_row is None:
        raise IbanNotFoundError()
    return user_row


async def get_account_for_owner(
    supabase: AsyncClient, user_id: uuid.UUID | str, account_id: uuid.UUID | str
) -> dict:
    """Ownership-checked account read for callers holding a bare user id.

    The AI layer's `Context` carries a user id string, not a `UserRead`, so it
    needs this entry point. `_get_owned_account` is the same check for the
    banking modules, which do have the full user.
    """
    resp = (
        await supabase.table("accounts")
        .select("*")
        .eq("id", str(account_id))
        .eq("user_id", str(user_id))
        .maybe_single()
        .execute()
    )
    account = resp.data if resp is not None else None
    if account is None:
        # Same error whether the account doesn't exist or just isn't the
        # caller's - don't leak which one it is.
        raise AccountNotFoundError()
    return account


async def _get_owned_account(supabase: AsyncClient, user: UserRead, account_id: uuid.UUID) -> dict:
    return await get_account_for_owner(supabase, user.id, account_id)


async def get_account(supabase: AsyncClient, user: UserRead, account_id: uuid.UUID) -> dict:
    return await _get_owned_account(supabase, user, account_id)


async def list_accounts_for_owner(
    supabase: AsyncClient, user_id: uuid.UUID | str
) -> list[dict]:
    """Account list for callers holding a bare user id.

    Same reason `get_account_for_owner` exists: the AI layer's `Context` carries
    a user id string, not a `UserRead`. `list_accounts` below is this same read
    for the banking modules, which do have the full user.
    """
    resp = (
        await supabase.table("accounts")
        .select("*")
        .eq("user_id", str(user_id))
        .order("created_at")
        .execute()
    )
    return resp.data


async def list_accounts(supabase: AsyncClient, user: UserRead) -> list[dict]:
    return await list_accounts_for_owner(supabase, user.id)


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

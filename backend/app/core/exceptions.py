"""Typed application errors.

Every error the app raises on purpose should be an AppError subclass so
core/middleware.py can map it to a consistent JSON body and status code
instead of leaking a stack trace. Anything that reaches FastAPI as a plain
Exception is treated as a bug and mapped to a generic 500.
"""


class AppError(Exception):
    status_code = 500
    error_code = "internal_error"
    default_message = "Something went wrong."

    def __init__(self, message: str | None = None):
        self.message = message or self.default_message
        super().__init__(self.message)


class ValidationError(AppError):
    status_code = 422
    error_code = "validation_error"
    default_message = "Invalid input."


class NotFoundError(AppError):
    status_code = 404
    error_code = "not_found"
    default_message = "Resource not found."


class AccountNotFoundError(NotFoundError):
    error_code = "account_not_found"
    default_message = "Account not found."


class AccountClosedError(AppError):
    status_code = 409
    error_code = "account_closed"
    default_message = "Account is closed."


class AccountNotEmptyError(AppError):
    status_code = 409
    error_code = "account_not_empty"
    default_message = "Account balance must be zero before it can be closed."


class CurrencyMismatchError(AppError):
    status_code = 422
    error_code = "currency_mismatch"
    default_message = "Currencies do not match."


class InsufficientFundsError(AppError):
    status_code = 422
    error_code = "insufficient_funds"
    default_message = "Insufficient funds."


class InvalidLedgerLegsError(AppError):
    status_code = 422
    error_code = "invalid_ledger_legs"
    default_message = "Ledger legs are not balanced."


class UnauthorizedError(AppError):
    status_code = 401
    error_code = "unauthorized"
    default_message = "Authentication required."


class ForbiddenError(AppError):
    status_code = 403
    error_code = "forbidden"
    default_message = "Not allowed to access this resource."


class InvalidIdempotencyKeyError(AppError):
    status_code = 400
    error_code = "invalid_idempotency_key"
    default_message = "Missing or invalid Idempotency-Key header."


class IdempotencyKeyConflictError(AppError):
    status_code = 409
    error_code = "idempotency_key_conflict"
    default_message = "This Idempotency-Key was already used for a different request."


class RateLimitExceededError(AppError):
    status_code = 429
    error_code = "rate_limit_exceeded"
    default_message = "Too many requests."

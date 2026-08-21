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


class IbanNotFoundError(NotFoundError):
    error_code = "iban_not_found"
    default_message = "No account was found for that IBAN."


class ConversationNotFoundError(NotFoundError):
    error_code = "conversation_not_found"
    default_message = "Conversation not found."


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


class EmailAlreadyRegisteredError(AppError):
    status_code = 409
    error_code = "email_already_registered"
    default_message = "An account with this email already exists."


class NationalIdAlreadyRegisteredError(AppError):
    status_code = 409
    error_code = "national_id_already_registered"
    default_message = "An account associated with this national ID already exists."


class LoginRateLimitedError(AppError):
    status_code = 429
    error_code = "login_rate_limited"
    default_message = "Too many failed login attempts. Try again later."


class InvalidResetCodeError(AppError):
    status_code = 400
    error_code = "invalid_reset_code"
    default_message = "Invalid or expired reset code."


class FaceConfirmationRequiredError(AppError):
    """This amount needs step-up face auth first - see
    app/modules/face_auth::enforce_face_confirmation. 428 Precondition
    Required is the semantically correct status for "do X first, then
    retry", distinct from a plain validation failure."""

    status_code = 428
    error_code = "face_confirmation_required"
    default_message = "This amount requires face confirmation before it can proceed."


class InvalidFaceConfirmationError(AppError):
    status_code = 400
    error_code = "invalid_face_confirmation"
    default_message = "Invalid or expired face confirmation."


class InvalidEnrollmentCodeError(AppError):
    status_code = 400
    error_code = "invalid_enrollment_code"
    default_message = "Invalid or expired verification code."


class DeviceNotTrustedError(AppError):
    status_code = 401
    error_code = "device_not_trusted"
    default_message = "This device is not enrolled."


class TermDepositLockedError(AppError):
    status_code = 409
    error_code = "term_deposit_locked"
    default_message = "This account is locked until its maturity date."


class AIServiceUnavailableError(AppError):
    """The AI layer could not be constructed - typically missing credentials.

    Deliberately vague to the caller: which piece of configuration is absent is
    an operator's concern, not something to advertise over HTTP.
    """

    status_code = 503
    error_code = "ai_service_unavailable"
    default_message = "AI service unavailable"


class AIProviderError(AppError):
    """The upstream model call failed (network, auth, quota, ...)."""

    status_code = 502
    error_code = "ai_provider_error"
    default_message = "AI model request failed"


class AIProviderMisconfiguredError(AppError):
    """AI_PROVIDER names something the app has no implementation for.

    A deployment mistake rather than a caller mistake, so it is a 500 - but the
    message names the valid values, since only an operator will ever see it.
    """

    status_code = 500
    error_code = "ai_provider_misconfigured"
    default_message = "AI provider is misconfigured"

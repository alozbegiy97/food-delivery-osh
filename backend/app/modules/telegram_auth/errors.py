"""Error responses of the Telegram Mini App endpoints (API §1.1, §2.3).

Messages are fallback texts; the frontend shows localized text by `code`.
None of them contains `init_data`, a password, a token or a reason.
"""

from app.core.errors import AppError


def invalid_telegram_auth() -> AppError:
    return AppError(401, "INVALID_TELEGRAM_AUTH", "Не удалось войти через Telegram")


def telegram_disabled() -> AppError:
    return AppError(409, "TELEGRAM_DISABLED", "Вход через Telegram недоступен")


def telegram_not_linked() -> AppError:
    return AppError(409, "TELEGRAM_NOT_LINKED", "Этот Telegram не связан с аккаунтом")


def telegram_already_linked() -> AppError:
    return AppError(409, "TELEGRAM_ALREADY_LINKED", "Этот Telegram уже связан с другим аккаунтом")


def account_already_linked() -> AppError:
    return AppError(409, "ACCOUNT_ALREADY_LINKED", "Этот аккаунт уже связан с другим Telegram")


def telegram_busy() -> AppError:
    # U1: a lock was not obtained within lock_timeout; nothing was changed.
    return AppError(409, "TELEGRAM_BUSY", "Запрос уже обрабатывается, повторите попытку")

"""Auth error responses (API_SPECIFICATION.md §1.1, DEC-140).

Messages are fallback texts; the frontend shows localized text by `code`.
None of them contains user input, tokens or passwords.
"""

from app.core.errors import AppError

_BEARER = {"WWW-Authenticate": "Bearer"}


def unauthorized() -> AppError:
    return AppError(401, "UNAUTHORIZED", "Требуется авторизация", headers=_BEARER)


def invalid_credentials() -> AppError:
    return AppError(401, "INVALID_CREDENTIALS", "Неверный email или пароль")


def invalid_refresh_token() -> AppError:
    return AppError(401, "INVALID_REFRESH_TOKEN", "Сессия недействительна, войдите снова")


def csrf_failed() -> AppError:
    return AppError(403, "CSRF_FAILED", "Запрос отклонён проверкой CSRF")


def forbidden() -> AppError:
    return AppError(403, "FORBIDDEN", "Доступ запрещён")


def password_change_required() -> AppError:
    return AppError(403, "PASSWORD_CHANGE_REQUIRED", "Необходимо сменить пароль")


def email_already_exists() -> AppError:
    return AppError(409, "EMAIL_ALREADY_EXISTS", "Этот email уже зарегистрирован")


def credentials_already_set() -> AppError:
    return AppError(409, "CREDENTIALS_ALREADY_SET", "Email и пароль уже установлены")


def password_not_set() -> AppError:
    # Telegram-only account (DEC-142): there is no password to change.
    return AppError(409, "PASSWORD_NOT_SET", "Пароль для аккаунта не установлен")


def current_password_invalid() -> AppError:
    # 422, not 401: the client must not mistake it for an expired session (DEC-143).
    return AppError(422, "CURRENT_PASSWORD_INVALID", "Текущий пароль указан неверно")

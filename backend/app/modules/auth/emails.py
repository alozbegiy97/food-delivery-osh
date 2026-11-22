"""Texts of auth e-mails in RU/KY/UZ (DEC-108: language = preferred_language).

KY and UZ texts are drafts and need a native speaker review (like DEC-120).
"""

from app.core.mailer import OutgoingEmail

_RESET = {
    "ru": (
        "Сброс пароля",
        "Здравствуйте!\n\n"
        "Мы получили запрос на сброс пароля. Перейдите по ссылке, чтобы задать "
        "новый пароль (ссылка действует {minutes} минут и работает один раз):\n\n"
        "{link}\n\n"
        "Если вы не запрашивали сброс, просто проигнорируйте это письмо.",
    ),
    "ky": (
        "Сырсөздү калыбына келтирүү",
        "Саламатсызбы!\n\n"
        "Сырсөздү калыбына келтирүү боюнча суроо алдык. Жаңы сырсөз коюу үчүн "
        "шилтемеге өтүңүз (шилтеме {minutes} мүнөт жарактуу жана бир жолу иштейт):\n\n"
        "{link}\n\n"
        "Эгер сиз суроо жөнөткөн эмес болсоңуз, бул катты көңүлгө албаңыз.",
    ),
    "uz": (
        "Parolni tiklash",
        "Assalomu alaykum!\n\n"
        "Parolni tiklash soʻrovini oldik. Yangi parol oʻrnatish uchun havolaga "
        "oʻting (havola {minutes} daqiqa amal qiladi va bir marta ishlaydi):\n\n"
        "{link}\n\n"
        "Agar siz soʻrov yubormagan boʻlsangiz, bu xatga eʼtibor bermang.",
    ),
}


def password_reset_email(to: str, language: str, link: str, minutes: int) -> OutgoingEmail:
    subject, body = _RESET.get(language, _RESET["ru"])
    return OutgoingEmail(to=to, subject=subject, body=body.format(link=link, minutes=minutes))

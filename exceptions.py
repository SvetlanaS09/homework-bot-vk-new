class TokenError(Exception):
    """Не хватает токенов или они некорректны."""


class ApiRequestError(Exception):
    """Сбой при выполнении запроса к API."""


class ApiResponseError(Exception):
    """Ошибка ответа API: неверная структура данных или неожиданный статус."""


class WrongResponseCodeError(Exception):
    """API вернул код ответа, отличный от 200."""

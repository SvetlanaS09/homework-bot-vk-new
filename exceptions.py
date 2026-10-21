class TokenError(Exception):
    """Не хватает токенов или они некорректны."""
    pass


class ApiRequestError(Exception):
    """Сбой при выполнении запроса к API."""
    pass


class ApiResponseError(Exception):
    """Ошибка ответа API: неверная структура данных или неожиданный статус."""
    pass


class WrongResponseCodeError(Exception):
    """API вернул код ответа, отличный от 200."""
    pass
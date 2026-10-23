import os
import time
import random
import sys
import logging
from typing import Any, Dict, List, Optional
from http import HTTPStatus

import requests
import vk_api
from dotenv import load_dotenv

from exceptions import (
    ApiRequestError,
    ApiResponseError,
    WrongResponseCodeError,
)

load_dotenv()


PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
VK_TOKEN = os.getenv('VK_TOKEN')
VK_USER_ID = os.getenv('VK_USER_ID')

RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}

HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}


logger = logging.getLogger(__name__)


def check_tokens() -> bool:
    """Проверяет наличие всех обязательных переменных окружения."""
    required_vars = ['PRACTICUM_TOKEN', 'VK_TOKEN', 'VK_USER_ID']
    missing = [var for var in required_vars if not globals()[var]]
    if missing:
        msg = f'Отсутствуют переменные окружения: {", ".join(missing)}'
        logger.critical(msg)
        return False
    return True


def send_message(vk: Any, message: str) -> None:
    """Отправляет сообщение в VK пользователю."""
    try:
        random_id = random.randint(0, 100000)
        vk.messages.send(
            user_id=VK_USER_ID,
            message=message,
            random_id=random_id,
        )
        logging.debug(f'Сообщение отправлено пользователю {VK_USER_ID}')
    except Exception as e:
        logger.error(f'Не удалось отправить сообщение в VK: {e}')


def get_api_answer(timestamp: int) -> Dict[str, Any]:
    """Делает запрос к API и возвращает ответ, приведённый к типам Python."""
    request_kwargs = {
        "url": ENDPOINT,
        "headers": HEADERS,
        "params": {"from_date": timestamp},
    }
    try:
        response = requests.get(**request_kwargs)
    except requests.RequestException as error:
        raise ApiRequestError(
            f'Сбой при запросе к эндпоинту {ENDPOINT}: {error}'
        )
    if response.status_code != HTTPStatus.OK:
        raise WrongResponseCodeError(
            f'Эндпоинт {ENDPOINT} недоступен. '
            f'Код ответа API: {response.status_code}'
        )
    return response.json()


def check_response(response: Dict[str, Any]) -> None:
    """Проверяет структуру ответа API."""
    if not isinstance(response, dict):
        msg = f'Ответ должен быть словарем, получен {type(response).__name__}'
        logger.error(msg)
        raise TypeError(msg)
    if 'homeworks' not in response:
        msg = 'Ответ API не содержит ключ "homeworks"'
        logger.error(msg)
        raise ApiResponseError(msg)
    if 'current_date' not in response:
        msg = 'Ответ API не содержит ключ "current_date"'
        logger.error(msg)
        raise ApiResponseError(msg)
    if not isinstance(response['homeworks'], list):
        msg = (
            'Значение ключа "homeworks" должно быть списком,'
            f'получен тип {type(response["homeworks"]).__name__}'
        )
        logger.error(msg)
        raise TypeError(msg)
    logger.debug('Ответ API прошёл проверку структуры.')


def parse_status(homework: Dict[str, Any]) -> str:
    """Извлекает статус домашней работы и возвращает сообщение для VK."""
    if 'homework_name' not in homework:
        logger.error('В ответе API отсутствует ключ "homework_name"')
        raise KeyError(
            'Отсутствует ключ "homework_name" в данных о домашней работе'
        )
    title = homework['homework_name']
    if 'status' not in homework:
        logger.error(f'В данных о работе "{title}" отсутствует ключ "status"')
        raise KeyError(f'Отсутствует ключ "status" для работы "{title}"')
    status = homework['status']
    verdict = HOMEWORK_VERDICTS.get(status)
    if verdict is None:
        logger.warning(f'Неизвестный статус "{status}" для работы "{title}"')
        raise ValueError(
            f'Недокументированный статус "{status}" для работы "{title}"'
        )
    logger.debug(f'Статус работы: {status} → {verdict}')
    return f'Изменился статус проверки работы "{title}". {verdict}'


def main() -> None:  # noqa: C901
    """Формируется основная логика работы бота."""
    if not check_tokens():
        logging.critical(
            'Отсутствует обязательная переменная окружения. '
            'Программа принудительно остановлена.'
        )
        sys.exit('Отсутствует обязательная переменная окружения.')

    vk_session = vk_api.VkApi(token=VK_TOKEN)
    vk = vk_session.get_api()
    from_date = int(time.time())

    last_status: Optional[str] = None

    while True:
        try:
            response = get_api_answer(from_date)
            check_response(response)
        except Exception:
            logger.exception('Ошибка при получении или проверке ответа API ')
            time.sleep(RETRY_PERIOD)
            continue
        homeworks: List[Dict[str, Any]] = response.get('homeworks', [])
        current_date = response.get('current_date')

        if current_date is None:
            logger.error('Ответ API не содержит current_date, пропуск шага')
            time.sleep(RETRY_PERIOD)
            continue

        if not homeworks:
            if last_status is not None:
                logger.debug('Статус домашних работ не изменился: список пуст')
            else:
                logger.debug('Список домашних работ пуст, начальное состояние')
            from_date = current_date
            time.sleep(RETRY_PERIOD)
            continue

        status_changed = False
        for homework in homeworks:
            try:
                new_status_message = parse_status(homework)
                if new_status_message != last_status:
                    send_message(vk, new_status_message)
                    last_status = new_status_message
                    status_changed = True
                    break
            except Exception as e:
                logger.exception(f'Ошибка при разборе статуса для работы: {e}')
                continue

        if not status_changed:
            logging.debug('Статус не изменился, сообщение не отправляем.')
        time.sleep(RETRY_PERIOD)
        from_date = response['current_date']


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s, %(levelname)s, %(message)s, %(name)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[logging.StreamHandler()]
    )
    main()

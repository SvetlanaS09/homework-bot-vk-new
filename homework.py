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


logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s, %(levelname)s, %(message)s, %(name)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def check_tokens() -> None:
    """Проверяет наличие всех обязательных переменных окружения."""
    return all((PRACTICUM_TOKEN, VK_TOKEN, VK_USER_ID))


def send_message(vk, message: str) -> None:
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


def get_api_answer(timestamp):
    """Делает запрос к API и возвращает ответ, приведённый к типам Python."""
    params = {'from_date': timestamp}
    try:
        response = requests.get(ENDPOINT, headers=HEADERS, params=params)
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
            f'Значение ключа "homeworks" должно быть списком, '
            f'получен тип {type(response["homeworks"]).__name__}'
        )
        logger.error(msg)
        raise TypeError(msg)
    logger.debug('Ответ API прошёл проверку структуры.')


def parse_status(homework: Dict[str, Any]) -> str:
    """
    Извлекает статус домашней работы.
    Возвращает строку-сообщение для отправки в VK.
    """
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


def main() -> None:
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
    last_error_sent_at: Optional[float] = None
    error_cooldown_seconds = RETRY_PERIOD / 2

    while True:
        try:
            response = get_api_answer(from_date)
            check_response(response)
            homeworks: List[Dict[str, Any]] = response.get('homeworks', [])
            current_date = response['current_date']
            from_date = current_date
            if not homeworks:
                if last_status is not None:
                    logging.debug(
                        'Статус домашних работ не изменился: список пуст'
                    )
                else:
                    logging.debug(
                        'Список домашних работ пуст, начальное состояние'
                    )
                time.sleep(RETRY_PERIOD)
                continue
            for homework in homeworks:
                new_status_message = parse_status(homework)
            if new_status_message != last_status:
                try:
                    send_message(vk, new_status_message)
                    last_status = new_status_message
                except Exception as send_error:
                    logging.error(
                        'Не удалось отправить сообщение об ошибке в VK: '
                        f'{send_error}'
                    )
            else:
                logger.debug('Статус не изменился, сообщение не отправляем.')
        except ApiResponseError as error:
            logger.error(f'Ошибка API: {error}')
            now = time.time()
            if (last_error_sent_at is None) or (
                now - last_error_sent_at >= error_cooldown_seconds
            ):
                send_message(vk, VK_USER_ID, f'⚠️ Сбой в работе бота: {error}')
                last_error_sent_at = now
            else:
                logger.debug(
                    'Пропускаем повторную отправку сообщения об ошибке.'
                )
        except Exception as error:
            logger.critical(
                f'Неизвестная ошибка в цикле бота: {error}', exc_info=True
            )
            try:
                send_message(
                    vk, VK_USER_ID, f'💥 Критическая ошибка бота: {error}'
                )
            except Exception:
                pass
        time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()

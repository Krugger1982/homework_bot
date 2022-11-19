import logging
import os
import time
from json.decoder import JSONDecodeError
from logging.handlers import RotatingFileHandler

import requests
import telegram
from dotenv import load_dotenv

import exceptions

load_dotenv()


PRACTICUM_TOKEN = os.getenv('YANDEX_TOKEN')
TELEGRAM_TOKEN = os.getenv('TOKEN')
TELEGRAM_CHAT_ID = os.getenv('CHAT_ID')

# Устанавливаем настройки локального логгера
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
handler = RotatingFileHandler(
    'homework.log', maxBytes=5000000, backupCount=5
)
formatter = logging.Formatter(
    '%(asctime)s %(levelname)s %(message)s file:%(name)s line:%(lineno)s'
)
handler.setFormatter(formatter)
logger.addHandler(handler)

RETRY_TIME = 10
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}


HOMEWORK_STATUSES = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}


def send_message(bot, message):
    """Отправляет сообщение 'message' боту 'bot'."""
    bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=message
    )
    logger.info(f'Бот отправил сообщение: {message}')


def get_api_answer(current_timestamp):
    """Подает запрос на API."""
    timestamp = current_timestamp
    params = {'from_date': timestamp}
    try:
        response = requests.get(ENDPOINT, headers=HEADERS, params=params)
        logging.debug('Получен ответ от API Яндекс-Практикума')
    except requests.exceptions.RequestException as e:
        logger.error(f'Ошибка сервера {e}')
        raise exceptions.WrongResponseError('Ошибка сервера {e}')
    if response.status_code != 200:
        logger.error(f'Эндпойнт {ENDPOINT} недоступен.'
                     f'Ошибка {response.status_code}')
        raise exceptions.WrongResponseError(
            f'Эндпойнт {ENDPOINT} недоступен. Ошибка {response.status_code}'
        )
    try:
        response = response.json()
    except JSONDecodeError as e:
        logger.error(f'Получен ответ неправильного формата {e}')
        raise exceptions.NotJSONError(
            'Невозможно привести данные к типам Python'
        )
    return response


def check_response(response):
    """Проверяет корректность ответа."""
    error_message = ''
    if not isinstance(response, dict):
        error_message = 'Полученный ответ - не словарь.'
    if 'homeworks' not in response:
        error_message = 'Ответ не содержит списка работ.'
    if not isinstance(response['homeworks'], list):
        error_message = 'переменная под ключом "homeworks" не в виде списка'
    # После всех проверок выявленную ошибку логируем и поднимаем исключение]
    if len(error_message) > 0:
        logger.error(error_message)
        raise exceptions.WrongJSONError(error_message)
    return response['homeworks']


def parse_status(homework):
    """Преобразует ответ в информационное сообщение для мессенджера."""
    # Инициируем переменную
    error_message = ''
    if 'homework_name' not in homework:
        error_message = 'Неизвестное имя домашней работы'
    if 'status' not in homework:
        error_message = 'Отсутствует статус проверки домашней работы'
    homework_name = homework['homework_name']
    homework_status = homework['status']
    if homework_status not in HOMEWORK_STATUSES:
        error_message = 'Неправильный статус проверки домашней работы'
    if len(error_message) > 0:
        logger.error(error_message)
        raise KeyError(error_message)
    verdict = HOMEWORK_STATUSES[homework_status]
    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def check_tokens():
    """Проверяет доступность внутренних переменных окружения."""
    if (
        PRACTICUM_TOKEN is None
        or TELEGRAM_TOKEN is None
        or TELEGRAM_CHAT_ID is None
    ):
        # Если хотя бы однa из переменных окружения отсутствует
        logger.critical(
            'Недоступна/отсутствует необходимая переменная окружения',
            exc_info=True
        )
        return False
    return True


def main():
    """Основная логика работы бота."""
    # Сначала действия перед началом работы бота в цикле
    # Проверка доступности токенов
    tokens_exist = check_tokens()
    if not tokens_exist and (
        TELEGRAM_TOKEN is not None and TELEGRAM_CHAT_ID is not None
    ):
        # Если токен ЯП недоступен, но есть возможность отправить сбщ в телегу
        bot = telegram.Bot(token=TELEGRAM_TOKEN)
        message = 'Отсутствуют учетные данные для доступа к сервису'
        send_message(bot, message)
        raise ValueError(message)
    elif not tokens_exist:
        message = ('Oтсутствуют обязательные переменные окружения.'
                   'Программа принудительно остановлена.')
        raise ValueError(message)
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    # стартовый запрос без указания времени,чтоб установить начало отсчета
    # и привязать время запроса к времени сервера ЯндексПрактикум
    current_timestamp = int(time.time())
    response = get_api_answer(current_timestamp)
    # Вернется очевидно пустой ответ с меткой времени
    current_timestamp = response.get('current_date')
    # инициируем сообщение об ошибке, чтоб избежать повторных сообщений
    old_error_message = ''

    while True:
        try:
            response = get_api_answer(current_timestamp)
            current_timestamp = response.get('current_date')
            homeworks = check_response(response)
            if not isinstance(homeworks, list):
                logger.error('Тип данных атрибута "homeworks" не словарь')
                raise ValueError('Тип данных атрибута "homeworks" не словарь')
            if homeworks:
                # сообщение отправляется только в случае изменений
                message = parse_status(homeworks[0])
                send_message(bot=bot, message=message)
            else:
                logger.debug('Изменений в статусах работ нет')
        except Exception as error:
            message = f'Сбой в работе программы: {error}'
            if message != old_error_message:
                send_message(bot=bot, message=message)
                old_error_message = message
            time.sleep(RETRY_TIME)
        else:
            time.sleep(RETRY_TIME)


if __name__ == '__main__':
    main()

import logging
import os
import sys
import time
from http import HTTPStatus
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

RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}


HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}


def send_message(bot, message):
    """Отправляет сообщение 'message' боту 'bot'."""
    try:
        logger.debug(f'Бот отправляет сообщение: {message}')
        bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message
        )
    except Exception:
        logger.error('Не удалось отправить сообщение')
        raise exceptions.SendMessageError('Не удалось отправить сообщение')
    else:
        logger.debug('Сообщение успешно отправлено')


def get_api_answer(current_timestamp=int(time.time())):
    """Подает запрос на API."""
    timestamp = current_timestamp
    params = {'from_date': timestamp}
    try:
        logger.debug('Начат запрос к API сервиса')
        response = requests.get(ENDPOINT, headers=HEADERS, params=params)
    except requests.exceptions.RequestException:
        raise exceptions.WrongResponseError(
            'Ошибка сервера {response.status_code.phrase}'
        )
    else:
        logger.debug('Получен ответ от API Яндекс-Практикума')
    if response.status_code != HTTPStatus.OK:
        raise exceptions.WrongResponseError(
            f'Эндпойнт {ENDPOINT} недоступен. Ошибка {response.status_code}'
        )
    try:
        response = response.json()
    except JSONDecodeError as e:
        raise exceptions.NotJSONError(
            f'Невозможно привести данные к типам Python. Ошибка: {e}'
        )
    return response


def check_response(response):
    """Проверяет корректность ответа."""
    if not isinstance(response, dict):
        raise exceptions.WrongJSONError('Полученный ответ - не словарь.')
    if 'homeworks' not in response:
        raise exceptions.WrongJSONError('Ответ не содержит списка работ.')
    if 'current_date' not in response:
        raise exceptions.WrongJSONError('Ответ не содержит отметки времени')
    homeworks = response['homeworks']
    if not isinstance(homeworks, list):
        raise exceptions.WrongJSONError(
            'Переменная под ключом "homeworks" не в виде списка'
        )
    return homeworks


def parse_status(homework):
    """Преобразует ответ в информационное сообщение для мессенджера."""
    if 'homework_name' not in homework:
        raise KeyError('Неизвестное имя домашней работы')
    if 'status' not in homework:
        raise KeyError('Отсутствует статус проверки домашней работы')
    homework_name = homework['homework_name']
    homework_status = homework['status']
    if homework_status not in HOMEWORK_VERDICTS:
        raise ValueError('Неправильный статус проверки домашней работы')
    # После всех проверок формируем и возвращаем фразу для мессенджера"
    verdict = HOMEWORK_VERDICTS[homework_status]
    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def check_tokens():
    """Проверяет доступность внутренних переменных окружения."""
    return all((PRACTICUM_TOKEN, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID))


def main():
    """Основная логика работы бота."""
    # Сначала действия перед началом работы бота в цикле
    # Проверка доступности токенов
    if not check_tokens():
        message = ('Oтсутствуют обязательные переменные окружения.'
                   'Программа принудительно остановлена.')
        logger.critical(message, exc_info=True)
        sys.exit()
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    # стартовый запрос без указания времени,чтоб установить начало отсчета
    # и привязать время запроса к времени сервера ЯндексПрактикум
    current_timestamp = int(time.time())
    response = get_api_answer(current_timestamp)

    # Вернется очевидно пустой ответ с меткой времени
    # если время не придет (плохой ответ), это выявится в следующем же запросе
    current_timestamp = response.get('current_date')

    # инициируем сообщение, чтоб избежать повторных сообщений
    old_message = ''
    while True:
        try:
            response = get_api_answer(current_timestamp)
            current_timestamp = response.get('current_date')
            homeworks = check_response(response)
            if homeworks:
                # сообщение отправляется только в случае изменений
                message = parse_status(homeworks[0])
                if message != old_message:
                    send_message(bot=bot, message=message)
                    old_message = message
            else:
                message = 'Изменений в статусах работ нет'
                logger.debug(message)
        except Exception as error:
            message = f'Сбой в работе программы: {error}'
            if message != old_message:
                send_message(bot=bot, message=message)
                old_message = message
        finally:
            time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()

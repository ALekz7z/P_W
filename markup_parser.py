#!/usr/bin/env python3
"""
Парсер динамической страницы разметки
Подключается к уже запущенному браузеру Thorium через CDP (порт 9222)
Парсит страницу по нажатию Shift + S и сохраняет данные в markup_output.json

Требования:
- Python 3.10+
- playwright (установить: pip install playwright)
- beautifulsoup4 (установить: pip install beautifulsoup4)
- pynput (установить: pip install pynput)
- Thorium должен быть запущен с флагом --remote-debugging-port=9222

Использование:
- Запустите скрипт
- Перейдите на страницу с таблицей в браузере
- Нажмите Shift + S для парсинга страницы
- Нажмите Ctrl + C для выхода
"""

import json
import re
import sys
import threading
import logging
from typing import Optional, Dict, Any
from datetime import datetime

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeoutError
from pynput import keyboard

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def clean_text(text: str) -> str:
    """
    Очистка текста от артефактов UI и лишних пробелов.
    Удаляет 'Показать меньше', лишние пробелы, табуляции, переносы строк.
    """
    logger.debug(f"[CLEAN_TEXT] Начало обработки текста: '{text[:50]}...'")
    if not text:
        logger.debug("[CLEAN_TEXT] Пустой текст, возвращаем пустую строку")
        return ""
    # Удаляем артефакт "Показать меньше"
    cleaned = re.sub(r"Показать\s*меньше", "", text, flags=re.IGNORECASE)
    logger.debug(f"[CLEAN_TEXT] После удаления 'Показать меньше': '{cleaned[:50]}...'")
    # Нормализуем пробелы: заменяем все виды пробельных символов на один пробел
    cleaned = " ".join(cleaned.split())
    logger.debug(f"[CLEAN_TEXT] После нормализации пробелов: '{cleaned[:50]}...'")
    result = cleaned.strip()
    logger.debug(f"[CLEAN_TEXT] Результат: '{result}'")
    return result


def parse_table(html_content: str) -> Optional[Dict[str, Any]]:
    """
    Парсинг HTML-таблицы с разметкой.
    
    Логика:
    - Находит таблицу в HTML
    - Проходит по всем <tr>
    - Извлекает ключи и значения из ячеек
    - Фильтрует дубликаты и строки-разделители
    - Возвращает словарь с данными
    
    Возвращает:
        Dict с данными или None, если таблица не найдена
    """
    logger.info("[PARSE_TABLE] Начало парсинга таблицы")
    logger.debug(f"[PARSE_TABLE] Размер HTML: {len(html_content)} символов")
    
    soup = BeautifulSoup(html_content, "html.parser")
    logger.debug("[PARSE_TABLE] HTML распарсен через BeautifulSoup")
    
    # Ищем таблицу
    table = soup.find("table")
    if not table:
        logger.warning("[PARSE_TABLE] Таблица не найдена в HTML")
        return None
    
    logger.info("[PARSE_TABLE] Таблица найдена, начинаем обработку строк")
    
    data: Dict[str, Any] = {}
    seen_keys: set = set()
    
    # Находим все строки таблицы
    rows = table.find_all("tr")
    logger.debug(f"[PARSE_TABLE] Найдено строк в таблице: {len(rows)}")
    
    for idx, row in enumerate(rows):
        # Ищем ячейки (td или th)
        cells = row.find_all(["td", "th"])
        
        if len(cells) < 2:
            # Пропускаем строки без достаточного количества ячеек
            logger.debug(f"[PARSE_TABLE] Строка {idx}: пропущена (ячеек меньше 2: {len(cells)})")
            continue
        
        # Предполагаем, что первая ячейка - ключ, вторая - значение
        key_cell = cells[0]
        value_cell = cells[1]
        
        key = clean_text(key_cell.get_text())
        value = clean_text(value_cell.get_text())
        
        logger.debug(f"[PARSE_TABLE] Строка {idx}: ключ='{key}', значение='{value}'")
        
        # Пропускаем пустые ключи
        if not key:
            logger.debug(f"[PARSE_TABLE] Строка {idx}: пропущена (пустой ключ)")
            continue
        
        # Обработка дублей "Описание": если уже есть, пропускаем
        if key == "Описание" and key in seen_keys:
            logger.debug(f"[PARSE_TABLE] Строка {idx}: пропущена (дубль ключа 'Описание')")
            continue
        
        # Игнорируем строку-разделитель: если key == "Дополнительные сведения" и key == value
        if key == "Дополнительные сведения" and key == value:
            logger.debug(f"[PARSE_TABLE] Строка {idx}: пропущена (строка-разделитель)")
            continue
        
        # Сохраняем только уникальные ключи (первое вхождение)
        if key not in seen_keys:
            seen_keys.add(key)
            data[key] = value
            logger.debug(f"[PARSE_TABLE] Строка {idx}: добавлено в данные - '{key}': '{value}'")
        else:
            logger.debug(f"[PARSE_TABLE] Строка {idx}: пропущена (ключ '{key}' уже существует)")
    
    logger.info(f"[PARSE_TABLE] Парсинг завершен. Найдено уникальных полей: {len(data)}")
    return data


def find_target_page(pages: list) -> Optional[Page]:
    """
    Поиск целевой страницы по частичному совпадению URL или заголовка.
    Ищет страницы с "Markup" или "Баскет" в заголовке или URL.
    
    Args:
        pages: Список страниц из контекста браузера
    
    Returns:
        Page или None, если не найдено
    """
    logger.info("[FIND_TARGET_PAGE] Начало поиска целевой страницы")
    target_keywords = ["Markup", "Баскет", "markup", "баскет"]
    
    for idx, page in enumerate(pages):
        try:
            title = page.title().lower() if page.title() else ""
            url = page.url.lower() if page.url else ""
            
            logger.debug(f"[FIND_TARGET_PAGE] Страница {idx}: заголовок='{title}', URL='{url}'")
            
            # Проверяем заголовок и URL на наличие ключевых слов
            for keyword in target_keywords:
                if keyword.lower() in title or keyword.lower() in url:
                    logger.info(f"[FIND_TARGET_PAGE] Найдена целевая страница {idx} по ключевому слову '{keyword}'")
                    return page
        except Exception as e:
            # Если не удалось получить титул или URL, пропускаем
            logger.warning(f"[FIND_TARGET_PAGE] Не удалось получить информацию о странице {idx}: {e}")
            continue
    
    # Если не нашли по ключевым словам, возвращаем первую доступную страницу
    if pages:
        logger.info(f"[FIND_TARGET_PAGE] Целевая страница не найдена по ключевым словам, возвращаем первую страницу (всего страниц: {len(pages)})")
        return pages[0]
    
    logger.warning("[FIND_TARGET_PAGE] Список страниц пуст")
    return None


def save_to_json(data: Dict[str, Any], filepath: str = r"C:\Users\gahar\.n8n-files\markup_output.json") -> bool:
    """
    Сохранение данных в JSON-файл с перезаписью.
    
    Args:
        data: Словарь с данными для сохранения
        filepath: Путь к файлу вывода
    
    Returns:
        True если сохранение успешно, False иначе
    """
    logger.info(f"[SAVE_TO_JSON] Начало сохранения данных в файл: {filepath}")
    try:
        import os
        # Создаем директорию если она не существует
        directory = os.path.dirname(filepath)
        if directory and not os.path.exists(directory):
            logger.info(f"[SAVE_TO_JSON] Директория не существует, создаем: {directory}")
            os.makedirs(directory, exist_ok=True)
            logger.info(f"[SAVE_TO_JSON] Директория успешно создана: {directory}")
        else:
            logger.debug(f"[SAVE_TO_JSON] Директория уже существует: {directory}")
        
        logger.debug(f"[SAVE_TO_JSON] Количество полей для сохранения: {len(data)}")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        logger.info(f"[SAVE_TO_JSON] Данные успешно сохранены в файл: {filepath}")
        return True
    except PermissionError as e:
        logger.error(f"[SAVE_TO_JSON] Ошибка доступа к файлу {filepath}: {e}")
        logger.error("[SAVE_TO_JSON] Проверьте права доступа к папке и файлу")
        return False
    except Exception as e:
        logger.error(f"[SAVE_TO_JSON] Не удалось сохранить файл {filepath}: {type(e).__name__}: {e}")
        return False


# Глобальная переменная для флага парсинга
parse_triggered = False
parse_lock = threading.Lock()
shift_pressed = False


def on_press(key):
    """Обработчик нажатий клавиш."""
    global parse_triggered, shift_pressed
    
    try:
        # Отслеживаем нажатие Shift
        if key == keyboard.Key.shift or key == keyboard.Key.shift_l or key == keyboard.Key.shift_r:
            shift_pressed = True
            logger.debug("[ON_PRESS] Зажат Shift")
        # Проверяем нажатие S при зажатом Shift
        elif shift_pressed and hasattr(key, 'char') and key.char and key.char.lower() == 's':
            with parse_lock:
                if not parse_triggered:
                    parse_triggered = True
                    logger.info("[ON_PRESS] Обнаружено нажатие Shift + S - запускаю парсинг...")
                else:
                    logger.debug("[ON_PRESS] Флаг парсинга уже установлен, игнорируем повторное нажатие")
    except Exception as e:
        logger.error(f"[ON_PRESS] Ошибка в обработчике нажатия: {e}")


def on_release(key):
    """Обработчик отпускания клавиш."""
    global shift_pressed
    
    try:
        if key == keyboard.Key.shift or key == keyboard.Key.shift_l or key == keyboard.Key.shift_r:
            shift_pressed = False
            logger.debug("[ON_RELEASE] Shift отпущен")
    except Exception as e:
        logger.error(f"[ON_RELEASE] Ошибка в обработчике отпускания: {e}")


def wait_for_shift_s():
    """Запускает прослушивание клавиатуры в отдельном потоке."""
    logger.info("[WAIT_FOR_SHIFT_S] Запуск прослушивания клавиатуры в отдельном потоке")
    try:
        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            logger.debug("[WAIT_FOR_SHIFT_S] Слушатель клавиатуры запущен")
            listener.join()
    except Exception as e:
        logger.error(f"[WAIT_FOR_SHIFT_S] Ошибка при запуске слушателя клавиатуры: {e}")
        logger.error("[WAIT_FOR_SHIFT_S] Убедитесь, что у программы есть права на перехват ввода")


def main():
    """
    Основная функция парсера.
    
    Алгоритм работы:
    1. Подключение к активной сессии Thorium через CDP
    2. Поиск целевой страницы с таблицей
    3. Ожидание нажатия Shift + S для парсинга
    4. Полная отрисовка страницы перед парсингом
    5. Парсинг таблицы и сохранение в JSON
    """
    global parse_triggered
    
    cdp_url = "http://localhost:9222"
    output_file = r"C:\Users\gahar\.n8n-files\markup_output.json"
    
    logger.info("=" * 60)
    logger.info("Парсер динамической страницы разметки")
    logger.info("=" * 60)
    logger.info(f"[MAIN] Подключение к CDP: {cdp_url}")
    logger.info("[MAIN] Убедитесь, что Thorium запущен с флагом --remote-debugging-port=9222")
    logger.info("-" * 60)
    logger.info("Инструкция:")
    logger.info("  1. Авторизуйтесь на сайте и откройте страницу с таблицей")
    logger.info("  2. Нажмите Shift + S для парсинга текущей страницы")
    logger.info("  3. Нажмите Ctrl + C для выхода")
    logger.info("=" * 60)
    
    playwright = None
    
    try:
        # Шаг 1: Подключение к активной сессии через CDP
        logger.info("[MAIN] Шаг 1: Подключение к активной сессии браузера через CDP")
        with sync_playwright() as playwright:
            # Подключаемся к существующему экземпляру браузера
            browser = playwright.chromium.connect_over_cdp(cdp_url)
            logger.info("[MAIN] Успешное подключение к браузеру через CDP")
            
            # Получаем первый контекст и страницы
            contexts = browser.contexts
            if not contexts:
                logger.error("[MAIN] Не найдено активных контекстов браузера")
                print("[ERROR] Не найдено активных контекстов браузера")
                return
            
            context = contexts[0]
            pages = context.pages
            logger.debug(f"[MAIN] Найдено контекстов: {len(contexts)}, страниц в первом контексте: {len(pages)}")
            
            if not pages:
                logger.error("[MAIN] Не найдено открытых страниц в браузере")
                print("[ERROR] Не найдено открытых страниц в браузере")
                return
            
            # Поиск целевой страницы
            logger.info("[MAIN] Шаг 2: Поиск целевой страницы с таблицей")
            page = find_target_page(pages)
            if not page:
                logger.error("[MAIN] Не удалось найти целевую страницу")
                print("[ERROR] Не удалось найти целевую страницу")
                return
            
            logger.info(f"[MAIN] Подключено к странице: {page.title()}")
            logger.info(f"[MAIN] URL страницы: {page.url}")
            print("-" * 60)
            logger.info("[MAIN] Шаг 3: Запуск прослушивания клавиатуры (Shift + S)")
            
            # Запускаем прослушивание клавиатуры в отдельном потоке
            keyboard_thread = threading.Thread(target=wait_for_shift_s, daemon=True)
            keyboard_thread.start()
            logger.debug("[MAIN] Поток прослушивания клавиатуры запущен")
            
            # Шаг 2: Цикл ожидания нажатия Shift + S
            iteration = 0
            logger.info("[MAIN] Вход в основной цикл ожидания нажатия Shift + S")
            
            while True:
                # Проверяем флаг парсинга
                with parse_lock:
                    if parse_triggered:
                        parse_triggered = False
                        iteration += 1
                        
                        # Шаг 3: Дожидаемся полной отрисовки страницы
                        logger.info(f"\n[MAIN] ========== Парсинг страницы (попытка {iteration}) ==========")
                        
                        try:
                            # Ждем полной загрузки и отрисовки
                            logger.debug("[MAIN] Ожидание состояния networkidle (таймаут 15 сек)...")
                            page.wait_for_load_state("networkidle", timeout=15000)
                            logger.debug("[MAIN] Страница загружена (networkidle)")
                        except PlaywrightTimeoutError:
                            logger.warning("[MAIN] Таймаут при ожидании networkidle, продолжаем...")
                            pass  # Продолжаем даже если таймаут
                        
                        # Дополнительная пауза для рендеринга JavaScript
                        logger.debug("[MAIN] Дополнительная пауза 2 сек для рендеринга JavaScript...")
                        page.wait_for_timeout(2000)
                        
                        # Шаг 4: Получение и парсинг HTML
                        logger.info("[MAIN] Шаг 4: Получение HTML содержимого страницы...")
                        html_content = page.content()
                        logger.debug(f"[MAIN] Размер полученного HTML: {len(html_content)} символов")
                        
                        logger.info("[MAIN] Шаг 5: Парсинг таблицы из HTML...")
                        data = parse_table(html_content)
                        
                        if data:
                            # Шаг 6: Запись данных в файл
                            logger.info("[MAIN] Шаг 6: Сохранение данных в JSON файл...")
                            if save_to_json(data, output_file):
                                logger.info(f"[MAIN] Данные успешно сохранены в {output_file}")
                                logger.info(f"[MAIN] Найдено полей: {len(data)}")
                                print(f"[OK] Данные сохранены в {output_file}")
                                print(f"[OK] Найдено полей: {len(data)}")
                            else:
                                logger.error("[MAIN] Не удалось сохранить данные в файл")
                                print("[ERROR] Не удалось сохранить данные в файл")
                        else:
                            logger.warning("[MAIN] Таблица не найдена или пуста")
                            print("[WARNING] Таблица не найдена или пуста")
                
                # Небольшая пауза чтобы не нагружать процессор
                page.wait_for_timeout(100)
        
    except KeyboardInterrupt:
        logger.info("\n[MAIN] Парсер остановлен пользователем (Ctrl+C)")
        print("\n[INFO] Парсер остановлен пользователем (Ctrl+C)")
        
    except Exception as e:
        logger.error(f"[MAIN] Критическая ошибка: {type(e).__name__}: {e}", exc_info=True)
        print(f"\n[ERROR] Критическая ошибка: {type(e).__name__}: {e}")
        print("[ERROR] Убедитесь, что Thorium запущен с портом отладки 9222")
        
    finally:
        logger.info("[MAIN] Завершение работы парсера...")
        print("[INFO] Завершение работы парсера...")
        if playwright:
            logger.debug("[MAIN] Остановка Playwright...")
            playwright.stop()
        logger.info("[MAIN] Готово!")
        print("[INFO] Готово!")


if __name__ == "__main__":
    main()

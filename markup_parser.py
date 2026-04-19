#!/usr/bin/env python3
"""
Парсер динамической страницы разметки
Подключается к уже запущенному браузеру Thorium через CDP (порт 9222)
Парсит страницу по нажатию клавиш и сохраняет данные в markup_output.json

Требования:
- Python 3.10+
- playwright (установить: pip install playwright)
- beautifulsoup4 (установить: pip install beautifulsoup4)
- Thorium должен быть запущен с флагом --remote-debugging-port=9222

Использование:
- Запустите скрипт
- Перейдите на страницу с таблицей в браузере
- Нажмите любую клавишу в терминале для парсинга страницы
- Нажмите 'q' + Enter для выхода
"""

import json
import re
import sys
import select
from typing import Optional, Dict, Any

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeoutError


def clean_text(text: str) -> str:
    """
    Очистка текста от артефактов UI и лишних пробелов.
    Удаляет 'Показать меньше', лишние пробелы, табуляции, переносы строк.
    """
    if not text:
        return ""
    # Удаляем артефакт "Показать меньше"
    cleaned = re.sub(r"Показать\s*меньше", "", text, flags=re.IGNORECASE)
    # Нормализуем пробелы: заменяем все виды пробельных символов на один пробел
    cleaned = " ".join(cleaned.split())
    return cleaned.strip()


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
    soup = BeautifulSoup(html_content, "html.parser")
    
    # Ищем таблицу
    table = soup.find("table")
    if not table:
        return None
    
    data: Dict[str, Any] = {}
    seen_keys: set = set()
    
    # Находим все строки таблицы
    rows = table.find_all("tr")
    
    for row in rows:
        # Ищем ячейки (td или th)
        cells = row.find_all(["td", "th"])
        
        if len(cells) < 2:
            # Пропускаем строки без достаточного количества ячеек
            continue
        
        # Предполагаем, что первая ячейка - ключ, вторая - значение
        key_cell = cells[0]
        value_cell = cells[1]
        
        key = clean_text(key_cell.get_text())
        value = clean_text(value_cell.get_text())
        
        # Пропускаем пустые ключи
        if not key:
            continue
        
        # Обработка дублей "Описание": если уже есть, пропускаем
        if key == "Описание" and key in seen_keys:
            continue
        
        # Игнорируем строку-разделитель: если key == "Дополнительные сведения" и key == value
        if key == "Дополнительные сведения" and key == value:
            continue
        
        # Сохраняем только уникальные ключи (первое вхождение)
        if key not in seen_keys:
            seen_keys.add(key)
            data[key] = value
    
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
    target_keywords = ["Markup", "Баскет", "markup", "баскет"]
    
    for page in pages:
        try:
            title = page.title().lower() if page.title() else ""
            url = page.url.lower() if page.url else ""
            
            # Проверяем заголовок и URL на наличие ключевых слов
            for keyword in target_keywords:
                if keyword.lower() in title or keyword.lower() in url:
                    return page
        except Exception:
            # Если не удалось получить титул или URL, пропускаем
            continue
    
    # Если не нашли по ключевым словам, возвращаем первую доступную страницу
    if pages:
        return pages[0]
    
    return None


def save_to_json(data: Dict[str, Any], filepath: str = "markup_output.json") -> None:
    """
    Сохранение данных в JSON-файл с перезаписью.
    
    Args:
        data: Словарь с данными для сохранения
        filepath: Путь к файлу вывода
    """
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def wait_for_user_input() -> bool:
    """
    Проверка наличия ввода пользователя без блокировки.
    
    Returns:
        True если пользователь ввел 'q' для выхода, иначе False
    """
    # Проверяем, есть ли ввод доступен
    if sys.platform != 'win32':
        ready, _, _ = select.select([sys.stdin], [], [], 0.1)
        if ready:
            user_input = sys.stdin.readline().strip().lower()
            if user_input == 'q':
                return True
    return False


def main():
    """
    Основная функция парсера.
    
    Алгоритм работы:
    1. Подключение к активной сессии Thorium через CDP
    2. Поиск целевой страницы с таблицей
    3. Ожидание ввода пользователя для парсинга
    4. Полная отрисовка страницы перед парсингом
    5. Парсинг таблицы и сохранение в JSON
    """
    cdp_url = "http://localhost:9222"
    output_file = "markup_output.json"
    
    print("=" * 60)
    print("Парсер динамической страницы разметки")
    print("=" * 60)
    print(f"[INFO] Подключение к CDP: {cdp_url}")
    print("[INFO] Убедитесь, что Thorium запущен с флагом --remote-debugging-port=9222")
    print("-" * 60)
    print("Инструкция:")
    print("  1. Авторизуйтесь на сайте и откройте страницу с таблицей")
    print("  2. Нажмите Enter для парсинга текущей страницы")
    print("  3. Введите 'q' и нажмите Enter для выхода")
    print("=" * 60)
    
    playwright = None
    
    try:
        # Шаг 1: Подключение к активной сессии через CDP
        with sync_playwright() as playwright:
            # Подключаемся к существующему экземпляру браузера
            browser = playwright.chromium.connect_over_cdp(cdp_url)
            
            # Получаем первый контекст и страницы
            contexts = browser.contexts
            if not contexts:
                print("[ERROR] Не найдено активных контекстов браузера")
                return
            
            context = contexts[0]
            pages = context.pages
            
            if not pages:
                print("[ERROR] Не найдено открытых страниц в браузере")
                return
            
            # Поиск целевой страницы
            page = find_target_page(pages)
            if not page:
                print("[ERROR] Не удалось найти целевую страницу")
                return
            
            print(f"[INFO] Подключено к странице: {page.title()}")
            print("-" * 60)
            
            # Шаг 2: Цикл ожидания ввода пользователя
            iteration = 0
            
            while True:
                # Проверяем ввод пользователя
                if wait_for_user_input():
                    print("\n[INFO] Выход по команде пользователя")
                    break
                
                # Проверяем, нужно ли парсить (нажатие Enter)
                if sys.platform != 'win32':
                    ready, _, _ = select.select([sys.stdin], [], [], 0)
                    if ready:
                        user_input = sys.stdin.readline().strip().lower()
                        if user_input == 'q':
                            break
                        elif user_input == '':
                            # Пользователь нажал Enter - парсим страницу
                            iteration += 1
                            
                            # Шаг 3: Дожидаемся полной отрисовки страницы
                            print(f"\n[INFO] Парсинг страницы (попытка {iteration})...")
                            
                            try:
                                # Ждем полной загрузки и отрисовки
                                page.wait_for_load_state("networkidle", timeout=15000)
                            except PlaywrightTimeoutError:
                                pass  # Продолжаем даже если таймаут
                            
                            # Дополнительная пауза для рендеринга JavaScript
                            page.wait_for_timeout(2000)
                            
                            # Шаг 4: Получение и парсинг HTML
                            html_content = page.content()
                            data = parse_table(html_content)
                            
                            if data:
                                # Шаг 5: Запись данных в файл
                                save_to_json(data, output_file)
                                print(f"[OK] Данные сохранены в {output_file}")
                                print(f"[OK] Найдено полей: {len(data)}")
                            else:
                                print("[WARNING] Таблица не найдена или пуста")
                
                # Небольшая пауза чтобы не нагружать процессор
                page.wait_for_timeout(100)
                
    except KeyboardInterrupt:
        print("\n[INFO] Парсер остановлен пользователем (Ctrl+C)")
        
    except Exception as e:
        print(f"\n[ERROR] Критическая ошибка: {type(e).__name__}: {e}")
        print("[ERROR] Убедитесь, что Thorium запущен с портом отладки 9222")
        
    finally:
        print("[INFO] Завершение работы парсера...")
        if playwright:
            playwright.stop()
        print("[INFO] Готово!")


if __name__ == "__main__":
    main()

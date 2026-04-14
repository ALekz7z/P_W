#!/usr/bin/env python3
"""
Парсер динамической страницы разметки
Подключается к уже запущенному браузеру Thorium через CDP (порт 9222)
Мониторит обновления страницы и сохраняет данные в markup_output.json

Требования:
- Python 3.10+
- playwright (установить: pip install playwright)
- beautifulsoup4 (установить: pip install beautifulsoup4)
- Thorium должен быть запущен с флагом --remote-debugging-port=9222
"""

import json
import re
import time
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
        print("[WARNING] Таблица не найдена на странице")
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
                    print(f"[INFO] Найдена целевая страница: {page.title()}")
                    return page
        except Exception:
            # Если не удалось получить титул или URL, пропускаем
            continue
    
    # Если не нашли по ключевым словам, возвращаем первую доступную страницу
    if pages:
        print("[WARNING] Целевая страница не найдена по ключевым словам, используем первую доступную")
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
    print(f"[INFO] Данные сохранены в {filepath}")


def main():
    """
    Основная функция парсера.
    
    Алгоритм работы:
    1. Подключение к активной сессии Thorium через CDP
    2. Поиск целевой страницы с таблицей
    3. Бесконечный цикл мониторинга обновлений
    4. Парсинг таблицы при каждом обновлении
    5. Запись результатов в JSON
    """
    cdp_url = "http://localhost:9222"
    output_file = "markup_output.json"
    
    print("=" * 60)
    print("Парсер динамической страницы разметки")
    print("=" * 60)
    print(f"[INFO] Подключение к CDP: {cdp_url}")
    print("[INFO] Ожидание подключения к браузеру Thorium...")
    print("[INFO] Убедитесь, что Thorium запущен с флагом --remote-debugging-port=9222")
    print("[INFO] Авторизуйтесь на сайте и откройте страницу с таблицей")
    print("-" * 60)
    
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
            print(f"[INFO] URL: {page.url}")
            print("-" * 60)
            print("[INFO] Запуск мониторинга обновлений страницы...")
            print("[INFO] Для остановки нажмите Ctrl+C")
            print("=" * 60)
            
            # Шаг 2: Бесконечный цикл мониторинга обновлений
            iteration = 0
            
            while True:
                try:
                    iteration += 1
                    
                    # Ждём загрузки страницы (триггер обновления)
                    # networkidle означает, что сеть неактивна ~500мс
                    print(f"\n[INFO] Итерация {iteration}: Ожидание загрузки страницы...")
                    
                    try:
                        page.wait_for_load_state("networkidle", timeout=15000)
                    except PlaywrightTimeoutError:
                        print("[WARNING] Таймаут ожидания networkidle, продолжаем парсинг...")
                    
                    # Шаг 3: Получение и парсинг HTML
                    print("[INFO] Получение содержимого страницы...")
                    html_content = page.content()
                    
                    print("[INFO] Парсинг таблицы...")
                    data = parse_table(html_content)
                    
                    if data:
                        # Шаг 4: Запись данных в файл
                        print(f"[INFO] Найдено полей: {len(data)}")
                        save_to_json(data, output_file)
                        
                        # Вывод ключей для отладки
                        print(f"[INFO] Ключи: {list(data.keys())[:10]}{'...' if len(data) > 10 else ''}")
                    else:
                        print("[WARNING] Нет данных для сохранения")
                    
                    # Ожидание следующего обновления
                    # Можно добавить небольшую задержку, чтобы не нагружать систему
                    time.sleep(1)
                    
                except PlaywrightTimeoutError as e:
                    print(f"[WARNING] Timeout при парсинге: {e}")
                    time.sleep(2)
                    
                except Exception as e:
                    print(f"[ERROR] Ошибка при парсинге: {type(e).__name__}: {e}")
                    time.sleep(2)
                    
    except KeyboardInterrupt:
        print("\n" + "=" * 60)
        print("[INFO] Парсер остановлен пользователем (Ctrl+C)")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n[ERROR] Критическая ошибка: {type(e).__name__}: {e}")
        print("[ERROR] Убедитесь, что Thorium запущен с портом отладки 9222")
        
    finally:
        # Шаг 5: Корректное завершение работы
        print("[INFO] Завершение работы парсера...")
        if playwright:
            playwright.stop()
        print("[INFO] Готово!")


if __name__ == "__main__":
    main()

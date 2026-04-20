# P_W
# 1. Установите зависимости
pip install playwright beautifulsoup4
playwright install

# 2. Запустите Thorium с открытым портом отладки:
"C:\Users\gahar\AppData\Local\Thorium\Application\thorium.exe" --remote-debugging-port=9222

# 3. Авторизуйтесь на сайте и откройте страницу с таблицей

# 4. Запустите парсер:
python markup_parser.py

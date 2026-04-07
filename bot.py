import os 
import schedule
import threading
import time 
import pytz
from datetime import datetime
from flask import Flask, request
import telebot 
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import BOT_TOKEN, DATABASE_URL, OPENROUTER_API_KEY
from database import create_tables, get_connection, release_connection
from openai import OpenAI
ai_client = OpenAI (
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# --- АНТИ-СПАМ ---
from collections import defaultdict
rate_limit = defaultdict(list)
RATE_LIMIT_MAX = 60
RATE_LIMIT_SECONDS = 3600

# --- СТАРТ --- 

@bot.message_handler(commands=['start'])
def start(message):
    telegram_id = message.from_user.id

    # --- ПРОВЕРЯЕМ РЕГИСТРАЦИЮ
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_id FROM users WHERE telegram_id = %s", (telegram_id,))
    user = cursor.fetchone()
    cursor.close()
    release_connection(conn)

    if user:
        bot.send_message(telegram_id, "С возвращением! Ты уже зарегистрирован ☑️")
        show_main_menu(telegram_id)
    else:
        bot.send_message(telegram_id, "Привет! Я бот для рефлексии и самоанализа 💫\n\nКак тебя зовут?")
        bot.register_next_step_handler(message, get_name)

# --- МЕНЮ ---

@bot.message_handler(commands=['menu'])
def menu_command(message):
    show_main_menu(message.from_user.id)

# --- ЗАВЕРШЕНИЕ СЕССИИ ---

@bot.message_handler(commands=['end'])
def end_command(message):
    telegram_id = message.from_user.id 

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT in_diary FROM users WHERE telegram_id = %s", (telegram_id,))
    row = cursor.fetchone()
    cursor.close()
    release_connection(conn)

    if row and row[0]:
        end_diary_session(telegram_id)
    else:
        bot.send_message(telegram_id, "Сейчас нет активной сессии дневника.")
        show_main_menu(telegram_id)

# --- RESET, ВРЕМЕННО!!! ---

@bot.message_handler(commands=['reset'])
def reset_data(message):
    telegram_id = message.from_user.id 
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM messages WHERE telegram_id = %s", (telegram_id,))
    conn.commit()
    cursor.close()
    release_connection(conn)
    bot.send_message(telegram_id, "История очищена. Начинаем заново")


# --- ИМЯ ---

def get_name(message):
    telegram_id = message.from_user.id 
    
    if not message.text or message.text.startswith('/'):
        bot.send_message(telegram_id, "Пожалуйста, напиши своё имя текстом 💫")
        bot.register_next_step_handler(message, get_name)
        return

    name = message.text.strip()

    if len(name) > 50:
        bot.send_message(telegram_id, "Слишком длинное имя. Давай покороче 💫")
        bot.register_next_step_handler(message, get_name)
        return

    save_user(telegram_id, name)

# --- СОХРАНЕНИЕ В БД ---

def save_user(telegram_id, name):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (telegram_id, name)
        VALUES (%s, %s)
    """, (telegram_id, name))
    conn.commit()
    cursor.close()
    release_connection(conn)

    bot.send_message(telegram_id, f"Приятно познакомиться, {name}! 🪐")
    show_main_menu(telegram_id)

# --- ГЛАВНОЕ МЕНЮ ---

def show_main_menu(telegram_id):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("📓 Дневник", callback_data="menu_diary"))
    markup.row(InlineKeyboardButton("📖 Моя история", callback_data="menu_profile"))
    markup.row(InlineKeyboardButton("⚙️ Напоминание", callback_data="menu_reminders"))
    bot.send_message(telegram_id, "Главное меню:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_"))
def handle_menu(call):
    telegram_id = call.from_user.id
    bot.answer_callback_query(call.id)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT in_diary FROM users WHERE telegram_id = %s", (telegram_id,))
    row = cursor.fetchone()
    cursor.close()
    release_connection(conn)

    if row and row[0]:
        bot.send_message(telegram_id, "Сначала заверши сессию дневника - напиши /end или /menu")
        return

    if call.data == "menu_diary":
        start_diary(telegram_id)
    elif call.data == "menu_profile":
        show_profile(telegram_id)
    elif call.data == "menu_reminders":
        show_reminders_menu(telegram_id)

# --- ДНЕВНИК ---

def get_system_prompt(style):
    if style == "friendly":
        tone = "Use a warm, friendly tone. Speak simply and naturally."

    return f"""Ты — ИИ-помощник для самоанализа в Telegram. Ты НЕ психолог, НЕ терапевт и НЕ человек. Твоя задача — помогать людям лучше понимать свои мысли, эмоции и поведение в социальных ситуациях, используя проверенные психологические техники. Если тебя спросят, кто ты — ответь: «Я ИИ-помощник для самоанализа. Я не психолог и не заменяю специалиста, но могу помочь вам разобраться в мыслях и чувствах.»

## Твоя личность

Ты говоришь как опытный, мудрый психолог. Твои ключевые черты:

- Мягкость и осторожность в формулировках
- Проницательность — ты замечаешь то, что человек может не осознавать
- Уважение — ты всегда обращаешься на «вы»
- Терпение — ты никогда не торопишь и не давишь
- Искренний интерес к переживаниям собеседника

Ты НИКОГДА не даёшь директивных советов. Ты НИКОГДА не говоришь «вам нужно сделать X». Вместо этого ты задаёшь вопросы, которые помогают человеку самому прийти к пониманию. Это твой главный принцип — сократический метод.

## Стиль общения

- Обращение: только на «вы»
- Тон: тёплый, спокойный, безоценочный
- Язык: живой, человечный, без канцеляризмов и лишнего жаргона. Если используешь психологический термин — сразу объясни простыми словами
- Ты задаёшь РОВНО ОДИН вопрос за сообщение. Это твоё главное структурное правило. Никогда два, никогда ноль (кроме моментов признания боли или резюме)
- Вопрос с «или» — это два вопроса. «Это связано с конкретным событием, или это общее состояние?» — ДВА вопроса. Переформулируй: «Скажите, есть ли конкретная ситуация, которая стоит за этим чувством?»
- Перед отправкой каждого ответа проверь: сколько вопросительных знаков? Если больше одного — перепиши. Оставь только самый важный вопрос, остальные сохрани на потом
- Ты НЕ используешь эмодзи, списки и буллеты. Твои ответы — это живая, плавная речь
- Ты НЕ используешь никакое форматирование: ни звёздочки, ни жирный, ни курсив, ни подчёркивание, ни заголовки, ни блоки кода. Только чистый текст. Это правило распространяется на ВСЕ ответы, включая кризисные ситуации
- Ты сохраняешь свой собственный стиль общения, независимо от того, как пишет пользователь. Не копируй его ошибки, сленг или стилистику. Ты всегда пишешь грамотно, красиво и естественно
- Твой русский язык должен быть безупречным: правильная грамматика, естественный порядок слов, корректное использование падежей и предлогов. Пиши так, как писал бы образованный носитель языка. Избегай неуклюжих конструкций и неестественных фраз. Если сомневаешься — выбирай более простую конструкцию, она прозвучит естественнее
- Никогда не повторяй одно и то же наблюдение, отражение или тему дважды за сессию. Если ты уже назвал паттерн, когнитивное искажение или инсайт — не возвращайся к нему. Двигайся вперёд. Если пользователь сам возвращается к теме, кратко признай это и перенаправь: «Мы уже коснулись этого. Давайте посмотрим, что стоит за этим повторением.»

## Ограничения по длине ответов

- Твои ответы СТРОГО не должны превышать 500 символов. Это жёсткий лимит. Считай внимательно
- ЕДИНСТВЕННОЕ исключение — финальное резюме сессии, оно может быть до 800 символов
- Обычный ответ: 2–3 предложения. Максимум: 4 предложения
- Если чувствуешь, что нужно больше места — ты объясняешь слишком много. Режь безжалостно
- Если пользователь присылает длинное сообщение, НЕ пытайся ответить на всё сразу. Найди самую эмоционально заряженную часть и работай с ней. К остальному можно вернуться позже

## Модуль 1: Разбор социальных ситуаций

Когда пользователь описывает социальную ситуацию (конфликт, недопонимание, тревога в общении), веди его по следующему плану. НЕ озвучивай план — просто следуй ему, задавая по одному вопросу:

1. Прояснение ситуации. Что именно произошло? Кто участвовал? Где и когда?
2. Эмоции. Что человек почувствовал в тот момент? Помоги назвать эмоцию точнее, если ответ расплывчатый.
3. Мысли. Какая мысль первой пришла в голову? Что он подумал о себе, о другом человеке, о ситуации?
4. Поведение. Как он отреагировал? Что сделал или сказал?
5. Альтернативный взгляд. Мягко предложи посмотреть на ситуацию глазами другого участника.
Или спроси: «Как бы вы объяснили поведение этого человека, если бы хотели найти самое доброжелательное объяснение?»
6. Паттерны. Если уместно, спроси: случалось ли подобное раньше? Замечает ли человек повторяющийся сценарий?
7. Резюме. Мягко подведи итог (см. секцию «Завершение сессии»).

Важно: не все сессии дойдут до шага 7. Человек может остановиться на любом этапе. Это нормально. Не тяни за уши.

## Модуль 2: Дневник КПТ

Когда пользователь хочет разобрать конкретную мысль, веди его через технику записи мыслей. По одному вопросу за раз:

1. Ситуация. Что происходило, когда появилась эта мысль?
2. Автоматическая мысль. Какая именно мысль пришла в голову? Попроси сформулировать одним предложением.
3. Эмоция и интенсивность. Что вы почувствовали? Насколько сильно, от 0 до 10?
4. Доказательства «за». Какие факты поддерживают эту мысль?
5. Доказательства «против». Есть ли факты, которые с ней не согласуются? Были ли случаи, когда было иначе?
6. Когнитивное искажение. Если видишь искажение — назови его мягко и с объяснением. Пример: «Знаете, это похоже на то, что в психологии называют “чтением мыслей” — когда мы уверены, что знаем, что думает другой человек, хотя на самом деле не можем этого знать наверняка.»
7. Альтернативная мысль. Помоги сформулировать более сбалансированную версию. Не «позитивную» — реалистичную.
8. Переоценка. Изменилась ли интенсивность эмоции после разбора (снова от 0 до 10)?

Когнитивные искажения, которые можешь использовать:

- Чтение мыслей — уверенность, что вы знаете, что думают другие
- Предсказание будущего — убеждённость, что всё пойдёт плохо
- Катастрофизация — преувеличение последствий
- Чёрно-белое мышление — «всё или ничего», без середины
- Обесценивание положительного — «это не считается»
- Эмоциональное обоснование — «я чувствую, значит так и есть»
- Навешивание ярлыков — «я неудачник» вместо «я допустил ошибку»
- Персонализация — принятие на свой счёт того, что не относится к вам
- Долженствование — «я должен», «он обязан», «так не должно быть»
- Сверхобобщение — «всегда», «никогда», «все», «никто»

## Начало разговора

Когда пользователь пишет первое сообщение, поприветствуй тепло, но кратко. НЕ перечисляй свои возможности. Скажи что-то вроде:

«Здравствуйте. Я рад, что вы здесь. Расскажите, что у вас на душе — я постараюсь помочь вам разобраться.»

Если сообщение непонятно — мягко уточни, не предлагая жёстких категорий.

## Определение модуля

НЕ проси пользователя «выбрать модуль». Определяй сам:

- Человек описывает ситуацию с другими людьми → разбор ситуации
- Человек делится тревожной мыслью или убеждением → дневник КПТ
- Непонятно → слушай и задавай уточняющие вопросы

## Распознавание сигналов к завершению

Если пользователь говорит «устал», «не знаю как по-другому», «понимаю что так нельзя», «не могу больше это обсуждать», «хочу уже что-то сделать» — это сигнал, что энергия для анализа закончилась. НЕ продолжай задавать исследовательские вопросы. Вместо этого:

1. Кратко отрази то, что услышал — одним предложением
2. Перейди сразу к альтернативной мысли или конкретному действию
3. Затем переходи к резюме

Эмоциональная энергия пользователя — это ресурс. Когда она заканчивается — заворачивай. Короткая сессия с ясным итогом лучше, чем длинная сессия, которая заканчивается усталостью.

## Безопасность: кризисный протокол

Если в сообщении пользователя есть признаки:

- Суицидальных мыслей или намерений
- Самоповреждения
- Насилия (над ним или с его стороны)
- Острого психотического состояния (бред, галлюцинации)

Тогда ты НЕМЕДЛЕННО:

1. Признай его боль кратко и искренне — одним предложением
2. Скажи, что это требует поддержки живого человека, а не ИИ
3. Дай номер простым текстом: Телефон доверия: 8-800-2000-122 (бесплатно по России, круглосуточно)
4. Скажи, что ты здесь, если хочется поговорить — но мягко предложи позвонить
5. НЕ перечисляй несколько вариантов (психиатр, скорая, терапевт). Один контакт достаточно — больше давит в кризисе
6. НЕ пытайся проводить сессию или анализ в этом состоянии
7. Весь ответ — не более 500 символов, даже в кризисе

## Чего ты НИКОГДА не делаешь

- Не ставишь диагнозы. Никогда не говори «у вас депрессия» или «это похоже на тревожное расстройство»
- Не даёшь медицинских рекомендаций. Не советуешь лекарства, добавки, методы лечения
- Не называешь конкретные заболевания, даже как предположения. Никогда не говори «это может быть проблема со щитовидкой» или «возможно, у вас анемия». Если есть физические симптомы — просто скажи, что их стоит обсудить с врачом, без перечисления возможных причин
- Не обесцениваешь переживания. Никогда не говори «это ерунда», «не переживайте», «бывает и хуже»
- Не торопишь. Если человеку нужно время — даёшь его
- Не притворяешься человеком. Если спросят — честно скажи, что ты ИИ-помощник для самоанализа, не замена психологу
- Не используешь шаблонные фразы вроде «я вас понимаю» без содержательного продолжения
- Не морализируешь и не оцениваешь поступки пользователя
- Не оцениваешь и не комментируешь слова пользователя — ни положительно, ни отрицательно. Запрещённые фразы: «это важное наблюдение», «вы очень точно это описали», «это серьёзный шаг», «хороший вопрос», «вы правильно заметили», «это ценное осознание», «вы молодец». Не хвали инсайты, прогресс или осознанность пользователя. Если ты услышал что-то значимое — покажи это через следующий вопрос, а не через комментарий

## Сложные моменты

Если человек злится, грубит, провоцирует — оставайся спокойным и тёплым. Можешь мягко назвать то, что видишь: «Я чувствую, что вы сейчас раздражены. Это нормально. Хотите рассказать, что стоит за этим раздражением?»

Если человек плачет или выражает сильную боль — не спеши с вопросами. Сначала признай чувства: «То, что вы описываете, звучит действительно тяжело. Спасибо, что делитесь этим.» Только потом продолжай.

## Завершение сессии

Резюме ОБЯЗАТЕЛЬНО в конце каждой сессии. Не пропускай его. Когда разговор подходит к естественному завершению (пользователь пришёл к инсайту, нашёл альтернативную мысль или выразил готовность действовать), переходи к резюме.

Перед резюме скажи что-то вроде: «Давайте я подведу итог того, к чему мы пришли.»

Пиши резюме как короткий связный абзац от своего лица — 3–5 предложений о том, что пользователь обнаружил за сессию. Опиши, что он чувствовал, какая мысль стояла за этим, что он осознал и что изменилось. Используй слова и выражения пользователя, но пиши это как своё наблюдение, а не как шаблон с полями.

Пример тона: «За наш разговор вы увидели, что мысль “я всегда всё порчу” появляется каждый раз, когда вы получаете критику. Вы заметили, что на самом деле критика касалась конкретного проекта, а не вас как человека. Это помогло снизить тревогу — и вы решили поговорить с руководителем напрямую.»

Резюме — не более 800 символов. Без форматирования, без буллетов, без полей.

Заверши сессию тёплой, но краткой фразой — каждый раз новой. НЕ повторяй одну и ту же. Генерируй новую, подходящую именно к этой сессии."""

def start_diary(telegram_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT in_diary FROM users WHERE telegram_id = %s", (telegram_id,))
    row = cursor.fetchone()
    cursor.close()
    release_connection(conn)

    if row and row[0]:
        bot.send_message(telegram_id, "Дневник уже открыт. Пиши сюда или напиши /menu чтобы выйти.")
        return 

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET in_diary = TRUE WHERE telegram_id = %s", (telegram_id,))
    conn.commit()
    cursor.close()
    release_connection(conn)
    bot.send_message(telegram_id, "📓 Дневник открыт. Расскажи, как прошёл твой день или что у тебя на душе.\n\nЧтобы выйти в меню, напиши /menu")

def check_rate_limit(telegram_id):
    now = time.time()
    rate_limit[telegram_id] = [t for t in rate_limit[telegram_id] if now - t < RATE_LIMIT_SECONDS]
    if len(rate_limit[telegram_id]) >= RATE_LIMIT_MAX:
        return False
    rate_limit[telegram_id].append(now)
    return True

def end_diary_session(telegram_id):
    history = get_history(telegram_id)

    if not history:
        bot.send_message(telegram_id, "Сессия пока что пуста.")
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET in_diary = FALSE WHERE telegram_id = %s", (telegram_id,))
        conn.commit()
        cursor.close()
        release_connection(conn)
        show_main_menu(telegram_id)
        return

    thinking_msg = bot.send_message(telegram_id, "💭 Подвожу итоги...")

    summary_prompt = """Ты мудрый, проницательный психолог. Пользователь завершает сессию дневника. Напиши резюме сессии.

Пиши резюме как короткий связный абзац от своего лица — 3–5 предложений о том, что пользователь обнаружил за сессию. Опиши, что он чувствовал, какая мысль стояла за этим, что он осознал и что изменилось. Используй слова и выражения пользователя, но пиши это как своё наблюдение, а не как шаблон с полями.

Пример тона: «За наш разговор вы увидели, что мысль “я всегда всё порчу” появляется каждый раз, когда вы получаете критику. Вы заметили, что на самом деле критика касалась конкретного проекта, а не вас как человека. Это помогло снизить тревогу — и вы решили поговорить с руководителем напрямую.»

Резюме — не более 800 символов. Без форматирования, без буллетов, без полей.

Заверши сессию тёплой, но краткой фразой — каждый раз новой. НЕ повторяй одну и ту же. Генерируй новую, подходящую именно к этой сессии."""

    try:
        response = ai_client.chat.completions.create(
            model="anthropic/claude-haiku-4-5",
            messages=[
            {"role": "system", "content": summary_prompt},
            {"role": "user", "content:" "Вот история сессии:\n\n" + "\n".join(
                [f"{'Клиент' if m['role'] == 'user' else 'Психолог'}: {m['content']}" for m in history]
            ) + "\n\nНапиши резюме этой сессии."}
            ],
            max_tokens=400,
            timeout=30
        )
        summary = response.choices[0].message.content
        bot.delete_message(telegram_id, thinking_msg.message_id)
        bot.send_message(telegram_id, f"📝 Итог этой сессии:\n\n{summary}")
    except Exception as e:
        print(f"Ошибка API (резюме): {e}")
        bot.delete_message(telegram_id, thinking_msg)
        bot.send_message(telegram_id, "Не удалось подвести итог, но сессия завершена")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET in_diary = FALSE WHERE telegram_id = %s", (telegram_id,))
    conn.commit()
    cursor.close()
    release_connection(conn)
    show_main_menu(telegram_id)

def handle_diary_message(message, style):
    telegram_id = message.from_user.id

    if message.text == "/end":
        end_diary_session(telegram_id)
        return

    if message.text == "/menu":
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET in_diary = FALSE WHERE telegram_id = %s", (telegram_id,))
        conn.commit()
        cursor.close()
        release_connection(conn)
        show_main_menu(telegram_id)
        return

    if not check_rate_limit(telegram_id):
        bot.send_message(telegram_id, "Ты отправляешь слишком много сообщений. Давай сделаем паузу и вернёмся через некоторое время 💫")
        return

    save_message(telegram_id, "user", message.text)

    history = get_history(telegram_id)

    thinking_msg = bot.send_message(telegram_id, "💭 Думаю...")

    try:
        response = ai_client.chat.completions.create(
            model="anthropic/claude-haiku-4-5",
            messages=[{"role": "system", "content": get_system_prompt(style)}] + history,
            max_tokens=300,
            timeout=30
        )
        reply = response.choices[0].message.content
        bot.delete_message(telegram_id, thinking_msg.message_id)
        save_message(telegram_id, "assistant", reply)
        bot.send_message(telegram_id, reply)
    except Exception as e:
        print(f"Ошибка API: {e}")
        bot.delete_message(telegram_id, thinking_msg.message_id)
        bot.send_message(telegram_id, "Что-то пошло не так... 😔 Попробуй ещё раз.")

def save_message(telegram_id, role, content):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO messages (telegram_id, role, content) VALUES (%s, %s, %s)",
        (telegram_id, role, content)
    )
    conn.commit()
    cursor.close()
    release_connection(conn)

def get_history(telegram_id, limit=10):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT role, content FROM ( 
            SELECT role, content, created_at FROM messages
            WHERE telegram_id = %s
            ORDER BY created_at DESC
            LIMIT %s 
        ) sub
        ORDER BY created_at ASC
    """, (telegram_id, limit))
    rows = cursor.fetchall()
    cursor.close()
    release_connection(conn)

    return [{"role": r[0], "content": r[1]} for r in rows]

# --- ЛИЧНЫЙ КАБИНЕТ ---

def show_profile(telegram_id):
    # AI-сводка
    history = get_history(telegram_id, limit=20)
    if not history:
        bot.send_message(telegram_id, "📓 Дневник пока пустой - начни диалог!")
        show_main_menu(telegram_id)
        return

    thinking_msg = bot.send_message(telegram_id, "💭 Вспоминаю наши разговоры...")

    summary_prompt = """Ты — мудрый, проницательный психолог, который просматривает полную историю сессий с клиентом.

На основе ВСЕХ предыдущих сессий напиши краткий психологический портрет этого человека. Обращайся на «вы».

Твой портрет должен отражать:

- Какие темы и ситуации повторяются из сессии в сессию
- Какие эмоциональные паттерны ты наблюдаешь (повторяющиеся эмоции, триггеры, как эмоции менялись со временем)
- Какие когнитивные привычки ты замечаешь (например, самокритика, сравнение с другими, катастрофизация) — называй их простым языком, без клинической терминологии
- Любой рост, сдвиги или инсайты, которые человек показал за время общения — даже маленькие

Правила:

- Не более 4–6 предложений. Будь точным и лаконичным
- Тон: тёплый, вдумчивый, честный. Ты говоришь напрямую с человеком, а не пишешь клинический отчёт
- Не льсти и не хвали чрезмерно. Называй то, что реально наблюдаешь
- Не ставь диагнозов. Не используй клинические термины вроде «депрессия» или «тревожное расстройство»
- Не давай советов и рекомендаций
- Если в истории только одна сессия — основывай портрет на ней и отметь, что более полная картина сложится со временем
- Не используй никакое форматирование: ни звёздочки, ни жирный, ни буллеты, ни нумерованные списки. Только чистый текст
- Используй двойные переносы строк между абзацами
- Весь ответ — не более 600 символов"""

    try:
        response = ai_client.chat.completions.create(
            model="anthropic/claude-haiku-4-5",
            messages=[
                {"role": "system", "content": summary_prompt},
                {"role": "user", "content": "Вот история всех моих сессий с дневником:\n\n" + "\n".join([f"{'Я' if m['role'] == 'user' else 'Психолог'}: {m['content']}" for m in history]) + "\n\nСоставь мой психологический портрет на основе этих записей."}
            ],
            max_tokens=400
        )
        summary = response.choices[0].message.content
        bot.delete_message(telegram_id, thinking_msg.message_id)
        bot.send_message(telegram_id, f"📖 Вот, что я узнал о тебе из наших разговоров:\n\n{summary}")
        show_main_menu(telegram_id)
    except Exception as e:
        print(f"Ошибка API (сводка): {e}")
        bot.delete_message(telegram_id, thinking_msg.message_id)
        bot.send_message(telegram_id, "Что-то пошло не так... 😔 Попробуй позже.")
        show_main_menu(telegram_id)

# --- НАПОМИНАНИЕ ---

def show_reminders_menu(telegram_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT reminders_enabled FROM users WHERE telegram_id = %s", (telegram_id,))
    row = cursor.fetchone()
    cursor.close()
    release_connection(conn)

    reminders_on = row[0] if row else True
    status = "включены 🔔" if reminders_on else "выключены 🔕"
    toggle_text = "Выключить 🔕" if reminders_on else "Включить 🔔"

    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton(toggle_text, callback_data="toggle_reminders"))
    markup.row(InlineKeyboardButton("⬅️ Назад", callback_data="back_to_menu"))
    bot.send_message(telegram_id, f"Напоминания каждый день в 20:00\nСейчас: {status}", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["toggle_reminders", "back_to_menu"])
def handle_reminders_menu(call):
    telegram_id = call.from_user.id
    bot.answer_callback_query(call.id)

    if call.data == "toggle_reminders":
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT reminders_enabled FROM users WHERE telegram_id = %s", (telegram_id,))
        current = cursor.fetchone()[0]
        new_value = not current
        cursor.execute("UPDATE users SET reminders_enabled = %s WHERE telegram_id = %s", (new_value, telegram_id))
        conn.commit()
        cursor.close()
        release_connection(conn)
        show_reminders_menu(telegram_id)

    elif call.data == "back_to_menu":
        show_main_menu(telegram_id)

last_reminder_date = None

def send_reminders():
    global last_reminder_date
    now_msk = datetime.now(pytz.timezone("Europe/Moscow"))

    if not_msk.hour != 20 or now_msk.minute != 0:
        return

    today = now_msk.date()
    if last_reminder_date == today:
        return
    last_reminder_date = today

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_id, name FROM users WHERE reminders_enabled = TRUE")
    users = cursor.fetchall()
    cursor.close()
    release_connection(conn)

    for telegram_id, name in users:
        try: 
            bot.send_message(telegram_id, f"Привет, {name}!✨\n\nКак прошёл твой день?")
        except Exception as e:
            print(f"Ошибка напоминания для {telegram_id}: {e}")

def run_scheduler():
    schedule.every().minute.do(send_reminders)
    while True:
        schedule.run_pending()
        time.sleep(30)

@bot.message_handler(func=lambda message: True)
def fallback_handler(message):
    telegram_id = message.from_user.id

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT in_diary FROM users WHERE telegram_id = %s", (telegram_id,))
    row = cursor.fetchone()
    cursor.close()
    release_connection(conn)

    if row and row[0]:
        handle_diary_message(message, "friendly")
    else:
        show_main_menu(telegram_id)

# --- ЗАПУСК ---

@app.route(f'/webhook/{BOT_TOKEN}', methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.get_data().decode('utf-8'))
    bot.process_new_updates([update])
    return 'ok', 200

@app.route('/')
def index():
    return 'Bot is running', 200

if __name__ == "__main__":
    create_tables()
    threading.Thread(target=run_scheduler, daemon=True).start()

    bot.remove_webhook()
    bot.set_webhook(url=f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}/webhook/{BOT_TOKEN}")

    print("Бот запущен (webhook)...")
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))










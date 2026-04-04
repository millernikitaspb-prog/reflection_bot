import os
import schedule
import threading
import time 
from datetime import datetime
import telebot 
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import BOT_TOKEN, DATABASE_URL, OPENROUTER_API_KEY
from database import create_tables, get_connection
import re
from openai import OpenAI
groq_client = OpenAI (
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

bot = telebot.TeleBot(BOT_TOKEN)

# временное хранилище 
user_data = {}

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
    conn.close()

    if user:
        bot.send_message(telegram_id, "С возвращением! Ты уже зарегистрирован ☑️")
        show_main_menu(telegram_id)
    else:
        user_data[telegram_id] = {}
        bot.send_message(telegram_id, "Привет! Я бот для рефлексии и самоанализа 🌿\n\nКак тебя зовут?")
        bot.register_next_step_handler(message, get_name)

# --- МЕНЮ ---

@bot.message_handler(commands=['menu'])
def menu_command(message):
    show_main_menu(message.from_user.id)

# --- ИМЯ ---

def get_name(message):
    telegram_id = message.from_user.id 
    user_data[telegram_id]['name'] = message.text 

    bot.send_message(telegram_id, f"Приятно познакомиться, {message.text}! Сколько тебе лет?")
    bot.register_next_step_handler(message, get_age)

# --- ВОЗРАСТ ---

def get_age(message):
    telegram_id = message.from_user.id 

    if not message.text.isdigit():
        bot.send_message(telegram_id, "Пожалуйста, введи число")
        bot.register_next_step_handler(message, get_age)
        return

    user_data[telegram_id]['age'] = int(message.text)

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("Дружески 😊", callback_data="style_friendly"),
        InlineKeyboardButton("Официально 🎩", callback_data="style_formal")
    )
    bot.send_message(telegram_id, "Как тебе комфортнее общаться?", reply_markup=markup)

# --- СТИЛЬ ОБЩЕНИЯ ---

@bot.callback_query_handler(func=lambda call: call.data.startswith("style_"))
def get_style(call):
    telegram_id = call.from_user.id 

    style = "friendly" if call.data == "style_friendly" else "formal"
    user_data[telegram_id]['style'] = style

    bot.answer_callback_query(call.id)
    
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("Калининград (UTC+2)", callback_data="tz_Europe/Kaliningrad"),
    )
    markup.row(
        InlineKeyboardButton("Москва (UTC+3)", callback_data="tz_Europe/Moscow"),
    )
    markup.row(
        InlineKeyboardButton("Самара (UTC+4)", callback_data="tz_Europe/Samara"),
    )
    markup.row(
        InlineKeyboardButton("Екатеринбург (UTC+5)", callback_data="tz_Asia/Yekaterinburg"),
    )
    markup.row(
        InlineKeyboardButton("Омск (UTC+6)", callback_data="tz_Asia/Omsk"),
    )
    markup.row(
        InlineKeyboardButton("Красноярск (UTC+7)", callback_data="tz_Asia/Krasnoyarsk"),
    )
    markup.row(
        InlineKeyboardButton("Иркутск (UTC+8)", callback_data="tz_Asia/Irkutsk"),
    )
    markup.row(
        InlineKeyboardButton("Якутск (UTC+9)", callback_data="tz_Asia/Yakutsk"),
    )
    markup.row(
        InlineKeyboardButton("Владивосток (UTC+10)", callback_data="tz_Asia/Vladivostok"),
    )
    markup.row(
        InlineKeyboardButton("Магадан (UTC+11)", callback_data="tz_Asia/Magadan"),
    )
    markup.row(
        InlineKeyboardButton("Камчатка (UTC+12)", callback_data="tz_Asia/Kamchatka"),
    )
    bot.send_message(telegram_id, "В каком часовом поясе ты находишься?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("tz_"))
def get_timezone(call):
    telegram_id = call.from_user.id 

    timezone = call.data.replace("tz_", "")
    user_data[telegram_id]['timezone'] = timezone

    bot.answer_callback_query(call.id)
    bot.send_message(telegram_id, "В какое время напоминать тебе об отметке настроения?\n\nНапиши в формате ЧЧ:ММ, например: 20:00")
    bot.register_next_step_handler(call.message, get_reminder_time)

# --- ВРЕМЯ НАПОМИНАНИЯ ---

def get_reminder_time(message):
    telegram_id = message.from_user.id 
    time_text = message.text.strip()

    # Проверка формата 
    parts = time_text.split(":")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        bot.send_message(telegram_id, "Неверный формат. Попробуй ещё раз, например: 20:00")
        bot.register_next_step_handler(message, get_reminder_time)
        return

    user_data[telegram_id]['reminder_time'] = time_text

    save_user(telegram_id)

# --- СОХРАНЕНИЕ В БД ---

def save_user(telegram_id):
    data = user_data[telegram_id]

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (telegram_id, name, age, style, reminder_time, timezone)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (telegram_id, data['name'], data['age'], data['style'], data['reminder_time'], data['timezone']))
    conn.commit()
    cursor.close()
    conn.close()

    del user_data[telegram_id]

    name = data['name']
    bot.send_message(telegram_id, f"Всё готово, {name}! 🎉\n\nРегистрация завершена.")
    show_main_menu(telegram_id)

# --- ГЛАВНОЕ МЕНЮ ---

def show_main_menu(telegram_id):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("📓 Дневник", callback_data="menu_diary"))
    markup.row(InlineKeyboardButton("😊 Настроение", callback_data="menu_mood"))
    markup.row(InlineKeyboardButton("👤 Личный кабинет", callback_data="menu_profile"))
    bot.send_message(telegram_id, "Главное меню:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_"))
def handle_menu(call):
    telegram_id = call.from_user.id
    bot.answer_callback_query(call.id)

    if call.data == "menu_diary":
        start_diary(telegram_id)
    elif call.data == "menu_mood":
        show_mood_menu(telegram_id)
    elif call.data == "menu_profile":
        show_profile(telegram_id)

# --- НАСТРОЕНИЕ ---

def show_mood_menu(telegram_id):
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("1 😣", callback_data="mood_1"),
        InlineKeyboardButton("2 🙁", callback_data="mood_2"),
        InlineKeyboardButton("3 😐", callback_data="mood_3"),
        InlineKeyboardButton("4 🙂", callback_data="mood_4"),
        InlineKeyboardButton("5 😄", callback_data="mood_5")
    )
    bot.send_message(telegram_id, "Как ты себя чувствуешь сегодня?\n\n1 - очень плохо, 5 - отлично", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("mood_"))
def handle_mood(call):
    telegram_id = call.from_user.id
    score = int(call.data.split("_")[1])

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO moods (telegram_id, score) VALUES (%s, %s)",
        (telegram_id, score)
    )
    conn.commit()
    cursor.close()
    conn.close()

    bot.answer_callback_query(call.id)

    response = {
        1: "Мне жаль 😣 Надеюсь, завтра будет лучше.",
        2: "Непростой день 🙁 Ты справляешься.",
        3: "Средне 😐 Бывает и лучше и хуже.",
        4: "Хорошо 🙂 Приятно слышать!",
        5: "отлично 😄 Так держать!"
    }

    bot.send_message(telegram_id, f"Настроение {score}/5 сохранено!\n\n{response[score]}")
    show_main_menu(telegram_id)

# --- ДНЕВНИК ---

def get_system_prompt(style):
    if style == "friendly":
        tone = "Use a warm, friendly tone. Speak simply and naturally."
    else:
        tone = "Use a polite and reserved tone. Speak formally."

    return f"""You are a personal diary assistant for reflection and self-analysis.
{tone} 
Your goal is to help the user reflect on their thoughts, feelings and daily events.
Ask deep but gentle questions. Do not give advice unless explicitly asked.
Keep responses short - 2 to 4 sentences.
Always respond in Russian, regardless of the langusge the user writes in.
Do not use any markdown formatting, no asterisks, no bold, no bullet points. Plain text only.
Use double line breaks between paragraphs."""

def clean_response(text):
    if not text:
        return ""
    text = re.sub(r'[a-zA-Z]{4,}', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def start_diary(telegram_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT style FROM users WHERE telegram_id = %s", (telegram_id,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    style = user[0] if user else "friendly"
    bot.send_message(telegram_id, "📓 Дневник открыт. Расскажи, как прошёл твой день или что у тебя на душе.\n\nЧтобы выйти в меню, напиши /menu")
    bot.register_next_step_handler_by_chat_id(telegram_id, lambda m: handle_diary_message(m, style))

def handle_diary_message(message, style):
    telegram_id = message.from_user.id

    if message.text == "/menu":
        show_main_menu(telegram_id)
        return

    save_message(telegram_id, "user", message.text)

    history = get_history(telegram_id)

    thinking_msg = bot.send_message(telegram_id, "💭 Думаю...")

    try:
        response = groq_client.chat.completions.create(
            model="anthropic/claude-haiku-4-5",
            messages=[{"role": "system", "content": get_system_prompt(style)}] + history,
            max_tokens=300,
            timeout=30
        )
        reply = response.choices[0].message.content
        bot.delete_message(telegram_id, thinking_msg.message_id)
        save_message(telegram_id, "assistant", reply)
        bot.send_message(telegram_id, reply)
        bot.register_next_step_handler_by_chat_id(telegram_id, lambda m: handle_diary_message(m, style))
    except Exception as e:
        print(f"Ошибка API: {e}")
        bot.delete_message(telegram_id, thinking_msg.message_id)
        bot.send_message(telegram_id, "Что-то пошло не так 😔 Попробуй ещё раз.")
        bot.register_next_step_handler_by_chat_id(telegram_id, lambda m: handle_diary_message(m, style))

def save_message(telegram_id, role, content):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO messages (telegram_id, role, content) VALUES (%s, %s, %s)",
        (telegram_id, role, content)
    )
    conn.commit()
    cursor.close()
    conn.close()

def get_history(telegram_id, limit=10):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT role, content FROM messages 
        WHERE telegram_id = %s
        ORDER BY created_at DESC
        LIMIT %s 
    """, (telegram_id, limit))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

# --- ЛИЧНЫЙ КАБИНЕТ ---

def show_profile(telegram_id):
    # История настроений 
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT score, created_at FROM moods
        WHERE telegram_id =%s
        ORDER BY created_at DESC
        LIMIT 7
    """, (telegram_id,))
    moods = cursor.fetchall()
    cursor.close()
    conn.close()

    if not moods:
        mood_text = "Ты ещё не отмечал настроение 😣"
    else:
        emoji_map = {1: "😣", 2: "🙁", 3: "😐", 4: "🙂", 5: "😄"}

        lines = []
        for score, data in moods:
            day = data.strftime("%d.%m")
            lines.append(f"{day} - {score}/5{emoji_map[score]}")
        mood_text = "📊 Настроение за последние дни:\n\n" + "\n".join(lines)

    bot.send_message(telegram_id, mood_text)

    # AI-сводка
    history = get_history(telegram_id, limit=20)
    if not history:
        bot.send_message(telegram_id, "📓 Дневник пока пустой - начни диалог!")
        show_main_menu(telegram_id)
        return

    thinking_msg = bot.send_message(telegram_id, "💭 Готовлю сводку...")

    summary_prompt = """You are an assistant that analyzes a user's diary entries.
Based on the conversation history, write a short summary in Russian (3-5 sentences):
- What topics the user reflected on
- What emotions were present
- Any positive patterns or progress you notice
Be warm and supportive. Always respond in Russian. 
Do not use any markdown formatting, no asterisks, no bold, no bullet points. Plain text only.
Use double line breaks between paragraphs."""

    response = groq_client.chat.completions.create(
        model="anthropic/claude-haiku-4-5",
        messages=[
            {"role": "system", "content": summary_prompt}
        ] + history + [
            {"role": "user", "content": "Сделай сводку моих записей в дневнике"}
        ],
        max_tokens=400
    )

    summary = response.choices[0].message.content
    bot.delete_message(telegram_id, thinking_msg.message_id)
    bot.send_message(telegram_id, f"🧠 Сводка по дневнику:\n\n{summary}", parse_mode='Markdown')
    show_main_menu(telegram_id)

def send_reminders():
    import pytz
    now_utc = datetime.now(pytz.utc)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_id, name, reminder_time, timezone FROM users")
    users = cursor.fetchall()
    cursor.close()
    conn.close()

    for telegram_id, name, reminder_time, timezone in users:
        try:
            tz = pytz.timezone(timezone or "Europe/Moscow")
            now_local = now_utc.astimezone(tz).strftime("%H:%M")

            if now_local == reminder_time:
                bot.send_message(telegram_id, f"Привет!, {name}!🌿\n\nНе забудь отметить настроение сегодня.")
                show_mood_menu(telegram_id)
        except Exception as e:
            print(f"Ошибка напоминания для {telegram_id}: {e}")

def run_scheduler():
    schedule.every().minute.do(send_reminders)
    while True:
        schedule.run_pending()
        time.sleep(30)

# --- ЗАПУСК ---

if __name__ == "__main__":
    create_tables()
    threading.Thread(target=run_scheduler, daemon=True).start()
    print("Бот запущен...")
    bot.polling()














import os
import asyncio
import pandas as pd
from datetime import datetime
import hashlib
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from cryptography.fernet import Fernet

# Загрузка переменных окружения
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

# Создаем папку data, если её нет
os.makedirs("data", exist_ok=True)

# Настройка шифрования
KEY_FILE = "data/secret.key"
ENCRYPTED_EXCEL = "data/students_encrypted.dat"

def get_or_create_key():
    if not os.path.exists(KEY_FILE):
        key = Fernet.generate_key()
        with open(KEY_FILE, "wb") as key_file:
            key_file.write(key)
    with open(KEY_FILE, "rb") as key_file:
        return key_file.read()

fernet = Fernet(get_or_create_key())

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Машина состояний (FSM)
class StarostaState(StatesGroup):
    auth = State()
    main_menu = State()
    waiting_for_subject = State()
    attendance_process = State()

# --- Хелперы для шифрования ---
def encrypt_file(file_data: bytes):
    return fernet.encrypt(file_data)

def decrypt_file():
    if not os.path.exists(ENCRYPTED_EXCEL):
        return None
    with open(ENCRYPTED_EXCEL, "rb") as f:
        encrypted_data = f.read()
    return fernet.decrypt(encrypted_data)

# --- Клавиатуры ---
def get_main_keyboard():
    kb = [
        [types.KeyboardButton(text="📋 Начать перекличку")],
        [types.KeyboardButton(text="📁 Загрузить список (Excel)")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_attendance_keyboard():
    kb = [
        [
            InlineKeyboardButton(text="✅ Присутствует", callback_data="att_yes"),
            InlineKeyboardButton(text="❌ Отсутствует", callback_data="att_no")
        ],
        [InlineKeyboardButton(text="🤒 Уважительная/Болеет", callback_data="att_excused")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

# --- Обработчики ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await message.answer("🔒 Введите пароль для доступа к функционалу старосты:")
    await state.set_state(StarostaState.auth)

@dp.message(StarostaState.auth)
async def check_password(message: types.Message, state: FSMContext):
    input_hash = hashlib.sha256(message.text.encode()).hexdigest()
    correct_hash = hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest()
    
    if input_hash == correct_hash:
        await message.answer("✅ Доступ разрешен! Выберите действие:", reply_markup=get_main_keyboard())
        await state.set_state(StarostaState.main_menu)
        await message.delete()
    else:
        await message.answer("❌ Неверный пароль. Попробуйте снова.")

@dp.message(F.text == "📁 Загрузить список (Excel)", StarostaState.main_menu)
async def request_excel(message: types.Message):
    await message.answer("Отправьте мне файл Excel (.xlsx).\nВ файле должна быть первая строка с заголовком **ФИО**.")

@dp.message(F.document, StarostaState.main_menu)
async def handle_document(message: types.Message, bot: Bot):
    if not message.document.file_name.endswith('.xlsx'):
        await message.answer("❌ Пожалуйста, отправьте файл формата .xlsx")
        return
    
    file_id = message.document.file_id
    file = await bot.get_file(file_id)
    file_data = await bot.download_file(file.file_path)
    
    encrypted_data = encrypt_file(file_data.read())
    with open(ENCRYPTED_EXCEL, "wb") as f:
        f.write(encrypted_data)
        
    await message.answer("✅ Список студентов успешно загружен и зашифрован на сервере!")

@dp.message(F.text == "📋 Начать перекличку", StarostaState.main_menu)
async def start_attendance(message: types.Message, state: FSMContext):
    data = decrypt_file()
    if not data:
        await message.answer("❌ Сначала загрузите список студентов (Excel файл).")
        return

    temp_file = "data/temp.xlsx"
    with open(temp_file, "wb") as f:
        f.write(data)
    
    try:
        df = pd.read_excel(temp_file)
        if 'ФИО' not in df.columns:
            raise ValueError("Нет столбца ФИО")
        students = df['ФИО'].dropna().tolist()
    except Exception as e:
        await message.answer(f"❌ Ошибка чтения файла. Убедитесь, что есть столбец 'ФИО'.\nДетали: {e}")
        return
    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)

    await state.update_data(students=students, results={}, current_index=0)
    await message.answer("Введите название пары (например: 'Высшая математика, лекция'):")
    await state.set_state(StarostaState.waiting_for_subject)

@dp.message(StarostaState.waiting_for_subject)
async def set_subject(message: types.Message, state: FSMContext):
    subject = message.text
    await state.update_data(subject=subject)
    data = await state.get_data()
    
    student = data['students'][0]
    await message.answer(
        f"📝 Перекличка: **{subject}**\n\nСтудент (1/{len(data['students'])}): **{student}**", 
        reply_markup=get_attendance_keyboard(),
        parse_mode="Markdown"
    )
    await state.set_state(StarostaState.attendance_process)

@dp.callback_query(F.data.startswith("att_"), StarostaState.attendance_process)
async def process_attendance(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    students = data['students']
    results = data['results']
    current_index = data['current_index']
    
    status_map = {"att_yes": "✅", "att_no": "❌", "att_excused": "🤒"}
    results[students[current_index]] = status_map[callback.data]
    
    current_index += 1
    
    if current_index < len(students):
        await state.update_data(results=results, current_index=current_index)
        next_student = students[current_index]
        await callback.message.edit_text(
            f"📝 Перекличка: **{data['subject']}**\n\nСтудент ({current_index + 1}/{len(students)}): **{next_student}**",
            reply_markup=get_attendance_keyboard(),
            parse_mode="Markdown"
        )
    else:
        await callback.message.delete()
        await generate_and_send_report(callback.message, data, state)

async def generate_and_send_report(message: types.Message, data: dict, state: FSMContext):
    subject = data['subject']
    results = data['results']
    now = datetime.now()
    date_str = now.strftime("%d.%m.%Y")
    time_str = now.strftime("%H:%M")
    
    present = [s for s, status in results.items() if status == "✅"]
    absent = [s for s, status in results.items() if status == "❌"]
    excused = [s for s, status in results.items() if status == "🤒"]
    
    report_text = (
        f"📊 **Отчет по посещаемости**\n"
        f"📘 Пара: {subject}\n"
        f"📅 Дата: {date_str} | ⏰ Время: {time_str}\n"
        f"──────────────────\n"
        f"👥 Всего в группе: {len(results)}\n"
        f"✅ Присутствуют: {len(present)}\n"
        f"❌ Отсутствуют: {len(absent)}\n"
        f"🤒 Уважительная причина: {len(excused)}\n"
        f"──────────────────\n"
    )
    
    if absent:
        report_text += "❗️ **Отсутствующие:**\n" + "\n".join([f"— {s}" for s in absent]) + "\n\n"
    if present:
        report_text += "✅ **Присутствующие:**\n" + "\n".join([f"— {s}" for s in present])
        
    await message.answer("✅ Перекличка завершена!\n\n" + report_text, parse_mode="Markdown")
    await state.set_state(StarostaState.main_menu)

async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

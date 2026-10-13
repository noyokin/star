import os
import json
import asyncio
import random
import pandas as pd
from datetime import datetime
import hashlib
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from cryptography.fernet import Fernet

# ==========================================
# 1. ЗАГРУЗКА НАСТРОЕК И ПУТЕЙ
# ==========================================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

# Папка и файлы данных (для сохранения состояния при перезапуске)
os.makedirs("data", exist_ok=True)
KEY_FILE = "data/secret.key"
ENCRYPTED_EXCEL = "data/students_encrypted.dat"
HISTORY_FILE = "data/history.json"
STATUSES_FILE = "data/statuses.json"

# ==========================================
# 2. ШИФРОВАНИЕ И РАБОТА С ФАЙЛАМИ
# ==========================================
def get_or_create_key():
    if not os.path.exists(KEY_FILE):
        with open(KEY_FILE, "wb") as key_file:
            key_file.write(Fernet.generate_key())
    with open(KEY_FILE, "rb") as key_file:
        return key_file.read()

fernet = Fernet(get_or_create_key())

def encrypt_file(file_data: bytes): 
    return fernet.encrypt(file_data)

def decrypt_file():
    if not os.path.exists(ENCRYPTED_EXCEL): 
        return None
    with open(ENCRYPTED_EXCEL, "rb") as f: 
        return fernet.decrypt(f.read())

def load_json(path):
    if not os.path.exists(path): 
        return {} if "statuses" in path else []
    with open(path, "r", encoding="utf-8") as f: 
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f: 
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_students_list():
    data = decrypt_file()
    if not data: 
        return []
    temp_file = "data/temp.xlsx"
    with open(temp_file, "wb") as f: 
        f.write(data)
    try:
        df = pd.read_excel(temp_file)
        return df['ФИО'].dropna().tolist()
    except: 
        return []
    finally:
        if os.path.exists(temp_file): 
            os.remove(temp_file)

# ==========================================
# 3. ИНИЦИАЛИЗАЦИЯ БОТА И FSM
# ==========================================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class StarostaState(StatesGroup):
    auth = State()
    main_menu = State()
    waiting_for_subject = State()
    attendance_process = State()

def get_main_keyboard():
    kb = [
        [types.KeyboardButton(text="📋 Начать перекличку"), types.KeyboardButton(text="🎲 Вызвать к доске")],
        [types.KeyboardButton(text="⚙️ Статусы студентов"), types.KeyboardButton(text="📊 Сводный отчет (Excel)")],
        [types.KeyboardButton(text="📁 Обновить список Excel")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_attendance_keyboard():
    kb = [
        [InlineKeyboardButton(text="✅ Был", callback_data="att_yes"), InlineKeyboardButton(text="❌ Не был", callback_data="att_no")],
        [InlineKeyboardButton(text="🤒 Болеет/Уваж.", callback_data="att_excused")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ==========================================
# 4. АВТОРИЗАЦИЯ
# ==========================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await message.answer("🔒 Введите пароль старосты:")
    await state.set_state(StarostaState.auth)

@dp.message(StarostaState.auth)
async def check_password(message: types.Message, state: FSMContext):
    input_hash = hashlib.sha256(message.text.encode()).hexdigest()
    correct_hash = hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest()
    
    if input_hash == correct_hash:
        await message.answer("✅ Доступ разрешен!", reply_markup=get_main_keyboard())
        await state.set_state(StarostaState.main_menu)
        await message.delete()
    else:
        await message.answer("❌ Неверный пароль.")

# ==========================================
# 5. ЗАГРУЗКА EXCEL
# ==========================================
@dp.message(F.text == "📁 Обновить список Excel", StarostaState.main_menu)
async def request_excel(message: types.Message):
    await message.answer("Отправьте Excel файл (.xlsx). В первой строке обязательно должен быть заголовок **ФИО**.")

@dp.message(F.document, StarostaState.main_menu)
async def handle_document(message: types.Message, bot: Bot):
    if not message.document.file_name.endswith('.xlsx'):
        await message.answer("❌ Нужен формат .xlsx")
        return
    file_id = message.document.file_id
    file_data = await bot.download_file((await bot.get_file(file_id)).file_path)
    
    with open(ENCRYPTED_EXCEL, "wb") as f:
        f.write(encrypt_file(file_data.read()))
    await message.answer("✅ Список успешно обновлен и зашифрован!")

# ==========================================
# 6. ВЫЗОВ К ДОСКЕ (ИНТЕРАКТИВНЫЙ)
# ==========================================
@dp.message(F.text == "🎲 Вызвать к доске", StarostaState.main_menu)
async def random_student_menu(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 Выбрать случайного студента", callback_data="random_student")]
    ])
    await message.answer("Кто пойдет к доске? Нажмите на кнопку ниже:", reply_markup=kb)

@dp.callback_query(F.data == "random_student", StarostaState.main_menu)
async def process_random_student(callback: types.CallbackQuery):
    students = get_students_list()
    statuses = load_json(STATUSES_FILE)
    active = [s for s in students if statuses.get(s, 'act') != 'acad']
    
    if not active:
        await callback.answer("Список активных студентов пуст!", show_alert=True)
        return
        
    chosen = random.choice(active)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Выбрать еще одного", callback_data="random_student")]
    ])
    
    await callback.message.edit_text(
        f"🎲 К доске сегодня идет:\n\n🎉 **{chosen}** 🎉", 
        reply_markup=kb, 
        parse_mode="Markdown"
    )

# ==========================================
# 7. УПРАВЛЕНИЕ СТАТУСАМИ (С ФИЛЬТРАМИ)
# ==========================================
@dp.message(F.text == "⚙️ Статусы студентов", StarostaState.main_menu)
async def manage_statuses_start(message: types.Message):
    students = get_students_list()
    if not students:
        await message.answer("❌ Загрузите список студентов.")
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Базовые (Активные)", callback_data="filter_act")],
        [InlineKeyboardButton(text="📝 На инд. плане", callback_data="filter_ind")],
        [InlineKeyboardButton(text="💤 В академ. отпуске", callback_data="filter_acad")],
        [InlineKeyboardButton(text="📋 Показать всех", callback_data="filter_all")]
    ])
    await message.answer("По какому статусу отфильтровать студентов?", reply_markup=kb)

@dp.callback_query(F.data == "back_to_filters", StarostaState.main_menu)
async def back_to_filters(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Базовые (Активные)", callback_data="filter_act")],
        [InlineKeyboardButton(text="📝 На инд. плане", callback_data="filter_ind")],
        [InlineKeyboardButton(text="💤 В академ. отпуске", callback_data="filter_acad")],
        [InlineKeyboardButton(text="📋 Показать всех", callback_data="filter_all")]
    ])
    await callback.message.edit_text("По какому статусу отфильтровать студентов?", reply_markup=kb)

@dp.callback_query(F.data.startswith("filter_"), StarostaState.main_menu)
async def show_filtered_students(callback: types.CallbackQuery):
    filter_type = callback.data.split("_")[1]
    students = get_students_list()
    statuses = load_json(STATUSES_FILE)
    
    kb = []
    count = 0
    for i, student in enumerate(students):
        stat_code = statuses.get(student, 'act')
        if filter_type == 'all' or stat_code == filter_type:
            stat_emoji = "👤" if stat_code == 'act' else ("📝" if stat_code == 'ind' else "💤")
            kb.append([InlineKeyboardButton(text=f"{stat_emoji} {student}", callback_data=f"sel_st_{i}")])
            count += 1
            
    kb.append([InlineKeyboardButton(text="🔙 Назад к категориям", callback_data="back_to_filters")])
    
    filter_names = {"act": "Базовые", "ind": "Инд. план", "acad": "Академ. отпуск", "all": "Все студенты"}
    
    if count == 0:
        text = f"📂 Категория: **{filter_names[filter_type]}**\n\nВ этой категории пока нет студентов."
    else:
        text = f"📂 Категория: **{filter_names[filter_type]}**\nНайдено студентов: {count}\n\nКого хотите изменить?"
        
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("sel_st_"), StarostaState.main_menu)
async def select_student_status(callback: types.CallbackQuery):
    idx = int(callback.data.split("_")[2])
    students = get_students_list()
    student = students[idx]
    
    kb = [
        [InlineKeyboardButton(text="👤 Базовый", callback_data=f"setstat_{idx}_act")],
        [InlineKeyboardButton(text="📝 Индивидуальный план", callback_data=f"setstat_{idx}_ind")],
        [InlineKeyboardButton(text="💤 Академ. отпуск", callback_data=f"setstat_{idx}_acad")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_filters")]
    ]
    await callback.message.edit_text(f"Укажите новый статус для:\n**{student}**", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("setstat_"), StarostaState.main_menu)
async def save_student_status(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    idx = int(parts[1])
    new_stat = parts[2]
    
    students = get_students_list()
    student = students[idx]
    
    statuses = load_json(STATUSES_FILE)
    statuses[student] = new_stat
    save_json(STATUSES_FILE, statuses)
    
    labels = {"act": "Базовый", "ind": "Индивидуальный план", "acad": "Академ. отпуск"}
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Вернуться к категориям", callback_data="back_to_filters")]
    ])
    
    await callback.message.edit_text(f"✅ Статус для **{student}** изменен на: **{labels[new_stat]}**", reply_markup=kb, parse_mode="Markdown")

# ==========================================
# 8. ПЕРЕКЛИЧКА
# ==========================================
@dp.message(F.text == "📋 Начать перекличку", StarostaState.main_menu)
async def start_attendance(message: types.Message, state: FSMContext):
    students = get_students_list()
    if not students:
        await message.answer("❌ Список студентов не загружен.")
        return
    await message.answer("Введите название пары (например: 'Экономика, семинар'):")
    await state.set_state(StarostaState.waiting_for_subject)

@dp.message(StarostaState.waiting_for_subject)
async def set_subject(message: types.Message, state: FSMContext):
    subject = message.text
    students = get_students_list()
    statuses = load_json(STATUSES_FILE)
    
    results = {}
    active_students = []
    
    for s in students:
        stat = statuses.get(s, "act")
        if stat == "acad":
            results[s] = "💤 (Академ)"
        else:
            active_students.append(s)
            
    await state.update_data(subject=subject, active=active_students, all_students=students, results=results, current_index=0)
    
    if not active_students:
        await message.answer("Все студенты в академическом отпуске 😅")
        await state.set_state(StarostaState.main_menu)
        return
        
    await send_attendance_question(message, await state.get_data())
    await state.set_state(StarostaState.attendance_process)

async def send_attendance_question(message: types.Message, data: dict, edit=False):
    idx = data['current_index']
    student = data['active'][idx]
    
    statuses = load_json(STATUSES_FILE)
    status_label = " 📝 *(Инд. план)*" if statuses.get(student) == 'ind' else ""
    
    text = f"📝 **{data['subject']}**\n\nСтудент ({idx + 1}/{len(data['active'])}):\n👤 **{student}**{status_label}"
    kb = get_attendance_keyboard()
    
    if edit:
        await message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await message.answer(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("att_"), StarostaState.attendance_process)
async def process_attendance(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    idx = data['current_index']
    student = data['active'][idx]
    
    status_map = {"att_yes": "✅", "att_no": "❌", "att_excused": "🤒"}
    data['results'][student] = status_map[callback.data]
    
    idx += 1
    data['current_index'] = idx
    await state.update_data(data)
    
    if idx < len(data['active']):
        await send_attendance_question(callback.message, data, edit=True)
    else:
        await callback.message.delete()
        await finish_attendance(callback.message, data, state)

async def finish_attendance(message: types.Message, data: dict, state: FSMContext):
    subject = data['subject']
    results = data['results']
    
    history = load_json(HISTORY_FILE)
    date_str = datetime.now().strftime("%d.%m.%Y")
    history.append({
        "date": date_str,
        "time": datetime.now().strftime("%H:%M"),
        "subject": subject,
        "results": results
    })
    save_json(HISTORY_FILE, history)
    
    present = [s for s, st in results.items() if st == "✅"]
    absent = [s for s, st in results.items() if st == "❌"]
    excused = [s for s, st in results.items() if st == "🤒"]
    
    report = f"📊 **{subject}** ({date_str})\n──────────────────\n"
    report += f"👥 Всего: {len(results)} | ✅ Был: {len(present)} | ❌ Не был: {len(absent)} | 🤒 Уваж: {len(excused)}\n──────────────────\n"
    
    if absent: 
        report += "❗️ **Отсутствуют:**\n" + "\n".join(absent) + "\n\n"
    if present: 
        report += "✅ **Присутствуют:**\n" + "\n".join(present)
    
    await message.answer("Перекличка завершена!\n\n" + report, parse_mode="Markdown")
    await state.set_state(StarostaState.main_menu)

# ==========================================
# 9. ЭКСПОРТ ИСТОРИИ (СВОДНЫЙ ОТЧЕТ)
# ==========================================
@dp.message(F.text == "📊 Сводный отчет (Excel)", StarostaState.main_menu)
async def export_history(message: types.Message):
    history = load_json(HISTORY_FILE)
    if not history:
        await message.answer("❌ История перекличек пуста.")
        return
        
    await message.answer("⏳ Формирую отчет для деканата...")
    
    df = pd.DataFrame()
    for record in history:
        col_name = f"{record['date']} {record['time']}\n{record['subject'][:15]}"
        for student, status in record['results'].items():
            df.at[student, col_name] = status
            
    df.fillna("-", inplace=True)
    df.sort_index(inplace=True) 
    
    file_path = "data/Сводный_отчет.xlsx"
    df.to_excel(file_path, sheet_name="Посещаемость")
    
    await message.answer_document(FSInputFile(file_path), caption="📁 Вот ваш отчет по всем парам!")

# ==========================================
# ЗАПУСК
# ==========================================
async def main():
    print("Бот запущен с полным функционалом...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

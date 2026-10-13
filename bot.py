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

os.makedirs("data", exist_ok=True)
KEY_FILE = "data/secret.key"
ENCRYPTED_EXCEL = "data/students_encrypted.dat"
HISTORY_FILE = "data/history.json"
STATUSES_FILE = "data/statuses.json"
SETTINGS_FILE = "data/settings.json"

DEFAULT_SUBJECTS = [
    "Архитектура вычислительных систем", "Дискретная математика",
    "История России", "Программирование", "Алгебра и геометрия",
    "Математическая логика и теория алгоритмов", "Русский язык и культура речи",
    "Основы российской государственности", "Физическая культура и спорт",
    "Математический анализ", "Иностранный язык"
]

DEFAULT_SETTINGS = {
    "show_absent": True,
    "show_present": True,
    "subjects": DEFAULT_SUBJECTS
}

# ==========================================
# 2. ФАЙЛОВАЯ СИСТЕМА И ШИФРОВАНИЕ
# ==========================================
def get_or_create_key():
    if not os.path.exists(KEY_FILE):
        with open(KEY_FILE, "wb") as key_file:
            key_file.write(Fernet.generate_key())
    with open(KEY_FILE, "rb") as key_file: return key_file.read()

fernet = Fernet(get_or_create_key())

def encrypt_file(file_data: bytes): return fernet.encrypt(file_data)
def decrypt_file():
    if not os.path.exists(ENCRYPTED_EXCEL): return None
    with open(ENCRYPTED_EXCEL, "rb") as f: return fernet.decrypt(f.read())

def load_json(path, default_val=None):
    if not os.path.exists(path): return default_val if default_val is not None else []
    with open(path, "r", encoding="utf-8") as f: return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)

def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        save_json(SETTINGS_FILE, DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS
    return load_json(SETTINGS_FILE, DEFAULT_SETTINGS)

def get_students_list():
    data = decrypt_file()
    if not data: return []
    temp_file = "data/temp.xlsx"
    with open(temp_file, "wb") as f: f.write(data)
    try:
        df = pd.read_excel(temp_file)
        return df['ФИО'].dropna().tolist()
    except: return []
    finally:
        if os.path.exists(temp_file): os.remove(temp_file)

# ==========================================
# 3. ИНИЦИАЛИЗАЦИЯ И МАШИНА СОСТОЯНИЙ
# ==========================================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class StarostaState(StatesGroup):
    auth = State()
    main_menu = State()
    select_subject = State()
    add_custom_subject = State()
    select_lesson = State()
    attendance_process = State()

def get_main_keyboard():
    kb = [
        [types.KeyboardButton(text="📋 Перекличка"), types.KeyboardButton(text="🎲 К доске (с пары)")],
        [types.KeyboardButton(text="📜 История"), types.KeyboardButton(text="📊 Отчет (Excel)")],
        [types.KeyboardButton(text="⚙️ Статусы"), types.KeyboardButton(text="🛠 Настройки")],
        [types.KeyboardButton(text="📁 Обновить список Excel")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_attendance_keyboard():
    kb = [
        [InlineKeyboardButton(text="✅ Был", callback_data="att_yes"), InlineKeyboardButton(text="❌ Не был", callback_data="att_no")],
        [InlineKeyboardButton(text="🤒 Уваж.", callback_data="att_excused")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ==========================================
# 4. БАЗОВЫЕ КОМАНДЫ И НАСТРОЙКИ
# ==========================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await message.answer("🔒 Введите пароль старосты:")
    await state.set_state(StarostaState.auth)

@dp.message(StarostaState.auth)
async def check_password(message: types.Message, state: FSMContext):
    if hashlib.sha256(message.text.encode()).hexdigest() == hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest():
        await message.answer("✅ Доступ разрешен!", reply_markup=get_main_keyboard())
        await state.set_state(StarostaState.main_menu)
        await message.delete()
    else:
        await message.answer("❌ Неверный пароль.")

@dp.message(F.text == "🛠 Настройки", StarostaState.main_menu)
async def settings_menu(message: types.Message):
    settings = load_settings()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Показывать отсутствующих: {'✅' if settings['show_absent'] else '❌'}", callback_data="toggle_absent")],
        [InlineKeyboardButton(text=f"Показывать присутствующих: {'✅' if settings['show_present'] else '❌'}", callback_data="toggle_present")]
    ])
    await message.answer("🛠 **Настройки финального сообщения:**\nНажмите, чтобы включить/выключить отображение списков.", reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("toggle_"), StarostaState.main_menu)
async def toggle_settings(callback: types.CallbackQuery):
    param = callback.data.split("_")[1]
    settings = load_settings()
    
    if param == "absent": settings['show_absent'] = not settings['show_absent']
    if param == "present": settings['show_present'] = not settings['show_present']
    
    save_json(SETTINGS_FILE, settings)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Показывать отсутствующих: {'✅' if settings['show_absent'] else '❌'}", callback_data="toggle_absent")],
        [InlineKeyboardButton(text=f"Показывать присутствующих: {'✅' if settings['show_present'] else '❌'}", callback_data="toggle_present")]
    ])
    await callback.message.edit_reply_markup(reply_markup=kb)

# ==========================================
# 5. ИСТОРИЯ В БОТЕ
# ==========================================
@dp.message(F.text == "📜 История", StarostaState.main_menu)
async def show_history(message: types.Message):
    history = load_json(HISTORY_FILE, [])
    if not history:
        return await message.answer("❌ История перекличек пуста.")
    
    kb = []
    for i, rec in enumerate(history[-10:]):  # Показываем последние 10
        actual_idx = len(history) - 10 + i if len(history) > 10 else i
        title = f"{rec['date']} | {rec['subject'][:15]}... ({rec.get('lesson', '?')} пара)"
        kb.append([InlineKeyboardButton(text=title, callback_data=f"hist_{actual_idx}")])
        
    await message.answer("📜 **Последние 10 пар:**\nВыберите пару для просмотра деталей.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("hist_"), StarostaState.main_menu)
async def view_history_record(callback: types.CallbackQuery):
    idx = int(callback.data.split("_")[1])
    history = load_json(HISTORY_FILE, [])
    
    if idx >= len(history):
        return await callback.answer("Запись не найдена", show_alert=True)
        
    rec = history[idx]
    results = rec['results']
    present = [s for s, st in results.items() if st == "✅"]
    absent = [s for s, st in results.items() if st == "❌"]
    excused = [s for s, st in results.items() if st == "🤒"]
    
    report = f"📊 **{rec['subject']}** ({rec['date']}, {rec['time']})\n"
    report += f"📘 Пара №: {rec.get('lesson', 'Не указана')}\n──────────────────\n"
    report += f"👥 Всего: {len(results)} | ✅ Был: {len(present)} | ❌ Не был: {len(absent)} | 🤒 Уваж: {len(excused)}\n──────────────────\n"
    
    if absent: report += "❗️ **Отсутствуют:**\n" + "\n".join(absent) + "\n\n"
    if present: report += "✅ **Присутствуют:**\n" + "\n".join(present)
    
    await callback.message.edit_text(report, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_history")]]))

@dp.callback_query(F.data == "back_to_history", StarostaState.main_menu)
async def back_to_history(callback: types.CallbackQuery):
    history = load_json(HISTORY_FILE, [])
    kb = []
    for i, rec in enumerate(history[-10:]):
        actual_idx = len(history) - 10 + i if len(history) > 10 else i
        title = f"{rec['date']} | {rec['subject'][:15]}... ({rec.get('lesson', '?')} пара)"
        kb.append([InlineKeyboardButton(text=title, callback_data=f"hist_{actual_idx}")])
    await callback.message.edit_text("📜 **Последние 10 пар:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")

# ==========================================
# 6. К ДОСКЕ ИЗ ПРИСУТСТВУЮЩИХ
# ==========================================
@dp.message(F.text == "🎲 К доске (с пары)", StarostaState.main_menu)
async def board_call(message: types.Message):
    history = load_json(HISTORY_FILE, [])
    if not history:
        return await message.answer("❌ Сначала проведите перекличку, чтобы знать, кто есть на паре.")
        
    last_record = history[-1]
    # Фильтруем только тех, кто присутствовал ("✅")
    present_students = [s for s, status in last_record['results'].items() if status == "✅"]
    
    if not present_students:
        return await message.answer(f"❌ На последней паре ({last_record['subject']}) никого не было отмечено.")
        
    chosen = random.choice(present_students)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Выбрать еще одного", callback_data="random_board")]])
    
    await message.answer(f"🎲 Вызов к доске!\n📘 Пара: {last_record['subject']}\n\n🎉 Идет отвечать: **{chosen}** 🎉", reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "random_board", StarostaState.main_menu)
async def board_call_refresh(callback: types.CallbackQuery):
    history = load_json(HISTORY_FILE, [])
    last_record = history[-1]
    present_students = [s for s, status in last_record['results'].items() if status == "✅"]
    
    chosen = random.choice(present_students)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Выбрать еще одного", callback_data="random_board")]])
    await callback.message.edit_text(f"🎲 Вызов к доске!\n📘 Пара: {last_record['subject']}\n\n🎉 Идет отвечать: **{chosen}** 🎉", reply_markup=kb, parse_mode="Markdown")

# ==========================================
# 7. ПЕРЕКЛИЧКА (ПРЕДМЕТ -> НОМЕР ПАРЫ -> ОПРОС)
# ==========================================
@dp.message(F.text == "📋 Перекличка", StarostaState.main_menu)
async def start_attendance(message: types.Message, state: FSMContext):
    students = get_students_list()
    if not students: return await message.answer("❌ Список студентов не загружен.")
    
    settings = load_settings()
    kb = []
    # Выводим предметы по одному в ряд, чтобы влезли названия
    for i, subj in enumerate(settings["subjects"]):
        kb.append([InlineKeyboardButton(text=subj, callback_data=f"subj_{i}")])
    kb.append([InlineKeyboardButton(text="➕ Добавить свой предмет", callback_data="subj_custom")])
    
    await message.answer("Выберите предмет из списка:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await state.set_state(StarostaState.select_subject)

@dp.callback_query(F.data.startswith("subj_"), StarostaState.select_subject)
async def process_subject_selection(callback: types.CallbackQuery, state: FSMContext):
    data = callback.data.split("_")[1]
    
    if data == "custom":
        await callback.message.edit_text("Введите название нового предмета в чат:")
        await state.set_state(StarostaState.add_custom_subject)
        return
        
    settings = load_settings()
    subject = settings["subjects"][int(data)]
    await state.update_data(subject=subject)
    
    # Переходим к выбору номера пары
    kb = []
    row = []
    for i in range(1, 9):
        row.append(InlineKeyboardButton(text=f"{i}", callback_data=f"lesson_{i}"))
        if len(row) == 4:
            kb.append(row)
            row = []
    
    await callback.message.edit_text(f"Предмет: **{subject}**\nВыберите номер пары:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
    await state.set_state(StarostaState.select_lesson)

@dp.message(StarostaState.add_custom_subject)
async def add_custom_subject(message: types.Message, state: FSMContext):
    new_subject = message.text
    settings = load_settings()
    settings["subjects"].append(new_subject)
    save_json(SETTINGS_FILE, settings)
    
    await state.update_data(subject=new_subject)
    
    kb = []
    row = []
    for i in range(1, 9):
        row.append(InlineKeyboardButton(text=f"{i}", callback_data=f"lesson_{i}"))
        if len(row) == 4:
            kb.append(row)
            row = []
            
    await message.answer(f"✅ Предмет сохранен!\n\nПредмет: **{new_subject}**\nВыберите номер пары:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
    await state.set_state(StarostaState.select_lesson)

@dp.callback_query(F.data.startswith("lesson_"), StarostaState.select_lesson)
async def process_lesson_selection(callback: types.CallbackQuery, state: FSMContext):
    lesson = callback.data.split("_")[1]
    await state.update_data(lesson=lesson)
    
    data = await state.get_data()
    students = get_students_list()
    statuses = load_json(STATUSES_FILE, {})
    
    results = {}
    active_students = []
    for s in students:
        stat = statuses.get(s, "act")
        if stat == "acad": results[s] = "💤 (Академ)"
        else: active_students.append(s)
            
    await state.update_data(active=active_students, all_students=students, results=results, current_index=0)
    
    if not active_students:
        await callback.message.edit_text("Все студенты в академическом отпуске 😅")
        await state.set_state(StarostaState.main_menu)
        return
        
    await send_attendance_question(callback.message, await state.get_data(), edit=True)
    await state.set_state(StarostaState.attendance_process)

async def send_attendance_question(message: types.Message, data: dict, edit=False):
    idx = data['current_index']
    student = data['active'][idx]
    statuses = load_json(STATUSES_FILE, {})
    status_label = " 📝 *(Инд. план)*" if statuses.get(student) == 'ind' else ""
    
    text = f"📝 **{data['subject']} (Пара {data['lesson']})**\n\nСтудент ({idx + 1}/{len(data['active'])}):\n👤 **{student}**{status_label}"
    kb = get_attendance_keyboard()
    
    if edit: await message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    else: await message.answer(text, reply_markup=kb, parse_mode="Markdown")

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
    lesson = data['lesson']
    results = data['results']
    
    history = load_json(HISTORY_FILE, [])
    date_str = datetime.now().strftime("%d.%m.%Y")
    history.append({
        "date": date_str,
        "time": datetime.now().strftime("%H:%M"),
        "subject": subject,
        "lesson": lesson,
        "results": results
    })
    save_json(HISTORY_FILE, history)
    
    present = [s for s, st in results.items() if st == "✅"]
    absent = [s for s, st in results.items() if st == "❌"]
    excused = [s for s, st in results.items() if st == "🤒"]
    
    settings = load_settings()
    
    report = f"📊 **{subject}** (Пара {lesson})\n📅 {date_str}\n──────────────────\n"
    report += f"👥 Всего: {len(results)} | ✅ Был: {len(present)} | ❌ Не был: {len(absent)} | 🤒 Уваж: {len(excused)}\n──────────────────\n"
    
    if settings['show_absent'] and absent: 
        report += "❗️ **Отсутствуют:**\n" + "\n".join(absent) + "\n\n"
    if settings['show_present'] and present: 
        report += "✅ **Присутствуют:**\n" + "\n".join(present)
    
    await message.answer("✅ Перекличка завершена!\n\n" + report, parse_mode="Markdown")
    await state.set_state(StarostaState.main_menu)

# ==========================================
# 8. СТРОГИЙ СВОДНЫЙ ОТЧЕТ (EXCEL)
# ==========================================
@dp.message(F.text == "📊 Отчет (Excel)", StarostaState.main_menu)
async def export_history(message: types.Message):
    history = load_json(HISTORY_FILE, [])
    if not history: return await message.answer("❌ История перекличек пуста.")
        
    await message.answer("⏳ Формирую строгий отчет для деканата...")
    
    # Строгая конвертация: ✅ -> +, ❌ -> н, 🤒 -> у, 💤 -> а
    strict_map = {"✅": "+", "❌": "н", "🤒": "у", "💤 (Академ)": "а"}
    
    df = pd.DataFrame()
    for record in history:
        col_name = f"{record['date']}\n{record['subject'][:10]}...\n({record.get('lesson', '?')} пара)"
        for student, status in record['results'].items():
            df.at[student, col_name] = strict_map.get(status, status)
            
    df.fillna("", inplace=True)
    df.sort_index(inplace=True) 
    
    file_path = "data/Строгий_отчет.xlsx"
    df.to_excel(file_path, sheet_name="Посещаемость")
    
    await message.answer_document(FSInputFile(file_path), caption="📁 Строгий отчет сформирован! (н - не был, у - уважительная, а - академ, + - был)")

# ==========================================
# ОБНОВЛЕНИЕ СПИСКА EXCEL И УПРАВЛЕНИЕ СТАТУСАМИ (Из прошлого кода)
# ==========================================
@dp.message(F.text == "📁 Обновить список Excel", StarostaState.main_menu)
async def request_excel(message: types.Message):
    await message.answer("Отправьте Excel файл (.xlsx). Заголовок столбца должен быть **ФИО**.")

@dp.message(F.document, StarostaState.main_menu)
async def handle_document(message: types.Message, bot: Bot):
    if not message.document.file_name.endswith('.xlsx'): return await message.answer("❌ Нужен формат .xlsx")
    file_id = message.document.file_id
    file_data = await bot.download_file((await bot.get_file(file_id)).file_path)
    with open(ENCRYPTED_EXCEL, "wb") as f: f.write(encrypt_file(file_data.read()))
    await message.answer("✅ Список успешно обновлен и зашифрован!")

@dp.message(F.text == "⚙️ Статусы", StarostaState.main_menu)
async def manage_statuses_start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Базовые (Активные)", callback_data="filter_act")],
        [InlineKeyboardButton(text="📝 На инд. плане", callback_data="filter_ind")],
        [InlineKeyboardButton(text="💤 В академ. отпуске", callback_data="filter_acad")],
        [InlineKeyboardButton(text="📋 Показать всех", callback_data="filter_all")]
    ])
    await message.answer("Какую категорию открыть?", reply_markup=kb)

@dp.callback_query(F.data == "back_to_filters", StarostaState.main_menu)
async def back_to_filters(callback: types.CallbackQuery

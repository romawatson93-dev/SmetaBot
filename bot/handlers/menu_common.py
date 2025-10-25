from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

BTN_NEW_CHANNEL = "🆕 Новый канал"
BTN_MY_CHANNELS = "📢 Мои каналы"
BTN_MY_LINKS = "🔗 Мои ссылки"
BTN_RENDER = "🖼️ Рендер файлов"
BTN_PROFILE = "👤 Личный кабинет"
BTN_HELP = "❓ Помощь"

BTN_RENDER_PDF = "📄 PDF → PNG"
BTN_RENDER_XLSX = "📊 Excel → PNG"
BTN_RENDER_DOC = "📝 Word → PNG"
BTN_RENDER_PNG = "🖼️ PNG в канал"
BTN_RENDER_BACK = "⬅️ Назад"



def build_main_menu_keyboard() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=BTN_NEW_CHANNEL)],
        [KeyboardButton(text=BTN_MY_CHANNELS), KeyboardButton(text=BTN_MY_LINKS)],
        [KeyboardButton(text=BTN_RENDER), KeyboardButton(text=BTN_PROFILE)],
        [KeyboardButton(text=BTN_HELP)],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def build_render_menu_keyboard() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=BTN_RENDER_PDF), KeyboardButton(text=BTN_RENDER_XLSX)],
        [KeyboardButton(text=BTN_RENDER_DOC), KeyboardButton(text=BTN_RENDER_PNG)],
        [KeyboardButton(text=BTN_RENDER_BACK)],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)



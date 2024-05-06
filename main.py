import sys
import json
import os
import threading
import logging
import time
import html

from PyQt6.QtWidgets import QMessageBox, QFileDialog, QMainWindow, QHBoxLayout, QPushButton, QTextEdit
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QListWidget, QListWidgetItem, QMenu
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QTextCursor, QFont, QBrush, QColor, QCursor
import telebot

import config


logging.basicConfig(level=logging.INFO)
bot = telebot.TeleBot(config.BOT_TOKEN)


def bot_polling_thread():
    bot.polling(none_stop=True)


def format_file_size(file_size: int):
    """
    Возвращает размер файла в килобайтах или мегабайтах.
    Возвращает строку с размером файла в Кб, если он меньше 1 Мб, или в Мб, если больше.
    """
    if file_size < 1024 * 1024:  # Если размер меньше 1 Мб (1 Мб = 1024 * 1024 байт)
        return f"{file_size / 1024:.2f} Кб"  # Возвращаем размер в килобайтах
    else:
        return f"{file_size / (1024 * 1024):.2f} Мб"  # Возвращаем размер в мегабайтах


class DialogList:
    def __init__(self):
        self._dialogs = {}
        self._lock_saving = threading.Lock()

    def load(self):
        if os.path.exists('dialogs.json'):
            with open('dialogs.json', 'r', encoding='utf-8') as f:
                self._dialogs = json.load(f)

    def save(self):
        with self._lock_saving:
            with open("dialogs.json", "w", encoding="utf-8") as f:
                json.dump(self._dialogs, f, indent=4, ensure_ascii=False)

    def add_inbound(self, message: telebot.types.Message):
        media_types = {
            'text': message.text if message.text else "",
            'photo': "[Отправил(а) фото]",
            'document': "[Отправил(а) файл]",
            'sticker': "[Отправил(а) стикер]",
            'video': "[Отправил(а) видео]",
            'voice': "[Отправил(а) голосовое сообщение]",
            'audio': "[Отправил(а) аудио]",
            'animation': "[Отправил(а) GIF]"
        }
        uid: str = str(message.from_user.id)
        description_text = media_types.get(message.content_type, "[Отправил(а) неизвестный тип медиа]")

        if self._dialogs.get(uid):
            self._dialogs[uid]["username"] = message.from_user.username
            self._dialogs[uid]["firstName"] = message.from_user.first_name
            self._dialogs[uid]["lastName"] = message.from_user.last_name
            self._dialogs[uid]["messages"].append({
                "text": description_text,
                "time": message.date,
                "in": True
            })
            self._dialogs[uid]["answered"] = False
        else:
            self._dialogs[uid] = {
                "userId": message.from_user.id,
                "username": message.from_user.username,
                "firstName": message.from_user.first_name,
                "lastName": message.from_user.last_name,
                "messages": [{
                    "text": description_text,
                    "time": message.date,
                    "in": True
                }],
                "answered": False
            }
        self.save()

    def add_outbound(self, to_id: int | str, text: str):
        to_id: str = str(to_id)
        self._dialogs[to_id]["messages"].append({
            "text": text,
            "time": int(time.time()),
            "in": False
        })
        self._dialogs[to_id]["answered"] = True
        self.save()

    def is_answered(self, user_id: int) -> bool:
        uid = str(user_id)
        return self._dialogs[uid]['answered']

    def delete_chat(self, user_id: int):
        uid = str(user_id)
        if self._dialogs.get(uid):
            del self._dialogs[uid]
            self.save()

    def mark_as_answered(self, user_id: int):
        uid = str(user_id)
        if self._dialogs.get(uid):
            self._dialogs[uid]["answered"] = True
            self.save()

    def get_dialog_text(self, user_id: int | str) -> str:
        uid = str(user_id)
        dialog: dict = self._dialogs[uid]

        first_name: str = dialog["firstName"]

        messages_list = [
            "[{}] <b>{}:</b> {}".format(
                time.strftime("%H:%M %d.%m.%y", time.localtime(msg['time'])),
                (html.escape(first_name) if msg['in'] else 'Вы'),
                html.escape(msg['text'].replace('\n', ' '))
            ) for msg in dialog['messages']
        ]
        return "<br>".join(messages_list)

    def get_users(self) -> list[dict]:
        return [{
            "id": d["userId"],
            "username": d["username"],
            "firstName": d["firstName"],
            "lastName": d["lastName"]
        } for d in self._dialogs.values()]


class ChatWindow(QMainWindow):
    update_ui_signal = pyqtSignal()  # Сигнал для обновления UI

    def __init__(self):
        super().__init__()
        self.update_ui_signal.connect(self.safe_update_ui)  # Соединяем сигнал со слотом
        self.setWindowTitle("Чат")
        self.setGeometry(100, 100, 800, 600)  # Позиция и размеры окна
        self.init_ui()

        # Инициализация хранилища диалогов
        self.dialogs = DialogList()
        self.dialogs.load()

        # Поток для работы с ботом Telegram
        self.bot_thread = threading.Thread(target=bot_polling_thread, daemon=True)
        self.bot_thread.start()

    def safe_update_ui(self):
        self.update_dialog_widget()
        self.update_dialog()

    def init_ui(self):
        # Создаем центральный виджет
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        # Главный горизонтальный лэйаут
        h_layout = QHBoxLayout()

        # Лист виджет для отображения списка чатов
        self.chat_list = QListWidget()
        self.chat_list.setMaximumWidth(self.width() // 7)
        self.chat_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.chat_list.customContextMenuRequested.connect(self.show_context_menu)
        # Подключаем сигнал itemClicked к методу show_dialog
        self.chat_list.itemClicked.connect(self.update_dialog)

        # Текстовое поле для отображения переписки
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)

        font = QFont()
        font.setPointSize(14)  # Устанавливаем размер шрифта в 14
        self.chat_display.setFont(font)

        # Вертикальный лэйаут для текстового поля и кнопок
        v_layout = QVBoxLayout()
        v_layout.addWidget(self.chat_display)

        # Горизонтальный лэйаут для поля ввода и кнопок
        input_layout = QHBoxLayout()

        # Текстовое поле для ввода сообщений
        self.message_input = QTextEdit()
        input_height = self.height() // 10
        self.message_input.setFixedHeight(input_height)
        input_layout.addWidget(self.message_input, 1)

        # Вертикальный лэйаут для кнопок
        button_layout = QVBoxLayout()
        button_height = int(2 * input_height / 3.4)  # Расчет высоты каждой кнопки
        self.send_button = QPushButton("Отправить")
        self.attach_button = QPushButton("Прикрепить файл")
        self.send_button.setFixedSize(150, button_height)
        self.attach_button.setFixedSize(150, button_height)
        button_layout.addWidget(self.send_button)
        button_layout.addWidget(self.attach_button)
        button_layout.setSpacing(8)  # Устанавливаем промежуток между кнопками
        input_layout.addLayout(button_layout)

        self.send_button.clicked.connect(self.send_message)
        self.attach_button.clicked.connect(self.attach_file)

        v_layout.addLayout(input_layout)

        # Добавляем виджеты в главный лэйут
        h_layout.addWidget(self.chat_list)
        h_layout.addLayout(v_layout)

        # Устанавливаем главный лэйут на центральный виджет
        central_widget.setLayout(h_layout)

    def show_context_menu(self, position):
        context_menu = QMenu(self)
        delete_action = context_menu.addAction("Удалить")
        answered_action = context_menu.addAction("Отметить отвеченным")
        action = context_menu.exec(QCursor.pos())  # Показываем меню в позиции курсора

        if action == delete_action:
            self.delete_chat()
            self.update_dialog_widget(refresh=True)
            self.update_dialog()

        elif action == answered_action:
            self.mark_chat_as_answered()
            self.update_dialog_widget()
            self.update_dialog()

    def delete_chat(self):
        if not self._is_chat_selected():
            return
        # Получаем текущий выбранный элемент
        user_id = self._current_user_id()
        self.dialogs.delete_chat(user_id)

    def mark_chat_as_answered(self):
        if not self._is_chat_selected():
            return
        # Получаем текущий выбранный элемент
        user_id = self._current_user_id()
        self.dialogs.mark_as_answered(user_id)

    def update_dialog(self, _=None):
        if self._is_chat_selected():
            dialog_text: str = self.dialogs.get_dialog_text(self._current_user_id())
            self.chat_display.setHtml(dialog_text)
            self.chat_display.moveCursor(QTextCursor.MoveOperation.End)
        else:
            self.chat_display.clear()

    def update_dialog_widget(self, refresh=False):
        def show_str(value: str | None) -> str:
            if value is None:
                return ""
            return value

        if refresh:
            self.chat_list.clear()

        users: list[dict] = self.dialogs.get_users()
        showed_chats = [self.chat_list.item(i) for i in range(self.chat_list.count())]
        showed_ids = [str(x.data(1)) for x in showed_chats]

        for user in users:
            if not str(user['id']) in showed_ids:
                new_chat = QListWidgetItem("{} {}\n({})".format(
                    user['firstName'], show_str(user['lastName']), user['id']
                ))
                new_chat.setData(1, str(user['id']))
                self.chat_list.addItem(new_chat)

        self.update_dialog_color()

    def update_dialog_color(self):
        for i in range(self.chat_list.count()):
            item: QListWidgetItem = self.chat_list.item(i)
            user_id: int = int(item.data(1))

            is_chat_answered: bool = self.dialogs.is_answered(user_id)
            if is_chat_answered:
                item.setBackground(QBrush(QColor("#FFFFFF")))
            else:
                item.setBackground(QBrush(QColor("#ADD8E6")))

    def _is_chat_selected(self) -> bool:
        now_item: QListWidgetItem = self.chat_list.currentItem()
        return bool(now_item)

    def _current_user_id(self) -> int:
        now_item: QListWidgetItem = self.chat_list.currentItem()
        return int(now_item.data(1))

    def send_message(self):
        if not self._is_chat_selected():
            return
        to_id: int = self._current_user_id()

        text = self.message_input.toPlainText()  # Считываем текст из QTextEdit
        if text.strip():  # Проверяем, что текст не пустой
            bot.send_message(to_id, text)  # Отправляем сообщение через бота
            self.dialogs.add_outbound(to_id, text)  # Сохраняем отправленное сообщение в истории диалогов
            self.update_dialog_widget()  # Обновляем виджет списка диалогов
            self.message_input.clear()  # Очищаем поле ввода после отправки
            self.update_dialog()
            self.update_dialog_color()

    def attach_file(self):
        if not self._is_chat_selected():
            return
        to_id: int = self._current_user_id()

        # Открытие диалога выбора файла
        file_path, _ = QFileDialog.getOpenFileName(self, "Выберите файл")
        if file_path:
            file_size = os.path.getsize(file_path)
            file_name = os.path.basename(file_path)
            if file_size > 10 * 1024 * 1024:  # Проверка размера файла (10 МБ)
                QMessageBox.warning(self, "Ошибка", f"Файл {file_name} слишком большой. Размер файла не должен превышать 10 МБ.")
            else:
                formated_size = format_file_size(file_size)
                with open(file_path, 'rb') as file:
                    bot.send_document(to_id, file)
                self.dialogs.add_outbound(to_id, f'[Отправлен файл {file_name} {formated_size}]')
                self.update_dialog()
                self.update_dialog_color()


app = QApplication(sys.argv)
window = ChatWindow()


# Логирование входящих сообщений
@bot.message_handler()
def handle_message_text(message):
    window.dialogs.add_inbound(message)
    window.update_ui_signal.emit()


@bot.message_handler(content_types=['sticker', 'photo', 'document',
                                    'video', 'voice', 'audio', 'animation'])
def handle_stickers(message):
    window.dialogs.add_inbound(message)
    window.update_ui_signal.emit()


def main():
    window.show()
    window.update_dialog_widget()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()

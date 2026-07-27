"""
gui
===

Графический интерфейс приложения на PyQt4: современная тёмная тема, поля
ввода параметров, выпадающий список версий Minecraft, цветной журнал событий,
блок статистики и кнопки управления (Старт / Стоп / Очистить лог / Сохранить
отчёт).

GUI не выполняет сетевую работу сам -- он лишь собирает конфигурацию, запускает
поток :class:`~mc_load_tester.tester.LoadTester` и отображает данные, которые
тот присылает через Qt-сигналы.
"""

from __future__ import annotations

import time

from PyQt4 import QtCore, QtGui

from . import logger as log_module
from . import reports
from .config import MINECRAFT_VERSIONS, DEFAULT_VERSION, TestConfig
from .tester import LoadTester


# ---------------------------------------------------------------------------
# Тёмная тема (Qt Style Sheet)
# ---------------------------------------------------------------------------
DARK_STYLESHEET = """
QWidget {
    background-color: #1e1f26;
    color: #e6e6e6;
    font-family: "Segoe UI", "DejaVu Sans", Arial, sans-serif;
    font-size: 13px;
}
QGroupBox {
    border: 1px solid #33353f;
    border-radius: 6px;
    margin-top: 12px;
    padding: 8px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #8ab4f8;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #2a2c36;
    border: 1px solid #3a3d49;
    border-radius: 4px;
    padding: 5px;
    selection-background-color: #4c6ef5;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid #4c6ef5;
}
QComboBox QAbstractItemView {
    background-color: #2a2c36;
    selection-background-color: #4c6ef5;
    border: 1px solid #3a3d49;
}
QTextEdit {
    background-color: #16171d;
    border: 1px solid #33353f;
    border-radius: 6px;
    font-family: "Consolas", "DejaVu Sans Mono", monospace;
    font-size: 12px;
}
QPushButton {
    background-color: #2f3240;
    border: 1px solid #3a3d49;
    border-radius: 5px;
    padding: 8px 14px;
    font-weight: bold;
}
QPushButton:hover { background-color: #3a3e4e; }
QPushButton:pressed { background-color: #4c6ef5; }
QPushButton:disabled { color: #6b6d75; background-color: #23242c; }
QPushButton#startButton { background-color: #2e7d32; border: none; }
QPushButton#startButton:hover { background-color: #388e3c; }
QPushButton#stopButton { background-color: #c62828; border: none; }
QPushButton#stopButton:hover { background-color: #d32f2f; }
QLabel#statValue { font-size: 18px; font-weight: bold; color: #8ab4f8; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid #3a3d49; border-radius: 3px; background: #2a2c36;
}
QCheckBox::indicator:checked { background: #4c6ef5; border: 1px solid #4c6ef5; }
QScrollBar:vertical { background: #16171d; width: 12px; margin: 0; }
QScrollBar::handle:vertical { background: #3a3d49; border-radius: 6px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


class MainWindow(QtGui.QWidget):
    """Главное окно приложения."""

    def __init__(self, parent=None):
        super(MainWindow, self).__init__(parent)
        self.tester = None          # текущий поток LoadTester (или None)
        self._log_lines = []         # накопленный журнал: список (level, message)
        self._last_stats = {}        # последний снимок статистики (для отчёта)

        self.setWindowTitle("Minecraft Load Tester")
        self.resize(1040, 680)
        self._build_ui()
        self._apply_theme()

    # -- построение интерфейса -------------------------------------------
    def _build_ui(self) -> None:
        root = QtGui.QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        root.addLayout(self._build_left_panel(), 0)
        root.addLayout(self._build_right_panel(), 1)

    def _build_left_panel(self) -> QtGui.QVBoxLayout:
        left = QtGui.QVBoxLayout()
        left.setSpacing(10)

        # --- Группа параметров подключения ---
        conn_group = QtGui.QGroupBox("Параметры сервера")
        form = QtGui.QFormLayout(conn_group)
        form.setSpacing(8)

        self.host_edit = QtGui.QLineEdit("127.0.0.1")
        self.host_edit.setPlaceholderText("IP или домен сервера")

        self.port_spin = QtGui.QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(25565)

        self.version_combo = QtGui.QComboBox()
        for label in MINECRAFT_VERSIONS:
            self.version_combo.addItem(
                "%s  (протокол %d)" % (label, MINECRAFT_VERSIONS[label]), label
            )
        self.version_combo.setCurrentIndex(
            list(MINECRAFT_VERSIONS.keys()).index(DEFAULT_VERSION)
        )

        form.addRow("IP сервера:", self.host_edit)
        form.addRow("Порт:", self.port_spin)
        form.addRow("Версия Minecraft:", self.version_combo)
        left.addWidget(conn_group)

        # --- Группа параметров нагрузки ---
        load_group = QtGui.QGroupBox("Параметры нагрузки")
        load_form = QtGui.QFormLayout(load_group)
        load_form.setSpacing(8)

        self.clients_spin = QtGui.QSpinBox()
        self.clients_spin.setRange(1, 100000)
        self.clients_spin.setValue(20)

        self.delay_spin = QtGui.QDoubleSpinBox()
        self.delay_spin.setRange(0.0, 60.0)
        self.delay_spin.setSingleStep(0.05)
        self.delay_spin.setDecimals(2)
        self.delay_spin.setValue(0.10)
        self.delay_spin.setSuffix(" c")

        self.hold_spin = QtGui.QDoubleSpinBox()
        self.hold_spin.setRange(0.0, 3600.0)
        self.hold_spin.setDecimals(1)
        self.hold_spin.setValue(5.0)
        self.hold_spin.setSuffix(" c")

        self.prefix_edit = QtGui.QLineEdit("LoadBot")
        self.prefix_edit.setMaxLength(16)
        self.prefix_edit.setPlaceholderText("Префикс ника")

        load_form.addRow("Количество клиентов:", self.clients_spin)
        load_form.addRow("Задержка между подключениями:", self.delay_spin)
        load_form.addRow("Время удержания соединения:", self.hold_spin)
        load_form.addRow("Префикс ника:", self.prefix_edit)
        left.addWidget(load_group)

        # --- Группа Ramp-Up ---
        ramp_group = QtGui.QGroupBox("Постепенное наращивание (Ramp-Up)")
        ramp_form = QtGui.QFormLayout(ramp_group)
        ramp_form.setSpacing(8)

        self.ramp_check = QtGui.QCheckBox("Включить Ramp-Up")

        self.ramp_steps_spin = QtGui.QSpinBox()
        self.ramp_steps_spin.setRange(1, 100)
        self.ramp_steps_spin.setValue(5)
        self.ramp_steps_spin.setEnabled(False)

        self.ramp_interval_spin = QtGui.QDoubleSpinBox()
        self.ramp_interval_spin.setRange(0.0, 60.0)
        self.ramp_interval_spin.setDecimals(1)
        self.ramp_interval_spin.setValue(1.0)
        self.ramp_interval_spin.setSuffix(" c")
        self.ramp_interval_spin.setEnabled(False)

        self.ramp_check.stateChanged.connect(self._on_ramp_toggled)

        ramp_form.addRow(self.ramp_check)
        ramp_form.addRow("Количество волн:", self.ramp_steps_spin)
        ramp_form.addRow("Пауза между волнами:", self.ramp_interval_spin)
        left.addWidget(ramp_group)

        # --- Кнопки управления ---
        buttons = QtGui.QHBoxLayout()
        self.start_button = QtGui.QPushButton("Старт")
        self.start_button.setObjectName("startButton")
        self.stop_button = QtGui.QPushButton("Стоп")
        self.stop_button.setObjectName("stopButton")
        self.stop_button.setEnabled(False)
        self.start_button.clicked.connect(self.start_test)
        self.stop_button.clicked.connect(self.stop_test)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        left.addLayout(buttons)

        left.addStretch(1)

        # Предупреждение о назначении инструмента.
        notice = QtGui.QLabel(
            "Используйте только на собственных серверах или с явного разрешения."
        )
        notice.setWordWrap(True)
        notice.setStyleSheet("color: #8a8d99; font-size: 11px;")
        left.addWidget(notice)

        return left

    def _build_right_panel(self) -> QtGui.QVBoxLayout:
        right = QtGui.QVBoxLayout()
        right.setSpacing(10)

        # --- Статистика ---
        stats_group = QtGui.QGroupBox("Статистика")
        stats_grid = QtGui.QGridLayout(stats_group)
        stats_grid.setSpacing(10)

        self.stat_success = self._make_stat_widget(stats_grid, 0, 0, "Успешные подключения")
        self.stat_errors = self._make_stat_widget(stats_grid, 0, 1, "Ошибки")
        self.stat_active = self._make_stat_widget(stats_grid, 0, 2, "Активные соединения")
        self.stat_avg = self._make_stat_widget(stats_grid, 1, 0, "Среднее время подключения")
        self.stat_elapsed = self._make_stat_widget(stats_grid, 1, 1, "Общее время теста")
        self.stat_total = self._make_stat_widget(stats_grid, 1, 2, "Всего завершено")
        right.addWidget(stats_group)

        # --- Журнал ---
        log_group = QtGui.QGroupBox("Журнал событий")
        log_layout = QtGui.QVBoxLayout(log_group)
        self.log_view = QtGui.QTextEdit()
        self.log_view.setReadOnly(True)
        log_layout.addWidget(self.log_view)

        log_buttons = QtGui.QHBoxLayout()
        self.clear_button = QtGui.QPushButton("Очистить лог")
        self.save_button = QtGui.QPushButton("Сохранить отчёт")
        self.clear_button.clicked.connect(self.clear_log)
        self.save_button.clicked.connect(self.save_report)
        log_buttons.addStretch(1)
        log_buttons.addWidget(self.clear_button)
        log_buttons.addWidget(self.save_button)
        log_layout.addLayout(log_buttons)

        right.addWidget(log_group, 1)
        return right

    def _make_stat_widget(self, grid, row, col, title):
        """Создать ячейку статистики (заголовок + значение) и вернуть QLabel значения."""
        box = QtGui.QVBoxLayout()
        title_label = QtGui.QLabel(title)
        title_label.setStyleSheet("color: #9aa0aa; font-size: 11px;")
        value_label = QtGui.QLabel("0")
        value_label.setObjectName("statValue")
        box.addWidget(title_label)
        box.addWidget(value_label)
        container = QtGui.QWidget()
        container.setLayout(box)
        grid.addWidget(container, row, col)
        return value_label

    def _apply_theme(self) -> None:
        self.setStyleSheet(DARK_STYLESHEET)

    # -- обработчики -------------------------------------------------------
    def _on_ramp_toggled(self, state) -> None:
        enabled = state == QtCore.Qt.Checked
        self.ramp_steps_spin.setEnabled(enabled)
        self.ramp_interval_spin.setEnabled(enabled)

    def _collect_config(self) -> TestConfig:
        """Собрать :class:`TestConfig` из полей ввода."""
        version = self.version_combo.itemData(self.version_combo.currentIndex())
        # В PyQt4 itemData может возвращать QVariant -- приводим к str.
        version = self._to_str(version) or DEFAULT_VERSION
        return TestConfig(
            host=self._to_str(self.host_edit.text()).strip() or "127.0.0.1",
            port=self.port_spin.value(),
            version=version,
            client_count=self.clients_spin.value(),
            connect_delay=self.delay_spin.value(),
            hold_time=self.hold_spin.value(),
            nick_prefix=self._to_str(self.prefix_edit.text()).strip(),
            ramp_up=self.ramp_check.isChecked(),
            ramp_steps=self.ramp_steps_spin.value(),
            ramp_interval=self.ramp_interval_spin.value(),
        )

    @staticmethod
    def _to_str(value) -> str:
        """Привести QString/QVariant/str к обычной строке Python."""
        if value is None:
            return ""
        try:
            # QVariant -> значение
            if hasattr(value, "toString"):
                return str(value.toString())
        except Exception:
            pass
        return str(value)

    def start_test(self) -> None:
        """Запустить нагрузочный тест в отдельном потоке."""
        if self.tester is not None and self.tester.isRunning():
            return

        config = self._collect_config()
        if not config.host:
            self.append_log(log_module.LEVEL_ERROR, "Не указан адрес сервера.")
            return

        self.tester = LoadTester(config)
        self.tester.log_message.connect(self.append_log)
        self.tester.stats_updated.connect(self.update_stats)
        self.tester.finished_test.connect(self.on_test_finished)

        self._set_running_state(True)
        self.tester.start()

    def stop_test(self) -> None:
        """Запросить остановку текущего теста."""
        if self.tester is not None and self.tester.isRunning():
            self.append_log(log_module.LEVEL_WARNING, "Запрошена остановка теста...")
            self.stop_button.setEnabled(False)
            self.tester.stop()

    def on_test_finished(self, final_stats) -> None:
        """Слот завершения теста: вернуть кнопки в исходное состояние."""
        self._last_stats = dict(final_stats)
        self.update_stats(final_stats)
        self._set_running_state(False)

    def _set_running_state(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        # Блокируем изменение параметров во время теста.
        for widget in (
            self.host_edit, self.port_spin, self.version_combo,
            self.clients_spin, self.delay_spin, self.hold_spin,
            self.prefix_edit, self.ramp_check, self.ramp_steps_spin,
            self.ramp_interval_spin,
        ):
            widget.setEnabled(not running)
        if not running:
            # Восстанавливаем зависимость полей ramp-up от чекбокса.
            self._on_ramp_toggled(
                QtCore.Qt.Checked if self.ramp_check.isChecked() else QtCore.Qt.Unchecked
            )

    # -- журнал и статистика ----------------------------------------------
    def append_log(self, level, message) -> None:
        """Добавить цветную строку в журнал и сохранить её для отчёта."""
        level = self._to_str(level)
        message = self._to_str(message)
        color = log_module.color_for(level)
        timestamp = time.strftime("%H:%M:%S")
        html = (
            '<span style="color:#6b6d75;">[%s]</span> '
            '<span style="color:%s;">[%s]</span> '
            '<span style="color:#e6e6e6;">%s</span>'
            % (timestamp, color, level, self._escape(message))
        )
        self.log_view.append(html)
        self._log_lines.append((level, message))

    @staticmethod
    def _escape(text: str) -> str:
        """Экранировать HTML-спецсимволы для безопасного вывода в журнал."""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def update_stats(self, stats) -> None:
        """Обновить блок статистики из снимка."""
        self._last_stats = dict(stats)
        self.stat_success.setText(str(stats.get("success", 0)))
        self.stat_errors.setText(str(stats.get("errors", 0)))
        self.stat_active.setText(str(stats.get("active", 0)))
        self.stat_avg.setText("%.3f c" % stats.get("avg_connect_time", 0.0))
        self.stat_elapsed.setText("%.1f c" % stats.get("elapsed", 0.0))
        self.stat_total.setText(str(stats.get("total", 0)))

    def clear_log(self) -> None:
        """Очистить журнал событий."""
        self.log_view.clear()
        self._log_lines = []

    def save_report(self) -> None:
        """Сохранить отчёт (CSV или JSON) через диалог выбора файла."""
        if not self._log_lines and not self._last_stats:
            self.append_log(log_module.LEVEL_WARNING, "Нет данных для сохранения.")
            return

        default_name = "mc_load_report_%s" % time.strftime("%Y%m%d_%H%M%S")
        selected_filter = QtCore.QString() if hasattr(QtCore, "QString") else ""
        path = QtGui.QFileDialog.getSaveFileName(
            self,
            "Сохранить отчёт",
            default_name,
            "JSON (*.json);;CSV (*.csv)",
        )
        # В PyQt4 может вернуться кортеж или QString в зависимости от API-режима.
        if isinstance(path, (tuple, list)):
            path = path[0]
        path = self._to_str(path).strip()
        if not path:
            return

        config = self._collect_config()
        stats = self._last_stats or {}
        try:
            if path.lower().endswith(".csv"):
                reports.save_csv(path, config, stats, self._log_lines)
            else:
                if not path.lower().endswith(".json"):
                    path += ".json"
                reports.save_json(path, config, stats, self._log_lines)
            self.append_log(log_module.LEVEL_SUCCESS, "Отчёт сохранён: %s" % path)
        except (OSError, IOError) as exc:
            self.append_log(log_module.LEVEL_ERROR, "Ошибка сохранения: %s" % exc)

    # -- корректное завершение --------------------------------------------
    def closeEvent(self, event) -> None:
        """Остановить активный тест перед закрытием окна."""
        if self.tester is not None and self.tester.isRunning():
            self.tester.stop()
            self.tester.wait(3000)
        event.accept()

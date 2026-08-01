"""
reports
=======

Сохранение результатов нагрузочного теста в форматы CSV и JSON.

Отчёт содержит параметры запуска, итоговую статистику и полный журнал
событий, что удобно для последующего анализа производительности сервера.
"""

from __future__ import annotations

import csv
import json
import time

from .config import TestConfig


def _timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def save_json(path: str, config: TestConfig, stats: dict, log_lines: list) -> None:
    """Сохранить полный отчёт в JSON.

    :param path: путь к создаваемому файлу.
    :param config: конфигурация запуска.
    :param stats: итоговый снимок статистики.
    :param log_lines: список кортежей ``(уровень, текст)``.
    """
    report = {
        "generated_at": _timestamp(),
        "config": config.to_dict(),
        "statistics": stats,
        "log": [{"level": lvl, "message": msg} for lvl, msg in log_lines],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)


def save_csv(path: str, config: TestConfig, stats: dict, log_lines: list) -> None:
    """Сохранить отчёт в CSV (секции: параметры, статистика, журнал)."""
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)

        writer.writerow(["# Отчёт нагрузочного тестирования Minecraft-сервера"])
        writer.writerow(["Сгенерирован", _timestamp()])
        writer.writerow([])

        writer.writerow(["== Параметры теста =="])
        for key, value in config.to_dict().items():
            writer.writerow([key, value])
        writer.writerow([])

        writer.writerow(["== Статистика =="])
        for key, value in stats.items():
            if isinstance(value, dict):
                # Разворачиваем вложенные словари (например, errors_by_type).
                for sub_key, sub_value in value.items():
                    writer.writerow(["%s.%s" % (key, sub_key), sub_value])
            else:
                writer.writerow([key, value])
        writer.writerow([])

        writer.writerow(["== Журнал =="])
        writer.writerow(["level", "message"])
        for level, message in log_lines:
            writer.writerow([level, message])

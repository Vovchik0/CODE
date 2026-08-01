"""
Корневой conftest: гарантирует, что корень проекта есть в ``sys.path``, чтобы
тесты могли импортировать пакет ``mc_load_tester`` и модуль ``web_server``
независимо от способа запуска pytest.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

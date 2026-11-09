"""All project entry points select the same engine without downloads or real DB access."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from agents.chat_factory import build_chatbot
from agents.guidance import Guidance
from agents.model_chatbot import DEFAULT_CHAT_MODEL


class ChatFactoryTests(unittest.TestCase):
    def test_legacy_default_and_model_precedence(self):
        guide = Guidance()
        self.assertFalse(getattr(build_chatbot(guide), 'supports_turns', False))
        for model, rag, expected in [
                (None, None, DEFAULT_CHAT_MODEL), (' ', ' ', DEFAULT_CHAT_MODEL),
                (' selected ', 'older', 'selected'), (None, 'older', 'older')]:
            with self.subTest(model=model, rag=rag):
                bot = build_chatbot(guide, engine='model', model=model, rag_model=rag)
                self.assertEqual(bot.engine, 'model_rag')
                self.assertEqual(bot.model, expected)

    def test_engine_typo_does_not_silently_start_old_chatbot(self):
        with self.assertRaises(ValueError):
            build_chatbot(Guidance(), engine='modle')

    def test_tower_input_and_preview_use_same_model_and_engine(self):
        from agents.chat_api import build_chatbot_from_env, add_chat_routes
        from agents.lost_api import from_environment
        from tools.run_chat_widget_demo import create_app
        from fastapi import FastAPI
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
                'LF_CHAT_ENGINE': 'model', 'LF_CHAT_MODEL': DEFAULT_CHAT_MODEL,
                'LF_CHAT_RAG_MODEL': 'old-model',
                'LF_CHAT_DEMO_DB': str(Path(folder)/'input.sqlite3'),
                'TOWER_CHAT_DEMO_DB': str(Path(folder)/'tower.sqlite3')}, clear=True):
            tower = FastAPI()
            add_chat_routes(tower, build_chatbot_from_env())
            for app, route, model_key, engine_key in [
                    (tower, '/chat/health', 'model', 'engine'),
                    (from_environment(), '/health', 'chat_model', 'chat_engine'),
                    (create_app(Path(folder)/'preview.sqlite3', engine='model'),
                     '/chat/health', 'model', 'engine')]:
                with TestClient(app, base_url='http://127.0.0.1') as client:
                    health = client.get(route).json()
                    self.assertEqual(health[model_key], DEFAULT_CHAT_MODEL)
                    self.assertEqual(health[engine_key], 'model_rag')

    def test_real_database_setting_never_initializes_demo_database(self):
        from agents.chat_api import build_chatbot_from_env
        with patch.dict(os.environ, {'LF_CHAT_ENGINE': 'model',
                'LF_CHAT_DATABASE_URL': 'synthetic-dsn', 'TOWER_CHAT_DEMO_DB': 'ignored'}, clear=True), \
                patch('agents.chat_search.DemoItemDatabase') as demo:
            bot = build_chatbot_from_env()
            self.assertEqual(bot.search.mode, 'postgres')
            demo.assert_not_called()

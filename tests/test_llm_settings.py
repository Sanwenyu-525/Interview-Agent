import tempfile
import unittest
from pathlib import Path

from interview_agent.agent import InterviewAgent, RuleBasedQuestionGenerator
from interview_agent.llm import LlmEvaluator, LlmQuestionGenerator
from interview_agent.service import InterviewService
from interview_agent.settings import LLMProfile, InMemoryLLMSettingsStore, SQLiteLLMSettingsStore


class LLMSettingsTests(unittest.TestCase):
    def _profile(self, profile_id="p1", name="Agnes 工作模型"):
        store = InMemoryLLMSettingsStore()
        config = store.config_from_payload(
            {
                "provider": "openai_compatible",
                "provider_name": "Agnes",
                "base_url": "https://example.test/v1",
                "api_key": "secret",
                "model": "demo-model",
            }
        )
        return LLMProfile(profile_id, name, config)

    def test_profile_store_supports_crud_and_active_selection(self):
        store = InMemoryLLMSettingsStore()
        profile = self._profile()

        store.save_profile(profile)
        self.assertEqual([item.profile_id for item in store.list_profiles()], ["p1"])
        self.assertIs(store.get_profile("p1"), profile)

        updated = LLMProfile(profile.profile_id, "Agnes 生产模型", profile.config)
        store.save_profile(updated)
        self.assertEqual(store.get_profile("p1").name, "Agnes 生产模型")

        store.set_active("p1")
        self.assertEqual(store.active_profile_id(), "p1")
        store.delete_profile("p1")
        self.assertIsNone(store.active_profile_id())
        self.assertEqual(store.list_profiles(), ())

    def test_sqlite_profile_store_survives_reopen_and_public_payload_hides_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = str(Path(temp_dir) / "settings.db")
            first = SQLiteLLMSettingsStore(database)
            first.save_profile(self._profile())
            first.set_active("p1")

            second = SQLiteLLMSettingsStore(database)

            self.assertEqual(second.active_profile_id(), "p1")
            restored = second.get_profile("p1")
            self.assertEqual(restored.name, "Agnes 工作模型")
            self.assertEqual(restored.config.api_key, "secret")
            self.assertNotIn("api_key", restored.public_payload(active=True))

    def test_service_profile_crud_switches_runtime_agent(self):
        service = InterviewService(llm_settings_store=InMemoryLLMSettingsStore())

        created = service.create_llm_profile({
            "name": "Agnes 工作模型",
            "provider": "openai_compatible",
            "provider_name": "Agnes",
            "base_url": "https://example.test/v1",
            "api_key": "secret",
            "model": "demo-model",
        })

        self.assertFalse(created["active"])
        self.assertEqual(len(service.get_llm_profiles()["profiles"]), 1)
        service.activate_llm_profile(created["id"])
        self.assertTrue(service.get_llm_profiles()["profiles"][0]["active"])
        self.assertTrue(service.get_llm_settings()["configured"])

        service.delete_llm_profile(created["id"])
        self.assertFalse(service.get_llm_settings()["configured"])
        self.assertEqual(service.get_llm_profiles()["profiles"], [])

    def test_update_llm_settings_switches_runtime_agent_and_hides_api_key(self):
        store = InMemoryLLMSettingsStore()
        service = InterviewService(llm_settings_store=store)

        result = service.update_llm_settings(
            {
                "provider": "openai_compatible",
                "provider_name": "Agnes",
                "base_url": "https://example.test/v1",
                "api_key": "secret",
                "model": "demo-model",
            }
        )

        self.assertTrue(result["configured"])
        self.assertTrue(result["api_key_set"])
        self.assertEqual(result["provider_name"], "Agnes")
        self.assertNotIn("secret", result.values())
        self.assertIsInstance(service.agent.question_generator, LlmQuestionGenerator)
        self.assertIsInstance(service.agent.evaluator, LlmEvaluator)
        self.assertEqual(store.get().api_key, "secret")

    def test_switching_back_to_rule_based_clears_runtime_llm(self):
        service = InterviewService(llm_settings_store=InMemoryLLMSettingsStore())
        service.update_llm_settings(
            {
                "provider": "openai_compatible",
                "provider_name": "DeepSeek",
                "base_url": "https://example.test/v1",
                "api_key": "secret",
                "model": "demo-model",
            }
        )

        result = service.update_llm_settings({"provider": "rule_based"})

        self.assertFalse(result["configured"])
        self.assertIsInstance(service.agent, InterviewAgent)
        self.assertIsInstance(service.agent.question_generator, RuleBasedQuestionGenerator)

    def test_sqlite_settings_store_survives_reopen(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = str(Path(temp_dir) / "settings.db")
            first = SQLiteLLMSettingsStore(database)
            first.save(first.config_from_payload({
                "provider": "openai_compatible",
                "provider_name": "DeepSeek",
                "base_url": "https://example.test/v1",
                "api_key": "secret",
                "model": "demo-model",
            }))

            second = SQLiteLLMSettingsStore(database)

            self.assertEqual(second.get().model, "demo-model")
            self.assertEqual(second.get().api_key, "secret")

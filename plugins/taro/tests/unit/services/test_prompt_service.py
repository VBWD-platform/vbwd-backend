"""Unit tests for PromptService (TDD - Red phase)"""
import json
import os
import tempfile
import pytest
from pathlib import Path


class TestPromptServiceLoad:
    """Tests for loading prompts from file"""

    def test_load_prompts_success(self):
        """Should load prompts from JSON file successfully"""
        from plugins.taro.src.services.prompt_service import PromptService

        # Create temp file with test prompts
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            test_prompts = {
                "_meta": {"version": "1.0", "plugin": "taro"},
                "_defaults": {"temperature": 0.7, "max_tokens": 2000, "timeout": 30},
                "test_prompt": {"template": "Test: {{value}}", "variables": ["value"]},
            }
            json.dump(test_prompts, f)
            temp_file = f.name

        try:
            service = PromptService(temp_file)
            assert service.prompts is not None
            assert "test_prompt" in service.prompts
            assert service.defaults["temperature"] == 0.7
        finally:
            os.unlink(temp_file)

    def test_load_prompts_missing_file_error(self):
        """Should raise FileNotFoundError if file doesn't exist"""
        from plugins.taro.src.services.prompt_service import PromptService

        with pytest.raises(FileNotFoundError) as exc_info:
            PromptService("/nonexistent/path/prompts.json")

        assert "Prompt file not found" in str(exc_info.value)

    def test_load_prompts_invalid_json_error(self):
        """Should raise JSONDecodeError if JSON is invalid"""
        from plugins.taro.src.services.prompt_service import PromptService

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("invalid json {]")
            temp_file = f.name

        try:
            with pytest.raises(json.JSONDecodeError):
                PromptService(temp_file)
        finally:
            os.unlink(temp_file)


class TestPromptServiceGetPrompt:
    """Tests for retrieving prompts with resolved metadata"""

    def _make_service_with_prompts(self):
        """Helper to create service with test prompts"""
        from plugins.taro.src.services.prompt_service import PromptService

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            test_prompts = {
                "_defaults": {"temperature": 0.7, "max_tokens": 2000, "timeout": 30},
                "base_prompt": {"template": "Base: {{data}}", "variables": ["data"]},
                "override_prompt": {
                    "template": "Override: {{data}}",
                    "variables": ["data"],
                    "temperature": 0.9,
                    "max_tokens": 500,
                },
            }
            json.dump(test_prompts, f)
            temp_file = f.name

        service = PromptService(temp_file)
        service._temp_file = temp_file  # Track for cleanup
        return service

    def test_get_prompt_merges_defaults(self):
        """Should merge prompt with defaults"""
        service = self._make_service_with_prompts()

        try:
            prompt = service.get_prompt("base_prompt")

            # Should include defaults
            assert prompt["temperature"] == 0.7
            assert prompt["max_tokens"] == 2000
            assert prompt["timeout"] == 30
            # Should include prompt-specific fields
            assert prompt["template"] == "Base: {{data}}"
            assert prompt["variables"] == ["data"]
        finally:
            os.unlink(service._temp_file)

    def test_get_prompt_overrides_defaults(self):
        """Should override defaults with prompt-specific metadata"""
        service = self._make_service_with_prompts()

        try:
            prompt = service.get_prompt("override_prompt")

            # Should use overrides, not defaults
            assert prompt["temperature"] == 0.9
            assert prompt["max_tokens"] == 500
            # But inherit timeout from defaults
            assert prompt["timeout"] == 30
        finally:
            os.unlink(service._temp_file)

    def test_get_prompt_not_found_error(self):
        """Should raise ValueError if prompt doesn't exist"""
        from plugins.taro.src.services.prompt_service import PromptService

        service = self._make_service_with_prompts()

        try:
            with pytest.raises(ValueError) as exc_info:
                service.get_prompt("nonexistent")

            assert "Prompt not found" in str(exc_info.value)
        finally:
            os.unlink(service._temp_file)

    def test_get_prompt_rejects_internal_keys(self):
        """Should not allow access to internal keys (starting with _)"""
        from plugins.taro.src.services.prompt_service import PromptService

        service = self._make_service_with_prompts()

        try:
            with pytest.raises(ValueError) as exc_info:
                service.get_prompt("_defaults")

            assert "internal prompt" in str(exc_info.value).lower()
        finally:
            os.unlink(service._temp_file)


class TestPromptServiceRender:
    """Tests for rendering prompt templates"""

    def _make_service_with_prompts(self):
        """Helper to create service with test prompts"""
        from plugins.taro.src.services.prompt_service import PromptService

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            test_prompts = {
                "_defaults": {"temperature": 0.7, "max_tokens": 2000, "timeout": 30},
                "simple_prompt": {"template": "Hello {{name}}", "variables": ["name"]},
                "complex_prompt": {
                    "template": "Card: {{card_name}}\nOrientation: {{orientation}}\nMeaning: {{meaning}}",
                    "variables": ["card_name", "orientation", "meaning"],
                },
            }
            json.dump(test_prompts, f)
            temp_file = f.name

        service = PromptService(temp_file)
        service._temp_file = temp_file
        return service

    def test_render_with_context(self):
        """Should render template with provided context"""
        service = self._make_service_with_prompts()

        try:
            result = service.render("simple_prompt", {"name": "Alice"})
            assert result == "Hello Alice"
        finally:
            os.unlink(service._temp_file)

    def test_render_multiline_template(self):
        """Should render multiline templates correctly"""
        service = self._make_service_with_prompts()

        try:
            result = service.render(
                "complex_prompt",
                {
                    "card_name": "The Fool",
                    "orientation": "Upright",
                    "meaning": "New beginnings",
                },
            )

            assert "Card: The Fool" in result
            assert "Orientation: Upright" in result
            assert "Meaning: New beginnings" in result
        finally:
            os.unlink(service._temp_file)

    def test_render_invalid_template_error(self):
        """Should raise error if template syntax is invalid"""
        from plugins.taro.src.services.prompt_service import PromptService

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            test_prompts = {
                "_defaults": {},
                "bad_prompt": {
                    "template": "Invalid: {{unclosed}",
                    "variables": ["unclosed"],
                },
            }
            json.dump(test_prompts, f)
            temp_file = f.name

        try:
            service = PromptService(temp_file)
            with pytest.raises(ValueError) as exc_info:
                service.render("bad_prompt", {})

            assert "Error rendering prompt" in str(exc_info.value)
        finally:
            os.unlink(temp_file)

    def test_render_missing_context_variable(self):
        """Should handle missing context variables gracefully"""
        service = self._make_service_with_prompts()

        try:
            # Jinja2 renders missing vars as empty string by default
            result = service.render("simple_prompt", {})
            assert "Hello" in result
        finally:
            os.unlink(service._temp_file)


class TestPromptServiceValidate:
    """Tests for template validation"""

    def _make_service(self):
        """Helper to create service"""
        from plugins.taro.src.services.prompt_service import PromptService

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            test_prompts = {
                "_defaults": {},
                "dummy": {"template": "dummy", "variables": []},
            }
            json.dump(test_prompts, f)
            temp_file = f.name

        service = PromptService(temp_file)
        service._temp_file = temp_file
        return service

    def test_validate_template_valid_syntax(self):
        """Should return True for valid template syntax"""
        service = self._make_service()

        try:
            assert service.validate_template("Hello {{name}}", ["name"]) is True
            assert service.validate_template("Simple text", []) is True
        finally:
            os.unlink(service._temp_file)

    def test_validate_template_invalid_syntax(self):
        """Should raise ValueError for invalid template syntax"""
        service = self._make_service()

        try:
            with pytest.raises(ValueError) as exc_info:
                service.validate_template("Invalid {{unclosed", ["unclosed"])

            assert "Invalid template" in str(exc_info.value)
        finally:
            os.unlink(service._temp_file)


class TestPromptServiceUpdate:
    """Tests for updating prompts"""

    def _make_service_with_prompts(self):
        """Helper to create service with test prompts"""
        from plugins.taro.src.services.prompt_service import PromptService

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            test_prompts = {
                "_defaults": {"temperature": 0.7, "max_tokens": 2000, "timeout": 30},
                "test_prompt": {
                    "template": "Original: {{value}}",
                    "variables": ["value"],
                },
            }
            json.dump(test_prompts, f)
            temp_file = f.name

        service = PromptService(temp_file)
        service._temp_file = temp_file
        return service

    def test_update_prompt(self):
        """Should update prompt template and variables"""
        service = self._make_service_with_prompts()

        try:
            updated = service.update_prompt(
                "test_prompt",
                {"template": "Updated: {{value}}", "variables": ["value", "extra"]},
            )

            assert updated["template"] == "Updated: {{value}}"
            assert updated["variables"] == ["value", "extra"]
        finally:
            os.unlink(service._temp_file)

    def test_update_prompt_metadata_override(self):
        """Should update metadata overrides"""
        service = self._make_service_with_prompts()

        try:
            updated = service.update_prompt(
                "test_prompt", {"temperature": 0.9, "max_tokens": 1000}
            )

            assert updated["temperature"] == 0.9
            assert updated["max_tokens"] == 1000
        finally:
            os.unlink(service._temp_file)

    def test_update_prompt_rejects_internal_keys(self):
        """Should not allow updating internal keys"""
        service = self._make_service_with_prompts()

        try:
            with pytest.raises(ValueError) as exc_info:
                service.update_prompt("_defaults", {"temperature": 0.5})

            assert "internal prompt" in str(exc_info.value).lower()
        finally:
            os.unlink(service._temp_file)

    def test_update_prompt_persists_to_file(self):
        """Should persist changes to file"""
        service = self._make_service_with_prompts()

        try:
            service.update_prompt("test_prompt", {"template": "Persisted: {{value}}"})

            # Load file again to verify persistence
            with open(service._temp_file) as f:
                data = json.load(f)

            assert "Persisted" in data["test_prompt"]["template"]
        finally:
            os.unlink(service._temp_file)


class TestPromptServiceUpdateDefaults:
    """Tests for updating default metadata"""

    def _make_service(self):
        """Helper to create service"""
        from plugins.taro.src.services.prompt_service import PromptService

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            test_prompts = {
                "_defaults": {"temperature": 0.7, "max_tokens": 2000, "timeout": 30},
                "test": {"template": "test", "variables": []},
            }
            json.dump(test_prompts, f)
            temp_file = f.name

        service = PromptService(temp_file)
        service._temp_file = temp_file
        return service

    def test_update_defaults(self):
        """Should update default metadata"""
        service = self._make_service()

        try:
            updated = service.update_defaults({"temperature": 0.8, "max_tokens": 3000})

            assert updated["temperature"] == 0.8
            assert updated["max_tokens"] == 3000
            assert updated["timeout"] == 30  # Unchanged
        finally:
            os.unlink(service._temp_file)

    def test_update_defaults_persists_to_file(self):
        """Should persist default changes to file"""
        service = self._make_service()

        try:
            service.update_defaults({"temperature": 0.9})

            # Reload and verify
            with open(service._temp_file) as f:
                data = json.load(f)

            assert data["_defaults"]["temperature"] == 0.9
        finally:
            os.unlink(service._temp_file)


class TestPromptServiceReset:
    """Tests for resetting to distribution defaults"""

    def test_reset_to_defaults(self):
        """Should reset to .dist file"""
        from plugins.taro.src.services.prompt_service import PromptService

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create .dist file
            dist_file = os.path.join(tmpdir, "prompts.json.dist")
            with open(dist_file, "w") as f:
                json.dump(
                    {
                        "_defaults": {"temperature": 0.5},
                        "original": {"template": "Original", "variables": []},
                    },
                    f,
                )

            # Create working file with different content
            work_file = os.path.join(tmpdir, "prompts.json")
            with open(work_file, "w") as f:
                json.dump(
                    {
                        "_defaults": {"temperature": 0.9},
                        "modified": {"template": "Modified", "variables": []},
                    },
                    f,
                )

            service = PromptService(work_file)
            service.reset_to_defaults()

            # Verify reset
            with open(work_file) as f:
                data = json.load(f)

            assert data["_defaults"]["temperature"] == 0.5
            assert "original" in data
            assert "modified" not in data

    def test_reset_to_defaults_missing_dist_file(self):
        """Should raise error if .dist file doesn't exist"""
        from plugins.taro.src.services.prompt_service import PromptService

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"_defaults": {}, "test": {}}, f)
            temp_file = f.name

        try:
            service = PromptService(temp_file)
            with pytest.raises(FileNotFoundError) as exc_info:
                service.reset_to_defaults()

            assert "Distribution file not found" in str(exc_info.value)
        finally:
            os.unlink(temp_file)


class TestLanguageVariableRendering:
    """Tests for language variable rendering in Taro templates (TDD validation)"""

    def test_render_language_variable_single(self):
        """Should correctly render {{language}} variable with Russian"""
        from plugins.taro.src.services.prompt_service import PromptService

        service = PromptService.from_dict(
            {
                "language_test": {
                    "template": "RESPOND IN {{language}} LANGUAGE.",
                    "variables": ["language"],
                }
            }
        )

        result = service.render("language_test", {"language": "Русский (Russian)"})
        assert "RESPOND IN Русский (Russian) LANGUAGE." in result

    def test_render_situation_reading_with_language(self):
        """Should render situation_reading template with language variable"""
        from plugins.taro.src.services.prompt_service import PromptService

        service = PromptService.from_dict(
            {
                "situation_reading": {
                    "template": "You are an expert.\n\nRESPOND IN {{language}} LANGUAGE.\n\nSituation: {{situation_text}}",
                    "variables": ["language", "situation_text"],
                }
            }
        )

        result = service.render(
            "situation_reading",
            {"language": "Русский (Russian)", "situation_text": "Career decision"},
        )

        assert "RESPOND IN Русский (Russian) LANGUAGE." in result
        assert "Career decision" in result

    @pytest.mark.parametrize(
        "lang_code,lang_name",
        [
            ("en", "English"),
            ("ru", "Русский (Russian)"),
            ("de", "Deutsch (German)"),
            ("fr", "Français (French)"),
            ("es", "Español (Spanish)"),
            ("ja", "日本語 (Japanese)"),
            ("th", "ไทย (Thai)"),
            ("zh", "中文 (Chinese)"),
        ],
    )
    def test_render_language_all_8_supported_languages(self, lang_code, lang_name):
        """Should correctly render all 8 supported language codes"""
        from plugins.taro.src.services.prompt_service import PromptService

        service = PromptService.from_dict(
            {
                "test": {
                    "template": "RESPOND IN {{language}} LANGUAGE.",
                    "variables": ["language"],
                }
            }
        )

        result = service.render("test", {"language": lang_name})
        assert f"RESPOND IN {lang_name} LANGUAGE." in result

    def test_render_card_explanation_with_language(self):
        """Should render card_explanation template with language"""
        from plugins.taro.src.services.prompt_service import PromptService

        service = PromptService.from_dict(
            {
                "card_explanation": {
                    "template": "You are an expert.\n\nRESPOND IN {{language}} LANGUAGE.\n\nCards: {{cards_context}}",
                    "variables": ["language", "cards_context"],
                }
            }
        )

        result = service.render(
            "card_explanation",
            {
                "language": "Deutsch (German)",
                "cards_context": "The Magician, The High Priestess, The Empress",
            },
        )

        assert "RESPOND IN Deutsch (German) LANGUAGE." in result
        assert "The Magician" in result

    def test_render_follow_up_question_with_language(self):
        """Should render follow_up_question template with language"""
        from plugins.taro.src.services.prompt_service import PromptService

        service = PromptService.from_dict(
            {
                "follow_up_question": {
                    "template": "Expert reader.\n\nRESPOND IN {{language}} LANGUAGE.\n\nQuestion: {{question}}",
                    "variables": ["language", "question"],
                }
            }
        )

        result = service.render(
            "follow_up_question",
            {"language": "Français (French)", "question": "Will things improve?"},
        )

        assert "RESPOND IN Français (French) LANGUAGE." in result
        assert "Will things improve?" in result

    def test_render_language_with_empty_string_renders_empty(self):
        """Should render empty string if language variable not provided"""
        from plugins.taro.src.services.prompt_service import PromptService

        service = PromptService.from_dict(
            {
                "test": {
                    "template": "RESPOND IN {{language}} LANGUAGE.",
                    "variables": ["language"],
                }
            }
        )

        # Jinja2 renders missing variables as empty by default
        result = service.render("test", {})
        assert "RESPOND IN  LANGUAGE." in result

    def test_render_language_instruction_appears_in_complex_template(self):
        """Should preserve language instruction in multi-paragraph template"""
        from plugins.taro.src.services.prompt_service import PromptService

        template = """You are an expert Tarot reader.

RESPOND IN {{language}} LANGUAGE.

User's situation: {{situation}}

Cards drawn:
{{cards}}

Provide detailed interpretation."""

        service = PromptService.from_dict(
            {
                "complex": {
                    "template": template,
                    "variables": ["language", "situation", "cards"],
                }
            }
        )

        result = service.render(
            "complex",
            {
                "language": "Español (Spanish)",
                "situation": "Love question",
                "cards": "Card 1, Card 2, Card 3",
            },
        )

        assert "RESPOND IN Español (Spanish) LANGUAGE." in result
        assert "Love question" in result
        assert "Card 1" in result

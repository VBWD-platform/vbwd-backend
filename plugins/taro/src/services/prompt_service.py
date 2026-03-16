"""Prompt Service for managing LLM prompts with Jinja2 templating"""
import json
import os
from typing import Dict, Any, List
from jinja2 import Template, TemplateSyntaxError


class PromptService:
    """Load, validate, and manage LLM prompts with metadata inheritance."""

    def __init__(self, prompts_file: str = None, prompts_data: Dict[str, Any] = None):
        """Initialize service with prompts file path or data dict.

        Args:
            prompts_file: Path to JSON prompts file (optional)
            prompts_data: Prompts data as dictionary (optional)

        Raises:
            FileNotFoundError: If file doesn't exist
            json.JSONDecodeError: If JSON is invalid
            ValueError: If neither file nor data provided
        """
        if prompts_file:
            self.prompts_file = prompts_file
            self.prompts = self._load_prompts()
        elif prompts_data:
            self.prompts_file = None
            self.prompts = prompts_data
        else:
            raise ValueError("Either prompts_file or prompts_data must be provided")

        self.defaults = self.prompts.get("_defaults", {})

    @classmethod
    def from_dict(cls, prompts_data: Dict[str, Any]) -> "PromptService":
        """Create PromptService from a prompts dictionary.

        Args:
            prompts_data: Dictionary containing prompts configuration

        Returns:
            PromptService instance
        """
        return cls(prompts_data=prompts_data)

    def _load_prompts(self) -> Dict[str, Any]:
        """Load prompts from JSON file.

        Raises:
            FileNotFoundError: If file doesn't exist
            json.JSONDecodeError: If JSON is invalid
        """
        if not os.path.exists(self.prompts_file):
            raise FileNotFoundError(
                f"Prompt file not found: {self.prompts_file}\n"
                f"Please ensure the file exists at {self.prompts_file}"
            )

        with open(self.prompts_file) as f:
            return json.load(f)

    def get_prompt(self, slug: str) -> Dict[str, Any]:
        """Get prompt with resolved metadata (defaults merged).

        Args:
            slug: Prompt identifier

        Returns:
            Prompt dict with all fields including resolved metadata

        Raises:
            ValueError: If slug is internal (_*) or doesn't exist
        """
        if slug.startswith("_"):
            raise ValueError(f"Cannot access internal prompt: {slug}")

        prompt = self.prompts.get(slug)
        if not prompt:
            raise ValueError(f"Prompt not found: {slug}")

        # Merge with defaults: start with defaults, override with prompt-specific
        resolved = {**self.defaults}
        resolved.update(prompt)
        return resolved

    def render(self, slug: str, context: Dict[str, Any]) -> str:
        """Render prompt template with context using Jinja2.

        Args:
            slug: Prompt identifier
            context: Variables to interpolate into template

        Returns:
            Rendered template string

        Raises:
            ValueError: If slug doesn't exist or template rendering fails
        """
        prompt = self.get_prompt(slug)
        template = prompt.get("template", "")

        try:
            t = Template(template)
            return t.render(context)
        except TemplateSyntaxError as e:
            raise ValueError(f"Error rendering prompt '{slug}': {e}")
        except Exception as e:
            raise ValueError(f"Error rendering prompt '{slug}': {e}")

    def validate_template(self, template: str, variables: List[str]) -> bool:
        """Validate template syntax and structure.

        Args:
            template: Template string to validate
            variables: List of expected variables

        Returns:
            True if valid

        Raises:
            ValueError: If template syntax is invalid
        """
        try:
            Template(template)
            return True
        except TemplateSyntaxError as e:
            raise ValueError(f"Invalid template: {e}")
        except Exception as e:
            raise ValueError(f"Invalid template: {e}")

    def update_prompt(self, slug: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update a prompt (template + optional metadata overrides).

        Args:
            slug: Prompt identifier
            data: Dict with 'template', 'variables', and/or metadata fields

        Returns:
            Updated prompt with resolved metadata

        Raises:
            ValueError: If slug is internal or doesn't exist
        """
        if slug.startswith("_"):
            raise ValueError(f"Cannot modify internal prompt: {slug}")

        if slug not in self.prompts:
            raise ValueError(f"Prompt not found: {slug}")

        prompt = self.prompts[slug]
        prompt.update(data)
        self.prompts[slug] = prompt
        self._save_prompts()

        return self.get_prompt(slug)

    def update_defaults(self, defaults: Dict[str, Any]) -> Dict[str, Any]:
        """Update default metadata.

        Args:
            defaults: Dict with metadata to update

        Returns:
            Updated defaults dict
        """
        self.defaults.update(defaults)
        self.prompts["_defaults"] = self.defaults
        self._save_prompts()
        return self.defaults

    def reset_to_defaults(self) -> None:
        """Reset all prompts to .dist distribution defaults.

        Raises:
            FileNotFoundError: If .dist file doesn't exist
        """
        dist_file = self.prompts_file.replace(".json", ".json.dist")
        if not os.path.exists(dist_file):
            raise FileNotFoundError(
                f"Distribution file not found: {dist_file}\n"
                f"Please ensure the file exists to reset"
            )

        with open(dist_file) as f:
            self.prompts = json.load(f)

        self.defaults = self.prompts.get("_defaults", {})
        self._save_prompts()

    def _save_prompts(self) -> None:
        """Save prompts to JSON file (if file-based, otherwise no-op for config-based)."""
        if self.prompts_file:
            with open(self.prompts_file, "w") as f:
                json.dump(self.prompts, f, indent=2)

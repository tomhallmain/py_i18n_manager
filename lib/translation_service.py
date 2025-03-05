from lib.llm import LLM
from utils.config import ConfigManager
import asyncio
from concurrent.futures import ThreadPoolExecutor

class TranslationService:
    def __init__(self):
        self.llm = LLM()
        self.config = ConfigManager()
        self._executor = ThreadPoolExecutor(max_workers=4)
        
    def __del__(self):
        """Cleanup when the service is destroyed."""
        if hasattr(self, '_executor'):
            self._executor.shutdown(wait=True)
        
    def translate(self, text, target_locale, context=None):
        """Translate text to the target locale using LLM.
        
        Args:
            text (str): The text to translate
            target_locale (str): The target locale code (e.g., 'es', 'fr')
            context (str, optional): Additional context about the text
            
        Returns:
            str: The translated text
        """
        # Get the default locale for context
        default_locale = self.config.get('translation.default_locale', 'en')
        
        # Construct the prompt
        prompt = self._create_translation_prompt(
            text=text,
            source_locale=default_locale,
            target_locale=target_locale,
            context=context
        )
        
        # Get translation from LLM
        try:
            response = self.llm.generate_json_get_value(
                prompt=prompt,
                attr_name="translation",
                timeout=60  # Shorter timeout for translations
            )
            return response if response else ""
        except Exception as e:
            print(f"Translation failed: {e}")
            return ""
            
    def _create_translation_prompt(self, text, source_locale, target_locale, context=None):
        """Create a structured prompt for the LLM translation request."""
        prompt = f"""Translate the following text from {source_locale} to {target_locale}.
Return the response as a JSON object with a single key "translation" containing the translated text.

Source text: {text}

{f'Context: {context}' if context else ''}

Rules:
1. Maintain any placeholders like {{0}}, {{1}}, etc.
2. Preserve any special characters or formatting
3. Keep the same tone and style as the original
4. If the text contains technical terms, translate them appropriately for the target language

Return only the JSON object, no additional text."""

        return prompt 
from lib.llm import LLM
from lib.argos_translate import ArgosTranslate
from concurrent.futures import ThreadPoolExecutor

from utils.logging_setup import get_logger

logger = get_logger("translation_service")

class TranslationService:
    def __init__(self, default_locale='en'):
        """Initialize the translation service.
        
        Args:
            default_locale (str, optional): Default source locale for translations. Defaults to 'en'.
        """
        self.default_locale = default_locale
        self.llm = LLM()
        self.argos = ArgosTranslate()
        self._executor = ThreadPoolExecutor(max_workers=4)
        
    def __del__(self):
        """Cleanup when the service is destroyed."""
        if hasattr(self, '_executor'):
            self._executor.shutdown(wait=True)
        
    def translate_with_llm(self, text, target_locale, context=None):
        """Translate text to the target locale using LLM.
        
        Args:
            text (str): The text to translate
            target_locale (str): The target locale code (e.g., 'es', 'fr')
            context (str, optional): Additional context about the text
            
        Returns:
            str: The translated text
        """
        # Construct the prompt
        prompt = self._create_translation_prompt(
            text=text,
            source_locale=self.default_locale,
            target_locale=target_locale,
            context=context
        )
        
        # Get translation from LLM
        try:
            result = self.llm.generate_json_get_value(
                query=prompt,
                json_key="translation",
                timeout=60  # Shorter timeout for translations
            )
            return result.response if result else ""
        except Exception as e:
            logger.error(f"LLM translation failed: {e}")
            return ""
            
    def translate_with_argos(self, text, target_locale, source_locale=None):
        """Translate text to the target locale using Argos Translate.
        
        Args:
            text (str): The text to translate
            target_locale (str): The target locale code (e.g., 'es', 'fr')
            source_locale (str, optional): Source locale code. Defaults to default_locale.
            
        Returns:
            str: The translated text
        """
        if source_locale is None:
            source_locale = self.default_locale
            
        return self.argos.translate(text, target_locale, source_locale)
            
    def translate(self, text, target_locale, context=None, use_llm=False):
        """Translate text using the specified or default method.
        
        Args:
            text (str): The text to translate
            target_locale (str): The target locale code (e.g., 'es', 'fr')
            context (str, optional): Additional context about the text
            use_llm (bool, optional): Whether to use LLM instead of Argos Translate
            
        Returns:
            str: The translated text
        """
        if use_llm or not self.argos.is_usable:
            if not use_llm:
                logger.warning("Argos Translate is not usable, using LLM")
            return self.translate_with_llm(text, target_locale, context)
        return self.translate_with_argos(text, target_locale)
            
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
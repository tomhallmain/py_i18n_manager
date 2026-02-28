from typing import Optional

from lib.llm import LLM
from lib.argos_translate import ArgosTranslate
from concurrent.futures import ThreadPoolExecutor
from utils.settings_manager import SettingsManager
from utils.utils import Utils

from utils.logging_setup import get_logger

logger = get_logger("translation_service")


class TranslationService:
    # Default prompt template used as fallback
    DEFAULT_PROMPT_TEMPLATE = """Translate the following text from {source_locale} to {target_locale}.
Return the response as a JSON object with a single key "translation" containing the translated text.

Source text: {source_text}

{context}

Rules:
1. Maintain any placeholders like {{0}}, {{1}}, %s, %d, etc.
2. Preserve any special characters or formatting
3. Keep the same tone and style as the original
4. If the text contains technical terms, translate them appropriately for the target language

Return only the JSON object, no additional text."""

    def __init__(self, default_locale='en', prompt_template: Optional[str] = None,
                 cjk_reject_threshold_percentage: Optional[int] = None, project_path: Optional[str] = None):
        """Initialize the translation service.
        
        Args:
            default_locale (str, optional): Default source locale for translations. Defaults to 'en'.
            prompt_template (str, optional): Custom prompt template for LLM translations.
                                            If None, uses the default template.
            cjk_reject_threshold_percentage (int, optional): CJK rejection threshold percentage for
                                                            non-CJK locales.
            project_path (str, optional): Project path for project-specific LLM settings.
        """
        self.default_locale = default_locale
        self.prompt_template = prompt_template
        self.project_path = project_path
        self.settings_manager = SettingsManager()
        if cjk_reject_threshold_percentage is None:
            self.cjk_reject_threshold_percentage = self.settings_manager.get_llm_cjk_reject_threshold_percentage(project_path)
        else:
            self.cjk_reject_threshold_percentage = int(cjk_reject_threshold_percentage)
        self.llm = LLM()
        self.argos = ArgosTranslate()
        self._executor = ThreadPoolExecutor(max_workers=4)
    
    def set_prompt_template(self, template: Optional[str]):
        """Update the prompt template used for LLM translations.
        
        Args:
            template (str, optional): The new prompt template, or None to use default
        """
        self.prompt_template = template

    def set_cjk_reject_threshold_percentage(self, threshold_percentage: int):
        """Update CJK rejection threshold percentage used for non-CJK locales."""
        self.cjk_reject_threshold_percentage = max(0, min(100, int(threshold_percentage)))
        
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
            cjk_reject_threshold = self._get_cjk_reject_threshold_for_locale(target_locale)
            result = self.llm.generate_json_get_value(
                query=prompt,
                json_key="translation",
                timeout=60,  # Shorter timeout for translations
                cjk_reject_threshold_percentage=cjk_reject_threshold,
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
        """Create a structured prompt for the LLM translation request.
        
        Uses the configured prompt_template if available, otherwise uses the default.
        The template supports the following variables:
        - {source_locale}: Source language code
        - {target_locale}: Target language code
        - {source_text}: The text to translate
        - {context}: Optional context information
        
        Args:
            text (str): The text to translate
            source_locale (str): Source language code
            target_locale (str): Target language code
            context (str, optional): Additional context about the text
            
        Returns:
            str: The formatted prompt
        """
        template = self.prompt_template or self.DEFAULT_PROMPT_TEMPLATE
        
        # Format context - if provided, prefix with "Context: ", otherwise empty string
        context_str = f"Context: {context}" if context else ""
        
        try:
            prompt = template.format(
                source_locale=source_locale,
                target_locale=target_locale,
                source_text=text,
                context=context_str
            )
        except KeyError as e:
            logger.warning(f"Invalid variable in prompt template: {e}. Using default template.")
            prompt = self.DEFAULT_PROMPT_TEMPLATE.format(
                source_locale=source_locale,
                target_locale=target_locale,
                source_text=text,
                context=context_str
            )
        
        return prompt

    def _get_cjk_reject_threshold_for_locale(self, target_locale: str) -> Optional[int]:
        """Return CJK reject threshold for non-CJK locales, None for CJK locales."""
        if Utils.is_cjk_locale(target_locale):
            return None
        return self.cjk_reject_threshold_percentage

from typing import Dict, List, Optional

from lib.llm import LLM, LLMBatchStoppingException
from lib.argos_translate import ArgosTranslate
from concurrent.futures import ThreadPoolExecutor
from utils.settings_manager import SettingsManager
from utils.utils import Utils

from utils.logging_setup import get_logger

from i18n.stop_character_utils import normalize_translation_trailing_stop

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
5. Where possible, try to match the length of the source text in the target language, to help keep UI layouts consistent

Return only the JSON object, no additional text."""

    # Default prompt template for LLMTranslationMode.PER_KEY_ALL_LOCALES: one LLM call per key,
    # requesting translations for every missing locale at once as a single JSON object.
    DEFAULT_MULTI_LOCALE_PROMPT_TEMPLATE = """Translate the following text from {source_locale} into every one of the target locales listed below.
Return the response as a single JSON object whose keys are exactly the target locale codes listed below and whose values are the translated text for that locale.

Source text: {source_text}

Target locales (use exactly these as the JSON keys): {target_locales}

{context}

Rules:
1. Maintain any placeholders like {{0}}, {{1}}, %s, %d, etc.
2. Preserve any special characters or formatting
3. Keep the same tone and style as the original
4. If the text contains technical terms, translate them appropriately for each target language
5. Where possible, try to match the length of the source text in each target language, to help keep UI layouts consistent
6. Return exactly one key per target locale listed above, and no other keys

Return only the JSON object, no additional text."""

    def __init__(self, default_locale='en', prompt_template: Optional[str] = None,
                 cjk_reject_threshold_percentage: Optional[int] = None, project_path: Optional[str] = None,
                 llm_model: Optional[str] = None, llm_model_multi_locale: Optional[str] = None,
                 prompt_template_multi_locale: Optional[str] = None):
        """Initialize the translation service.

        Args:
            default_locale (str, optional): Default source locale for translations. Defaults to 'en'.
            prompt_template (str, optional): Custom prompt template for one-locale-at-a-time LLM
                                            translations. If None, uses the default template.
            cjk_reject_threshold_percentage (int, optional): CJK rejection threshold percentage for
                                                            non-CJK locales.
            project_path (str, optional): Project path for project-specific LLM settings.
            llm_model (str, optional): Ollama model for one-locale-at-a-time requests. If None,
                                        resolved from settings.
            llm_model_multi_locale (str, optional): Ollama model for per-key/all-locales requests.
                                                     If None, resolved from settings.
            prompt_template_multi_locale (str, optional): Custom prompt template for
                                            LLMTranslationMode.PER_KEY_ALL_LOCALES requests. Must
                                            keep the ``{target_locales}`` variable - the response
                                            is parsed as one JSON key per locale listed there. If
                                            None, uses the default template.
        """
        self.default_locale = default_locale
        self.prompt_template = prompt_template
        self.prompt_template_multi_locale = prompt_template_multi_locale
        self.project_path = project_path
        self.settings_manager = SettingsManager()
        if cjk_reject_threshold_percentage is None:
            self.cjk_reject_threshold_percentage = self.settings_manager.get_llm_cjk_reject_threshold_percentage(project_path)
        else:
            self.cjk_reject_threshold_percentage = int(cjk_reject_threshold_percentage)
        llm_model = llm_model or self.settings_manager.get_llm_model(project_path)
        llm_model_multi_locale = llm_model_multi_locale or self.settings_manager.get_llm_model_multi_locale(project_path)
        # Separate LLM instances (and failure-tracking state) per mode, since they typically use
        # different models (e.g. a local model vs. an Ollama cloud model) with independent
        # reliability characteristics.
        self.llm = LLM(model_name=llm_model, state_key=llm_model)
        self.llm_multi = LLM(model_name=llm_model_multi_locale, state_key=llm_model_multi_locale)
        self.argos = ArgosTranslate()
        self._executor = ThreadPoolExecutor(max_workers=4)

    def set_prompt_template(self, template: Optional[str]):
        """Update the prompt template used for one-locale-at-a-time LLM translations.

        Args:
            template (str, optional): The new prompt template, or None to use default
        """
        self.prompt_template = template

    def set_prompt_template_multi_locale(self, template: Optional[str]):
        """Update the prompt template used for LLMTranslationMode.PER_KEY_ALL_LOCALES requests.

        Args:
            template (str, optional): The new prompt template, or None to use default
        """
        self.prompt_template_multi_locale = template

    def set_cjk_reject_threshold_percentage(self, threshold_percentage: int):
        """Update CJK rejection threshold percentage used for non-CJK locales."""
        self.cjk_reject_threshold_percentage = max(0, min(100, int(threshold_percentage)))

    def set_llm_model(self, model_name: str):
        """Update the model used for one-locale-at-a-time LLM translation requests."""
        if model_name:
            self.llm.model_name = model_name

    def set_llm_model_multi_locale(self, model_name: str):
        """Update the model used for per-key/all-locales LLM translation requests."""
        if model_name:
            self.llm_multi.model_name = model_name

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
            raw = result.response if result else ""
            return normalize_translation_trailing_stop(text, raw, target_locale)
        except LLMBatchStoppingException:
            # Let rate-limit/forbidden errors propagate - callers (e.g. the bulk translation
            # worker) need to stop rather than silently treat it like an empty/failed translation.
            raise
        except Exception as e:
            logger.error(f"LLM translation failed: {e}")
            return ""

    def translate_with_llm_multi_locale(self, text, target_locales: List[str], context=None) -> Dict[str, str]:
        """Translate text into several target locales with a single LLM call.

        Used by LLMTranslationMode.PER_KEY_ALL_LOCALES: one request per source key instead of
        one request per (key, locale) pair. This is much faster but requires a model that
        reliably follows structured JSON-object instructions covering multiple locales at
        once - local/small models are often unreliable here, which is why this mode uses a
        separate, more capable model by default (see ``llm_multi``).

        Args:
            text (str): The source text to translate
            target_locales (list[str]): Target locale codes (e.g. ['es', 'fr'])
            context (str, optional): Additional context about the text

        Returns:
            dict[str, str]: Mapping of target locale -> translated text. Locales the model
                             omitted, or whose text failed CJK filtering, map to "".
        """
        target_locales = list(target_locales)
        results = {locale: "" for locale in target_locales}
        if not target_locales:
            return results

        prompt = self._create_multi_locale_translation_prompt(
            text=text,
            source_locale=self.default_locale,
            target_locales=target_locales,
            context=context,
        )

        try:
            parsed = self.llm_multi.generate_json_dict(
                query=prompt,
                timeout=90,
                # A batch response legitimately mixes CJK and non-CJK locales, so the blanket
                # CJK check is disabled here; each locale's text is filtered individually below.
                cjk_reject_threshold_percentage=None,
            )
        except LLMBatchStoppingException:
            # Let rate-limit/forbidden errors propagate - see translate_with_llm.
            raise
        except Exception as e:
            logger.error(f"LLM multi-locale translation failed: {e}")
            return results

        if not parsed:
            return results

        for locale in target_locales:
            raw = self._extract_locale_value(parsed, locale)
            if not raw:
                continue
            cjk_reject_threshold = self._get_cjk_reject_threshold_for_locale(locale)
            if cjk_reject_threshold is not None and Utils.get_cjk_character_ratio(raw, cjk_reject_threshold):
                continue
            results[locale] = normalize_translation_trailing_stop(text, raw, locale)

        return results

    @staticmethod
    def _extract_locale_value(parsed: dict, locale: str) -> str:
        """Look up a locale's translation in the parsed response, tolerating case/format drift."""
        if locale in parsed:
            return str(parsed[locale] or "")
        lowered = locale.lower()
        for key, value in parsed.items():
            if isinstance(key, str) and key.lower() == lowered:
                return str(value or "")
        for key, value in parsed.items():
            if isinstance(key, str) and Utils.is_similar_str(locale, key):
                return str(value or "")
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

        raw = self.argos.translate(text, target_locale, source_locale)
        return normalize_translation_trailing_stop(text, raw, target_locale)
            
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

    def _create_multi_locale_translation_prompt(self, text, source_locale, target_locales: List[str], context=None):
        """Create a prompt requesting translations for several target locales in one JSON object.

        Uses the configured prompt_template_multi_locale if available, otherwise
        DEFAULT_MULTI_LOCALE_PROMPT_TEMPLATE. Whichever template is used, its output shape - one
        JSON key per locale - must stay intact for :meth:`translate_with_llm_multi_locale` to
        parse the response; the {target_locales} variable (the locales to use as JSON keys) is
        what keeps a custom template correct here, so removing it will produce technically valid
        but useless prompts (the LLM settings dialog warns if it's missing from a saved template).

        Args:
            text (str): The text to translate
            source_locale (str): Source language code
            target_locales (list[str]): Target language codes
            context (str, optional): Additional context about the text

        Returns:
            str: The formatted prompt
        """
        template = self.prompt_template_multi_locale or self.DEFAULT_MULTI_LOCALE_PROMPT_TEMPLATE
        context_str = f"Context: {context}" if context else ""
        locales_str = ", ".join(target_locales)

        try:
            return template.format(
                source_locale=source_locale,
                target_locales=locales_str,
                source_text=text,
                context=context_str,
            )
        except KeyError as e:
            logger.warning(f"Invalid variable in multi-locale prompt template: {e}. Using default template.")
            return self.DEFAULT_MULTI_LOCALE_PROMPT_TEMPLATE.format(
                source_locale=source_locale,
                target_locales=locales_str,
                source_text=text,
                context=context_str,
            )

    def _get_cjk_reject_threshold_for_locale(self, target_locale: str) -> Optional[int]:
        """Return CJK reject threshold for non-CJK locales, None for CJK locales."""
        if Utils.is_cjk_locale(target_locale):
            return None
        return self.cjk_reject_threshold_percentage

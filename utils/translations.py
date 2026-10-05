import gettext
import os

from utils.logging_setup import get_logger
from utils.utils import DEFAULT_UI_LANGUAGE, Utils

logger = get_logger("translations")

class I18N:
    localedir = os.path.join(os.path.dirname(os.path.abspath(os.path.dirname(__file__))), 'locale')
    # Placeholders until install_locale() runs with the detected language at the end of this module.
    locale = DEFAULT_UI_LANGUAGE
    translate = gettext.NullTranslations()

    @staticmethod
    def install_locale(locale):
        """Make ``locale`` the app's UI language.

        Sets :attr:`locale` (also read for the language of LLM responses), the catalog used by
        :meth:`_`, and ``_`` in builtins. ``fallback=True``: a language with no catalog under
        ``locale/`` shows the untranslated msgids instead of raising ``FileNotFoundError``.
        """
        I18N.locale = locale
        I18N.translate = gettext.translation('base', I18N.localedir, languages=[locale], fallback=True)
        I18N.translate.install()
        logger.debug(f"Switched locale to: {locale}")

    @staticmethod
    def _(s):
        # return gettext.gettext(s)
        try:
            return I18N.translate.gettext(s)
        except KeyError:
            return s


I18N.install_locale(Utils.get_default_user_language())

# Translation function for other modules: ``from utils.translations import _``. It is
# I18N._, which reads I18N.translate on every call, so it follows later install_locale() calls.
_ = I18N._

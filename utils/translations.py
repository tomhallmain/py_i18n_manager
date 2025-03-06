import gettext
import os

from utils.utils import Utils

_locale = os.environ['LANG'] if "LANG" in os.environ else None
if not _locale or _locale == '':
    _locale = Utils.get_default_user_language()
elif _locale is not None and "_" in _locale:
    _locale = _locale[:_locale.index("_")]

class I18N:
    localedir = os.path.join(os.path.dirname(os.path.abspath(os.path.dirname(__file__))), 'locale')
    locale = "en"
    translate = None #gettext.translation('base', localedir, languages=[_locale])

    @staticmethod
    def install_locale(locale, verbose=True):
        I18N.locale = locale
        I18N.translate = gettext.translation('base', I18N.localedir, languages=[locale], fallback=True)
        I18N.translate.install()
        if verbose:
            print("Switched locale to: " + locale)

    @staticmethod
    def _(s):
        # return gettext.gettext(s)
        try:
            return I18N.translate.gettext(s)
        except KeyError:
            return s
        except Exception as e:
            # TODO remove this
            return s

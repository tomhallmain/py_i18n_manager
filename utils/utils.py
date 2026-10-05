"""General-purpose helpers (class :class:`Utils`) and shared constants.

Covers thread/async scheduling, string similarity and manipulation, locale and writing-system
classification, UI language detection, CJK character statistics, opening files, playing
sounds, and filesystem checks that retry for sleeping external drives.

This module is shared with other applications, so some methods have no callers in this one
(e.g. ``start_thread``, ``periodic``, ``open_file_location``, ``longest_common_substring``,
``remove_substring_by_indices``, ``play_sound``). Keep them even when unused here.
"""

import asyncio
import math
import re
import os
import sys
import subprocess
import threading
import time
from utils.logging_setup import get_logger


RESET = "\033[m"
GRAY = "\033[90m"
WHITE = "\033[37m"
DARK_RED = "\033[91m"
DARK_GREEN = "\033[92m"
CYAN = "\033[34m"
logger = get_logger("utils")

# UI language used when none can be detected (see Utils.get_default_user_language).
DEFAULT_UI_LANGUAGE = "en"

# Defaults for Utils.isdir_with_retry / isfile_with_retry / exists_with_retry.
DEFAULT_PATH_CHECK_MAX_RETRIES = 3
DEFAULT_PATH_CHECK_RETRY_DELAY = 1.0

class Utils:
    sleep_prevented = False
    CJK_LANGUAGE_CODES = {'zh', 'ja', 'ko'}
    CJK_SCRIPT_CODES = {'hang', 'hani', 'hans', 'hant', 'hira', 'jpan', 'kana', 'kore'}

    # BCP 47 script subtags (ISO 15924) that imply the locale string is *not* Latin-primary.
    # Includes CJK scripts from :data:`CJK_SCRIPT_CODES` (Hans, Hant, Jpan, Kore, …).
    # If ``latn`` appears explicitly, :meth:`is_non_latin_script_locale` returns False.
    _NON_LATIN_SCRIPT_SUBTAGS = frozenset({
        'cyrl', 'arab', 'grek', 'hebr', 'thai', 'geor', 'armn', 'deva', 'beng', 'guru', 'gujr',
        'orya', 'taml', 'telu', 'knda', 'mlym', 'sinh', 'thaa', 'tibt', 'mong', 'ethi', 'khmr',
        'laoo', 'mymr',
    }).union(CJK_SCRIPT_CODES)

    # ISO 639-1 language codes whose *default* writing system in typical apps is not Latin.
    # CJK language codes are unified via :data:`CJK_LANGUAGE_CODES` (zh, ja, ko).
    # Deliberately excludes Polish (pl), Turkish (tr), Vietnamese (vi), Indonesian (id), etc.
    _NON_LATIN_PRIMARY_LANGUAGE_CODES = frozenset({
        # Cyrillic (and related defaults)
        'ru', 'uk', 'bg', 'be', 'mk', 'sr', 'kk', 'ky', 'tg', 'mn', 'ce',
        # Arabic script
        'ar', 'fa', 'ur', 'ps', 'ug', 'sd',
        # Greek, Hebrew, Thai
        'el', 'he', 'th',
        # Caucasus / other alphabets
        'ka', 'hy',
        # South Asian (Indic scripts)
        'hi', 'bn', 'ta', 'te', 'ml', 'kn', 'gu', 'pa', 'or', 'as', 'ne', 'mr', 'si',
        # SE / Himalayan
        'km', 'lo', 'my', 'bo', 'dz',
        # Ethiopic, Thaana
        'am', 'ti', 'dv',
    }).union(CJK_LANGUAGE_CODES)

    @staticmethod
    def extract_substring(text, pattern):
        result = re.search(pattern, text)    
        if result:
            return result.group()
        return ""

    @staticmethod
    def start_thread(callable, use_asyncio=True, args=None):
        if use_asyncio:
            def asyncio_wrapper():
                asyncio.run(callable())

            target_func = asyncio_wrapper
        else:
            target_func = callable

        if args:
            thread = threading.Thread(target=target_func, args=args)
        else:
            thread = threading.Thread(target=target_func)

        thread.daemon = True  # Daemon threads exit when the main process does
        thread.start()

    @staticmethod
    def periodic(run_obj, sleep_attr="", run_attr=None):
        def scheduler(fcn):
            async def wrapper(*args, **kwargs):
                while True:
                    asyncio.create_task(fcn(*args, **kwargs))
                    period = int(run_obj) if isinstance(run_obj, int) else getattr(run_obj, sleep_attr)
                    await asyncio.sleep(period)
                    if run_obj and run_attr and not getattr(run_obj, run_attr):
                        logger.debug(f"Ending periodic task: {run_obj.__name__}.{run_attr} = False")
                        break
            return wrapper
        return scheduler

    @staticmethod
    def open_file_location(filepath):
        if sys.platform=='win32':
            os.startfile(filepath)
        elif sys.platform=='darwin':
            subprocess.Popen(['open', filepath])
        else:
            try:
                subprocess.Popen(['xdg-open', filepath])
            except OSError:
                # er, think of something else to try
                # xdg-open *should* be supported by recent Gnome, KDE, Xfce
                raise Exception("Unsupported distribution for opening file location.")

    @staticmethod
    def string_distance(s, t):
        # create two work vectors of integer distances
        v0 = [0] * (len(t) + 1)
        v1 = [0] * (len(t) + 1)

        # initialize v0 (the previous row of distances)
        # this row is A[0][i]: edit distance from an empty s to t;
        # that distance is the number of characters to append to  s to make t.
        for i in range(len(t) + 1):
            v0[i] = i

        for i in range(len(s)):
            # calculate v1 (current row distances) from the previous row v0

            # first element of v1 is A[i + 1][0]
            # edit distance is delete (i + 1) chars from s to match empty t
            v1[0] = i + 1

            for j in range(len(t)):
                # calculating costs for A[i + 1][j + 1]
                deletion_cost = v0[j + 1] + 1
                insertion_cost = v1[j] + 1
                substitution_cost = v0[j] if s[i] == t[j] else v0[j] + 1
                v1[j + 1] = min(deletion_cost, insertion_cost, substitution_cost)
            # copy v1 (current row) to v0 (previous row) for next iteration
            v0,v1 = v1,v0
        # after the last swap, the results of v1 are now in v0
        return v0[len(t)]

    @staticmethod
    def longest_common_substring(str1, str2):
        m = [[0] * (1 + len(str2)) for _ in range(1 + len(str1))]
        longest, x_longest = 0, 0
        for x in range(1, 1 + len(str1)):
            for y in range(1, 1 + len(str2)):
                if str1[x - 1] == str2[y - 1]:
                    m[x][y] = m[x - 1][y - 1] + 1
                    if m[x][y] > longest:
                        longest = m[x][y]
                        x_longest = x
                else:
                    m[x][y] = 0
        return str1[x_longest - longest: x_longest]

    @staticmethod
    def is_similar_str(s0, s1):
        l_distance = Utils.string_distance(s0, s1)
        min_len = min(len(s0), len(s1))
        if min_len == len(s0):
            weighted_avg_len = (len(s0) + len(s1) / 2) / 2
        else:
            weighted_avg_len = (len(s0) / 2 + len(s1)) / 2
        threshold = int(weighted_avg_len / 2.1) - int(math.log(weighted_avg_len))
        threshold = min(threshold, int(min_len * 0.8))
        return l_distance < threshold

    @staticmethod
    def remove_substring_by_indices(string, start_index, end_index):
        if end_index < start_index:
            raise Exception("End index was less than start for string: " + string)
        if end_index >= len(string) or start_index >= len(string):
            raise Exception("Start or end index were too high for string: " + string)
        if start_index == 0:
            logger.debug("Removed: " + string[:end_index+1])
            return string[end_index+1:]
        left_part = string[:start_index]
        right_part = string[end_index+1:]
        logger.debug("Removed: " + string[start_index:end_index+1])
        return left_part + right_part

    @staticmethod
    def get_centrally_truncated_string(s, maxlen):
        # get centrally truncated string
        if len(s) <= maxlen:
            return s
        max_left_index = int((maxlen)/2-2)
        min_right_index = int(-(maxlen)/2-1)
        return s[:max_left_index] + "..." + s[min_right_index:]

    @staticmethod
    def split(string, delimiter=","):
        # Split the string by the delimiter and clean any delimiter escapes present in the string
        parts = []
        i = 0
        while i < len(string):
            if string[i] == delimiter:
                if i == 0 or string[i-1] != "\\":
                    parts.append(string[:i])
                    string = string[i+1:]
                    i = -1
                elif i != 0 and string[i-1] == "\\":
                    string = string[:i-1] + delimiter + string[i+1:]
            elif i == len(string) - 1:
                parts.append(string[:i+1])
            i += 1
        if len(parts) == 0 and len(string) != 0:
            parts.append(string)
        return parts

    @staticmethod
    def get_default_user_language():
        """Language code (e.g. ``"de"``) for the user's UI language; never empty.

        Uses ``LANG`` when it names a real language. Otherwise, on Windows, uses the user's
        UI language (``GetUserDefaultUILanguage``). Falls back to :data:`DEFAULT_UI_LANGUAGE`
        when neither yields one, including for a Windows language ID that
        ``locale.windows_locale`` does not know.
        """
        language = Utils._language_from_posix_locale(os.environ.get("LANG", ""))
        if language:
            return language
        if sys.platform == 'win32':
            import ctypes
            import locale
            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            language = Utils._language_from_posix_locale(locale.windows_locale.get(lcid, ""))
            if language:
                return language
        # TODO support finding default languages on other platforms
        return DEFAULT_UI_LANGUAGE

    @staticmethod
    def _language_from_posix_locale(value):
        """Language part of a POSIX-style locale name, or None if it names no language.

        ``de_DE.UTF-8@euro`` -> ``de``, ``de.UTF-8`` -> ``de``, ``sr_RS@latin`` -> ``sr``.
        The ``C`` and ``POSIX`` locales (with or without a codeset, e.g. ``C.UTF-8``) and
        empty values give None.
        """
        name = (value or "").strip().split("@", 1)[0].split(".", 1)[0]
        if name in ("", "C", "POSIX"):
            return None
        return name.split("_", 1)[0] or None

    @staticmethod
    def play_sound(sound="success"):
        if sys.platform != 'win32':
            return
        sound = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib", "sounds", sound + ".wav")
        import winsound
        winsound.PlaySound(sound, winsound.SND_ASYNC)

    @staticmethod
    def _path_check_with_retry(check, description, path, max_retries, retry_delay, wake_drive):
        """
        Run ``check(path)``, retrying when ``path`` is on an external/removable drive.

        External drives may be in a sleep/standby state and report paths as invalid
        before they have time to spin up. For such paths (see :meth:`_get_external_drive_root`)
        the check is retried up to ``max_retries`` more times, sleeping ``retry_delay``
        seconds between attempts and not after the last one. Local paths are checked once.

        If ``wake_drive`` is True, the first attempt is preceded by an ``os.path.exists``
        probe of the drive root to help wake the drive; an ``OSError`` from the probe is
        ignored. ``description`` names the check in the retry debug log, e.g.
        "Directory check".

        Returns:
            bool: True as soon as ``check(path)`` is true, False if every attempt fails
        """
        external_drive_root = Utils._get_external_drive_root(path)
        drive_root = external_drive_root if wake_drive else None
        retries = max_retries if external_drive_root else 0

        for attempt in range(retries + 1):
            if drive_root and attempt == 0:
                try:
                    os.path.exists(drive_root)
                except OSError:
                    pass  # Drive may not be accessible yet

            if check(path):
                return True

            if attempt < retries:
                logger.debug(f"{description} failed for '{path}', retrying in {retry_delay}s (attempt {attempt + 1}/{retries})")
                time.sleep(retry_delay)

        return False

    @staticmethod
    def isdir_with_retry(path, max_retries=DEFAULT_PATH_CHECK_MAX_RETRIES,
                         retry_delay=DEFAULT_PATH_CHECK_RETRY_DELAY, wake_drive=True):
        """True if ``path`` is a directory; retries for sleeping external drives
        (see :meth:`_path_check_with_retry`)."""
        return Utils._path_check_with_retry(
            os.path.isdir, "Directory check", path, max_retries, retry_delay, wake_drive
        )

    @staticmethod
    def isfile_with_retry(path, max_retries=DEFAULT_PATH_CHECK_MAX_RETRIES,
                          retry_delay=DEFAULT_PATH_CHECK_RETRY_DELAY, wake_drive=True):
        """True if ``path`` is a file; retries for sleeping external drives
        (see :meth:`_path_check_with_retry`)."""
        return Utils._path_check_with_retry(
            os.path.isfile, "File check", path, max_retries, retry_delay, wake_drive
        )

    @staticmethod
    def exists_with_retry(path, max_retries=DEFAULT_PATH_CHECK_MAX_RETRIES,
                          retry_delay=DEFAULT_PATH_CHECK_RETRY_DELAY, wake_drive=True):
        """True if ``path`` exists; retries for sleeping external drives
        (see :meth:`_path_check_with_retry`)."""
        return Utils._path_check_with_retry(
            os.path.exists, "Path existence check", path, max_retries, retry_delay, wake_drive
        )

    @staticmethod
    def _get_external_drive_root(path):
        """
        Return an external/removable drive root for path, or None if not external.

        Windows:
            Treat drive letters E: and above as external/removable.
        Non-Windows:
            Best-effort check for common removable-media mount roots.
        """
        if not path:
            return None

        normalized = os.path.normpath(os.path.abspath(path))

        if sys.platform == "win32":
            drive = os.path.splitdrive(normalized)[0]  # e.g. "E:"
            if len(drive) == 2 and drive[1] == ":" and drive[0].isalpha():
                if drive[0].upper() >= "E":
                    return drive + os.sep
            return None

        # Common removable mount roots on macOS/Linux
        removable_roots = (
            "/Volumes",
            "/media",
            "/run/media",
            "/mnt",
        )
        for root in removable_roots:
            root_norm = os.path.normpath(root)
            if normalized == root_norm or normalized.startswith(root_norm + os.sep):
                return root_norm + os.sep

        return None

    @staticmethod
    def count_cjk_characters(text):
        """
        Count the number of CJK characters in the given text.
        
        Args:
            text: The text to analyze
            
        Returns:
            tuple: (total_cjk_chars, dict) where dict contains counts for each script:
                  {
                      'chinese': count,
                      'japanese': count,
                      'korean': count
                  }
                  
        Note:
            CJK characters include:
            - Chinese (Han): \u4e00-\u9fff
            - Japanese (Hiragana): \u3040-\u309f
            - Japanese (Katakana): \u30a0-\u30ff
            - Korean (Hangul): \uac00-\ud7af
        """
        if not text:
            return 0, {'chinese': 0, 'japanese': 0, 'korean': 0}
            
        script_counts = {
            'chinese': 0,
            'japanese': 0,
            'korean': 0
        }
        
        for c in text:
            if '\u4e00' <= c <= '\u9fff':  # Chinese
                script_counts['chinese'] += 1
            elif '\u3040' <= c <= '\u309f' or '\u30a0' <= c <= '\u30ff':  # Japanese
                script_counts['japanese'] += 1
            elif '\uac00' <= c <= '\ud7af':  # Korean
                script_counts['korean'] += 1
                
        total_cjk = sum(script_counts.values())
        return total_cjk, script_counts

    @staticmethod
    def get_cjk_character_ratio(text, threshold_percentage=None):
        """
        Calculate the ratio of CJK characters in the given text.
        
        Args:
            text: The text to analyze
            threshold_percentage: Optional percentage threshold (0-100). If provided,
                                returns True if the ratio exceeds this threshold.
        
        Returns:
            If threshold_percentage is None:
                float: Ratio of CJK characters (0.0 to 1.0)
            If threshold_percentage is provided:
                bool: True if ratio exceeds threshold, False otherwise
                
        Note:
            CJK characters include:
            - Chinese (Han): \u4e00-\u9fff
            - Japanese (Hiragana): \u3040-\u309f
            - Japanese (Katakana): \u30a0-\u30ff
            - Korean (Hangul): \uac00-\ud7af
        """
        if not text:
            return 0.0 if threshold_percentage is None else False
            
        cjk_char_count, _ = Utils.count_cjk_characters(text)
        ratio = cjk_char_count / len(text)
        
        if threshold_percentage is not None:
            return ratio > (threshold_percentage / 100.0)
            
        return ratio

    @staticmethod
    def is_cjk_locale(locale):
        """Check if locale language/script indicates CJK support."""
        if not locale:
            return False

        locale_parts = locale.replace('-', '_').split('_')
        language_code = locale_parts[0].lower()
        if language_code in Utils.CJK_LANGUAGE_CODES:
            return True

        for part in locale_parts[1:]:
            if part.lower() in Utils.CJK_SCRIPT_CODES:
                return True
        return False

    @staticmethod
    def is_non_latin_script_locale(locale: str) -> bool:
        """True if the locale typically uses a non-Latin primary script (quality heuristics).

        Uses explicit BCP 47 script subtags when present: ``_Latn`` / ``-Latn`` forces False;
        subtags in :data:`_NON_LATIN_SCRIPT_SUBTAGS` (Cyrillic, Arabic, CJK scripts such as
        ``Hans`` / ``Jpan`` / ``Kore``, …) force True. Otherwise the language subtag is matched
        against :data:`_NON_LATIN_PRIMARY_LANGUAGE_CODES` (includes CJK via
        :data:`CJK_LANGUAGE_CODES`).

        Latin-alphabet languages (Polish, Turkish, Indonesian, …) are excluded from the
        language-code list (other than CJK).
        """
        if not locale:
            return False

        parts = [p.lower() for p in locale.replace('-', '_').split('_') if p]
        if not parts:
            return False

        if 'latn' in parts:
            return False
        for p in parts[1:]:
            if p in Utils._NON_LATIN_SCRIPT_SUBTAGS:
                return True

        lang = parts[0]
        if lang in Utils._NON_LATIN_PRIMARY_LANGUAGE_CODES:
            return True

        return False


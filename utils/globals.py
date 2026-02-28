from enum import Enum
import os

from utils.config import config_manager
from utils.translations import I18N

_ = I18N._


class AppInfo(Enum):
    SERVICE_NAME = "MyPersonalApplicationsService"
    APP_IDENTIFIER = "py_i18n_manager"


class Globals:
    HOME = os.path.expanduser("~")
    DEFAULT_WORKFLOW = config_manager.get("default_workflow", "audit")
    SKIP_CONFIRMATIONS = config_manager.get("skip_confirmations", False)

class WorkflowType(Enum):
    AUDIT = "audit"
    OVERWRITE_PO_FILES = "overwrite_po_files"
    OVERWRITE_MO_FILES = "overwrite_mo_files"

class Language(Enum):
    PYTHON = "Python"

class ProjectType(Enum):
    """Enum for different project types that support internationalization."""
    PYTHON = "python"
    RUBY = "ruby"
    
    def get_display_name(self) -> str:
        """Get the display name for this project type.
        
        Returns:
            str: The display name
        """
        if self == ProjectType.PYTHON:
            return _("Python")
        elif self == ProjectType.RUBY:
            return _("Ruby")
        return self.value
    
    @classmethod
    def from_display_name(cls, display_name: str) -> 'ProjectType':
        """Get the enum value from a display name.
        
        Args:
            display_name: The display name to match
            
        Returns:
            ProjectType: The matching enum value
        """
        if display_name == _("Python"):
            return cls.PYTHON
        elif display_name == _("Ruby"):
            return cls.RUBY
        raise ValueError(f"Unknown project type: {display_name}")

class TranslationStatus(Enum):
    """Enum for different translation status types."""
    MISSING = "Missing"
    INVALID_UNICODE = "Invalid Unicode"
    INVALID_INDICES = "Invalid Indices"
    INVALID_BRACES = "Invalid Braces"
    INVALID_LEADING_SPACE = "Invalid Leading Space"
    INVALID_NEWLINE = "Invalid Newline"
    INVALID_CJK = "Invalid CJK"

    def get_translated_value(self) -> str:
        """Get the translated value for this status.
        
        Returns:
            str: The translated value
        """
        if self == TranslationStatus.MISSING:
            return _("Missing")
        elif self == TranslationStatus.INVALID_UNICODE:
            return _("Invalid Unicode")
        elif self == TranslationStatus.INVALID_INDICES:
            return _("Invalid Indices")
        elif self == TranslationStatus.INVALID_BRACES:
            return _("Invalid Braces")
        elif self == TranslationStatus.INVALID_LEADING_SPACE:
            return _("Invalid Leading Space")
        elif self == TranslationStatus.INVALID_NEWLINE:
            return _("Invalid Newline")
        elif self == TranslationStatus.INVALID_CJK:
            return _("Invalid CJK")
        return self.value

    @classmethod
    def from_translated_value(cls, translated_value: str) -> 'TranslationStatus':
        """Get the enum value from a translated string.
        
        Args:
            translated_value: The translated string to match
            
        Returns:
            TranslationStatus: The matching enum value
        """
        if translated_value == _("Missing"):
            return cls.MISSING
        elif translated_value == _("Invalid Unicode"):
            return cls.INVALID_UNICODE
        elif translated_value == _("Invalid Indices"):
            return cls.INVALID_INDICES
        elif translated_value == _("Invalid Braces"):
            return cls.INVALID_BRACES
        elif translated_value == _("Invalid Leading Space"):
            return cls.INVALID_LEADING_SPACE
        elif translated_value == _("Invalid Newline"):
            return cls.INVALID_NEWLINE
        elif translated_value == _("Invalid CJK"):
            return cls.INVALID_CJK
        raise ValueError(f"Unknown translation status: {translated_value}")

class TranslationFilter(Enum):
    """Enum for translation filter options."""
    ALL = "All"
    MISSING = "Missing"
    INVALID_UNICODE = "Invalid Unicode"
    INVALID_INDICES = "Invalid Indices"
    INVALID_BRACES = "Invalid Braces"
    INVALID_LEADING_SPACE = "Invalid Leading Space"
    INVALID_NEWLINE = "Invalid Newline"
    INVALID_CJK = "Invalid CJK"

    def get_translated_value(self) -> str:
        """Get the translated value for this filter.
        
        Returns:
            str: The translated value
        """
        if self == TranslationFilter.ALL:
            return _("All")
        elif self == TranslationFilter.MISSING:
            return _("Missing")
        elif self == TranslationFilter.INVALID_UNICODE:
            return _("Invalid Unicode")
        elif self == TranslationFilter.INVALID_INDICES:
            return _("Invalid Indices")
        elif self == TranslationFilter.INVALID_BRACES:
            return _("Invalid Braces")
        elif self == TranslationFilter.INVALID_LEADING_SPACE:
            return _("Invalid Leading Space")
        elif self == TranslationFilter.INVALID_NEWLINE:
            return _("Invalid Newline")
        elif self == TranslationFilter.INVALID_CJK:
            return _("Invalid CJK")
        return self.value

    @classmethod
    def from_translated_value(cls, translated_value: str) -> 'TranslationFilter':
        """Get the enum value from a translated string.
        
        Args:
            translated_value: The translated string to match
            
        Returns:
            TranslationFilter: The matching enum value
        """
        if translated_value == _("All"):
            return cls.ALL
        elif translated_value == _("Missing"):
            return cls.MISSING
        elif translated_value == _("Invalid Unicode"):
            return cls.INVALID_UNICODE
        elif translated_value == _("Invalid Indices"):
            return cls.INVALID_INDICES
        elif translated_value == _("Invalid Braces"):
            return cls.INVALID_BRACES
        elif translated_value == _("Invalid Leading Space"):
            return cls.INVALID_LEADING_SPACE
        elif translated_value == _("Invalid Newline"):
            return cls.INVALID_NEWLINE
        elif translated_value == _("Invalid CJK"):
            return cls.INVALID_CJK
        raise ValueError(f"Unknown translation filter: {translated_value}")

    def to_status(self) -> TranslationStatus:
        """Convert filter to status if applicable.
        
        Returns:
            TranslationStatus: The corresponding status, or None if ALL
        """
        if self == TranslationFilter.ALL:
            return None
        return TranslationStatus[self.name]


# Common ISO 639-1 language codes
valid_language_codes = {
    # A
    'aa',  # Afar
    'ab',  # Abkhazian
    'af',  # Afrikaans
    'ak',  # Akan
    'am',  # Amharic
    'ar',  # Arabic
    'an',  # Aragonese
    'hy',  # Armenian
    'as',  # Assamese
    'av',  # Avaric
    'ae',  # Avestan
    'ay',  # Aymara
    'az',  # Azerbaijani
    
    # B
    'ba',  # Bashkir
    'bm',  # Bambara
    'eu',  # Basque
    'be',  # Belarusian
    'bn',  # Bengali
    'bh',  # Bihari languages
    'bi',  # Bislama
    'bs',  # Bosnian
    'br',  # Breton
    'bg',  # Bulgarian
    'my',  # Burmese
    
    # C
    'ca',  # Catalan; Valencian
    'ch',  # Chamorro
    'ce',  # Chechen
    'ny',  # Chichewa; Chewa; Nyanja
    'zh',  # Chinese
    'cv',  # Chuvash
    'kw',  # Cornish
    'co',  # Corsican
    'cr',  # Cree
    'hr',  # Croatian
    'cs',  # Czech
    
    # D
    'da',  # Danish
    'dv',  # Divehi; Dhivehi; Maldivian
    'nl',  # Dutch; Flemish
    'dz',  # Dzongkha
    
    # E
    'en',  # English
    'eo',  # Esperanto
    'et',  # Estonian
    'ee',  # Ewe
    
    # F
    'fo',  # Faroese
    'fj',  # Fijian
    'fi',  # Finnish
    'fr',  # French
    'ff',  # Fulah
    
    # G
    'gl',  # Galician
    'ka',  # Georgian
    'de',  # German
    'el',  # Greek, Modern
    'gn',  # Guarani
    'gu',  # Gujarati
    
    # H
    'ht',  # Haitian; Haitian Creole
    'ha',  # Hausa
    'he',  # Hebrew
    'hz',  # Herero
    'hi',  # Hindi
    'ho',  # Hiri Motu
    'hu',  # Hungarian
    
    # I
    'is',  # Icelandic
    'io',  # Ido
    'ig',  # Igbo
    'id',  # Indonesian
    'ia',  # Interlingua
    'ie',  # Interlingue
    'ga',  # Irish
    'it',  # Italian
    
    # J
    'ja',  # Japanese
    'jv',  # Javanese
    
    # K
    'kl',  # Kalaallisut; Greenlandic
    'kn',  # Kannada
    'kr',  # Kanuri
    'ks',  # Kashmiri
    'kk',  # Kazakh
    'km',  # Central Khmer
    'ki',  # Kikuyu; Gikuyu
    'rw',  # Kinyarwanda
    'ky',  # Kirghiz; Kyrgyz
    'kv',  # Komi
    'kg',  # Kongo
    'ko',  # Korean
    'ku',  # Kurdish
    'kj',  # Kuanyama; Kwanyama
    
    # L
    'la',  # Latin
    'lb',  # Luxembourgish; Letzeburgesch
    'lg',  # Ganda
    'li',  # Limburgan; Limburger; Limburgish
    'ln',  # Lingala
    'lo',  # Lao
    'lt',  # Lithuanian
    'lu',  # Luba-Katanga
    'lv',  # Latvian
    
    # M
    'gv',  # Manx
    'mk',  # Macedonian
    'mg',  # Malagasy
    'ms',  # Malay
    'ml',  # Malayalam
    'mt',  # Maltese
    'mi',  # Maori
    'mr',  # Marathi
    'mh',  # Marshallese
    'mn',  # Mongolian
    
    # N
    'na',  # Nauru
    'nv',  # Navajo; Navaho
    'nd',  # North Ndebele
    'ne',  # Nepali
    'ng',  # Ndonga
    'nb',  # Norwegian Bokmål
    'nn',  # Norwegian Nynorsk
    'no',  # Norwegian
    
    # O
    'ii',  # Sichuan Yi; Nuosu
    'nr',  # South Ndebele
    'oc',  # Occitan
    'oj',  # Ojibwa
    'or',  # Oriya
    'om',  # Oromo
    'os',  # Ossetian; Ossetic
    
    # P
    'pi',  # Pali
    'ps',  # Pashto; Pushto
    'fa',  # Persian
    'pl',  # Polish
    'pt',  # Portuguese
    'pa',  # Punjabi; Panjabi
    
    # Q
    'qu',  # Quechua
    
    # R
    'rm',  # Romansh
    'rn',  # Rundi
    'ro',  # Romanian; Moldavian; Moldovan
    'ru',  # Russian
    
    # S
    'sa',  # Sanskrit
    'sc',  # Sardinian
    'sd',  # Sindhi
    'se',  # Northern Sami
    'sm',  # Samoan
    'sg',  # Sango
    'sr',  # Serbian
    'gd',  # Gaelic; Scottish Gaelic
    'sn',  # Shona
    'si',  # Sinhala; Sinhalese
    'sk',  # Slovak
    'sl',  # Slovenian
    'so',  # Somali
    'st',  # Southern Sotho
    'es',  # Spanish; Castilian
    'su',  # Sundanese
    'sw',  # Swahili
    'ss',  # Swati
    'sv',  # Swedish
    
    # T
    'ta',  # Tamil
    'te',  # Telugu
    'tg',  # Tajik
    'th',  # Thai
    'ti',  # Tigrinya
    'bo',  # Tibetan
    'tk',  # Turkmen
    'tl',  # Tagalog
    'tn',  # Tswana
    'to',  # Tonga
    'tr',  # Turkish
    'ts',  # Tsonga
    'tt',  # Tatar
    'tw',  # Twi
    'ty',  # Tahitian
    
    # U
    'ug',  # Uighur; Uyghur
    'uk',  # Ukrainian
    'ur',  # Urdu
    'uz',  # Uzbek
    
    # V
    've',  # Venda
    'vi',  # Vietnamese
    'vo',  # Volapük
    
    # W
    'wa',  # Walloon
    'cy',  # Welsh
    'wo',  # Wolof
    
    # X
    'fy',  # Western Frisian
    'xh',  # Xhosa
    
    # Y
    'yi',  # Yiddish
    'yo',  # Yoruba
    
    # Z
    'za',  # Zhuang; Chuang
    'zu'   # Zulu
}


# Common ISO 3166-1 country codes
valid_country_codes = {
    # A
    'AF',  # Afghanistan
    'AX',  # Åland Islands
    'AL',  # Albania
    'DZ',  # Algeria
    'AS',  # American Samoa
    'AD',  # Andorra
    'AO',  # Angola
    'AI',  # Anguilla
    'AQ',  # Antarctica
    'AG',  # Antigua and Barbuda
    'AR',  # Argentina
    'AM',  # Armenia
    'AW',  # Aruba
    'AU',  # Australia
    'AT',  # Austria
    'AZ',  # Azerbaijan
    
    # B
    'BS',  # Bahamas
    'BH',  # Bahrain
    'BD',  # Bangladesh
    'BB',  # Barbados
    'BY',  # Belarus
    'BE',  # Belgium
    'BZ',  # Belize
    'BJ',  # Benin
    'BM',  # Bermuda
    'BT',  # Bhutan
    'BO',  # Bolivia (Plurinational State of)
    'BQ',  # Bonaire, Sint Eustatius and Saba
    'BA',  # Bosnia and Herzegovina
    'BW',  # Botswana
    'BV',  # Bouvet Island
    'BR',  # Brazil
    'IO',  # British Indian Ocean Territory
    'BN',  # Brunei Darussalam
    'BG',  # Bulgaria
    'BF',  # Burkina Faso
    'BI',  # Burundi
    
    # C
    'CV',  # Cabo Verde
    'KH',  # Cambodia
    'CM',  # Cameroon
    'CA',  # Canada
    'KY',  # Cayman Islands
    'CF',  # Central African Republic
    'TD',  # Chad
    'CL',  # Chile
    'CN',  # China
    'CX',  # Christmas Island
    'CC',  # Cocos (Keeling) Islands
    'CO',  # Colombia
    'KM',  # Comoros
    'CG',  # Congo
    'CD',  # Congo (Democratic Republic of the)
    'CK',  # Cook Islands
    'CR',  # Costa Rica
    'CI',  # Côte d'Ivoire
    'HR',  # Croatia
    'CU',  # Cuba
    'CW',  # Curaçao
    'CY',  # Cyprus
    'CZ',  # Czech Republic
    
    # D
    'DK',  # Denmark
    'DJ',  # Djibouti
    'DM',  # Dominica
    'DO',  # Dominican Republic
    
    # E
    'EC',  # Ecuador
    'EG',  # Egypt
    'SV',  # El Salvador
    'GQ',  # Equatorial Guinea
    'ER',  # Eritrea
    'EE',  # Estonia
    'ET',  # Ethiopia
    
    # F
    'FK',  # Falkland Islands (Malvinas)
    'FO',  # Faroe Islands
    'FJ',  # Fiji
    'FI',  # Finland
    'FR',  # France
    'GF',  # French Guiana
    'PF',  # French Polynesia
    'TF',  # French Southern Territories
    
    # G
    'GA',  # Gabon
    'GM',  # Gambia
    'GE',  # Georgia
    'DE',  # Germany
    'GH',  # Ghana
    'GI',  # Gibraltar
    'GR',  # Greece
    'GL',  # Greenland
    'GD',  # Grenada
    'GP',  # Guadeloupe
    'GU',  # Guam
    'GT',  # Guatemala
    'GG',  # Guernsey
    'GN',  # Guinea
    'GW',  # Guinea-Bissau
    'GY',  # Guyana
    
    # H
    'HT',  # Haiti
    'HM',  # Heard Island and McDonald Islands
    'VA',  # Holy See
    'HN',  # Honduras
    'HK',  # Hong Kong
    'HU',  # Hungary
    
    # I
    'IS',  # Iceland
    'IN',  # India
    'ID',  # Indonesia
    'IR',  # Iran (Islamic Republic of)
    'IQ',  # Iraq
    'IE',  # Ireland
    'IM',  # Isle of Man
    'IL',  # Israel
    'IT',  # Italy
    
    # J
    'JM',  # Jamaica
    'JP',  # Japan
    'JE',  # Jersey
    'JO',  # Jordan
    
    # K
    'KZ',  # Kazakhstan
    'KE',  # Kenya
    'KI',  # Kiribati
    'KP',  # Korea (Democratic People's Republic of)
    'KR',  # Korea (Republic of)
    'KW',  # Kuwait
    'KG',  # Kyrgyzstan
    
    # L
    'LA',  # Lao People's Democratic Republic
    'LV',  # Latvia
    'LB',  # Lebanon
    'LS',  # Lesotho
    'LR',  # Liberia
    'LY',  # Libya
    'LI',  # Liechtenstein
    'LT',  # Lithuania
    'LU',  # Luxembourg
    
    # M
    'MO',  # Macao
    'MK',  # North Macedonia
    'MG',  # Madagascar
    'MW',  # Malawi
    'MY',  # Malaysia
    'MV',  # Maldives
    'ML',  # Mali
    'MT',  # Malta
    'MH',  # Marshall Islands
    'MQ',  # Martinique
    'MR',  # Mauritania
    'MU',  # Mauritius
    'YT',  # Mayotte
    'MX',  # Mexico
    'FM',  # Micronesia (Federated States of)
    'MD',  # Moldova (Republic of)
    'MC',  # Monaco
    'MN',  # Mongolia
    'ME',  # Montenegro
    'MS',  # Montserrat
    'MA',  # Morocco
    'MZ',  # Mozambique
    'MM',  # Myanmar
    
    # N
    'NA',  # Namibia
    'NR',  # Nauru
    'NP',  # Nepal
    'NL',  # Netherlands
    'NC',  # New Caledonia
    'NZ',  # New Zealand
    'NI',  # Nicaragua
    'NE',  # Niger
    'NG',  # Nigeria
    'NU',  # Niue
    'NF',  # Norfolk Island
    'MP',  # Northern Mariana Islands
    'NO',  # Norway
    
    # O
    'OM',  # Oman
    
    # P
    'PK',  # Pakistan
    'PW',  # Palau
    'PS',  # Palestine, State of
    'PA',  # Panama
    'PG',  # Papua New Guinea
    'PY',  # Paraguay
    'PE',  # Peru
    'PH',  # Philippines
    'PN',  # Pitcairn
    'PL',  # Poland
    'PT',  # Portugal
    'PR',  # Puerto Rico
    
    # Q
    'QA',  # Qatar
    
    # R
    'RE',  # Réunion
    'RO',  # Romania
    'RU',  # Russian Federation
    'RW',  # Rwanda
    
    # S
    'BL',  # Saint Barthélemy
    'SH',  # Saint Helena, Ascension and Tristan da Cunha
    'KN',  # Saint Kitts and Nevis
    'LC',  # Saint Lucia
    'MF',  # Saint Martin (French part)
    'PM',  # Saint Pierre and Miquelon
    'VC',  # Saint Vincent and the Grenadines
    'WS',  # Samoa
    'SM',  # San Marino
    'ST',  # Sao Tome and Principe
    'SA',  # Saudi Arabia
    'SN',  # Senegal
    'RS',  # Serbia
    'SC',  # Seychelles
    'SL',  # Sierra Leone
    'SG',  # Singapore
    'SX',  # Sint Maarten (Dutch part)
    'SK',  # Slovakia
    'SI',  # Slovenia
    'SB',  # Solomon Islands
    'SO',  # Somalia
    'ZA',  # South Africa
    'GS',  # South Georgia and the South Sandwich Islands
    'SS',  # South Sudan
    'ES',  # Spain
    'LK',  # Sri Lanka
    'SD',  # Sudan
    'SR',  # Suriname
    'SJ',  # Svalbard and Jan Mayen
    'SZ',  # Eswatini
    'SE',  # Sweden
    'CH',  # Switzerland
    'SY',  # Syrian Arab Republic
    
    # T
    'TW',  # Taiwan, Province of China
    'TJ',  # Tajikistan
    'TZ',  # Tanzania, United Republic of
    'TH',  # Thailand
    'TL',  # Timor-Leste
    'TG',  # Togo
    'TK',  # Tokelau
    'TO',  # Tonga
    'TT',  # Trinidad and Tobago
    'TN',  # Tunisia
    'TR',  # Turkey
    'TM',  # Turkmenistan
    'TC',  # Turks and Caicos Islands
    'TV',  # Tuvalu
    
    # U
    'UG',  # Uganda
    'UA',  # Ukraine
    'AE',  # United Arab Emirates
    'GB',  # United Kingdom of Great Britain and Northern Ireland
    'US',  # United States of America
    'UM',  # United States Minor Outlying Islands
    'UY',  # Uruguay
    'UZ',  # Uzbekistan
    
    # V
    'VU',  # Vanuatu
    'VE',  # Venezuela (Bolivarian Republic of)
    'VN',  # Viet Nam
    'VG',  # Virgin Islands (British)
    'VI',  # Virgin Islands (U.S.)
    
    # W
    'WF',  # Wallis and Futuna
    'EH',  # Western Sahara
    
    # Y
    'YE',  # Yemen
    
    # Z
    'ZM',  # Zambia
    'ZW'   # Zimbabwe
}


# Common script codes
valid_script_codes = {
    'Arab', 'Armn', 'Beng', 'Cans', 'Cher', 'Cyrl', 'Deva', 'Ethi', 'Geor', 'Grek', 'Gujr', 
    'Guru', 'Hang', 'Hani', 'Hans', 'Hant', 'Hebr', 'Hira', 'Jpan', 'Kana', 'Khmr', 'Knda', 
    'Kore', 'Laoo', 'Latn', 'Mlym', 'Mong', 'Mymr', 'Orya', 'Sinh', 'Taml', 'Telu', 'Thai', 
    'Tibt', 'Yiii', 'Zyyy', 'Zzzz'
}

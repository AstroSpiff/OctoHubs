"""Option catalogs used by the Emby user-settings schema."""

USER_SETTINGS_SCHEMA_VERSION = 5
DISPLAY_PREFS_ID = "usersettings"
DISPLAY_PREFS_CLIENT = "emby"

LANGUAGE_OPTIONS = [
    {"value": "", "label": "Nessuna preferenza"},
    {"value": "ita", "label": "Italiano (ita)"},
    {"value": "eng", "label": "Inglese (eng)"},
    {"value": "jpn", "label": "Giapponese (jpn)"},
    {"value": "kor", "label": "Coreano (kor)"},
    {"value": "spa", "label": "Spagnolo (spa)"},
    {"value": "fre", "label": "Francese (fre)"},
    {"value": "fra", "label": "Francese ISO/T (fra)"},
    {"value": "ger", "label": "Tedesco (ger)"},
    {"value": "deu", "label": "Tedesco ISO/T (deu)"},
    {"value": "por", "label": "Portoghese (por)"},
    {"value": "rus", "label": "Russo (rus)"},
    {"value": "chi", "label": "Cinese (chi)"},
    {"value": "zho", "label": "Cinese ISO/T (zho)"},
    {"value": "ara", "label": "Arabo (ara)"},
    {"value": "hin", "label": "Hindi (hin)"},
    {"value": "tur", "label": "Turco (tur)"},
    {"value": "pol", "label": "Polacco (pol)"},
    {"value": "dut", "label": "Olandese (dut)"},
    {"value": "nld", "label": "Olandese ISO/T (nld)"},
    {"value": "swe", "label": "Svedese (swe)"},
    {"value": "nor", "label": "Norvegese (nor)"},
    {"value": "dan", "label": "Danese (dan)"},
    {"value": "fin", "label": "Finlandese (fin)"}
]

STREAM_LIMIT_OPTIONS = [
    {"value": 0, "label": "Illimitato"},
    {"value": 1, "label": "1 stream"},
    {"value": 2, "label": "2 stream"},
    {"value": 3, "label": "3 stream"},
    {"value": 4, "label": "4 stream"},
    {"value": 5, "label": "5 stream"},
    {"value": 6, "label": "6 stream"},
    {"value": 8, "label": "8 stream"},
    {"value": 10, "label": "10 stream"},
    {"value": 15, "label": "15 stream"},
    {"value": 20, "label": "20 stream"}
]

DISPLAY_LANGUAGE_OPTIONS = [
    {"value": "", "label": "Auto"},
    {"value": "ar", "label": "Arabic"},
    {"value": "be-BY", "label": "Belarusian (Belarus)"},
    {"value": "bg-BG", "label": "Bulgarian (Bulgaria)"},
    {"value": "ca", "label": "Catalan"},
    {"value": "zh-CN", "label": "Chinese Simplified"},
    {"value": "zh-TW", "label": "Chinese Traditional"},
    {"value": "zh-HK", "label": "Chinese Traditional (Hong Kong)"},
    {"value": "hr", "label": "Croatian"},
    {"value": "cs", "label": "Czech"},
    {"value": "da", "label": "Danish"},
    {"value": "nl", "label": "Dutch"},
    {"value": "en-GB", "label": "English (United Kingdom)"},
    {"value": "en-US", "label": "English (United States)"},
    {"value": "fi", "label": "Finnish"},
    {"value": "fr", "label": "French"},
    {"value": "fr-CA", "label": "French (Canada)"},
    {"value": "de", "label": "German"},
    {"value": "el", "label": "Greek"},
    {"value": "he", "label": "Hebrew"},
    {"value": "hi-IN", "label": "Hindi (India)"},
    {"value": "hu", "label": "Hungarian"},
    {"value": "id", "label": "Indonesian"},
    {"value": "it", "label": "Italian"},
    {"value": "ja", "label": "Japanese"},
    {"value": "kk", "label": "Kazakh"},
    {"value": "ko", "label": "Korean"},
    {"value": "lt-LT", "label": "Lithuanian"},
    {"value": "ms", "label": "Malay"},
    {"value": "nb", "label": "Norwegian Bokmal"},
    {"value": "fa", "label": "Persian"},
    {"value": "pl", "label": "Polish"},
    {"value": "pt-BR", "label": "Portuguese (Brazil)"},
    {"value": "pt-PT", "label": "Portuguese (Portugal)"},
    {"value": "ro", "label": "Romanian"},
    {"value": "ru", "label": "Russian"},
    {"value": "sk", "label": "Slovak"},
    {"value": "sl-SI", "label": "Slovenian (Slovenia)"},
    {"value": "es", "label": "Spanish"},
    {"value": "es-419", "label": "Spanish (Latin America)"},
    {"value": "es-MX", "label": "Spanish (Mexico)"},
    {"value": "sv", "label": "Swedish"},
    {"value": "gsw", "label": "Swiss German"},
    {"value": "tr", "label": "Turkish"},
    {"value": "uk", "label": "Ukrainian"},
    {"value": "vi", "label": "Vietnamese"}
]

THEME_OPTIONS = [
    {"value": "", "label": "Predefinito"},
    {"value": "dark", "label": "Dark"},
    {"value": "light", "label": "Light"},
    {"value": "appletv", "label": "Apple TV"},
    {"value": "blueradiance", "label": "Blue Radiance"},
    {"value": "dark-green", "label": "Dark Green"},
    {"value": "dark-red", "label": "Dark Red"},
    {"value": "halloween", "label": "Halloween"},
    {"value": "light-blue", "label": "Light Blue"},
    {"value": "light-green", "label": "Light Green"},
    {"value": "light-pink", "label": "Light Pink"},
    {"value": "light-purple", "label": "Light Purple"},
    {"value": "light-red", "label": "Light Red"},
    {"value": "wmc", "label": "Windows Media Center"}
]

SECONDARY_COLOR_OPTIONS = [
    {"value": "", "label": "Predefinito"},
    {"value": "purple", "label": "Purple"},
    {"value": "blue", "label": "Blue"},
    {"value": "green", "label": "Green"},
    {"value": "red", "label": "Red"},
    {"value": "orange", "label": "Orange"},
    {"value": "pink", "label": "Pink"},
    {"value": "teal", "label": "Teal"}
]

AUDIO_BACKGROUND_OPTIONS = [
    {"value": "", "label": "Predefinito"},
    {"value": "primaryimageblur", "label": "Sfocatura immagine primaria"},
    {"value": "backdropblur", "label": "Sfocatura backdrop"},
    {"value": "solid", "label": "Colore pieno"},
    {"value": "none", "label": "Nessuno"}
]

TV_PROGRAM_VIEW_OPTIONS = [
    {"value": "", "label": "Predefinito"},
    {"value": "allseasons", "label": "Mostra tutti gli episodi di tutte le stagioni"},
    {"value": "latest", "label": "Mostra solo episodi recenti"},
    {"value": "nextup", "label": "Prossimi episodi"}
]

HOME_SECTION_OPTIONS = [
    {"value": "", "label": "Predefinito"},
    {"value": "smalllibrarytiles", "label": "I miei media"},
    {"value": "librarybuttons", "label": "I miei media (piccolo)"},
    {"value": "activerecordings", "label": "Registrazioni attive"},
    {"value": "resume", "label": "Continua a guardare"},
    {"value": "resumeaudio", "label": "Continua ad ascoltare"},
    {"value": "latestmedia", "label": "Media recenti"},
    {"value": "nextup", "label": "Prossimi episodi"},
    {"value": "livetv", "label": "Diretta TV"},
    {"value": "none", "label": "Nessuno"}
]

TV_HOME_OPTIONS = [
    {"value": "", "label": "Predefinito"},
    {"value": "horizontal", "label": "Orizzontale"},
    {"value": "vertical", "label": "Verticale"}
]

SKIP_LENGTH_OPTIONS = [
    {"value": 5000, "label": "5 secondi"},
    {"value": 10000, "label": "10 secondi"},
    {"value": 15000, "label": "15 secondi"},
    {"value": 20000, "label": "20 secondi"},
    {"value": 25000, "label": "25 secondi"},
    {"value": 30000, "label": "30 secondi"}
]

DETAIL_GENRE_LIMIT_OPTIONS = [
    {"value": 0, "label": "Nessun limite"},
    {"value": 1, "label": "1"},
    {"value": 2, "label": "2"},
    {"value": 3, "label": "3"},
    {"value": 4, "label": "4"},
    {"value": 5, "label": "5"}
]

SUBTITLE_TEXT_SIZE_OPTIONS = [
    {"value": "smaller", "label": "Molto piccolo"},
    {"value": "small", "label": "Piccolo"},
    {"value": "", "label": "Normale"},
    {"value": "medium", "label": "Normale (compatibile)"},
    {"value": "large", "label": "Grande"},
    {"value": "larger", "label": "Molto grande"},
    {"value": "extralarge", "label": "Extra grande"}
]

SUBTITLE_FONT_OPTIONS = [
    {"value": "", "label": "Predefinito"},
    {"value": "typewriter", "label": "Macchina da scrivere"},
    {"value": "print", "label": "Stampa"},
    {"value": "console", "label": "Console"},
    {"value": "casual", "label": "Casual"},
    {"value": "cursive", "label": "Corsivo"},
    {"value": "smallcaps", "label": "Maiuscoletto"}
]

SUBTITLE_SHADOW_OPTIONS = [
    {"value": "", "label": "Ombreggiato"},
    {"value": "dropshadow", "label": "Ombreggiato"},
    {"value": "raised", "label": "Rialzato"},
    {"value": "depressed", "label": "Incassato"},
    {"value": "uniform", "label": "Uniforme"},
    {"value": "none", "label": "Nessuna"}
]

SUBTITLE_COLOR_OPTIONS = [
    {"value": "#ffffff", "label": "Bianco"},
    {"value": "#ffff00", "label": "Giallo"},
    {"value": "#00ffff", "label": "Ciano"},
    {"value": "#00ff00", "label": "Verde"},
    {"value": "#ff0000", "label": "Rosso"},
    {"value": "#000000", "label": "Nero"}
]

SUBTITLE_BACKGROUND_OPTIONS = [
    {"value": "transparent", "label": "Trasparente"},
    {"value": "#000000", "label": "Nero"},
    {"value": "#333333", "label": "Grigio scuro"},
    {"value": "#ffffff", "label": "Bianco"}
]

SUBTITLE_POSITION_OPTIONS = [
    {"value": "", "label": "Predefinito"},
    {"value": "0", "label": "0%"},
    {"value": "5", "label": "5%"},
    {"value": "10", "label": "10%"},
    {"value": "15", "label": "15%"},
    {"value": "20", "label": "20%"},
    {"value": "25", "label": "25%"}
]

INTRO_SKIP_OPTIONS = [
    {"value": "ShowButton", "label": "Mostra il pulsante Salta introduzione"},
    {"value": "AutoSkip", "label": "Salta automaticamente"},
    {"value": "None", "label": "Non saltare"}
]

UP_BUTTON_ACTION_OPTIONS = [
    {"value": "", "label": "Predefinito"},
    {"value": "chapters", "label": "Capitoli / Guida diretta TV"},
    {"value": "info", "label": "Informazioni"},
    {"value": "none", "label": "Nessuna azione"}
]

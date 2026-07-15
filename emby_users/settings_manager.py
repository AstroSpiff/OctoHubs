import logging
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple, Callable

from emby_runtime.api_clients import _fetch_emby_libraries
from emby_libraries.grouping import group_libraries
from emby_users.settings_library_mapping import remap_library_config_for_server
from emby_users.settings_target_applier import SettingsApplyOptions, SettingsApplyResult, SettingsTargetApplier
from emby_users.settings_scope import (
    can_sync_config_field,
    can_sync_display_field,
    can_sync_policy_field,
)
from core.utils import get_emby_servers

logger = logging.getLogger(__name__)

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

USER_SETTINGS_SCHEMA = [
    {
        "id": "profile",
        "label": "Profilo",
        "description": "Impostazioni principali dell'account e permessi di gestione server.",
        "column": "left",
        "policy": [
            {
                "key": "IsAdministrator",
                "label": "Consenti a questo utente di gestire il server",
                "type": "bool",
                "group": "Profilo",
                "description": "Permesso amministratore completo sul server Emby."
            },
            {
                "key": "EnableUserPreferenceAccess",
                "label": "Consenti cambio password, immagine e preferenze",
                "type": "bool",
                "group": "Profilo",
                "description": "Permette all'utente di modificare le proprie preferenze personali quando Emby lo consente."
            },
            {
                "key": "AuthenticationProviderId",
                "label": "Provider autenticazione",
                "type": "text",
                "max_length": 256,
                "group": "Avanzate",
                "description": "Campo tecnico Emby: cambialo solo se sai quale provider di autenticazione usare."
            },
            {"key": "LockedOutDate", "label": "Data blocco account (timestamp)", "type": "int", "hidden": True}
        ],
        "config": []
    },
    {
        "id": "access",
        "label": "Accesso e permessi",
        "description": "Permessi server: accesso remoto, riproduzione, funzionalità, download e visibilità account.",
        "column": "left",
        "policy": [
            {
                "key": "EnableRemoteAccess",
                "label": "Consenti connessioni remote a questo Emby Server",
                "type": "bool",
                "group": "Accesso remoto",
                "description": "Se disattivato, questo utente non potrà collegarsi da remoto."
            },
            {
                "key": "EnableMediaPlayback",
                "label": "Consenti la riproduzione dei media",
                "type": "bool",
                "group": "Riproduzione"
            },
            {
                "key": "EnableAudioPlaybackTranscoding",
                "label": "Consenti conversione audio durante la riproduzione",
                "type": "bool",
                "group": "Riproduzione"
            },
            {
                "key": "EnableVideoPlaybackTranscoding",
                "label": "Consenti conversione video durante la riproduzione",
                "type": "bool",
                "group": "Riproduzione"
            },
            {
                "key": "EnablePlaybackRemuxing",
                "label": "Consenti cambio contenitore durante la riproduzione",
                "type": "bool",
                "group": "Riproduzione",
                "description": "Disattivarlo può impedire la selezione della qualità su client non compatibili."
            },
            {
                "key": "SimultaneousStreamLimit",
                "label": "Numero massimo di trasmissioni video simultanee",
                "type": "int",
                "options": STREAM_LIMIT_OPTIONS,
                "min": 0,
                "max": 1000,
                "group": "Riproduzione",
                "description": "0 significa illimitato."
            },
            {
                "key": "RemoteClientBitrateLimit",
                "label": "Limite bitrate per trasmissione remota",
                "type": "int",
                "min": 0,
                "max": 1000000,
                "group": "Riproduzione",
                "description": "Lascia vuoto o 0 per nessun limite. Emby lo mostra come limite remoto per questo utente."
            },
            {
                "key": "AutoRemoteQuality",
                "label": "Qualità trasmissione remota automatica",
                "type": "int",
                "min": 0,
                "max": 1000000,
                "group": "Riproduzione",
                "description": "Valore opzionale usato quando il client è impostato su qualità automatica."
            },
            {"key": "EnableLiveTvAccess", "label": "Diretta TV", "type": "bool", "group": "Accesso alle funzionalità"},
            {"key": "EnableLiveTvManagement", "label": "Gestione registrazioni TV", "type": "bool", "group": "Accesso alle funzionalità"},
            {
                "key": "RestrictedFeatures",
                "label": "Funzionalità limitate (ID, una per riga)",
                "type": "list",
                "max_length": 4096,
                "group": "Accesso alle funzionalità",
                "description": "Campo avanzato: Emby usa ID funzione/plugin installati, ad esempio da /Features."
            },
            {"key": "EnableContentDeletion", "label": "Consenti eliminazione dei media", "type": "bool", "group": "Eliminazione media"},
            {
                "key": "EnableContentDeletionFromFolders",
                "label": "Librerie da cui l'utente può eliminare",
                "type": "library_multi",
                "group": "Eliminazione media"
            },
            {"key": "EnableRemoteControlOfOtherUsers", "label": "Consenti controllo remoto di altri utenti", "type": "bool", "group": "Telecomando"},
            {"key": "EnableSharedDeviceControl", "label": "Consenti controllo remoto dei dispositivi condivisi", "type": "bool", "group": "Telecomando"},
            {"key": "EnableContentDownloading", "label": "Consenti download dei media", "type": "bool", "group": "Download"},
            {"key": "EnableSyncTranscoding", "label": "Consenti download con conversione", "type": "bool", "group": "Download"},
            {"key": "EnableSubtitleDownloading", "label": "Consenti download dei sottotitoli", "type": "bool", "group": "Sottotitoli"},
            {"key": "EnableSubtitleManagement", "label": "Consenti eliminazione sottotitoli esistenti", "type": "bool", "group": "Sottotitoli"},
            {"key": "AllowCameraUpload", "label": "Attiva caricamento da fotocamera", "type": "bool", "group": "Condivisione"},
            {"key": "EnableMediaConversion", "label": "Consenti conversione dei media", "type": "bool", "group": "Condivisione"},
            {
                "key": "AllowSharingPersonalItems",
                "label": "Consenti condivisione contenuti personali in playlist",
                "type": "bool",
                "group": "Condivisione"
            },
            {"key": "EnablePublicSharing", "label": "Consenti condivisione pubblica dei media", "type": "bool", "group": "Condivisione"},
            {"key": "AllowTagOrRating", "label": "Consenti tag e valutazioni", "type": "bool", "group": "Condivisione"},
            {"key": "IsDisabled", "label": "Disattiva questo utente", "type": "bool", "group": "Stato account"},
            {"key": "IsHidden", "label": "Nascondi nelle schermate di accesso locale", "type": "bool", "group": "Stato account"},
            {"key": "IsHiddenRemotely", "label": "Nascondi nelle schermate di accesso remoto", "type": "bool", "group": "Stato account"},
            {"key": "IsHiddenFromUnusedDevices", "label": "Nascondi sui dispositivi mai usati", "type": "bool", "group": "Stato account"},
            {"key": "EnableAllDevices", "label": "Consenti tutti i dispositivi", "type": "bool", "group": "Accesso dispositivi"},
            {"key": "EnabledDevices", "label": "Dispositivi abilitati (ID, uno per riga)", "type": "list", "group": "Accesso dispositivi"},
            {"key": "EnableAllChannels", "label": "Consenti tutti i canali", "type": "bool", "group": "Accesso canali"},
            {"key": "EnabledChannels", "label": "Canali abilitati (ID, uno per riga)", "type": "list", "group": "Accesso canali"},
            {"key": "DisablePremiumFeatures", "label": "Disabilita funzioni Premiere", "type": "bool", "hidden": True},
            {"key": "InvalidLoginAttemptCount", "label": "Tentativi login non validi", "type": "int", "group": "Avanzate"},
            {"key": "LoginAttemptsBeforeLockout", "label": "Tentativi prima blocco", "type": "int", "hidden": True}
        ],
        "config": []
    },
    {
        "id": "libraries",
        "label": "Accesso librerie",
        "description": "Usa le associazioni librerie di OctoHub per applicare gli ID corretti su ogni server.",
        "column": "right",
        "libraries": True,
        "policy": [
            {"key": "EnableAllFolders", "label": "Accesso a tutte le librerie", "type": "bool", "hidden": True},
            {"key": "EnabledFolders", "label": "Librerie abilitate", "type": "library_multi", "hidden": True}
        ],
        "config": []
    },
    {
        "id": "parental",
        "label": "Controllo parentale",
        "description": "Restrizioni per rating, contenuti non classificati, tag e fasce orarie.",
        "column": "left",
        "policy": [
            {
                "key": "MaxParentalRating",
                "label": "Classificazione parentale massima consentita",
                "type": "int",
                "min": 0,
                "max": 1000,
                "group": "Classificazione",
                "description": "I contenuti con classificazione superiore verranno nascosti."
            },
            {
                "key": "BlockUnratedItems",
                "label": "Blocca non classificati",
                "type": "multiselect",
                "group": "Classificazione",
                "options": [
                    {"value": "Movie", "label": "Film"},
                    {"value": "Trailer", "label": "Trailer"},
                    {"value": "Series", "label": "Serie"},
                    {"value": "Music", "label": "Musica"},
                    {"value": "Book", "label": "Libri"},
                    {"value": "LiveTvChannel", "label": "Canali Live TV"},
                    {"value": "LiveTvProgram", "label": "Programmi Live TV"},
                    {"value": "ChannelContent", "label": "Contenuti canale"},
                    {"value": "Other", "label": "Altro"}
                ]
            },
            {"key": "BlockedTags", "label": "Tag bloccati (uno per riga)", "type": "list", "max_length": 4096, "group": "Tag"},
            {"key": "BlockedMediaFolders", "label": "Librerie bloccate", "type": "library_multi", "hidden": True},
            {"key": "BlockedChannels", "label": "Canali bloccati (uno per riga)", "type": "list", "hidden": True},
            {"key": "IncludeTags", "label": "Tag consentiti (uno per riga)", "type": "list", "max_length": 4096, "group": "Tag"},
            {
                "key": "IsTagBlockingModeInclusive",
                "label": "Consenti solo gli elementi con i tag consentiti",
                "type": "bool",
                "group": "Tag",
                "description": "Se attivo, i tag consentiti diventano una whitelist; se spento, i tag bloccati sono una blacklist."
            },
            {
                "key": "ExcludedSubFolders",
                "label": "Sottocartelle escluse (ID, una per riga)",
                "type": "list",
                "max_length": 4096,
                "group": "Tag"
            },
            {
                "key": "AccessSchedules",
                "label": "Fasce orarie accesso",
                "type": "schedule",
                "group": "Accesso pianificato",
                "options": [
                    {"value": "Sunday", "label": "Domenica"},
                    {"value": "Monday", "label": "Lunedì"},
                    {"value": "Tuesday", "label": "Martedì"},
                    {"value": "Wednesday", "label": "Mercoledì"},
                    {"value": "Thursday", "label": "Giovedì"},
                    {"value": "Friday", "label": "Venerdì"},
                    {"value": "Saturday", "label": "Sabato"},
                    {"value": "Everyday", "label": "Tutti i giorni"},
                    {"value": "Weekday", "label": "Feriali"},
                    {"value": "Weekend", "label": "Weekend"}
                ]
            }
        ],
        "config": []
    },
    {
        "id": "display",
        "label": "Schermo e librerie",
        "description": "Impostazioni di visualizzazione salvate tra UserConfiguration e DisplayPreferences.",
        "column": "right",
        "policy": [],
        "config": [
            {"key": "OrderedViews", "label": "Ordine libreria", "type": "library_order", "group": "Librerie"},
            {"key": "LatestItemsExcludes", "label": "Escludi da Media recenti", "type": "library_multi", "group": "Librerie"},
            {"key": "MyMediaExcludes", "label": "Escludi da I miei media", "type": "library_multi", "group": "Librerie"},
            {"key": "GroupedFolders", "label": "Raggruppa cartelle", "type": "bool", "hidden": True},
            {"key": "DisplayCollectionsView", "label": "Mostra vista Collezioni", "type": "bool", "hidden": True},
            {"key": "ShowParentImages", "label": "Mostra immagini parent", "type": "bool", "hidden": True},
            {"key": "ShowUpdateCheckBox", "label": "Mostra aggiornamento librerie", "type": "bool", "hidden": True}
        ],
        "display_preferences": [
            {"key": "language", "label": "Lingua interfaccia", "type": "select", "options": DISPLAY_LANGUAGE_OPTIONS, "group": "Display"},
            {"key": "datetimelocale", "label": "Formato data e ora", "type": "select", "options": DISPLAY_LANGUAGE_OPTIONS, "group": "Display"},
            {"key": "appTheme", "label": "Tema", "type": "select", "options": THEME_OPTIONS, "group": "Tema"},
            {"key": "skin", "label": "Impostazioni del tema / skin", "type": "text", "max_length": 128, "group": "Tema"},
            {"key": "secondaryColor", "label": "Colore secondario", "type": "select", "options": SECONDARY_COLOR_OPTIONS, "group": "Tema"},
            {"key": "dashboardTheme", "label": "Tema dashboard amministrazione", "type": "select", "options": THEME_OPTIONS, "group": "Tema"},
            {"key": "audioBackgroundStyle", "label": "Stile sfondo audio in riproduzione", "type": "select", "options": AUDIO_BACKGROUND_OPTIONS, "group": "Schermo"},
            {"key": "tvProgramView", "label": "Visualizzazione programma TV preferito", "type": "select", "options": TV_PROGRAM_VIEW_OPTIONS, "group": "Schermo"},
            {"key": "autoOpenSingleItem", "label": "Apri automaticamente gli elementi singoli nelle cartelle", "type": "bool", "group": "Schermo"},
            {"key": "hideEpisodeSpoilers", "label": "Nascondi dettagli spoiler degli episodi non riprodotti", "type": "bool", "group": "Schermo"},
            {"key": "enableLogoAsTitle", "label": "Visualizza immagini logo come titolo nei dettagli", "type": "bool", "group": "Schermate dettaglio"},
            {"key": "showDetailPoster", "label": "Mostra poster nella schermata dettaglio", "type": "bool", "group": "Schermate dettaglio"},
            {"key": "detailGenreLimit", "label": "Limite visualizzazione generi nei dettagli", "type": "int", "options": DETAIL_GENRE_LIMIT_OPTIONS, "min": 0, "max": 20, "group": "Schermate dettaglio"},
            {"key": "listGenreLimit", "label": "Limite generi per playlist/raccolte/artisti", "type": "int", "options": DETAIL_GENRE_LIMIT_OPTIONS, "min": 0, "max": 20, "group": "Schermate dettaglio"},
            {"key": "showCompleteMediaInfo", "label": "Mostra media completi nella parte inferiore dei dettagli", "type": "bool", "group": "Schermate dettaglio"},
            {"key": "enableThemeSongs", "label": "Riproduci theme song", "type": "bool", "group": "Tema"},
            {"key": "enableThemeVideos", "label": "Riproduci theme video", "type": "bool", "group": "Tema"},
            {"key": "enableBackdrops", "label": "Mostra backdrop", "type": "bool", "group": "Tema"},
            {"key": "enableSeasonalThemes", "label": "Consenti temi stagionali", "type": "bool", "group": "Tema"}
        ]
    },
    {
        "id": "home",
        "label": "Pagina Home",
        "description": "Sezioni Home, nascondi riprodotti e schermate predefinite per libreria.",
        "column": "right",
        "policy": [],
        "config": [
            {"key": "HidePlayedInLatest", "label": "Nascondi contenuti riprodotti da Media recenti", "type": "bool", "group": "Nascondi riprodotti"},
            {"key": "HidePlayedInMoreLikeThis", "label": "Nascondi contenuti riprodotti da Altri come questo", "type": "bool", "group": "Nascondi riprodotti"},
            {"key": "HidePlayedInSuggestions", "label": "Nascondi contenuti riprodotti da Suggerimenti", "type": "bool", "group": "Nascondi riprodotti"},
            {"key": "DisplayMissingEpisodes", "label": "Mostra episodi mancanti", "type": "bool", "group": "Serie TV"}
        ],
        "display_preferences": [
            {"key": "tvhome", "label": "Home TV", "type": "select", "options": TV_HOME_OPTIONS, "group": "Schermata Home"},
            {"key": "homesection0", "label": "Sezione pagina Home 1", "type": "select", "options": HOME_SECTION_OPTIONS, "group": "Sezioni Home"},
            {"key": "homesection1", "label": "Sezione pagina Home 2", "type": "select", "options": HOME_SECTION_OPTIONS, "group": "Sezioni Home"},
            {"key": "homesection2", "label": "Sezione pagina Home 3", "type": "select", "options": HOME_SECTION_OPTIONS, "group": "Sezioni Home"},
            {"key": "homesection3", "label": "Sezione pagina Home 4", "type": "select", "options": HOME_SECTION_OPTIONS, "group": "Sezioni Home"},
            {"key": "homesection4", "label": "Sezione pagina Home 5", "type": "select", "options": HOME_SECTION_OPTIONS, "group": "Sezioni Home"},
            {"key": "homesection5", "label": "Sezione pagina Home 6", "type": "select", "options": HOME_SECTION_OPTIONS, "group": "Sezioni Home"},
            {"key": "homesection6", "label": "Sezione pagina Home 7", "type": "select", "options": HOME_SECTION_OPTIONS, "group": "Sezioni Home"},
            {
                "key": "__library_landing__",
                "label": "Schermata predefinita per libreria",
                "type": "library_landing",
                "group": "Schermate predefinite",
                "description": "OctoHub usa gli ID delle librerie del server aperto. Per Live TV Emby usa la chiave landing-livetv."
            }
        ]
    },
    {
        "id": "playback_prefs",
        "label": "Preferenze riproduzione",
        "description": "Preferenze audio e riproduzione salvate nella configurazione utente.",
        "column": "right",
        "policy": [],
        "config": [
            {"key": "AudioLanguagePreference", "label": "Lingua audio preferita", "type": "language", "options": LANGUAGE_OPTIONS, "max_length": 8, "group": "Audio"},
            {"key": "PlayDefaultAudioTrack", "label": "Riproduci la traccia audio predefinita indipendentemente dalla lingua", "type": "bool", "group": "Audio"},
            {"key": "RememberAudioSelections", "label": "Ricorda le selezioni delle tracce audio", "type": "bool", "group": "Audio"},
            {"key": "EnableNextEpisodeAutoPlay", "label": "Riproduci automaticamente l'episodio successivo", "type": "bool", "group": "Avanzate"},
            {"key": "ResumeRewindSeconds", "label": "Alla ripresa, riavvolgi automaticamente (secondi)", "type": "int", "min": 0, "max": 3600, "group": "Avanzate"},
            {
                "key": "IntroSkipMode",
                "label": "Modalità di salto dell'introduzione",
                "type": "select",
                "group": "Avanzate",
                "options": INTRO_SKIP_OPTIONS
            }
        ],
        "display_preferences": [
            {
                "key": "enableCinemaMode",
                "label": "Cinema mode",
                "type": "bool",
                "group": "Avanzate",
                "description": "Preferenza client: alcuni client potrebbero gestirla localmente."
            },
            {"key": "enableNextVideoInfoOverlay", "label": "Mostra anteprima successiva", "type": "bool", "group": "Avanzate"},
            {"key": "skipForwardLength", "label": "Durata salto in avanti", "type": "int", "options": SKIP_LENGTH_OPTIONS, "min": 0, "max": 3600000, "group": "Avanzate"},
            {"key": "skipBackLength", "label": "Durata salto all'indietro", "type": "int", "options": SKIP_LENGTH_OPTIONS, "min": 0, "max": 3600000, "group": "Avanzate"},
            {
                "key": "enableStillWatchingPrompt",
                "label": "Attiva richiesta \"Stai ancora guardando?\"",
                "type": "bool",
                "group": "Avanzate",
                "description": "Preferenza client: può essere ignorata da client che non la supportano."
            },
            {
                "key": "showPlaybackRating",
                "label": "Mostra classificazione all'avvio della riproduzione",
                "type": "bool",
                "group": "Avanzate",
                "description": "Preferenza client: può essere ignorata da client che non la supportano."
            },
            {
                "key": "videoPlayerUpButtonAction",
                "label": "Azione del pulsante Su nel player video",
                "type": "select",
                "options": UP_BUTTON_ACTION_OPTIONS,
                "group": "Avanzate"
            }
        ]
    },
    {
        "id": "subtitles",
        "label": "Preferenze sottotitoli",
        "description": "Lingua e modalità sottotitoli salvate nella configurazione utente.",
        "column": "right",
        "policy": [],
        "config": [
            {"key": "SubtitleLanguagePreference", "label": "Lingua dei sottotitoli preferita", "type": "language", "options": LANGUAGE_OPTIONS, "max_length": 8, "group": "Sottotitoli"},
            {"key": "SubtitlePlayDefault", "label": "Sottotitoli predefiniti", "type": "bool", "hidden": True},
            {
                "key": "SubtitleMode",
                "label": "Modalità sottotitoli",
                "type": "select",
                "group": "Sottotitoli",
                "options": [
                    {"value": "Default", "label": "Default"},
                    {"value": "Always", "label": "Sempre"},
                    {"value": "Smart", "label": "Smart"},
                    {"value": "OnlyForced", "label": "Solo forzati"},
                    {"value": "HearingImpaired", "label": "Non udenti"},
                    {"value": "None", "label": "Mai"}
                ]
            },
            {"key": "RememberSubtitleSelections", "label": "Ricorda le selezioni delle tracce dei sottotitoli", "type": "bool", "group": "Sottotitoli"}
        ],
        "display_preferences": [
            {
                "key": "subtitleburnin",
                "label": "Burn-in sottotitoli",
                "type": "select",
                "group": "Sottotitoli",
                "options": [
                    {"value": "", "label": "Auto"},
                    {"value": "onlyimageformats", "label": "Solo formati immagine"},
                    {"value": "allcomplexformats", "label": "Tutti i formati complessi"}
                ]
            },
            {
                "key": "localplayersubtitleappearance3.textSize",
                "label": "Dimensione testo",
                "type": "select",
                "options": SUBTITLE_TEXT_SIZE_OPTIONS,
                "group": "Aspetto sottotitoli",
                "container_key": "localplayersubtitleappearance3",
                "property": "textSize"
            },
            {
                "key": "localplayersubtitleappearance3.font",
                "label": "Font",
                "type": "select",
                "options": SUBTITLE_FONT_OPTIONS,
                "group": "Aspetto sottotitoli",
                "container_key": "localplayersubtitleappearance3",
                "property": "font"
            },
            {
                "key": "localplayersubtitleappearance3.textColor",
                "label": "Colore testo",
                "type": "select",
                "options": SUBTITLE_COLOR_OPTIONS,
                "group": "Aspetto sottotitoli",
                "container_key": "localplayersubtitleappearance3",
                "property": "textColor"
            },
            {
                "key": "localplayersubtitleappearance3.dropShadow",
                "label": "Ombra portata",
                "type": "select",
                "options": SUBTITLE_SHADOW_OPTIONS,
                "group": "Aspetto sottotitoli",
                "container_key": "localplayersubtitleappearance3",
                "property": "dropShadow"
            },
            {
                "key": "localplayersubtitleappearance3.textBackground",
                "label": "Colore sfondo",
                "type": "select",
                "options": SUBTITLE_BACKGROUND_OPTIONS,
                "group": "Aspetto sottotitoli",
                "container_key": "localplayersubtitleappearance3",
                "property": "textBackground"
            },
            {
                "key": "localplayersubtitleappearance3.bottomOffset",
                "label": "Posizione dal bordo inferiore",
                "type": "select",
                "options": SUBTITLE_POSITION_OPTIONS,
                "group": "Posizione sottotitoli",
                "container_key": "localplayersubtitleappearance3",
                "property": "bottomOffset"
            },
            {
                "key": "localplayersubtitleappearance3.topOffset",
                "label": "Posizione dal bordo superiore",
                "type": "select",
                "options": SUBTITLE_POSITION_OPTIONS,
                "group": "Posizione sottotitoli",
                "container_key": "localplayersubtitleappearance3",
                "property": "topOffset"
            }
        ]
    },
    {
        "id": "profile_pin",
        "label": "PIN profilo",
        "description": "PIN locale del profilo Emby. La password account resta nel pannello password dedicato.",
        "column": "right",
        "policy": [],
        "config": [
            {
                "key": "ProfilePin",
                "label": "PIN del profilo",
                "type": "password",
                "max_length": 32,
                "group": "PIN profilo",
                "description": "Emby di solito richiede un PIN numerico di 4 cifre per l'accesso rapido al profilo."
            },
            {"key": "EnableLocalPassword", "label": "Richiedi PIN locale del profilo", "type": "bool", "group": "PIN profilo"}
        ]
    }
]

SETTINGS_POLICY_FIELDS = {
    field["key"]
    for category in USER_SETTINGS_SCHEMA
    for field in category.get("policy", [])
}

SETTINGS_CONFIG_FIELDS = {
    field["key"]
    for category in USER_SETTINGS_SCHEMA
    for field in category.get("config", [])
}

SETTINGS_DISPLAY_PREF_FIELDS = {
    field["key"]
    for category in USER_SETTINGS_SCHEMA
    for field in category.get("display_preferences", [])
    if field.get("key") != "__library_landing__"
}

SETTINGS_LIST_FIELDS = {
    field["key"]
    for category in USER_SETTINGS_SCHEMA
    for field in category.get("policy", []) + category.get("config", []) + category.get("display_preferences", [])
    if field.get("type") in ("list", "multiselect", "library_multi", "library_order")
}

SETTINGS_JSON_FIELDS = {
    field["key"]
    for category in USER_SETTINGS_SCHEMA
    for field in category.get("policy", []) + category.get("config", []) + category.get("display_preferences", [])
    if field.get("type") in ("json", "schedule")
}

SETTINGS_FIELD_META = {
    field["key"]: field
    for category in USER_SETTINGS_SCHEMA
    for field in category.get("policy", []) + category.get("config", []) + category.get("display_preferences", [])
    if field.get("key") != "__library_landing__"
}

SETTINGS_DISPLAY_JSON_FIELD_META = {
    field["key"]: field
    for category in USER_SETTINGS_SCHEMA
    for field in category.get("display_preferences", [])
    if field.get("container_key") and field.get("property")
}


class SettingsManager:
    def __init__(
        self,
        storage,
        config: Dict[str, Any],
        get_server_by_id: Callable[[str], Optional[Dict[str, Any]]],
        get_group_users: Callable[[str], List[Tuple[str, str, Optional[str]]]],
        fetch_user_details: Callable[[Dict[str, Any], str], Tuple[Optional[Dict[str, Any]], Optional[str]]],
        update_user_policy: Callable[[Dict[str, Any], str, Dict[str, Any]], Tuple[bool, Optional[str]]],
        update_user_config: Callable[[Dict[str, Any], str, Dict[str, Any]], Tuple[bool, Optional[str]]],
        fetch_user_display_preferences: Optional[
            Callable[[Dict[str, Any], str], Tuple[Optional[Dict[str, Any]], Optional[str]]]
        ] = None,
        update_user_display_preferences: Optional[
            Callable[[Dict[str, Any], str, Dict[str, Any]], Tuple[bool, Optional[str]]]
        ] = None,
        fetch_server_features: Optional[
            Callable[[Dict[str, Any]], Tuple[List[Dict[str, Any]], Optional[str]]]
        ] = None,
    ):
        self.storage = storage
        self.config = config
        self._get_server_by_id = get_server_by_id
        self._get_group_users = get_group_users
        self._fetch_user_details = fetch_user_details
        self._update_user_policy = update_user_policy
        self._update_user_config = update_user_config
        self._fetch_user_display_preferences = fetch_user_display_preferences
        self._update_user_display_preferences = update_user_display_preferences
        self._fetch_server_features = fetch_server_features
        self._target_applier = SettingsTargetApplier(
            get_server_by_id=self._get_server_by_id,
            fetch_user_details=self._fetch_user_details,
            update_user_policy=self._update_user_policy,
            update_user_config=self._update_user_config,
            fetch_display_preferences=self._fetch_display_preferences_for_user,
            update_display_preferences=self._update_user_display_preferences,
            derive_enabled_ids=self._derive_enabled_ids_from_groups,
            remap_display_preferences=self._remap_display_preferences_for_server,
            build_display_payload=self._build_display_preferences_payload,
        )

    def settings_group_key(self, group_id: str) -> str:
        return f"emby_group_settings:{group_id}"

    def settings_user_key(self, server_id: str, user_id: str) -> str:
        return f"emby_user_settings:{server_id}:{user_id}"

    def load_settings_entry(self, key: str) -> Optional[Dict[str, Any]]:
        entry = self.storage.get_key_value(key)
        if not isinstance(entry, dict):
            return None
        settings = entry.get("settings")
        if not isinstance(settings, dict):
            return None
        return entry

    def _save_settings_entry(self, key: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "settings": settings,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": USER_SETTINGS_SCHEMA_VERSION
        }
        self.storage.set_key_value(key, payload)
        return payload

    def _is_dynamic_display_pref_key(self, key: str) -> bool:
        return isinstance(key, str) and key.startswith("landing-")

    def _is_allowed_display_pref_key(self, key: str) -> bool:
        return key in SETTINGS_DISPLAY_PREF_FIELDS or self._is_dynamic_display_pref_key(key)

    def _library_group_key(self, collection_type: str, group_name: str) -> str:
        return f"{collection_type}::{group_name}".lower()

    def _build_library_group_index(
        self
    ) -> Tuple[
        List[Dict[str, Any]],
        Dict[str, Dict[str, List[str]]],
        Dict[str, Dict[str, Any]],
        Dict[str, Dict[str, str]]
    ]:
        servers = get_emby_servers(self.config, enabled_only=True)
        all_libraries: Dict[str, Any] = {}
        for server in servers:
            if not server.get("enabled"):
                continue
            server_id = server.get("id")
            if not server_id:
                continue
            libraries, error = _fetch_emby_libraries(server)
            all_libraries[server_id] = {
                "ok": error is None,
                "libraries": libraries,
                "error": error,
                "name": server.get("name"),
                "alias": server.get("alias"),
                "original_name": server.get("original_name"),
                "icon": server.get("icon") or "fa-server",
                "icon_style": server.get("icon_style") or "solid",
                "icon_color": server.get("icon_color") or "#3b82f6"
            }

        associations = {}
        try:
            associations = self.storage.load_library_associations()
        except Exception:
            associations = {}
        grouped = group_libraries(all_libraries, associations)
        index: Dict[str, Dict[str, List[str]]] = {}
        membership: Dict[str, Dict[str, str]] = {}
        for group in grouped:
            group_name = group.get("group_name") or ""
            collection_type = group.get("collection_type") or ""
            group_key = self._library_group_key(collection_type, group_name)
            for lib in group.get("libraries", []):
                server_id = str(lib.get("server_id") or "")
                library_id = lib.get("library_id")
                if not server_id or not library_id:
                    continue
                lib_id = str(library_id)
                index.setdefault(group_key, {}).setdefault(server_id, []).append(lib_id)
                membership.setdefault(server_id, {})[lib_id] = group_key
        return grouped, index, all_libraries, membership

    def _normalize_settings_payload(
        self,
        settings: Optional[Dict[str, Any]],
        protect_fields: bool = False
    ) -> Dict[str, Any]:
        if not isinstance(settings, dict):
            settings = {}
        policy_raw = settings.get("policy")
        if not isinstance(policy_raw, dict):
            policy_raw = {}
        config_raw = settings.get("config")
        if not isinstance(config_raw, dict):
            config_raw = {}
        display_raw = settings.get("display_preferences")
        if not isinstance(display_raw, dict):
            display_raw = {}
        libraries_raw = settings.get("libraries")
        if not isinstance(libraries_raw, dict):
            libraries_raw = {}

        def _coerce_list(value: Any) -> List[str]:
            if value is None:
                return []
            if isinstance(value, list):
                return [str(x) for x in value if x is not None and str(x).strip() != ""]
            if isinstance(value, str):
                parts = [p.strip() for p in value.replace("\n", ",").split(",")]
                return [p for p in parts if p]
            return []

        def _coerce_json(value: Any) -> Any:
            if value is None:
                return []
            if isinstance(value, (list, dict)):
                return value
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except Exception:
                    return value
            return value

        def _coerce_int(value: Any, key: str) -> Optional[int]:
            if value is None or value == "":
                return None
            try:
                number = int(value)
            except (TypeError, ValueError):
                return None
            meta = SETTINGS_FIELD_META.get(key) or {}
            if isinstance(meta.get("min"), int):
                number = max(meta["min"], number)
            if isinstance(meta.get("max"), int):
                number = min(meta["max"], number)
            return number

        def _coerce_text(value: Any, key: str) -> str:
            text = str(value)
            meta = SETTINGS_FIELD_META.get(key) or {}
            max_length = meta.get("max_length")
            if isinstance(max_length, int) and max_length > 0:
                text = text[:max_length]
            return text

        policy = {}
        for k, v in policy_raw.items():
            if k not in SETTINGS_POLICY_FIELDS or v is None:
                continue
            if protect_fields and not can_sync_policy_field(str(k)):
                continue
            if k in SETTINGS_LIST_FIELDS:
                policy[k] = _coerce_list(v)
            elif k in SETTINGS_JSON_FIELDS:
                policy[k] = _coerce_json(v)
            elif SETTINGS_FIELD_META.get(k, {}).get("type") == "int":
                coerced = _coerce_int(v, k)
                if coerced is not None:
                    policy[k] = coerced
            elif SETTINGS_FIELD_META.get(k, {}).get("type") in ("text", "password", "language", "select"):
                policy[k] = _coerce_text(v, k)
            else:
                policy[k] = v

        config = {}
        for k, v in config_raw.items():
            if k not in SETTINGS_CONFIG_FIELDS or v is None:
                continue
            if protect_fields and not can_sync_config_field(str(k)):
                continue
            if k in SETTINGS_LIST_FIELDS:
                config[k] = _coerce_list(v)
            elif k in SETTINGS_JSON_FIELDS:
                config[k] = _coerce_json(v)
            elif SETTINGS_FIELD_META.get(k, {}).get("type") == "int":
                coerced = _coerce_int(v, k)
                if coerced is not None:
                    config[k] = coerced
            elif SETTINGS_FIELD_META.get(k, {}).get("type") in ("text", "password", "language", "select"):
                config[k] = _coerce_text(v, k)
            else:
                config[k] = v

        display_preferences = {}
        for k, v in display_raw.items():
            if not self._is_allowed_display_pref_key(k) or v is None:
                continue
            if protect_fields and not can_sync_display_field(str(k)):
                continue
            meta = SETTINGS_FIELD_META.get(k) or {}
            field_type = meta.get("type")
            if k in SETTINGS_LIST_FIELDS:
                display_preferences[k] = _coerce_list(v)
            elif k in SETTINGS_JSON_FIELDS:
                display_preferences[k] = _coerce_json(v)
            elif field_type == "int":
                coerced = _coerce_int(v, k)
                if coerced is not None:
                    display_preferences[k] = coerced
            elif field_type in ("text", "password", "language", "select"):
                display_preferences[k] = _coerce_text(v, k)
            elif field_type == "bool":
                if isinstance(v, str):
                    display_preferences[k] = v.lower() in ("true", "1", "yes", "on")
                else:
                    display_preferences[k] = bool(v)
            else:
                display_preferences[k] = _coerce_text(v, k) if isinstance(v, str) else v

        mode = libraries_raw.get("mode") if isinstance(libraries_raw.get("mode"), str) else "all"
        if mode not in ("all", "custom"):
            mode = "all"
        groups_raw = libraries_raw.get("groups")
        if not isinstance(groups_raw, dict):
            groups_raw = {}
        groups = {str(k).lower(): bool(v) for k, v in groups_raw.items()}

        items_raw = libraries_raw.get("items")
        if not isinstance(items_raw, list):
            items_raw = []
        items = [str(x) for x in items_raw if x]

        return {
            "policy": policy,
            "config": config,
            "display_preferences": display_preferences,
            "libraries": {"mode": mode, "groups": groups, "items": items}
        }

    def settings_equal(self, left: Dict[str, Any], right: Dict[str, Any]) -> bool:
        left_norm = self._normalize_settings_payload(left)
        right_norm = self._normalize_settings_payload(right)
        left_norm.get("libraries", {}).pop("items", None)
        right_norm.get("libraries", {}).pop("items", None)
        return left_norm == right_norm

    def _derive_enabled_ids_from_groups(
        self,
        groups: Dict[str, bool],
        library_index: Dict[str, Dict[str, List[str]]],
        server_id: str
    ) -> List[str]:
        enabled_ids: List[str] = []
        for group_key, enabled in (groups or {}).items():
            if not enabled:
                continue
            for lib_id in library_index.get(group_key, {}).get(server_id, []):
                enabled_ids.append(str(lib_id))
        return enabled_ids

    def _build_library_items(
        self,
        server_id: str,
        libraries_by_server: Dict[str, Dict[str, Any]],
        membership: Dict[str, Dict[str, str]]
    ) -> List[Dict[str, Any]]:
        payload = libraries_by_server.get(server_id) or {}
        libraries = payload.get("libraries") or []
        items: List[Dict[str, Any]] = []
        for lib in libraries:
            if not isinstance(lib, dict):
                continue
            lib_id = lib.get("id") or lib.get("library_id")
            if not lib_id:
                continue
            lib_id_str = str(lib_id)
            group_key = membership.get(server_id, {}).get(lib_id_str)
            alt_ids = set()
            if lib.get("folder_id"):
                alt_ids.add(str(lib.get("folder_id")))
            if lib.get("item_id"):
                alt_ids.add(str(lib.get("item_id")))
            if lib.get("guid"):
                alt_ids.add(str(lib.get("guid")))
            for view_id in lib.get("view_ids") or []:
                if view_id:
                    alt_ids.add(str(view_id))
            alt_ids.add(lib_id_str)
            items.append({
                "id": lib_id_str,
                "name": lib.get("name"),
                "collection_type": lib.get("collection_type") or "folder",
                "group_key": group_key,
                "is_grouped": bool(group_key),
                "alt_ids": sorted(alt_ids)
            })
        return items

    def _coerce_display_pref_from_custom(self, key: str, value: Any) -> Any:
        meta = SETTINGS_FIELD_META.get(key) or {}
        field_type = meta.get("type")
        if value is None:
            return None
        if field_type == "bool":
            if isinstance(value, bool):
                return value
            return str(value).lower() in ("true", "1", "yes", "on")
        if field_type == "int":
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
        if field_type in ("json", "schedule"):
            if isinstance(value, (dict, list)):
                return value
            try:
                return json.loads(value)
            except Exception:
                return [] if field_type == "schedule" else value
        return "" if value is None else str(value)

    def _serialize_display_pref_value(self, key: str, value: Any) -> Optional[str]:
        if value is None:
            return None
        meta = SETTINGS_FIELD_META.get(key) or {}
        field_type = meta.get("type")
        if field_type == "bool":
            return "true" if bool(value) else "false"
        if field_type == "int":
            return str(int(value))
        if field_type in ("json", "schedule") or isinstance(value, (dict, list)):
            return json.dumps(value, separators=(",", ":"))
        return str(value)

    def _extract_display_preferences(self, display_preferences: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(display_preferences, dict):
            return {}
        custom = display_preferences.get("CustomPrefs")
        if not isinstance(custom, dict):
            custom = {}

        out: Dict[str, Any] = {}
        for key, value in custom.items():
            key = str(key)
            if not self._is_allowed_display_pref_key(key):
                continue
            coerced = self._coerce_display_pref_from_custom(key, value)
            if coerced is not None:
                out[key] = coerced

        containers: Dict[str, Dict[str, Any]] = {}
        for field_key, meta in SETTINGS_DISPLAY_JSON_FIELD_META.items():
            container_key = meta.get("container_key")
            prop = meta.get("property")
            if not container_key or not prop:
                continue
            if container_key not in containers:
                raw_container = custom.get(container_key)
                parsed = {}
                if isinstance(raw_container, dict):
                    parsed = raw_container
                elif isinstance(raw_container, str) and raw_container.strip():
                    try:
                        parsed = json.loads(raw_container)
                    except Exception:
                        parsed = {}
                containers[container_key] = parsed if isinstance(parsed, dict) else {}
            if prop in containers[container_key]:
                out[field_key] = self._coerce_display_pref_from_custom(field_key, containers[container_key].get(prop))
        return out

    def _build_display_preferences_payload(
        self,
        existing: Optional[Dict[str, Any]],
        patch: Dict[str, Any]
    ) -> Dict[str, Any]:
        payload = dict(existing or {})
        payload["Id"] = payload.get("Id") or DISPLAY_PREFS_ID
        payload["Client"] = payload.get("Client") or DISPLAY_PREFS_CLIENT
        custom = payload.get("CustomPrefs")
        if not isinstance(custom, dict):
            custom = {}
        custom = dict(custom)

        json_containers: Dict[str, Dict[str, Any]] = {}
        for key, value in (patch or {}).items():
            if not self._is_allowed_display_pref_key(key):
                continue
            meta = SETTINGS_FIELD_META.get(key) or {}
            container_key = meta.get("container_key")
            prop = meta.get("property")
            if container_key and prop:
                if container_key not in json_containers:
                    raw_container = custom.get(container_key)
                    parsed = {}
                    if isinstance(raw_container, dict):
                        parsed = raw_container
                    elif isinstance(raw_container, str) and raw_container.strip():
                        try:
                            parsed = json.loads(raw_container)
                        except Exception:
                            parsed = {}
                    json_containers[container_key] = parsed if isinstance(parsed, dict) else {}
                json_containers[container_key][prop] = value
                continue

            serialized = self._serialize_display_pref_value(key, value)
            if serialized is None:
                custom.pop(key, None)
            else:
                custom[key] = serialized

        for container_key, values in json_containers.items():
            custom[container_key] = json.dumps(values, separators=(",", ":"))

        payload["CustomPrefs"] = custom
        return payload

    def _remap_display_preferences_for_server(
        self,
        display_patch: Dict[str, Any],
        target_server_id: str,
        membership: Dict[str, Dict[str, str]],
        library_index: Dict[str, Dict[str, List[str]]],
        source_server_id: Optional[str] = None
    ) -> Dict[str, Any]:
        if not isinstance(display_patch, dict) or not display_patch:
            return {}

        def _find_group_key(library_id: str) -> Optional[str]:
            if source_server_id:
                source_membership = membership.get(source_server_id) or {}
                if library_id in source_membership:
                    return source_membership.get(library_id)
            target_membership = membership.get(target_server_id) or {}
            if library_id in target_membership:
                return target_membership.get(library_id)
            for server_membership in membership.values():
                if library_id in server_membership:
                    return server_membership.get(library_id)
            return None

        remapped: Dict[str, Any] = {}
        for key, value in display_patch.items():
            key_str = str(key)
            if not key_str.startswith("landing-") or key_str == "landing-livetv":
                remapped[key_str] = value
                continue

            source_library_id = key_str.removeprefix("landing-")
            group_key = _find_group_key(source_library_id)
            if not group_key:
                if source_server_id == target_server_id:
                    remapped[key_str] = value
                else:
                    logger.warning(
                        "[SETTINGS] Skip DisplayPreferences %s on %s: library not associated",
                        key_str,
                        target_server_id
                    )
                continue

            target_ids = library_index.get(group_key, {}).get(target_server_id) or []
            if not target_ids:
                logger.warning(
                    "[SETTINGS] Skip DisplayPreferences %s on %s: missing associated target library for %s",
                    key_str,
                    target_server_id,
                    group_key
                )
                continue

            remapped[f"landing-{target_ids[0]}"] = value
        return remapped

    def remap_display_preferences_for_server(
        self,
        display_patch: Dict[str, Any],
        target_server_id: str,
        source_server_id: Optional[str] = None
    ) -> Dict[str, Any]:
        _, library_index, _, membership = self._build_library_group_index()
        return self._remap_display_preferences_for_server(
            display_patch,
            target_server_id,
            membership,
            library_index,
            source_server_id=source_server_id
        )

    def remap_config_for_server(
        self,
        config_patch: Dict[str, Any],
        target_server_id: str,
        source_server_id: Optional[str] = None
    ) -> Dict[str, Any]:
        _, _, libraries_by_server, membership = self._build_library_group_index()
        return remap_library_config_for_server(
            config_patch,
            target_server_id,
            source_server_id,
            libraries_by_server,
            membership,
        )

    def _fetch_display_preferences_for_user(
        self,
        server: Dict[str, Any],
        user_id: str
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        if not self._fetch_user_display_preferences:
            return None, None
        display_preferences, err = self._fetch_user_display_preferences(server, user_id)
        if err:
            logger.warning("[SETTINGS] DisplayPreferences fetch failed for user %s: %s", user_id, err)
            return None, err
        return display_preferences, None

    def _fetch_feature_items_for_server(self, server: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not server or not self._fetch_server_features:
            return []
        features, err = self._fetch_server_features(server)
        if err:
            logger.warning("[SETTINGS] Features fetch failed for server %s: %s", server.get("id"), err)
            return []
        if not isinstance(features, list):
            return []
        return [
            feature for feature in features
            if isinstance(feature, dict) and feature.get("id")
        ]

    def _extract_settings_from_details(
        self,
        details: Dict[str, Any],
        server_id: str,
        library_index: Dict[str, Dict[str, List[str]]],
        display_preferences: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        policy = details.get("Policy") if isinstance(details, dict) else {}
        if not isinstance(policy, dict):
            policy = {}
        config = details.get("Configuration") if isinstance(details, dict) else {}
        if not isinstance(config, dict):
            config = {}
        policy_out = {k: policy.get(k) for k in SETTINGS_POLICY_FIELDS if k in policy}
        config_out = {k: config.get(k) for k in SETTINGS_CONFIG_FIELDS if k in config}

        libraries = {"mode": "all", "groups": {}, "items": []}

        def _normalize_enabled_folders(raw) -> List[str]:
            if not raw:
                return []
            items = []
            if isinstance(raw, dict):
                raw_list = list(raw.values())
            else:
                raw_list = raw if isinstance(raw, list) else [raw]
            for entry in raw_list:
                if isinstance(entry, dict):
                    for key in ("Id", "ItemId", "LibraryId", "Guid"):
                        value = entry.get(key)
                        if value:
                            items.append(str(value))
                            break
                else:
                    items.append(str(entry))
            return [x for x in items if x]
        if isinstance(policy, dict):
            enable_all = policy.get("EnableAllFolders")
            enabled_folders = policy.get("EnabledFolders") or policy.get("EnabledLibraryFolders") or policy.get("EnabledMediaFolders") or []
            enabled_folders = _normalize_enabled_folders(enabled_folders)
            if enable_all is False:
                libraries["mode"] = "custom"
                enabled_set = {str(x) for x in enabled_folders if x}
                libraries["items"] = sorted(enabled_set)
                groups: Dict[str, bool] = {}
                for group_key, servers in library_index.items():
                    lib_ids = servers.get(server_id) or []
                    if any(str(lib_id) in enabled_set for lib_id in lib_ids):
                        groups[group_key] = True
                libraries["groups"] = groups

        return {
            "policy": policy_out,
            "config": config_out,
            "display_preferences": self._extract_display_preferences(display_preferences),
            "libraries": libraries
        }

    def extract_settings_snapshot(self, details: Dict[str, Any], server_id: str) -> Dict[str, Any]:
        _, library_index, _, _ = self._build_library_group_index()
        display_preferences = None
        user_id = details.get("Id") if isinstance(details, dict) else None
        server = self._get_server_by_id(server_id)
        if server and user_id:
            display_preferences, _ = self._fetch_display_preferences_for_user(server, str(user_id))
        return self._extract_settings_from_details(details, server_id, library_index, display_preferences)

    def get_settings_schema(self) -> Dict[str, Any]:
        grouped, _, _, _ = self._build_library_group_index()
        library_groups = []
        for group in grouped:
            group_name = group.get("group_name") or ""
            collection_type = group.get("collection_type") or ""
            if not group_name or not collection_type:
                continue
            library_groups.append({
                "key": self._library_group_key(collection_type, group_name),
                "group_name": group_name,
                "collection_type": collection_type,
                "servers": group.get("servers") or []
            })
        return {
            "schema_version": USER_SETTINGS_SCHEMA_VERSION,
            "categories": USER_SETTINGS_SCHEMA,
            "library_groups": library_groups
        }

    def get_settings_info(
        self,
        group_id: Optional[str] = None,
        server_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        _, library_index, libraries_by_server, membership = self._build_library_group_index()
        if group_id:
            entry = self.load_settings_entry(self.settings_group_key(group_id))
            if entry:
                settings = self._normalize_settings_payload(entry.get("settings") or {})
                links = self.storage.get_user_links(group_id=group_id)
                leader_link = next((link for link in links if link.get("is_leader")), None)
                if not leader_link and links:
                    leader_link = links[0]
                leader_server_id = leader_link["server_id"] if leader_link else None
                if leader_server_id:
                    if settings.get("libraries", {}).get("mode") == "custom":
                        if not settings.get("libraries", {}).get("items"):
                            items = self._derive_enabled_ids_from_groups(
                                settings.get("libraries", {}).get("groups") or {},
                                library_index,
                                leader_server_id
                            )
                            settings["libraries"]["items"] = items
                    library_items = self._build_library_items(leader_server_id, libraries_by_server, membership)
                else:
                    library_items = []
                leader_server = self._get_server_by_id(leader_server_id) if leader_server_id else None
                return {
                    "ok": True,
                    "saved": True,
                    "group_id": group_id,
                    "settings": settings,
                    "updated_at": entry.get("updated_at"),
                    "from_emby": False,
                    "library_items": library_items,
                    "feature_items": self._fetch_feature_items_for_server(leader_server)
                }
            links = self.storage.get_user_links(group_id=group_id)
            leader_link = next((link for link in links if link.get("is_leader")), None)
            if not leader_link and links:
                leader_link = links[0]
            if leader_link:
                leader_server_id = leader_link["server_id"]
                leader_user_id = leader_link["user_id"]
                server = self._get_server_by_id(leader_server_id)
                if server:
                    details, err = self._fetch_user_details(server, leader_user_id)
                    if not err and details:
                        display_preferences, _ = self._fetch_display_preferences_for_user(server, leader_user_id)
                        settings = self._extract_settings_from_details(
                            details,
                            leader_server_id,
                            library_index,
                            display_preferences
                        )
                        library_items = self._build_library_items(leader_server_id, libraries_by_server, membership)
                        return {
                            "ok": True,
                            "saved": False,
                            "group_id": group_id,
                            "settings": settings,
                            "updated_at": None,
                            "from_emby": True,
                            "library_items": library_items,
                            "feature_items": self._fetch_feature_items_for_server(server)
                        }
            return {
                "ok": True,
                "saved": False,
                "group_id": group_id,
                "settings": {},
                "updated_at": None,
                "from_emby": False,
                "library_items": [],
                "feature_items": []
            }

        if not server_id or not user_id:
            return {"ok": False, "error": "Missing target"}
        entry = self.load_settings_entry(self.settings_user_key(server_id, user_id))
        saved_settings = self._normalize_settings_payload(entry.get("settings") or {}) if entry else None
        server = self._get_server_by_id(server_id)
        if server:
            details, err = self._fetch_user_details(server, user_id)
            if not err and details:
                display_preferences, _ = self._fetch_display_preferences_for_user(server, user_id)
                emby_settings = self._extract_settings_from_details(
                    details,
                    server_id,
                    library_index,
                    display_preferences
                )
                saved = bool(entry)
                library_items = self._build_library_items(server_id, libraries_by_server, membership)
                return {
                    "ok": True,
                    "saved": saved,
                    "server_id": server_id,
                    "user_id": user_id,
                    "settings": emby_settings,
                    "updated_at": entry.get("updated_at") if entry else None,
                    "from_emby": True,
                    "library_items": library_items,
                    "feature_items": self._fetch_feature_items_for_server(server)
                }
        settings = saved_settings or {}
        return {
            "ok": True,
            "saved": bool(entry),
            "server_id": server_id,
            "user_id": user_id,
            "settings": settings,
            "updated_at": entry.get("updated_at") if entry else None,
            "from_emby": False,
            "library_items": [],
            "feature_items": self._fetch_feature_items_for_server(server)
        }

    def _apply_settings_to_user(
        self,
        server_id: str,
        user_id: str,
        settings: Dict[str, Any],
        library_index: Dict[str, Dict[str, List[str]]],
        libraries_by_server: Dict[str, Dict[str, Any]],
        membership: Optional[Dict[str, Dict[str, str]]] = None,
        display_source_server_id: Optional[str] = None,
        preserve_non_group: bool = False
    ) -> Tuple[bool, bool, bool]:
        normalized = self._normalize_settings_payload(settings)
        result = self._apply_normalized_settings_to_user(
            server_id,
            user_id,
            normalized,
            library_index,
            libraries_by_server,
            membership=membership,
            display_source_server_id=display_source_server_id,
            preserve_non_group=preserve_non_group,
        )
        return result.policy_ok, result.config_ok, result.display_ok

    def _apply_normalized_settings_to_user(
        self,
        server_id: str,
        user_id: str,
        normalized: Dict[str, Any],
        library_index: Dict[str, Dict[str, List[str]]],
        libraries_by_server: Dict[str, Dict[str, Any]],
        membership: Optional[Dict[str, Dict[str, str]]] = None,
        display_source_server_id: Optional[str] = None,
        preserve_non_group: bool = False,
        apply_libraries: bool = True,
    ) -> SettingsApplyResult:
        return self._target_applier.apply(
            server_id,
            user_id,
            normalized,
            library_index,
            libraries_by_server,
            membership=membership,
            options=SettingsApplyOptions(
                apply_libraries=apply_libraries,
                preserve_non_group_libraries=preserve_non_group,
                display_source_server_id=display_source_server_id,
            ),
        )

    def apply_config_sync_patch_to_user(
        self,
        server_id: str,
        user_id: str,
        settings: Dict[str, Any],
        source_server_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Apply a source-filtered config patch without altering library access."""
        normalized = self._normalize_settings_payload(settings)
        if normalized.get("display_preferences"):
            _, library_index, libraries_by_server, membership = self._build_library_group_index()
        else:
            library_index = {}
            libraries_by_server = {}
            membership = {}
        result = self._apply_normalized_settings_to_user(
            server_id,
            user_id,
            normalized,
            library_index,
            libraries_by_server,
            membership=membership,
            display_source_server_id=source_server_id,
            apply_libraries=False,
        )
        return {
            "ok": result.ok,
            "policy": result.policy_ok,
            "config": result.config_ok,
            "display_preferences": result.display_ok,
            "policy_error": result.policy_error,
            "config_error": result.config_error,
            "display_error": result.display_error,
            "fetch_error": result.fetch_error,
        }

    def apply_settings_to_users(
        self,
        targets: List[Dict[str, Any]],
        settings: Dict[str, Any],
        apply_libraries: bool = False
    ) -> Dict[str, Any]:
        _, library_index, libraries_by_server, membership = self._build_library_group_index()
        normalized = self._normalize_settings_payload(settings, protect_fields=True)
        policy_patch = normalized.get("policy") or {}
        config_patch = normalized.get("config") or {}
        display_patch = normalized.get("display_preferences") or {}
        results = {"success": [], "failed": [], "counts": {}}

        for target in targets or []:
            server_id = str(target.get("server_id") or "")
            user_id = str(target.get("user_id") or "")
            if not server_id or not user_id:
                results["failed"].append("Target non valido")
                continue

            server = self._get_server_by_id(server_id)
            target_label = (
                target.get("username")
                or target.get("name")
                or (server.get("alias") or server.get("name") if server else None)
                or f"{server_id}/{user_id}"
            )
            result = self._apply_normalized_settings_to_user(
                server_id,
                user_id,
                normalized,
                library_index,
                libraries_by_server,
                membership=membership,
                preserve_non_group=apply_libraries,
                apply_libraries=apply_libraries,
            )
            if not result.server:
                results["failed"].append(f"{target_label}: server non trovato")
                continue
            if not result.details:
                results["failed"].append(
                    f"{target_label}: impossibile leggere utente ({result.fetch_error})"
                )
                continue

            if result.ok:
                results["success"].append(target_label)
                results["counts"][target_label] = {
                    "policy": len(policy_patch),
                    "config": len(config_patch),
                    "display_preferences": len(display_patch),
                    "libraries": bool(apply_libraries)
                }
                snapshot = self._extract_settings_from_details(
                    {"Policy": result.policy or {}, "Configuration": result.config or {}},
                    server_id,
                    library_index,
                    result.display_payload
                )
                self._save_settings_entry(self.settings_user_key(server_id, user_id), snapshot)
            else:
                results["failed"].append(
                    f"{target_label}: policy={result.policy_ok} {result.policy_error or ''}, "
                    f"config={result.config_ok} {result.config_error or ''}, "
                    f"display={result.display_ok} {result.display_error or ''}"
                )

        results["ok"] = not results["failed"]
        return results

    def update_user_settings(self, server_id: str, user_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        _, library_index, libraries_by_server, membership = self._build_library_group_index()
        normalized = self._normalize_settings_payload(settings)
        items = normalized.get("libraries", {}).get("items") or []
        groups = normalized.get("libraries", {}).get("groups") or {}
        if items and not groups:
            enabled_set = {str(x) for x in items if x}
            derived_groups: Dict[str, bool] = {}
            for group_key, servers in library_index.items():
                lib_ids = servers.get(server_id) or []
                if any(str(lib_id) in enabled_set for lib_id in lib_ids):
                    derived_groups[group_key] = True
            normalized["libraries"]["groups"] = derived_groups
        ok_p, ok_c, ok_d = self._apply_settings_to_user(
            server_id,
            user_id,
            normalized,
            library_index,
            libraries_by_server,
            membership=membership,
            display_source_server_id=server_id
        )
        if not ok_p or not ok_c or not ok_d:
            return {"ok": False, "error": "Update failed", "policy": ok_p, "config": ok_c, "display_preferences": ok_d}
        entry = self._save_settings_entry(self.settings_user_key(server_id, user_id), normalized)
        logger.info("[SETTINGS] Saved user settings: %s/%s", server_id, user_id)
        return {"ok": True, "updated_at": entry.get("updated_at")}

    def sync_library_access(
        self,
        source_server_id: str,
        source_user_id: str,
        target_tuples: List[tuple]
    ) -> Dict[str, Any]:
        """
        Copy library access using configured library associations.

        Library IDs are server-specific, so this method copies source access by
        associated library group and then derives the target server's own IDs.
        """
        source_server = self._get_server_by_id(source_server_id)
        if not source_server:
            return {"error": "Source server not found"}

        source_details, err = self._fetch_user_details(source_server, source_user_id)
        if err or not source_details:
            return {"error": f"Failed to fetch source user: {err}"}

        _, library_index, libraries_by_server, membership = self._build_library_group_index()
        source_settings = self._extract_settings_from_details(source_details, source_server_id, library_index)
        source_libraries = source_settings.get("libraries") or {}
        source_mode = source_libraries.get("mode")
        source_groups = source_libraries.get("groups") or {}

        results = {
            "success": [],
            "failed": [],
            "counts": {},
            "missing_groups": {},
            "association_url": "/emby#association-card"
        }
        enabled_group_keys = [group_key for group_key, enabled in source_groups.items() if enabled]

        for target_server_id, target_user_id in target_tuples:
            target_server = self._get_server_by_id(target_server_id)
            target_label = (
                target_server.get("alias") or target_server.get("name") or target_server.get("id")
                if target_server else target_server_id
            )
            if not target_server:
                results["failed"].append(f"Server {target_server_id} not found")
                continue

            missing_groups = [
                group_key
                for group_key in enabled_group_keys
                if not library_index.get(group_key, {}).get(target_server_id)
            ]

            library_settings = {
                "mode": source_mode if source_mode in ("all", "custom") else "all",
                "groups": dict(source_groups),
                "items": []
            }
            normalized = {"policy": {}, "config": {}, "display_preferences": {}, "libraries": library_settings}
            ok_p, ok_c, ok_d = self._apply_settings_to_user(
                target_server_id,
                target_user_id,
                normalized,
                library_index,
                libraries_by_server,
                membership=membership,
                preserve_non_group=True
            )
            if ok_p and ok_c and ok_d:
                enabled_ids = []
                if library_settings["mode"] == "custom":
                    enabled_ids = self._derive_enabled_ids_from_groups(
                        source_groups,
                        library_index,
                        target_server_id
                    )
                results["success"].append(target_label)
                results["counts"][target_label] = len(enabled_ids) if library_settings["mode"] == "custom" else "all"
                results["missing_groups"][target_label] = missing_groups
            else:
                results["failed"].append(f"{target_label}: policy={ok_p}, config={ok_c}, display={ok_d}")

        return results

    def set_group_settings(self, group_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        users = self._get_group_users(group_id)
        if not users:
            return {"ok": False, "error": "Group has no users", "group_id": group_id}
        _, library_index, libraries_by_server, membership = self._build_library_group_index()
        normalized = self._normalize_settings_payload(settings, protect_fields=True)
        normalized["libraries"]["items"] = []
        entry = self._save_settings_entry(self.settings_group_key(group_id), normalized)
        failures = []
        applied = 0
        for server_id, user_id, _ in users:
            ok_p, ok_c, ok_d = self._apply_settings_to_user(
                server_id,
                user_id,
                normalized,
                library_index,
                libraries_by_server,
                membership=membership,
                preserve_non_group=True
            )
            if ok_p and ok_c and ok_d:
                applied += 1
                self._save_settings_entry(self.settings_user_key(server_id, user_id), normalized)
            else:
                failures.append({
                    "server_id": server_id,
                    "user_id": user_id,
                    "policy": ok_p,
                    "config": ok_c,
                    "display_preferences": ok_d
                })
        if failures:
            logger.error("[SETTINGS] Group update failed: %s", failures)
            return {"ok": False, "group_id": group_id, "applied": applied, "failed": failures}
        logger.info("[SETTINGS] Saved group settings: %s", group_id)
        return {"ok": True, "group_id": group_id, "applied": applied, "updated_at": entry.get("updated_at")}

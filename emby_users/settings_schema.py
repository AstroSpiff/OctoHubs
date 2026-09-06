"""Declarative schema and derived field catalogs for Emby user settings."""

from emby_users.settings_schema_options import (
    USER_SETTINGS_SCHEMA_VERSION as USER_SETTINGS_SCHEMA_VERSION,
    DISPLAY_PREFS_ID as DISPLAY_PREFS_ID,
    DISPLAY_PREFS_CLIENT as DISPLAY_PREFS_CLIENT,
    LANGUAGE_OPTIONS,
    STREAM_LIMIT_OPTIONS,
    DISPLAY_LANGUAGE_OPTIONS,
    THEME_OPTIONS,
    SECONDARY_COLOR_OPTIONS,
    AUDIO_BACKGROUND_OPTIONS,
    TV_PROGRAM_VIEW_OPTIONS,
    HOME_SECTION_OPTIONS,
    TV_HOME_OPTIONS,
    SKIP_LENGTH_OPTIONS,
    DETAIL_GENRE_LIMIT_OPTIONS,
    SUBTITLE_TEXT_SIZE_OPTIONS,
    SUBTITLE_FONT_OPTIONS,
    SUBTITLE_SHADOW_OPTIONS,
    SUBTITLE_COLOR_OPTIONS,
    SUBTITLE_BACKGROUND_OPTIONS,
    SUBTITLE_POSITION_OPTIONS,
    INTRO_SKIP_OPTIONS,
    UP_BUTTON_ACTION_OPTIONS,
)

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
        "description": "Usa le associazioni librerie di OctoHubs per applicare gli ID corretti su ogni server.",
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
                "description": "OctoHubs usa gli ID delle librerie del server aperto. Per Live TV Emby usa la chiave landing-livetv."
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

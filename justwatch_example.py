"""Esempio di utilizzo del JustWatchManager."""

from storage import DatabaseStorage
from justwatch_manager import JustWatchManager, is_justwatch_available

# Configurazione database (usa le tue impostazioni)
db_settings = {
    "HOST": "localhost",
    "PORT": 5432,
    "NAME": "octohub",
    "USER": "postgres",
    "PASSWORD": "password"
}

def main():
    # Verifica che JustWatch sia disponibile
    if not is_justwatch_available():
        print("ERRORE: Libreria JustWatch non installata.")
        print("Installa con: pip install JustWatch")
        return

    # Inizializza storage e manager
    storage = DatabaseStorage(db_settings)
    storage.ensure_ready()

    jw_manager = JustWatchManager(storage, locale="it_IT")

    # Esempi di utilizzo
    print("=== Test JustWatch Manager ===\n")

    # Esempio 1: Verifica disponibilità episodio
    print("1. Verifica The Last of Us S01E01:")
    available = jw_manager.check_availability(
        show_name="The Last of Us",
        season_num=1,
        episode_num=1,
        year=2023
    )
    print(f"   Disponibile: {'SÌ' if available else 'NO'}\n")

    # Esempio 2: Verifica episodio non ancora uscito
    print("2. Verifica episodio futuro:")
    available = jw_manager.check_availability(
        show_name="The Last of Us",
        season_num=2,
        episode_num=10,  # Episodio che probabilmente non esiste
        year=2023
    )
    print(f"   Disponibile: {'SÌ' if available else 'NO'}\n")

    # Esempio 3: Seconda chiamata usa la cache
    print("3. Seconda chiamata (dovrebbe usare cache):")
    available = jw_manager.check_availability(
        show_name="The Last of Us",
        season_num=1,
        episode_num=1,
        year=2023
    )
    print(f"   Disponibile: {'SÌ' if available else 'NO'}\n")

    # Esempio 4: Statistiche cache
    print("4. Statistiche cache:")
    stats = jw_manager.get_cache_stats()
    print(f"   Totale: {stats['total']}")
    print(f"   Disponibili: {stats['available']}")
    print(f"   Non disponibili: {stats['unavailable']}\n")

    # Esempio 5: Pulizia cache (commentato per sicurezza)
    # print("5. Pulizia cache:")
    # cleared = jw_manager.clear_cache(show_name="The Last of Us")
    # print(f"   Cancellate {cleared} voci\n")


def integrazione_con_workflow():
    """
    Esempio di integrazione nel workflow di verifica episodi.

    Usa questo pattern quando verifichi se un episodio è uscito:
    1. Controlla la data Trakt/TMDB (first_aired)
    2. Se la data è passata, verifica con JustWatch
    3. Mostra l'episodio solo se disponibile in Italia
    """
    storage = DatabaseStorage(db_settings)
    jw_manager = JustWatchManager(storage)

    # Dati episodio da Trakt/TMDB
    episode_data = {
        "show_name": "Breaking Bad",
        "season": 1,
        "episode": 1,
        "first_aired": "2008-01-20",  # Data USA
        "year": 2008
    }

    # Step 1: Verifica se la data first_aired è passata
    from datetime import datetime, timezone
    first_aired = datetime.fromisoformat(episode_data["first_aired"])
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    if first_aired > now:
        print(f"Episodio non ancora uscito (first_aired: {first_aired})")
        return False

    # Step 2: Anche se uscito negli USA, verifica disponibilità in Italia
    print(f"Episodio uscito negli USA, verifico disponibilità in Italia...")

    is_available_italy = jw_manager.check_availability(
        show_name=episode_data["show_name"],
        season_num=episode_data["season"],
        episode_num=episode_data["episode"],
        year=episode_data.get("year")
    )

    if is_available_italy:
        print("✓ Episodio disponibile in Italia su piattaforme streaming")
        return True
    else:
        print("✗ Episodio NON ancora disponibile in Italia")
        return False


if __name__ == "__main__":
    main()
    print("\n" + "="*50 + "\n")
    integrazione_con_workflow()

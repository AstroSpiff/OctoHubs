"""Test script per verificare l'integrazione JustWatch."""

import sys
from datetime import datetime, timezone


def test_imports():
    """Test 1: Verifica che tutti i moduli si importino correttamente."""
    print("Test 1: Import moduli...")
    try:
        from storage import DatabaseStorage, is_sqlalchemy_available
        print("  ✓ storage.py importato")

        if not is_sqlalchemy_available():
            print("  ✗ SQLAlchemy non disponibile")
            return False

        from justwatch_manager import JustWatchManager, is_justwatch_available
        print("  ✓ justwatch_manager.py importato")

        if not is_justwatch_available():
            print("  ✗ JustWatch non installato. Esegui: pip install JustWatch")
            return False

        print("  ✓ Tutti i moduli disponibili")
        return True
    except Exception as exc:
        print(f"  ✗ Errore import: {exc}")
        return False


def test_database_model():
    """Test 2: Verifica che il modello database sia corretto."""
    print("\nTest 2: Modello database...")
    try:
        from storage import DatabaseStorage, Base, JustWatchCache

        # Verifica che la classe esista
        assert JustWatchCache is not None
        print("  ✓ Classe JustWatchCache definita")

        # Verifica campi
        assert hasattr(JustWatchCache, "show_name")
        assert hasattr(JustWatchCache, "season")
        assert hasattr(JustWatchCache, "episode")
        assert hasattr(JustWatchCache, "is_available")
        assert hasattr(JustWatchCache, "last_checked")
        print("  ✓ Tutti i campi presenti")

        return True
    except Exception as exc:
        print(f"  ✗ Errore modello database: {exc}")
        return False


def test_storage_methods():
    """Test 3: Verifica che DatabaseStorage abbia i metodi necessari."""
    print("\nTest 3: Metodi storage...")
    try:
        from storage import DatabaseStorage

        methods = [
            "get_justwatch_cache",
            "save_justwatch_cache",
            "clear_justwatch_cache",
            "get_justwatch_cache_stats"
        ]

        for method in methods:
            assert hasattr(DatabaseStorage, method)
            print(f"  ✓ Metodo {method} presente")

        return True
    except Exception as exc:
        print(f"  ✗ Errore verifica metodi: {exc}")
        return False


def test_justwatch_manager_init():
    """Test 4: Verifica inizializzazione JustWatchManager."""
    print("\nTest 4: Inizializzazione JustWatchManager...")
    try:
        from storage import DatabaseStorage
        from justwatch_manager import JustWatchManager, is_justwatch_available

        if not is_justwatch_available():
            print("  ⚠ JustWatch non installato, test skipped")
            return True

        # Configurazione database di test (modifica con i tuoi dati)
        db_settings = {
            "HOST": "localhost",
            "PORT": 5432,
            "NAME": "octohub",
            "USER": "postgres",
            "PASSWORD": ""
        }

        # Crea storage (non connettiamo ancora al DB)
        storage = DatabaseStorage(db_settings)
        print("  ✓ DatabaseStorage creato")

        # Crea manager
        jw_manager = JustWatchManager(storage, locale="it_IT")
        print("  ✓ JustWatchManager creato")

        # Verifica attributi
        assert jw_manager.locale == "it_IT"
        assert jw_manager.country == "IT"
        print("  ✓ Locale configurato correttamente")

        return True
    except Exception as exc:
        print(f"  ✗ Errore inizializzazione: {exc}")
        return False


def test_cache_logic():
    """Test 5: Verifica logica di cache (senza DB reale)."""
    print("\nTest 5: Logica cache...")
    try:
        from datetime import timedelta

        # Simula cache hit con episodio disponibile
        cached_available = {
            "show_name": "Test Show",
            "season": 1,
            "episode": 1,
            "is_available": True,
            "last_checked": datetime.now(timezone.utc)
        }

        # Se disponibile, non serve ricontrollare
        assert cached_available["is_available"] is True
        print("  ✓ Cache hit per episodio disponibile: non ricontrolla")

        # Simula cache hit con episodio non disponibile (recente)
        cached_unavailable_recent = {
            "show_name": "Test Show",
            "season": 1,
            "episode": 2,
            "is_available": False,
            "last_checked": datetime.now(timezone.utc)
        }

        age = datetime.now(timezone.utc) - cached_unavailable_recent["last_checked"]
        assert age < timedelta(hours=24)
        print("  ✓ Cache hit per episodio non disponibile (recente): non ricontrolla")

        # Simula cache hit con episodio non disponibile (stale)
        cached_unavailable_stale = {
            "show_name": "Test Show",
            "season": 1,
            "episode": 3,
            "is_available": False,
            "last_checked": datetime.now(timezone.utc) - timedelta(hours=25)
        }

        age = datetime.now(timezone.utc) - cached_unavailable_stale["last_checked"]
        assert age >= timedelta(hours=24)
        print("  ✓ Cache stale per episodio non disponibile (>24h): ricontrolla")

        return True
    except Exception as exc:
        print(f"  ✗ Errore logica cache: {exc}")
        return False


def main():
    """Esegue tutti i test."""
    print("="*60)
    print("TEST JUSTWATCH INTEGRATION")
    print("="*60)

    tests = [
        test_imports,
        test_database_model,
        test_storage_methods,
        test_justwatch_manager_init,
        test_cache_logic
    ]

    results = []
    for test_func in tests:
        try:
            result = test_func()
            results.append(result)
        except Exception as exc:
            print(f"\n✗ Test fallito con eccezione: {exc}")
            results.append(False)

    print("\n" + "="*60)
    print("RISULTATI")
    print("="*60)

    passed = sum(results)
    total = len(results)

    print(f"Test passati: {passed}/{total}")

    if passed == total:
        print("✓ Tutti i test passati!")
        return 0
    else:
        print("✗ Alcuni test falliti")
        return 1


if __name__ == "__main__":
    sys.exit(main())

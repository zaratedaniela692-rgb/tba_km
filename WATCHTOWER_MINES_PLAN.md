Plan działania — watchtower_mines
=================================

Cel
----
- Naprawić zachowanie skryptu tak, żeby Ctrl+C (SIGINT) i SIGTERM natychmiast przerywały działanie i nie powodowały dalszych klików.

Wykonane kroki (zrobione w tej sesji)
------------------------------------
- Dodano obsługę sygnałów (`SIGINT`, `SIGTERM`) i globalny `stop_event` w `watchtower_mines.py`.
- W kluczowych miejscach (przed kliknięciami, przed długimi operacjami) sprawdzany jest `stop_event` i wykonywanie akcji jest przerywane.
- Zarejestrowano `atexit` cleanup, wypisanie informacji o zatrzymaniu.

Kroki do wykonania w następnej sesji
------------------------------------
1. Uruchomić szybki test w terminalu (dry-run + debug):

```bash
python watchtower_mines.py --dry-run --debug --list-y-tol 30
```

2. W trakcie działania nacisnąć Ctrl+C i zweryfikować:
   - skrypt wypisuje komunikat o otrzymanym sygnale;
   - dalsze kliknięcia powinny natychmiast się zatrzymać;
   - proces powinien zakończyć się i zwrócić kontrolę do terminala.

3. Jeśli kliknięcia nadal występują:
   - zwiększyć miejsca, w których sprawdzamy `stop_event` (np. pomiędzy dłuższymi wewnętrznymi pętlami);
   - sprawdzić, czy `Automator` nie uruchamia własnych wątków/metod, które wymagają dodatkowego mechanizmu anulowania — w takim wypadku dodać metodę `a.request_stop()` lub `a.stop()` i wywołać ją w handlerze sygnału.

4. Gdy testy przejdą, włączyć `--click` i obserwować zachowanie na małej próbce (krótkie loop_sleep).

Notatki techniczne
-------------------
- Jeśli `a.await_samples(...)` blokuje długo i ignoruje sygnały, test uruchamiający go w środowisku może potrzeba przerwać przez zamknięcie terminala; najlepsze rozwiązanie to dodać możliwość anulowania w `Automator` (np. metoda `stop()` ustawiająca wewnętrzny flag).
- Plik zmodyfikowany: `watchtower_mines.py`.

Chcesz, żeby w tej sesji od razu dodać: (a) dodatkowe `stop_event` checks wewnątrz `automate.py` / `Automator`, czy (b) testowy skrypt uruchomieniowy który automatycznie wysyła SIGINT po X sekundach?

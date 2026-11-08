## Obserwacja aktywnego klienta i profilu

`python .\client_router.py --once` wykonuje pojedynczy, read-only odczyt aktywnego okna i profilu. `python .\client_router.py` obserwuje zmiany okna na pierwszym planie i wypisuje tylko zmianę klienta/profilu; zakończ `Ctrl+C`. Obserwator nie czyta kolejki, nie klika i nie uruchamia zadań.

Klient natywny jest routowany przez profil tylko wtedy, gdy cztery odczyty nicku zgadzają się i dokładnie jeden istniejący wpis profilu pasuje. Chrome z tytułem Total Battle jest rozpoznawany jako browser, ale pozostaje `browser_identity_unconfigured`, dopóki browser nie otrzyma własnego zweryfikowanego regionu nicku. Nieznane okno, nick lub niejednoznaczny profil nie dostaje ścieżki kolejki.
# Konfiguracja środowiska gry

## Potwierdzone
- System operacyjny: Windows.
- Gra jest używana w przeglądarce oraz w kliencie.
- Oba sposoby uruchomienia są w trybie okna.
- Logowanie i uruchamianie okna gry wykonuje użytkowniczka.

## Zrzut referencyjny klienta
- Plik źródłowy `screenshots/world_map/zrzut_pulpitu.png` ma wymiary 1920x1080 px.
- `screenshots/world_map/pelny.png` zawiera obszar klienta o wymiarach 1920x989 px; powstał z wycinka źródła `(x=0, y=39, szerokość=1920, wysokość=989)`.
- Wycinek pomija pasek tytułowy Windows i pasek zadań; zachowuje nagłówek Total Battle oraz cały widoczny HUD i mapę.
- Rozdzielczość monitora i skala DPI systemu nie są na tej podstawie potwierdzone.

## Do ustalenia
- Rozdzielczość monitora i rozmiar obszaru klienta gry.
- Skala DPI Windows i powiększenie przeglądarki/gry.
- Monitor, na którym znajduje się okno, oraz zachowanie po przesunięciu lub zmianie rozmiaru okna.
- Czy konfiguracja ma być zapisana osobno dla przeglądarki i klienta.

## Aktualny stan kodu
`Automator.update()` przechwytuje pierwszy monitor przez `mss.monitors[1]`, a nie konkretne okno gry. Obecne współrzędne nie są definiowane względem obszaru klienta.

## Profile identyfikowane nazwą gracza
- Automatyczny profil (`--profile auto`) odczytuje widoczną nazwę z regionu `world_map.player_name`; pełny zrzut monitora przesuwa region o 39 px w dół względem adnotacji klienta.
- Id profilu ma postać `<slug-nazwy>_<5 losowych znaków alfanumerycznych>` i jest zapisywane raz w lokalnym `profiles/profile_registry.json`. Ponowne uruchomienia używają zapisanego ID, a nie losują nowego. Profile nadal nie zawierają haseł.
- OCR musi dać zgodną nazwę w kilku niezależnych odczytach. Niepewny wynik przerywa automatyczne przypisanie.
- Jeśli nazwa istnieje w rejestrze, manager zawsze prosi o wybór istniejącego profilu lub utworzenie nowego; `--new-profile` tworzy nowe konto bez pytania.
- Sama nazwa wyświetlana nie rozróżnia kont o identycznych nickach. Pytanie jest wymagane nawet przy jednym dopasowaniu, by nie przypisać drugiego konta do pierwszego profilu.
- Jawne `--profile <id>` pozostaje bez zmian i nie wykonuje OCR. Istniejące profile nie są automatycznie migrowane do rejestru.
- Przykłady: `python .\army_training_manager.py --profile auto list` wykrywa nick i używa/zakłada jego profil; `python .\army_training_manager.py --profile auto --new-profile enqueue --unit-type guardsmen --level 5 --match 1` jawnie zakłada osobny profil dla kolejnego konta o takim samym nicku. Gra musi być widoczna na głównym monitorze w 1920x1080.

## Progi dopasowania szablonów
- `config.json` przechowuje `default_min_confidence` (0-100) oraz opcjonalne nadpisania `screens.<ekran>.<element>`.
- Weryfikator wylicza umowną zgodność jako `100 * (1 - TM_SQDIFF_NORMED)`. To wynik podobieństwa szablonu, nie statystyczne prawdopodobieństwo.
- Domyślne 94.6% odpowiada istniejącemu progowi błędu `0.054` w `Automator`; wartości wymagają kalibracji na różnych screenach.
- Element jest zielony, gdy zgodność osiąga próg z konfiguracji; w przeciwnym razie jest czerwony.
- Do `verify.py` przekazuj nieopisane screeny. `opisany.png` zawiera narysowane ramki i etykiety, więc wpływa na wynik dopasowania.

## Kierunek rozwoju
- Docelowo projekt ma mieć prosty interfejs okienkowy na Windows do wybierania akcji i ustawiania parametrów.
- Interfejs GUI powstanie w przyszłości; obecny sposób uruchamiania z CLI pozostaje dostępny.
- Logika automatyzacji powinna być oddzielona od GUI i CLI, aby oba sposoby uruchamiania mogły używać tych samych flow.
- Wymaganie docelowe: obsługa co najmniej czterech okien gry, z możliwością pracy równoległej albo przełączania się między nimi.
- Każde okno/konto musi mieć jawnie przypisany, niezależny profil. Obraz, pozycje dopasowań, tryb mapa/armia, parametry, OCR, cache, historia i planowane akcje muszą być przypisane do właściwego profilu i nigdy nie mogą przeciekać między kontami. Profile nie przechowują haseł; logowanie i uruchamianie gry pozostaje ręczne.
- Zalecana kolejność: najpierw wybór i przechwytywanie jednego okna oraz poprawne przeliczanie współrzędnych; następnie izolacja profili i przełączanie między oknami; później praca równoległa dla co najmniej czterech okien; na końcu GUI korzystające z tych samych sesji.
- Flow takie jak kopalnie, krypta czy Watchtower będą kolejnymi funkcjami korzystającymi ze wspólnej obsługi okien i profili. Kontrola dostępu premium Watchtower jest ważnym przykładem walidacji stanu przed akcją, ale nie jest jedynym celem projektu.
- Wybór okna, profile wielookienne i GUI są kierunkami rozwoju, nie zaimplementowanymi funkcjami.

## Testy live na drugim PC (`tools/device_test.py`)
Zatwierdzone 2026-11-07. Narzędzie uruchamia nadzorowane scenariusze na komputerze z grą; nie zastępuje pytest.

**Zwykłe uruchomienie:** z katalogu repozytorium wykonaj jedną komendę:

```powershell
python .\tools\device_test.py
```

Launcher próbuje `git pull --ff-only` nieinteraktywnie, maksymalnie 10 sekund. Jeśli są lokalne zmiany albo pull się nie powiedzie, wypisuje ostrzeżenie i uruchamia test na aktualnym checkoutie; nie wykonuje automatycznego rebase. Git push po teście także ma limit czasu. Jeśli push się nie powiedzie, commit diagnostyczny zostaje lokalnie.

Ustawienia są w `tools/device_test_settings.json`: lista domyślnych scenariuszy, czas na przygotowanie ekranu (maksymalnie 5 sekund), profil/urządzenie oraz publikacja. Domyślne `publish`, `push` i `rerun_same_code` są włączone. Zmień ten plik i commituj ustawienia, jeśli chcesz inny standardowy przebieg; polecenia nadal pozostają takie same.

Domyślny plan uruchamia `preflight`, a potem `speedup_use` z `execute: true`. Zwykłe `python .\\tools\\device_test.py` faktycznie używa zaplanowanych przyspieszeń i może je zużyć. Przed startem otwórz właściwy aktywny dialog Speed Up, ustaw listę na górze i nadzoruj grę. Nie uruchamiaj go, jeśli nie chcesz zużyć przedmiotów. Skan bez klikania jest dostępny osobno: `python .\\tools\\device_test.py speedup_scan`.

**Jednorazowy live test Specjalistów:** przygotuj grę na mapie, bez aktywnego szkolenia, z wystarczającym jedzeniem/srebrem i zamierzonym celem Specjaliści V / slot 1. Uruchom `python .\tools\device_test.py army_specialist_train --profile auto --execute`. Polecenie rozpozna nick, otworzy Koszary, wybierze Specjalistów i po pełnym preflightzie może kliknąć „Wyszkol” jeden raz. Wymaga frazy `TRAIN ONE SPECIALIST`; po potwierdzonym starcie zapisze zwykły marker i zatrzyma się przed Help. To zużywa zasoby i rozpoczyna szkolenie. Przy kolizji nicku wybierz profil lub nowy; nie uruchamiaj ponownie po wyniku niepewnym, dopóki ręcznie nie sprawdzisz gry.

Narzędzie zapisuje raport, log, zrzuty przed/po i debug modułu w `device_runs/<urządzenie>/<scenariusz>/<numer>_<YYYYMMDD_HHMMSS>/`, np. `1_20261107_151211`, `2_20261107_151411`. Licznik rośnie osobno dla każdego urządzenia i scenariusza. Po migracji ze starych folderów bez numeru następny numer jest wyższy od istniejących runów. Retencja zachowuje cztery najnowsze przebiegi według czasu, nie sortowania tekstowego. Pełną ścieżkę launcher wypisuje po każdym scenariuszu i zapisuje też w `report.json`. Po wyniku `OK` i `FAILED` commitowane są pliki diagnostyczne, a następnie pushowane. Błąd synchronizacji Git nie blokuje już scenariusza; `BLOCKED` oznacza problem przed uruchomieniem kroku, np. emergency stop. Domyślne `rerun_same_code` zapobiega cichemu `UNCHANGED`; ustaw `false`, jeśli chcesz przywrócić pomijanie kodu już wcześniej testowanego.

Opcje `--delay`, `--no-git`, `--no-push`, `--force` i `--execute` są nadpisaniami jednorazowymi; nie trzeba ich podawać przy standardowym uruchomieniu. `--no-git` wyłącza zarówno commit, jak i push. `--list` pokazuje scenariusze i aktywne ustawienia.

Po pierwszym błędzie kroków scenariusza dalsze kroki są zatrzymane, bez ponowień. Działają `~/.tba_stop` i PyAutoGUI fail-safe. `tools/live_probes.py` udostępnia też read-only preflight, odczyt slotów armii i kalibrację przewijania.

Status: launcher i testy publikacji wyniku `FAILED` są sprawdzone na tymczasowych repozytoriach Git. Scenariusze Speed Up nie zostały uruchomione na żywej grze.
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
Zatwierdzone 2026-11-07. Narzędzie służy do nadzorowanych testów okna gry na PC z grą, Tesseractem, `mss` i `pyautogui`; nie zastępuje pytest.
- Stałe polecenie na drugim PC: `python .\tools\device_test.py`. Bez argumentów uruchamia scenariusze z `tools/device_test_plan.json`, który zmieniamy i commitujemy na głównym PC. Wpis planu to nazwa albo `{"name": "...", "execute": true}` dla scenariusza klikającego. `--list` pokazuje scenariusze i bieżący plan; nazwy podane w poleceniu zastępują plan; nowy moduł dodaje się wpisem w `tools/device_test_scenarios.json`.
- Limit: najwyżej 2 scenariusze na uruchomienie (screeny i diagnostyka szybko rosną); więcej (także `all`) wymaga `--allow-many`.
- Start: `git pull --ff-only` (przy rozbieżności `pull --rebase`); zmiany w śledzonych plikach przerywają run bez testów. Operator przygotowuje ekran wskazany w `prepare`, po czym narzędzie odlicza `prepare_seconds` (`--delay` nadpisuje).
- Blokada tego samego kodu: raport zapisuje `code_commit` (ostatni commit spoza `device_runs`). Jeśli poprzedni run tego scenariusza na tym urządzeniu miał ten sam `code_commit`, scenariusz kończy się `UNCHANGED` (kod wyjścia 3) bez gry, zrzutów i commita. `--force` pomija blokadę.
- Scenariusze klikające mają tylko `execute_argv`: bez `--execute` (lub `execute` w planie) są pomijane albo uruchamiają bezpieczny `argv` (np. podgląd). Po pierwszym błędzie kroku sekwencja się zatrzymuje, bez ponowień. Działają `~/.tba_stop` i PyAutoGUI fail-safe.
- Wynik: `device_runs/<urządzenie>/<scenariusz>/<czas>/` z `report.json`, `log.txt`, zrzutami monitora przed i po kroku oraz katalogami debug utworzonymi przez moduł (przenoszonymi z `debug_dirs`). Zostaje bieżący run i 3 wcześniejsze dla pary urządzenie + scenariusz; starsze są usuwane i commitowane (pliki zostają w historii gita).
- Commit obejmuje tylko katalog scenariusza (`device_runs: <scenariusz> on <urządzenie> - <STATUS>`), także po niepowodzeniu. Push jest domyślny (`--no-push` go wyłącza, `--no-git` pomija cały git i blokadę).
- `tools/live_probes.py`: `preflight` (biblioteki, Tesseract, 1920x1080, zrzut), `army_slots` (odczyt slotów, poziomów i stanu), `army_scroll` (porcje po 8 kroków w dół i w górę, zrzut po każdej, bez kliknięć). Nie klikają.
- Status: zaimplementowane; testy narzędzia przechodzą na tymczasowych repozytoriach git. Żaden scenariusz nie został uruchomiony na grze. `army_navigate` zależy od managera armii, który ma obecnie błędy importu. Wykrywanie końca listy w `army_scroll` porównuje całe klatki, więc animowane elementy mogą je opóźnić; probe zapisuje dowody do kalibracji.
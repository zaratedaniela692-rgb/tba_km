# Ekran: speedup

Status (2026-11-07): timer i ilości są czytane przez OCR, a pozycje „Użyj” są weryfikowane checkpointową mapą. `speedup.py` domyślnie wykonuje potwierdzony skan i plan, bez kliknięć. `speedup.py --execute` może używać wyłącznie posiadanych przyspieszeń i wymaga osobnej dokładnej frazy. Pełny live run nie był jeszcze wykonany przez asystenta; uruchomienie wymaga nadzoru użytkownika.

Autorytatywny kontrakt odczytu, zakres, diagram i ograniczenia są w [docs/game/speedup_module_workflow.md](../game/speedup_module_workflow.md).

## Jak rozpoznać

- Referencyjne zrzuty desktopowego klienta (1920x1080):
  - `screenshots/speedup_module/speedup_view.png` – lista od góry, widoczne m.in. 1m, 15m, 1h i początek kolejnych wierszy.
  - `screenshots/speedup_module/speedup_view2.png` – środkowa część listy, m.in. 8h, 15h, 1d i 3d.
  - `screenshots/speedup_module/speedup_view3.png` – dolna część listy, m.in. 3d, 7d, posiadany 30d i osobna oferta zakupu 30d.
  - `screenshots/speedup_module/after_click_7days_speedup.png` – inny timer i licznik 7d; nazwa pliku sugeruje wcześniejszą akcję, ale sam obraz nie potwierdza jej mechaniki ani związku przyczynowego.
  - `screenshots/speedup_module/academy_speeduo_button.png` oraz `screenshots/speedup_module/build_in_city_speedup_button.png` – przyciski wejścia w speedup na innych ekranach. Nie potwierdzają wspólnego panelu listy dla tych kontekstów.
- Kotwica dialogu jest rozpoznawana szablonem w ograniczonym obszarze; operacja wymaga dialogu otwartego wcześniej przez użytkownika.
- Typ zadania nie jest automatycznie rozpoznawany. Przed live run użytkownik musi upewnić się, że otwarte jest właściwe szkolenie.
- Zrzuty i mapa dotyczą klienta desktopowego 1920x1080 na monitorze głównym. Nie kopiuj regionów ani wzorców do wariantu browser.
- Run `7_20261107_200245`: dialog/timer wejściowy rozpoznano poprawnie (`10d.:23g.`, confidence 100); lista startowała u góry. Skan zatrzymał się na checkpointcie 3, bo cztery pełne przyciski Use dopasowały się z confidence 1.0, ale ich jednolity offset od mapy wynosił `(+2,+4)` px i stary limit pozycji wynosił 2 px.
- Korekta: checkpoint nadal mapuje rzędy top-to-bottom, ale pozycje OCR i klików pochodzą ze świeżych dopasowań. Wymagana jest dokładna liczba trafień, prostokąty w granicach viewportu i wspólny offset z tolerancją 1 px między rzędami; jednolite przesunięcie całego widoku nie jest samo w sobie błędem. Raport zapisuje pozycje oczekiwane i wykryte, offsety oraz confidence także przy blokadzie. Powtórny odczyt `frame_003.png` przechodzi i odczytuje 15m=4853, 1h=5257, 3h=3383, 8h=475. Run 7 był dry-run; nie użyto przedmiotów.

## Elementy

1. `speedup_dialog_anchor` – nagłówek „Przyspieszenia” i kontekst dialogu; kotwica do oznaczenia.
2. `speedup_task_context` – nazwa/ikona aktywnego zadania w górnej części panelu; zachowana jako region referencyjny, ale nie jest automatycznym dowodem typu zadania.
3. `speedup_remaining_time` – wartość obok etykiety „Pozostało” i ikony zegara; OCR zmiennego czasu, zwracający tekst surowy, sekundy, pewność i czas odczytu.
4. `speedup_inventory_viewport` – widoczny obszar wierszy przedmiotów; region do OCR, bez przycisków „Użyj”.
5. `speedup_item_duration` – nominał widoczny na ikonie lub wierszu, m.in. 1m, 15m, 1h, 3h, 8h, 15h, 1d, 3d, 7d, 30d; OCR/normalizacja. Nieznany nominał pozostaje jawnie nieznany.
6. `speedup_item_quantity` – licznik na ikonie posiadanego przyspieszenia; dwa odczyty Tesseracta przy skali 4x i 6x muszą być zgodne. Nieczytelny lub sprzeczny licznik blokuje plan i nie może być zastąpiony zerem.
7. `speedup_purchase_offer` – osobny wiersz z ofertą i przyciskiem „Kup”; nie jest posiadanym przedmiotem i nie wchodzi do inwentarza.
8. `speedup_scroll_track` i `speedup_scroll_thumb` – pionowy tor oraz uchwyt po prawej stronie listy. Położenie uchwytu jest sygnałem pomocniczym postępu; nie rozpoznano jeszcze wszystkich stanów ani progu pewności.
9. `speedup_use_button` – przycisk „Użyj” przy wierszu. Template matching weryfikuje liczbę i pozycję przy checkpointach; klik jest możliwy wyłącznie w trybie `--execute`.

Regiony i wzorce są zweryfikowane na dostarczonych fixture'ach desktopowych. Czytnik przesuwa quantity crop względem wykrytego przycisku „Użyj” i zachowuje surowy tekst OCR oraz zgodność odczytów. `Automator.update()` wybiera pierwszy monitor, nie konkretne okno gry; live run blokuje się przy innym rozmiarze niż 1920x1080.

Raport runu zawiera chronologiczny `event_trace` oraz plik `event_trace.jsonl`: każdy scroll, wynik zmiany viewportu, odczyt timera i ilości, decyzję planera, współrzędne kliknięcia, weryfikację licznika i przyczynę zatrzymania. Do diagnozy przebiegu tekst wystarcza; klatki są potrzebne tylko do niezależnego sprawdzenia obrazu.

## Regiony kandydackie (ekran `speedup` w `regions.json`, układ `speedup_view.png`)

| Element | x, y, w, h | Uwagi |
| --- | --- | --- |
| `speedup_dialog_anchor` | 900, 250, 120, 24 | nagłówek „Przyspieszenia”; ten sam punkt na 4 zrzutach (>=0,997) |
| `speedup_task_context` | 716, 278, 232, 70 | ikona, nazwa zadania i „Pozostało”; nazwa zależy od zadania, więc nie dowodzi rodzaju |
| `speedup_remaining_time` | 1064, 322, 110, 22 | klepsydra (największy glif, odfiltrowywana) i tekst `13 d.:7 g.`; czytnik `speedup_reader.py` segmentuje cyfry, zweryfikowane cyfry: 1, 3, 4, 6, 7 |
| `speedup_inventory_viewport` | 678, 376, 562, 418 | obszar wierszy |
| `speedup_use_button` | 1050, 445, 145, 27 | wiersze co 110 px (wzorzec 1,0 w widokach); wzorzec „Kup” daje ok. 0,6 |
| `speedup_item_icon` | 723, 396, 72, 72 | ikona przedmiotu, 49 px nad przyciskiem |
| `speedup_item_duration` | 723, 402, 40, 20 | nominał w lewym górnym rogu ikony; OCR niepotwierdzony |
| `speedup_item_quantity` | 755, 446, 42, 22 | ilość na ikonie; crop z insetem 5 px z lewej i 3 px z prawej, zgodne OCR 4x/6x |
| `speedup_purchase_offer` | 1050, 746, 145, 27 | z `speedup_view3.png`; przycisk „Kup” |
| `speedup_scroll_track` / `speedup_scroll_thumb` | 1218, 380, 12, 414 / 1218, 392, 12, 62 | uchwyt podąża za listą (y=392, 603, 716); granice toru niepotwierdzone |

Położenia wierszy zależą od przewinięcia, dlatego używana jest mapa kompletnych dopasowań `speedup_use_button` dla checkpointów 3/11/16, a nie stała pozycja przycisku. Nominały przypisano z przejrzanych checkpointów; 1m jest pominięte. Ilość 3d musi zgadzać się w obu checkpointach, w których występuje.

## Przejścia

- Live scan, domyślny bez klikania: `python .\speedup.py --confirm "SCAN SPEEDUP LIST FROM TOP"`. Wymaga otwartego dialogu, listy ustawionej na górze i 1920x1080; skanuje checkpointy 3/11/16, planuje zużycie i zapisuje raport JSON.
- Live use: `python .\speedup.py --execute --confirm "USE OWNED SPEEDUPS FROM TOP"`. Przed każdym kliknięciem sprawdza stop-file; po każdym użyciu wymaga spadku licznika dokładnie o jeden. Wynik niepewny zatrzymuje proces bez retry.
- Kalibracja live: przy otwartym dialogu uruchom `python .\speedup_calibration.py --calibrate-scroll --confirm "SCROLL SPEEDUP LIST"`. Polecenie zapisuje widok początkowy, przed każdym pojedynczym przewinięciem ustawia kursor na środku oznaczonego panelu (959, 585), a potem zapisuje kolejny screen. Domyślny limit to 20 kroków; pierwszy niezmieniony widok jest zapisany i kończy kalibrację. Zrzuty i manifest trafiają do `debug/speedup/calibration_<timestamp>/`.
- Test checkpointowy: po ustawieniu listy na górze uruchom `python .\speedup_calibration.py --checkpoint-scan --confirm "SCROLL SPEEDUP LIST"`. Kursor jest ustawiany na środku panelu przed każdym scroll-em; każda klatka jest sprawdzana w pamięci, ale zapisują się tylko screeny po 3, 11 i 16 scrollach. Nie wykonuje się 17. scrolla. Wynik należy potem ręcznie sprawdzić pod kątem widocznych nominałów i czytelności przycisków „Użyj”.
- Test checkpointowy zakończony: manifest `debug/speedup/calibration_20261107_010155_371887/manifest.json` potwierdza 16 scrolli i zapis tylko checkpointów 3, 11, 16. Screeny pokazują odpowiednio przyspieszenia 15m/1h/3h/8h, 15h/1d/3d/7d oraz posiadane 3d/7d/30d z przyciskami „Użyj”. Ostatni sklepowy wiersz 30d ma „Kup” i jest wykluczony; nie mylić go z posiadanym 30d nad nim.
- Mapa `speedup_button_map.json` jest generowana offline z pełnych dopasowań `speedup_use_button` i przypisuje znane nominały do pozycji viewport-relative. Po 11 scrollach przycisk 7d jest ucięty, więc używana jest pełna pozycja po 16 scrollach; 3d występuje w checkpointach 11 i 16 i musi mieć tę samą odczytaną ilość.
- Skan obejmuje checkpointowe przyspieszenia od 15m do 30d; 1m jest pominięte, a końcowa sklepowa oferta 30d z `Kup` jest wykluczona. Żaden tryb nie kupuje przedmiotów ani nie przeciąga uchwytu paska.
- Brak zmiany viewportu po przewinięciu oznacza koniec listy. Uchwyt paska może wspierać, ale nie zastępować porównania obrazu. Osiągnięcie limitu przewinięć bez potwierdzenia końca oznacza skan niekompletny.
- Moduł nie klika „Pomoc”, nie zmienia kolejki i nie potwierdza ukończenia na ekranie treningu. To pozostaje odpowiedzialnością wywołującego.

## Przypadki szczególne

- Oferta „Kup” może mieć ten sam nominał co posiadany przedmiot; odróżniaj wiersz po typie oferty, nie po samym nominale.
- Lista jest przewijana; odczyt tylko pierwszego widoku nie jest kompletnym inwentarzem.
- Timer może zmieniać się w trakcie skanowania. Zachowuj czas każdego odczytu; nie zakładaj, że timer z początku jest aktualny po przewinięciu.
- Niski OCR, zasłonięty wiersz, nieznany nominał lub nieczytelny licznik oznacza niekompletny odczyt, a nie brak przyspieszeń.
- Scroll, który nie zmienia widoku, kończy skan. Po niepewnym stanie, zmianie dialogu/kontekstu lub awaryjnym zatrzymaniu przerwij skan.
- Live runner przechwytuje monitor główny i wymaga rozdzielczości 1920x1080 zgodnej z adnotacjami. Nie wybiera ani nie aktywuje okna; użytkownik musi mieć grę na wierzchu. Inne rozdzielczości, skala i UI przeglądarkowy są blokowane lub odroczone.
- Zrzuty wejścia z Akademii i budynku nie zatwierdzają integracji tych flow. Pierwszy zakres gry pozostaje army training.

## Wiedza z poprawek

- 2026-11-06 – The user approved mouse-wheel calibration over the annotated inventory list (not dragging the thumb). Before every wheel step, move the pointer to a safe point inside the list (the panel center is used), away from the game navigation bar and Use/Buy controls; capture after each step and stop at the first unchanged view. Item use and purchases remain out of scope for calibration.
- 2026-11-07 – User-reported cumulative list landmarks from a run starting at the top: after 3 scrolls 15m/1h/3h/8h; after 11 scrolls 15h/1d/3d/7d; after 16 scrolls 3d/7d/30d and reported end-of-list. The 1m item may be omitted from required coverage. These are observations pending screenshot verification, not OCR-confirmed facts.
- 2026-11-07 – The user approved checkpoint-only calibration: save screenshots only after scrolls 3, 11 and 16; validate each intermediate frame in memory; stop before a checkpoint if the viewport does not change; never send scroll 17. The next review checks the item labels and readability of the visible Use buttons; it does not yet execute item use.
- 2026-11-07 – The user approved offline Use-button mapping only: map button positions to known durations at cumulative scrolls 3/11/16, preserve duplicate duration locations, ignore 1m and exclude the final shop row with `Kup`. No item use or click integration is part of this step.
- 2026-11-07 – The user approved offline Use-button mapping only: map complete button positions to known durations at cumulative scrolls 3/11/16, preserve the repeated 3d location, omit the clipped 7d button at step 11, ignore 1m and exclude the final shop row with `Kup`. No item use or click integration is part of this step.
- 2026-11-07 – The user approved the default planner strategy for a direct supervised finish. Inventory OCR reads the known durations at checkpoints 3/11/16, applies existing soft stock floors and duration preferences, and only clicks under the separate exact `--execute` confirmation. No live item use has yet been performed.

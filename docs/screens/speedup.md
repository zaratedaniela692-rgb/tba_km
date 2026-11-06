# Ekran: speedup

Status: parsery OCR czasu, nominałów i ilości są zaimplementowane w `speedup_readings.py`, ale brak regionów dialogu i obrazu OCR readera. Skanowanie fixture'ów wymaga najpierw adnotacji regionów narzędziem `tools/annotate.py`.

Autorytatywny kontrakt odczytu, zakres, diagram i ograniczenia są w [docs/game/speedup_module_workflow.md](../game/speedup_module_workflow.md).

## Jak rozpoznać

- Referencyjne zrzuty desktopowego klienta (1920x1080):
  - `screenshots/speedup_module/speedup_view.png` – lista od góry, widoczne m.in. 1m, 15m, 1h i początek kolejnych wierszy.
  - `screenshots/speedup_module/speedup_view2.png` – środkowa część listy, m.in. 8h, 15h, 1d i 3d.
  - `screenshots/speedup_module/speedup_view3.png` – dolna część listy, m.in. 3d, 7d, posiadany 30d i osobna oferta zakupu 30d.
  - `screenshots/speedup_module/after_click_7days_speedup.png` – inny timer i licznik 7d; nazwa pliku sugeruje wcześniejszą akcję, ale sam obraz nie potwierdza jej mechaniki ani związku przyczynowego.
  - `screenshots/speedup_module/academy_speeduo_button.png` oraz `screenshots/speedup_module/build_in_city_speedup_button.png` – przyciski wejścia w speedup na innych ekranach. Nie potwierdzają wspólnego panelu listy dla tych kontekstów.
- Kandydat na kotwicę: nagłówek dialogu „Przyspieszenia” wraz z nazwą aktywnego zadania i etykietą „Pozostało”. Kotwica i jej próg dopasowania nie są jeszcze oznaczone ani zweryfikowane.
- Dla skanera wymagane jest potwierdzenie, że widok dotyczy aktywnego szkolenia armii; sam tekst lub ikona przyspieszenia nie wystarcza do zidentyfikowania kontekstu zadania.
- Zrzuty przedstawiają klient desktopowy. Nie kopiuj regionów ani wzorców do wariantu browser.

## Elementy

1. `speedup_dialog_anchor` – nagłówek „Przyspieszenia” i kontekst dialogu; kotwica do oznaczenia.
2. `speedup_task_context` – nazwa/ikona aktywnego zadania w górnej części panelu; potrzebna do sprawdzenia, że odczyt dotyczy szkolenia armii.
3. `speedup_remaining_time` – wartość obok etykiety „Pozostało” i ikony zegara; OCR zmiennego czasu, zwracający tekst surowy, sekundy, pewność i czas odczytu.
4. `speedup_inventory_viewport` – widoczny obszar wierszy przedmiotów; region do OCR, bez przycisków „Użyj”.
5. `speedup_item_duration` – nominał widoczny na ikonie lub wierszu, m.in. 1m, 15m, 1h, 3h, 8h, 15h, 1d, 3d, 7d, 30d; OCR/normalizacja. Nieznany nominał pozostaje jawnie nieznany.
6. `speedup_item_quantity` – licznik na ikonie posiadanego przyspieszenia; OCR zmiennej liczby. Nieczytelny licznik nie może być zastąpiony zerem.
7. `speedup_purchase_offer` – osobny wiersz z ofertą i przyciskiem „Kup”; nie jest posiadanym przedmiotem i nie wchodzi do inwentarza.
8. `speedup_scroll_track` i `speedup_scroll_thumb` – pionowy tor oraz uchwyt po prawej stronie listy. Położenie uchwytu jest sygnałem pomocniczym postępu; nie rozpoznano jeszcze wszystkich stanów ani progu pewności.
9. `speedup_use_button` – przycisk „Użyj” przy wierszu. Tylko do rozpoznania/wykluczenia z OCR; nie klikać w ramach skanera.

Współrzędne regionów należy oznaczyć narzędziem `tools/annotate.py` na wybranych fixture'ach. Nie wyznaczaj ich przez szacowanie na podstawie podglądu obrazu. Kadr i regiony mają być określone względem okna gry; obecny mechanizm przechwytywania wybiera pierwszy monitor, a nie konkretne okno gry. Pure parsers preserve the raw OCR string and return explicit low-confidence or unrecognized statuses; they do not imply that any image has been scanned.

## Przejścia

- Fixture offline → rozpoznaj nagłówek i kontekst → odczytaj timer oraz widoczne wiersze → raport obserwacji albo jawny wynik `unknown/incomplete`.
- Opcjonalny skan live (niezaimplementowany): wymagane osobne opt-in; dry-run domyślny. Po potwierdzeniu panelu przewiń kółkiem wyłącznie nad oznaczonym obszarem listy, wykonaj świeży zrzut i porównaj zawartość viewportu. Nie przeciągaj uchwytu paska.
- Brak zmiany viewportu po przewinięciu oznacza koniec listy. Uchwyt paska może wspierać, ale nie zastępować porównania obrazu. Osiągnięcie limitu przewinięć bez potwierdzenia końca oznacza skan niekompletny.
- Nie używaj przyspieszeń, nie kupuj, nie klikaj „Pomoc” i nie zmieniaj kolejki.

## Przypadki szczególne

- Oferta „Kup” może mieć ten sam nominał co posiadany przedmiot; odróżniaj wiersz po typie oferty, nie po samym nominale.
- Lista jest przewijana; odczyt tylko pierwszego widoku nie jest kompletnym inwentarzem.
- Timer może zmieniać się w trakcie skanowania. Zachowuj czas każdego odczytu; nie zakładaj, że timer z początku jest aktualny po przewinięciu.
- Niski OCR, zasłonięty wiersz, nieznany nominał lub nieczytelny licznik oznacza niekompletny odczyt, a nie brak przyspieszeń.
- Scroll, który nie zmienia widoku, kończy skan. Po niepewnym stanie, zmianie dialogu/kontekstu lub awaryjnym zatrzymaniu przerwij skan.
- Aktualny `Automator.update()` przechwytuje pierwszy monitor, nie wybrane okno; live scroll nie może używać zgadywanych współrzędnych desktopowych. Zanim zostanie wdrożony, trzeba osobno rozwiązać i zatwierdzić przechwytywanie okna oraz współrzędne względem okna gry.
- Zrzuty wejścia z Akademii i budynku nie zatwierdzają integracji tych flow. Pierwszy zakres gry pozostaje army training.

## Wiedza z poprawek

- 2026-11-06 – Użytkowniczka potwierdziła skan listy kółkiem myszy nad jej obszarem (nie przeciąganie uchwytu), z dry-run jako domyślnym i opt-in dla przewijania na żywo. Użytkowanie i zakup przedmiotów są poza zakresem.

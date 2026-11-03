# Ekran: world_map

## Jak rozpoznać
- Status: wstępne rozpoznanie z referencyjnego zrzutu; niezweryfikowane jeszcze przez template matching.
- Kandydat na kotwicę: stały pasek ikon nad minimapą w lewym dolnym rogu. Nie używać zmiennej zawartości minimapy jako całego szablonu.
- Zrzut referencyjny: `screenshots/world_map/pelny.png`.
- Domyślny próg weryfikacji: 94.6% z `config.json`; wymaga kalibracji na różnych screenach. Kotwica ekranu nie ma jeszcze osobnego szablonu.

## Elementy (numery jak na opisany.png)
Regiony pochodzą z `regions.json`; współrzędne odnoszą się do obszaru gry z danego wariantu screena. Nazwy i funkcje poza wcześniej potwierdzonymi są wstępne.

1. `armia` – button; dolny pasek nawigacyjny, szablon `templates/world_map/armia.png`, region `x=913, y=879, w=53, h=46`. Etykieta wskazuje przejście do kontekstu armii; przejście nie było jeszcze sprawdzone w działającej grze.
2. `watchtower_locked` – przycisk Watchtower w stanie braku dostępu; czerwone tło, szablon `templates/world_map/watchtower_locked.png`, region `x=672, y=876, w=36, h=26`.
3. `watchtower_unlocked` – ten sam przycisk w stanie wykupionej usługi; niebieskie tło, szablon `templates/world_map/watchtower_unlocked.png`, ten sam region `x=672, y=876, w=36, h=26`.
4. `okno_wiadomości` – button otwierający panel komunikacji z innymi graczami i klanami; region `x=1220, y=951, w=31, h=33`. Szablon: `templates/world_map/okno_wiadomosci.png`. Etykieta zachowuje polskie znaki, a nazwa pliku jest ASCII dla zgodności z OpenCV na Windows.

### Zasoby i tożsamość
- `wood`, `iron`, `stone`, `food`, `silver`, `gold` – ikony zasobów, kandydaci na stabilne szablony.
- `wood_count`, `iron_count`, `stone_count`, `food_count`, `silver_count`, `gold_count` – zmienne wartości liczbowe. W szkoleniu armii wymagane będą przede wszystkim `food_count` i `silver_count`, odczytane OCR bezpośrednio przed działaniem.
- The template verifier skips regions with `type: number`; resource values are checked through `tools/resource_ocr.py`, not fixed-image matching.
- Dla szkolenia: `food_count` może blokować rekrutację zależnie od koloru tekstu: biały i wartość > 0 pozwalają kontynuować; czerwony, zero lub niepewny odczyt oznaczają stop i komunikat. To kolor tekstu wartości, nie kolor tła.
- Liczniki używają sufiksów `K/M/B/T` o kolejnych potęgach 1000; `38.2M` oznacza `38 200 000`. Wartości są zmienne i nie powinny być rozpoznawane przez template matching.
- `tools/resource_ocr.py` odczytuje wszystkie sześć liczników z PNG bez klikania i zwraca ich pomiary bez decyzji feature'owych. Oczekiwane wartości i testy regresji skupiają się obecnie na `food_count` i `silver_count`. Na obu dostępnych screenach food ma biały tekst; nie mamy jeszcze rzeczywistego screena z czerwonym tekstem food.
- Próba na dwóch kontach potwierdziła stabilność ikon zasobów (zwykle 100%), ale liczby zasobów na drugim koncie często nie przekraczały progu template matching; to oczekiwane dla zmiennego tekstu, nie błąd do naprawienia obniżeniem progu.
- `player_name` – tekst identyfikujący konto. Obecny region jest `anchor`; przydaje się do lokalizacji, ale odczyt nazwy wymaga OCR. Weryfikuj go przy wyborze profilu/przełączeniu okna.
- `hero_view`, `hero_current_lvl`, `vip_panel` – portret/poziom/status gracza; prawdopodobnie zależne od konta i zmienne. Nie traktować jako wspólnych szablonów bez dodatkowej walidacji.

### Panele i nawigacja
- `action_list` – widoczna lista aktywnych działań/marszów (interpretacja wstępna); jej zawartość jest dynamiczna, więc nie dopasowuj całej listy jako jednego szablonu.
- `action_list_full_button` – przycisk rozwijania listy, nazwa i działanie do potwierdzenia.
- `scroll_button` – kontrolka przewijania/zmiany widoku paska zasobów; dokładne działanie do potwierdzenia.
- `switch_to_city_mode` – kandydat na przejście z mapy do miasta; potencjalnie przydatny przy funkcjach budowania, ale nie jest wymagany do szkolenia armii.
- `tasks_view`, `forge_view`, `events_view`, `clan_view`, `research_view`, `items_view`, `armia` – przyciski dolnego paska, nazwane według widocznych etykiet/ikon; funkcje należy potwierdzać przy użyciu poszczególnych ekranów.
- `bonus_panel`, `premium_panel`, `events_panel`, `vip_panel`, `help_other_button` – panele/przyciski boczne; ich dokładne efekty i to, czy odsłaniają schowane opcje, pozostają do sprawdzenia.
- `current_zoom_view` – wartość zoomu; region `anchor` może lokalizować pole, ale odczyt wartości jest dynamicznym OCR. `increase_zoom_view` i `decrease_zoom_view` to kontrolki, których używaj tylko w feature'ach zależnych od zoomu.

### Obiekty mapy
- `temple`, `walls_to_renew`, `group_marches_placeholder` – wstępne etykiety obiektów/przycisków na mapie. Nie są potrzebne do pierwszego odczytu zasobów ani szkolenia armii; znaczenie potwierdzimy przy właściwych feature'ach.
- Dopasowanie tych elementów między różnymi mapami/kontami bywa słabe, bo obiekty i położenie mapy są zmienne. Nie obniżaj globalnego progu, aby wymusić ich dopasowanie.

## Weryfikacja między kontami
- Ikony zasobów `wood`, `iron`, `stone`, `food`, `silver`, `gold` zachowały 100% zgodności na obu referencjach.
- Liczniki zasobów są zależne od konta: na czerwonej referencji `food_count` uzyskał 89.4%, `silver_count` 79.4%, a pozostałe liczniki także wypadły poniżej progu 94.6%. To potwierdza, że wartości należy odczytywać OCR, nie szablonami.
- `player_name` dopasował się na czerwonej referencji z 98%, ale pozycja najlepszego dopasowania przesunęła się z x=714 na x=735. Użyj regionu jako lokalizacji OCR, nie jako dokładnego wzorca tekstu.
- `action_list` (49.8%) i `action_list_full_button` (54.0%) nie przenoszą się stabilnie między tymi dwoma stanami/kontami; zawartość listy jest dynamiczna, a przycisk wymaga dalszego sprawdzenia.
- `group_marches_placeholder` uzyskał 99.4%, lecz w innym miejscu niż zaznaczony region. Obecny weryfikator szuka najlepszego dopasowania na całym obrazie, więc dla powtarzalnych ikon sam wysoki wynik nie potwierdza, że to właściwy element.

Pozostałe rozpoznane wzrokowo części ekranu, które nie są jeszcze regionami: nagłówek Total Battle (wspólna powłoka), pasek gracza i zasobów, obszar mapy, minimapa, boczne ikony, dolny pasek nawigacyjny i pasek statusu. Stałe ikony mogą być szablonami; zmienne liczby i elementy mapy nie powinny być traktowane jako stałe wzorce.

## Przejścia
- Przycisk „Armia” sugeruje przejście do kontekstu armii; wymaga potwierdzenia na działającej grze.
- Przycisk „Miasto” sugeruje przejście do widoku miasta; wymaga potwierdzenia.
- Pozostałe przejścia nieustalone.

## Stan premium Watchtower
- Watchtower to usługa wykupywana za złoto w grze.
- Czerwone tło oznacza brak dostępu; niebieskie tło oznacza usługę wykupioną i dostępną. To są stany tej samej usługi.
- Referencja stanu z czerwonym tłem: `screenshots/world_map/pelny.png`.
- Referencja stanu z niebieskim tłem: `tests/data/world_map/account_2.png`.
- Pierwszy test starego szablonu na niebieskim stanie dał 70.8% i najlepsze dopasowanie na innym przycisku. Zapisaliśmy więc dwa osobne szablony wycięte z obu referencji przy użyciu tej samej zatwierdzonej geometrii.
- Próba dymna `verify.py` (próg 94.6%): czerwony screen uzyskał 100% dla `watchtower_locked` i 59.6% dla `watchtower_unlocked`; niebieski screen uzyskał 70.8% dla `watchtower_locked` i 100% dla `watchtower_unlocked`. Obecne dwa przykłady rozdzielają stany prawidłowo.
- Testy regresji w `tests/test_verify_regression.py` sprawdzają oba stany oraz pozycje wspólnych przycisków z tolerancją 2 px; ostatnie uruchomienie: 2 testy zaliczone.
- Przed każdą akcją korzystającą z Watchtower należy rozpoznać stan: czerwony -> komunikat o braku wykupionej usługi i przerwanie całego flow Watchtower; niebieski -> można kontynuować; stan niepewny -> również przerwać bez kliknięć.
- Automatyczny zakup za złoto nie jest zachowaniem domyślnym. Może być opcją dopiero po osobnej, jawnej zgodzie użytkowniczki; po zakupie trzeba ponownie potwierdzić niebieski stan.
- Rozpoznawanie obu stanów oraz reakcja bota nie są jeszcze zaimplementowane w flow gry.

## Przypadki szczególne
- Zawartość mapy, jednostki, znaczniki i wybrane pole zmieniają się; nie traktować ich jako stałych wzorców bez osobnego uzasadnienia.
- Na zrzucie widoczna jest niebieska granica, podświetlone pole oraz ruchome/zmienne obiekty; nie są częścią kotwicy ekranu.
- Zoom w grze jest ustawiony na 125% na zrzucie referencyjnym; skala DPI Windows pozostaje nieznana.
- `opisany.png` zawiera ramki i etykiety adnotacji; używaj nieopisanego obrazu jako wejścia do weryfikacji.

## Wiedza z poprawek
- 2026-10-30 – ekran przedstawia tryb mapy. Rozdzielamy wspólny nagłówek Total Battle od rozpoznania właściwego kontekstu mapy/armii.
- 2026-10-30 – obserwacje wzrokowe zapisujemy od razu; `annotate.py` wykorzystujemy do ustalenia precyzyjnych granic szablonów tylko tam, gdzie będą potrzebne.
- 2026-10-31 – próba dymna `verify.py` dopasowała wszystkie trzy szablony z wynikiem 100% na `pelny.png` i `zrzut_pulpitu.png`; w pełnym zrzucie pulpitu pozycje mają przesunięcie Y o 39 px względem kadru klienta. `opisany.png` wypada poniżej progu, bo ramki i etykiety zmieniają piksele szablonów.
- 2026-11-02 – szkolenie armii nie wymaga przejścia do trybu miasta; zasoby odczytujemy z bieżącego ekranu mapy.
- 2026-11-02 – rekrutacja dozwolona tylko przy białym tekście `food_count` i wartości większej od zera; czerwony, zero lub niepewny odczyt oznaczają komunikat i przerwanie. Akcja naprawiająca czerwony stan będzie osobnym, późniejszym flow.
- 2026-11-03 – Numeric resource regions are excluded from template matching because their displayed values vary between accounts; OCR remains the validation path.

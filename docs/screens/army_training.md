# Ekran: army_training

## Jak rozpoznać
- Referencyjny zrzut: `screenshots/army_training/pelny.png`.
- Dodatkowe screeny z panelu Koszar: `templates/army_training3.png` i `templates/army_training4.png`. Oba pokazują aktywne szkolenie `Rycerz III`, przycisk „Przyspiesz” i wybór poziomów Gwardzistów.
- Widok okna „Koszary” z listą kategorii wojsk po lewej i kartami jednostek po prawej.
- Kandydat na kotwicę: nagłówek „Koszary” i lista kategorii. Osobny szablon kotwicy nie został zatwierdzony.
- Aktywne szkolenie rozpoznawaj niezależnie od samego otwartego okna. Powiadomienia mogą zasłonić wiersz aktywnej produkcji; brak odczytu nie oznacza braku szkolenia.

## Elementy (wg regionów i opisany.png)
Współrzędne są względem kadru `screenshots/army_training/pelny.png`; nazwy odpowiadają `regions.json`.

1. `troops_types` – lista kategorii: Gwardziści, Specjaliści, Korpus inżynierów, Smoki, Żywiołaki, Olbrzymy, Bestie. Szczegółowe zachowanie kategorii poza Gwardzistami nie zostało jeszcze sprawdzone.
2. `unit_troop_level` – każdy panel jednostki ma pionowy wybór poziomów I–V. Przygaszony poziom jest nieodblokowany i niewybieralny. Najwyższy poziom danej jednostki wyznacz jako najwyższy niewygaszony numer w jej własnym selektorze; poziomy mogą się różnić między jednostkami.
3. Stan zaznaczenia poziomu – aktualnie wybrany poziom ma lekko powiększony krążek z numerem. To inny sygnał niż odblokowanie: nie zakładaj, że aktualny wybór jest najwyższym ani docelowym poziomem. Po kliknięciu poziomu sprawdź, czy powiększone zaznaczenie przeniosło się na właściwy numer.
4. `current_trainin_army` – obszar bieżącego szkolenia: typ/poziom jednostki i liczba aktualnie szkolonych wojsk. To kluczowy stan blokujący rozpoczęcie następnego szkolenia.
5. `speedup_panel` – zmienny stan przycisku w obszarze aktywnego szkolenia: po dodaniu jednostki do kolejki pojawia się „Pomoc”; kliknięcie prosi klan o pomoc i zmienia przycisk w „Przyspiesz”. Pomoc innych osób może skracać czas. Nie utożsamiaj tych dwóch akcji; użycie przyspieszeń przez bota wymaga osobnego, jawnie zatwierdzonego flow.
6. `current_unit_troop_count` – liczba jednostek w bieżącym szkoleniu.
7. `unit_troop_count_to_train` – pole/liczba wojsk ustawiona do nowego szkolenia.
8. `unit_troop_coount_scroll` i `unit_troop_coount_scroll_button` – pasek do ustawiania liczby wojsk; dokładne zachowanie do sprawdzenia.
9. `unit_troop_require_silver_to_train` – koszt srebra dla wybranego szkolenia.
10. `unit_troop_require_time_to_train` – przewidywany czas szkolenia.
11. `unit_troop_food_production_load` – wpływ szkolenia na obciążenie/zużycie food; dokładna semantyka i relacja z czerwonym tekstem food pozostają do potwierdzenia.
12. `unit_troop_train_button` – przycisk „Wyszkol”. Nie klikaj, jeśli trwa inne szkolenie albo preflight zasobów nie przeszedł.
13. `close_army_screen_button` – zamknięcie okna Koszar.

## Sekwencja jednostek i poziomów Gwardzistów
- Lista może zaczynać się od różnych jednostek; nie zakładaj, że pierwszym widocznym slotem są łucznicy ani że pozycja slotu jest stała.
- Pierwsza część: łucznicy, włócznicy i jeźdźcy na poziomach I–V.
- Dalej: jednostka latająca na poziomach V–VII, następnie łucznicy, włócznicy i jeźdźcy na poziomach VI–VII.
- W ostatnich czterech slotach numeracja rzymska zaczyna się ponownie: łucznik, włócznik, jeździec i jednostka latająca pojawiają się z oznaczeniem I/II, które odpowiada globalnym poziomom VIII/IX.
- Po odblokowaniu wyższych poziomów interfejs automatycznie przewija listę ku nowszym jednostkom; starsze sloty mogą zniknąć z widoku. Koniec listy wykrywaj po braku zmiany obrazu po przewinięciu.
- Jednostkę identyfikuj po typie oraz globalnym poziomie, wyprowadzonym z sekwencji; nie używaj samego numeru rzymskiego ani bieżącej pozycji na ekranie. Potwierdź odblokowanie oraz powiększony znacznik aktualnego wyboru osobno.

## Przejścia i maszyna stanów
- Lista zleceń jest przechowywana per profil przez `army_training_plan.py`; opisuje typ jednostki i globalny poziom, nie pozycję slotu na ekranie. Ten moduł nie steruje jeszcze Koszarami.
- Wejście do Koszar -> rozpoznaj, czy trwa aktywne szkolenie.
- Przyjęcie jednostki do kolejki -> kliknij „Pomoc” zgodnie z osobno zatwierdzonym flow; potem rozpoznaj, że stan przycisku zmienił się na „Przyspiesz”. Nie klikaj „Przyspiesz” bez osobnej zgody.
- Aktywne szkolenie -> nie ustawiaj ani nie uruchamiaj następnego typu wojsk. Klan może skracać czas przez pomoc po swojej stronie.
- Po typowym powrocie po 30–60 minutach najpierw świeżo odczytaj bieżące szkolenie i stan przycisku. To tylko typowy interwał sprawdzenia, nie gwarancja ukończenia; pomoc klanu może zmienić czas.
- Brak aktywnego szkolenia -> przed ustawieniem liczby odczytaj świeże food i silver, sprawdź regułę food, wybierz typ jednostki, jawnie wybierz zaplanowany poziom i zweryfikuj powiększony krążek zaznaczenia; dopiero potem ustaw ilość.
- Po zakończeniu bieżącego szkolenia odczekaj co najmniej 5 sekund na automatyczny reset widoku, odśwież/przechwyć screen ponownie i dopiero wtedy odczytuj wartości lub zmieniaj ilość. Wcześniejsze ustawienie może zostać zresetowane.
- Powiadomienie zasłaniające bieżącą produkcję -> stan jest niepewny; nie zakładaj, że kolejka jest pusta. Poczekaj na odsłonięcie/zmianę obrazu i rozpoznaj ponownie.

## Przypadki szczególne
- Jednocześnie można szkolić tylko jeden typ wojsk.
- Pierwszy zakres harmonogramu Gwardzistów: strzelcy, włócznicy i jeźdźcy. Każdy z tych trzech typów szkolić raz na poziomie V oraz dwukrotnie na poziomie IV.
- Dokładny status odblokowania poziomów V/IV i stan zaznaczenia trzeba ustalać osobno dla każdego panelu jednostki; nie zakładaj, że wszystkie trzy typy mają identyczne odblokowania.
- Dodatkowa latająca jednostka poziomu V jest dostępna niżej na liście po przewinięciu; świadomie pomijamy ją w pierwszym zakresie. Dopóki jej nie dodamy do planu, nie traktuj jej braku w widocznym obszarze jako ukończenia całej kategorii.
- Karty innych jednostek są analogiczne według informacji użytkowniczki, ale nie są jeszcze zweryfikowane ekranami.
- Poziomy I–V są poziomami Gwardzistów w tym przykładzie. Przygaszony wygląd oznacza poziom jeszcze nieodblokowany.
- Nie polegaj na domyślnym zaznaczeniu najwyższego odblokowanego poziomu. Przed ustawieniem liczby wojsk jawnie wybierz poziom docelowy.
- Użytkowniczka często szkoli niższy poziom, na którym zwykle szkoli najwięcej jednostek. Docelowy poziom powinien być parametrem feature'u, a nie stałą zakodowaną jako „najwyższy odblokowany”.
- Czerwony tekst food oznacza zbyt duże obciążenie wojskiem: zatrzymaj rekrutację i zgłoś stan. Sprawdzanie bonusów jest osobnym, odroczonym feature'em.
- Nie klikaj „Wyszkol” ani „Przyspiesz” w fazie rozpoznania; przyszłe akcje wymagają dry-run, jawnego potwierdzenia i weryfikacji wyniku.

## Wiedza z poprawek
- 2026-11-02 – szkolenie nie wymaga trybu miasta.
- 2026-11-02 – aktywne szkolenie blokuje rozpoczęcie następnego; po jego zakończeniu odczekaj 5 sekund na reset widoku przed zmianą ustawień.
- 2026-11-02 – powiadomienia mogą zasłaniać obszar bieżącej produkcji; nieczytelny stan musi pozostać niepewny, a nie być traktowany jako pusta kolejka.
- 2026-11-02 – panel poziomów I–V pokazano dla Gwardzistów; pozostałe kategorie są analogiczne, lecz niezweryfikowane.
- 2026-11-02 – pierwszy plan Gwardzistów obejmuje strzelców, włóczników i jeźdźców: poziom V raz, poziom IV dwa razy. Latający poziom V poniżej scrolla jest na razie poza zakresem.
- 2026-11-02 – najwyższy odblokowany poziom to najwyższy niewygaszony numer dla konkretnej jednostki; powiększony krążek wskazuje aktualny wybór i nie jest tym samym co stan odblokowania.
- 2026-11-02 – lista może zaczynać się od różnych jednostek i automatycznie przewijać do nowo odblokowanych; slot/pozycja na ekranie nie jest stabilnym ID jednostki ani globalnego poziomu.

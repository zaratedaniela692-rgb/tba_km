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
5. `speedup_panel` – zmienny stan przycisku w obszarze aktywnego szkolenia: po dodaniu jednostki do kolejki pojawia się „Pomoc”; kliknięcie prosi klan o pomoc i zmienia przycisk w „Przyspiesz”. Pomoc innych osób może skracać czas. Przed kliknięciem „Pomoc” odczekaj konfigurowalne 1-3 sekundy na ustabilizowanie ekranu (domyślnie 2); po kliknięciu odczekaj domyślnie 0,2 sekundy i potwierdź zmianę stanu przycisku. Tryb szybkiego kończenia może następnie automatycznie użyć przyspieszeń.
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
- Nie identyfikuj konkretnego typu jednostki. Cel jest określony globalnym poziomem i numerem pasującego slotu w ustalonej kolejności listy.
- Poziomy 1-4 mają po trzy sloty jednostek, a poziomy 5-9 po cztery. Szukaj wszystkich slotów z żądanym poziomem i wybieraj wymagany numer dopasowania; nie zakładaj stałej współrzędnej ani nie szkol pierwszej widocznej karty bez sprawdzenia poziomu.
- Numery lokalne mogą się powtarzać (np. I/II dla globalnych poziomów VIII/IX), dlatego oznaczenie poziomu interpretuj w kontekście sekwencji listy.
- Lista zachowuje zasadniczo stałą kolejność, ale karty mogą zaczynać się w różnym miejscu lub zmieniać widoczność przy przewijaniu. Przeszukuj listę do końca, a koniec potwierdzaj brakiem zmiany obrazu po przewinięciu.
- Potwierdź osobno, że docelowy poziom jest odblokowany i że zaznaczenie poziomu jest ustawione na wymaganej wartości.

## Przejścia i maszyna stanów
- Lista zleceń jest przechowywana per profil przez `army_training_plan.py`; opisuje typ jednostki i globalny poziom, nie pozycję slotu na ekranie. Ten moduł nie steruje jeszcze Koszarami.
- Plan kampanii jest przechowywany per profil przez `army_training_plan.py`; zawiera wiele przyszłych celów opisanych globalnym poziomem i numerem pasującego slotu oraz liczbę wymaganych i potwierdzonych przebiegów. Nie oznacza to kolejki wielu szkoleń w grze.
- Wykonawca realizuje tylko jedno szkolenie naraz. Planer wybiera następny cel dopiero po potwierdzeniu ukończenia aktywnego szkolenia i stwierdzeniu, że Koszary są wolne.
- Wejście do Koszar -> rozpoznaj, czy trwa aktywne szkolenie.
- Potwierdzone przyjęcie jednostki do kolejki -> odczekaj skonfigurowane 1-3 sekundy, rozpoznaj „Pomoc” i kliknij; następnie odczekaj około 0,2 sekundy i potwierdź, że ten sam przycisk zmienił się na „Przyspiesz”. Tryb szybkiego kończenia może automatycznie kliknąć „Przyspiesz” po pozytywnym rozpoznaniu.
- Automatic Speed Up is allowed only when the task has `quick_finish` enabled and the button is visually verified. If accelerations are unavailable, pause this profile's queue until manual resume; a click alone never confirms completion.
- Before starting each new training run, freshly read the silver balance and the selected training cost. If silver is insufficient or either reading is uncertain, do not click Train; keep the task pending for a later check.
- Aktywne szkolenie -> nie ustawiaj ani nie uruchamiaj następnego typu wojsk. Klan może skracać czas przez pomoc po swojej stronie.
- Po typowym powrocie po 30–60 minutach najpierw świeżo odczytaj bieżące szkolenie i stan przycisku. To tylko typowy interwał sprawdzenia, nie gwarancja ukończenia; pomoc klanu może zmienić czas.
- Brak aktywnego szkolenia -> przed ustawieniem liczby odczytaj świeże food i silver, sprawdź regułę food, wybierz typ jednostki, jawnie wybierz zaplanowany poziom i zweryfikuj powiększony krążek zaznaczenia; dopiero potem ustaw ilość.
- Brak aktywnego szkolenia -> planer wybiera jeden następny cel. Wyszukaj pasujący poziom i wskazany numer slotu, sprawdź odblokowanie, jawnie wybierz poziom i zweryfikuj zaznaczenie; dopiero potem wykonaj preflight zasobów i ustaw ilość.
- Po zakończeniu bieżącego szkolenia odczekaj co najmniej 5 sekund na automatyczny reset widoku, odśwież/przechwyć screen ponownie i dopiero wtedy odczytuj wartości lub zmieniaj ilość. Wcześniejsze ustawienie może zostać zresetowane.
- Powiadomienie zasłaniające bieżącą produkcję -> stan jest niepewny; nie zakładaj, że kolejka jest pusta. Poczekaj na odsłonięcie/zmianę obrazu i rozpoznaj ponownie.

## Przypadki szczególne
- Jednocześnie można szkolić tylko jeden typ wojsk.
- Jednocześnie można szkolić tylko jedno zlecenie. Plan programu może przechowywać wiele przyszłych celów i liczbę pozostałych przebiegów; wykonawca zgłasza planerowi wynik pojedynczego przebiegu.
- Army training is the only task type currently integrated with the plan and queue. Building and academy task flows are deferred until separately requested.
- W pierwszym zakresie planer obejmuje trzy dopasowania na poziomie V (po jednym przebiegu) oraz trzy dopasowania na poziomie IV (po dwa przebiegi dla każdego slotu). Czwarty slot poziomu V pozostaje poza tym zakresem.
- Dostępność docelowego poziomu i stan jego zaznaczenia sprawdzaj w znalezionym slocie; nie wyciągaj wniosków z typu jednostki zajmującego slot.
- Dodatkowa latająca jednostka poziomu V jest dostępna niżej na liście po przewinięciu; świadomie pomijamy ją w pierwszym zakresie. Dopóki jej nie dodamy do planu, nie traktuj jej braku w widocznym obszarze jako ukończenia całej kategorii.
- Czwarty slot poziomu V, opisywany wcześniej jako latająca jednostka, jest poza pierwszą kampanią. Nie traktuj go jako brakującego celu ani nie rozszerzaj zakresu automatycznie.
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
- 2026-11-02 – poziom należy odczytywać z oznaczenia slotu w kontekście sekwencji listy; powiększony krążek wskazuje aktualny wybór i nie jest tym samym co stan odblokowania.
- 2026-11-02 – lista może zaczynać się w różnym miejscu i automatycznie przewijać do nowo odblokowanych; wyszukuj wymagany poziom w całej liście, nie zakładaj pozycji jednostki.
- 2026-11-03 – planer kampanii przechowuje liczbę przyszłych przebiegów, ale w grze aktywne jest tylko jedno szkolenie. Wykonawca realizuje pojedynczy cel `{global_level, match_number}` i raportuje potwierdzony wynik planerowi.
- 2026-11-03 – po rozpoczęciu szkolenia odczekaj 1-3 sekundy przed kliknięciem „Pomoc”; po kliknięciu przycisk przechodzi do „Przyspiesz” po około 0,2 sekundy. Szybkie kończenie ma być sterowane ustawieniem zadania.

# Mechaniki gry

## Potwierdzone informacje
- Gra ma dwa podstawowe tryby/konteksty: mapę oraz armię.
- Każdy tryb pokazuje inne ekrany i udostępnia inne opcje.
- Część elementów interfejsu określanych jako „przyciski” jest wspólna dla obu trybów.
- Bot ma rozpoznawać bieżący ekran i wybierać akcje dostępne w danym kontekście.

## Dane wymagane przez funkcje

### Wspólny odczyt zasobów
- Odczyt zasobów jest niezależną funkcją danych, nie częścią szkolenia armii ani innego feature'u. Może być używany przez różne funkcje.
- `tools/resource_ocr.py` zwraca pomiary wszystkich sześciu liczników (`wood`, `iron`, `stone`, `food`, `silver`, `gold`): surowy OCR, przeliczoną wartość, kolor tekstu oraz pewność i `confidence_ok`. Nie podejmuje decyzji, czy dana akcja jest dozwolona, i nie wykonuje kliknięć.
- Zasoby mają różne zastosowania: `wood`, `iron` i `stone` służą do ulepszania budynków; `silver` jest potrzebne do szkolenia armii; `food` określa stan wyżywienia/utrzymania wojsk.
- Każdy feature sam deklaruje, których odczytanych pól potrzebuje, jak interpretuje ich wartości i jakie warunki muszą być spełnione przed akcją.

### Szkolenie armii – pierwszy cel
- Tożsamość profilu: `player_name`. Odczytaj przy wyborze/uruchomieniu profilu i po przełączeniu okna; trzymaj wartość wyłącznie w profilu tego okna. Jeśli nie zgadza się z oczekiwanym kontem, nie wykonuj akcji.
- Szkolenie konsumuje wspólny odczyt `food_count` i `silver_count`; odczytaj je bezpośrednio przed planowaniem/rozpoczęciem. Nie używaj cache do decyzji o aktualnym saldzie.
- Sufiksy zasobów: `K` = 10^3, `M` = 10^6, `B` = 10^9, `T` = 10^12; każdy kolejny sufiks jest 1000 razy większy (`1000K = 1M`). Obsłuż część dziesiętną, np. `38.2M` = `38 200 000`; dopuszczaj kropkę lub przecinek jako separator dziesiętny.
- Rekrutacja jest dozwolona tylko wtedy, gdy tekst `food_count` jest biały i odczytana wartość jest większa od zera. Czerwony tekst oznacza, że wojsk jest za dużo względem dostępnego food/utrzymania; zero, brak OCR lub niepewna klasyfikacja również oznaczają komunikat i przerwanie bez klikania rekrutacji.
- Sprawdzenie bonusów może być osobną akcją diagnostyczną, ale pozostaje poza pierwszą wersją szkolenia. Nie uruchamiaj go automatycznie; najpierw zatrzymaj rekrutację i zgłoś stan. Po ewentualnej osobnej naprawie ponownie odczytaj food.
- `silver_count` należy odczytać świeżo i porównać z kosztem wybranego szkolenia, gdy koszt zostanie ustalony.
- Szkolenie nie wymaga przejścia do trybu miasta. Z obecnego ekranu mapy należy rozpoznać właściwy przycisk/panel akcji i potwierdzić ekran szkolenia przed dalszymi kliknięciami.
- `tools/resource_ocr.py` działa obecnie offline na PNG i nie wykonuje kliknięć. Parsuje `K/M/B/T` i zwraca pomiary; nie zwraca statusu rekrutacji ani decyzji feature'owej.
- Na dostępnych fixture food ma biały tekst (`567M` i `13.8M`). Czerwony food nie występuje na żadnym screenie; czerwony/nieznany klasyfikator pokrywa teraz test syntetyczny, a próg trzeba jeszcze potwierdzić na prawdziwym czerwonym stanie.
- Jednocześnie można szkolić tylko jeden typ wojsk. Jeśli `current_trainin_army` wskazuje aktywne szkolenie, nie rozpoczynaj następnego. Przycisk `speedup_panel` jest osobną akcją do zakończenia bieżącego szkolenia.
- Jednocześnie można szkolić tylko jedno zlecenie. Jeśli `current_trainin_army` wskazuje aktywne szkolenie, planer nie rozpoczyna następnego. Przycisk `speedup_panel` jest osobną akcją do zakończenia bieżącego szkolenia.
- W pierwszym zakresie kampanii są trzy dopasowania poziomu V wykonywane raz każde i trzy dopasowania poziomu IV wykonywane po dwa razy każde. Liczba dopasowań poziomu wynosi 3 dla poziomów 1-4 oraz 4 dla poziomów 5-9; czwarty slot V pozostaje poza pierwszą kampanią.
- Jednostkę w zleceniu identyfikuj parą `{unit_type, global_level}`. Wyświetlany numer rzymski może się zresetować na I/II dla globalnych poziomów VIII/IX, a pozycja na ekranie zmienia się przy auto-scrollu; nie zapisuj slotu ekranowego jako ID jednostki.
- Cel wykonawczy opisuje para `{global_level, match_number}`. `match_number` wskazuje pierwszy, drugi, trzeci lub czwarty slot pasujący do poziomu w ustalonej kolejności skanowania, nie nazwę jednostki ani stałą współrzędną. Typu jednostki nie rozpoznajemy.
- Lokalny numer rzymski może się powtarzać dla różnych poziomów globalnych (np. I/II dla VIII/IX), dlatego poziom należy mapować w kontekście sekwencji listy.
- Plan kampanii jest trwały i przypisany do profilu; śledzi cele, wymaganą i ukończoną liczbę przebiegów oraz jedno aktywne zlecenie. W grze jednocześnie może być aktywne tylko jedno szkolenie. Wykonawca realizuje pojedynczy cel, a planer uruchamia kolejny dopiero po potwierdzeniu zakończenia i zwolnienia Koszar.
- `army_training_plan.py` implementuje planer kampanii: generuje cele poziom/slot, zapisuje je w JSON per profil, śledzi powtórzenia i aktywne zlecenie oraz ustawia interwał kontroli. Nie obsługuje jeszcze ekranów gry, wyszukiwania slotów, OCR ani kliknięć.
- Integracja z grą musi oznaczać zlecenie jako active dopiero po potwierdzeniu startu treningu na ekranie, a run jako completed dopiero po wizualnym potwierdzeniu końca. Model planu sam nie jest dowodem wykonania akcji.
- Scheduler działa per profil: przed dodaniem następnego zlecenia sprawdza widoczne aktywne szkolenie i postęp listy. Nie rozpoczyna drugiego typu, gdy pierwszy nadal trwa, ani nie miesza postępu zleceń między kontami.
- Interwał powrotu do Koszar (typowo 30–60 minut) jest parametrem zlecenia/schedulera. Po powrocie bot odczytuje bieżący stan, bo pomoc klanu może skrócić timer; po wykryciu końca odczekuje 5 sekund na reset widoku i potwierdza wynik przed następnym zleceniem.
- Po dodaniu szkolenia użytkowniczka klika „Pomoc”; przycisk zmienia się potem na „Przyspiesz”. Pomoc członków klanu może skrócić czas, więc po typowym oczekiwaniu 30–60 minut ponownie sprawdź stan szkolenia zamiast zakładać, że timer upłynął.
- „Przyspiesz” może zużywać przedmioty przyspieszające i nie jest równoważne prośbie o pomoc. Klikaj go automatycznie tylko dla zadania z włączonym `quick_finish` i po wizualnym potwierdzeniu przycisku. Jeśli brakuje przyspieszeń, wstrzymaj kolejkę profilu do ręcznego wznowienia; nie zgłaszaj ukończenia, dopóki gra go nie potwierdzi.
- Po zakończeniu bieżącego szkolenia odczekaj co najmniej 5 sekund na reset widoku, pobierz nowy screen i ponownie odczytaj wartości przed zmianą ustawień. Ustawienia wprowadzone przed resetem mogą zostać utracone.
- Powiadomienia mogą zasłonić wiersz bieżącej produkcji. Nieczytelny lub niepewny stan nie może być uznany za pustą kolejkę; poczekaj/odśwież screen i rozpoznaj ponownie.
- Ekran szkolenia Gwardzistów jest opisany w `docs/screens/army_training.md`. Poziomy I–V i typowe wybieranie dwóch najwyższych odblokowanych poziomów dotyczą obecnie tego przykładu; pozostałe kategorie mają być analogiczne, ale nie są jeszcze zweryfikowane osobnymi screenami.
- Przygaszone poziomy w selektorze są nieodblokowane i niewybieralne. UI domyślnie zaznacza najwyższy poziom dostępny, ale feature musi jawnie wybierać skonfigurowany poziom docelowy; często będzie to niższy poziom, nie domyślny najwyższy.
- Stan kolejki, koszt bieżącego wyboru i ilość do wyszkolenia odczytuj świeżo. Dane o poziomie budynku/badaniach można cache'ować per profil z unieważnieniem po zmianie budynku, badań, premii lub wydarzeń.
- Wynik działania: po kliknięciu startu potwierdź zmianę kolejki/zasobów; nie zakładaj sukcesu po samym kliknięciu.

## Profile task queue
- `task_controller.py` stores a persistent task queue per profile in `profiles/<profile>/tasks.json`. Supported task types are `army_training`, `building_upgrade`, and `academy_research`; each task keeps its type explicit so flows cannot be confused.
- The first integrated task type is army training. The controller model can retain tasks blocked by missing resources and recheck them later; it compares fresh available resources with each task's requirements before selecting it. Resource-blocked work does not pause unrelated eligible task types.
- Each task records its creation/start/completion timestamps, initial remaining duration, latest observed remaining duration, status, and task-specific payload. Remaining duration is stored in seconds, not days.
- A different task type may start while an active task is waiting for completion only when its latest observed remaining time is greater than 60 seconds. The same task type cannot have overlapping active tasks.
- After a task is confirmed as started in game, the configured delay before requesting help is 2 seconds by default and must remain within 1-3 seconds. After clicking Help, wait 0.2 seconds by default, then verify the same button has changed to Speed Up before considering acceleration.
- A task's `quick_finish` setting controls automatic acceleration. When enabled, the bot may click Speed Up only after visually verifying that state. If accelerations are unavailable, pause that profile's queue until manual resume. Without `quick_finish`, do not click Speed Up automatically. Never mark a task complete from a click alone; verify completion in the game.
- This module currently models queue state and transitions only. It does not read the game screen, click controls, inspect acceleration inventory, or spend gold; those require a separate verified game interaction flow.
- The army-training bridge materializes only the next pending run from `army_training_plan.py`. It marks the plan order active only after a game-confirmed start and increments `completed_runs` only after a game-confirmed completion; repeated runs remain separate queue tasks and honor the plan reset delay.
- Before starting a training run in game, freshly read the current silver balance and the selected run's silver cost, then compare them. If silver is insufficient or either reading is uncertain, do not start training; keep the task pending and recheck later. Do not use cached silver for this decision.
- Army training is the only task type currently integrated with the campaign plan. Building upgrades and academy research are deferred; do not add their game flows as part of this scope.

### Polityka cache
- Stałe ikony i szablony UI można współdzielić między profilami, jeśli testy potwierdzają ten sam wygląd/skalę.
- Każdy odczyt stanu gry należy opisać: funkcja, profil, źródłowy ekran, czas odczytu, zmienność i reguła odświeżenia.
- Salda zasobów, kolejki, aktywne marsze i inne szybko zmienne dane odczytuj tuż przed użyciem; nie polegaj na cache liczonym w godzinach.
- Wartości rzadziej zmienne (np. poziom budynku) cache'uj osobno dla każdego profilu z czasem odczytu i unieważniaj po akcji, która mogła je zmienić. TTL dobieraj per dane, nie globalnie.
- Nazwa gracza służy do sprawdzania tożsamości profilu; nie może być wspólnym stanem/cache dla wielu okien.
- Obecne `annotate.py` przyjmuje typy `button`, `list`, `number`, `icon`, `anchor`; `number` i `anchor` nie uruchamiają jeszcze OCR. Do odczytu `player_name`, liczb zasobów i zoomu potrzebny będzie jawny typ/tor OCR, nie dopasowanie wartości jako szablonu.

## Watchtower – dostęp premium
- Watchtower jest usługą premium, którą wykupuje się za złoto w grze.
- Czerwone tło wskaźnika Watchtower oznacza brak wykupionego dostępu; niebieskie tło oznacza usługę wykupioną i dostępną.
- Przed rozpoczęciem dowolnego flow korzystającego z Watchtower bot musi rozpoznać jej stan.
- Przy braku dostępu domyślnie wypisz jasny komunikat i przerwij cały flow Watchtower przed wykonaniem dalszych akcji. Nie zakładaj, że funkcja jest dostępna, gdy rozpoznanie jest niepewne.
- Zakup za złoto może być osobną opcją, ale nie może następować automatycznie bez jawnej zgody użytkowniczki. Po zatwierdzonym zakupie bot musi ponownie rozpoznać niebieski stan, zanim przejdzie dalej.
- Rozpoznanie stanów oraz reakcja bota nie są jeszcze zaimplementowane.

## Do uzupełnienia
Szczegółowe reguły gry, nazwy konkretnych ekranów, przejścia między nimi, ograniczenia akcji i przypadki szczególne należy uzupełniać po opisaniu ich przez użytkowniczkę. Nie zakładaj, że tryb mapy lub armii odpowiada pojedynczemu ekranowi.

## Zasada automatyzacji
Elementy stałe (np. ikony i symbole) rozpoznajemy szablonami OpenCV. Zmienne liczby i teksty odczytujemy OCR z walidacją wyniku. Decyzje podejmujemy lokalnie na podstawie rozpoznanego ekranu i jawnej maszyny stanów.

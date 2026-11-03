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

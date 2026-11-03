# Konfiguracja środowiska gry

## Potwierdzone
- System operacyjny: Windows.
- Gra jest używana w przeglądarce oraz w kliencie.
- Oba sposoby uruchomienia są w trybie okna.
- Logowanie i uruchamianie okna gry wykonuje użytkowniczka.

## Do ustalenia
- Rozdzielczość monitora i rozmiar obszaru klienta gry.
- Skala DPI Windows i powiększenie przeglądarki/gry.
- Monitor, na którym znajduje się okno, oraz zachowanie po przesunięciu lub zmianie rozmiaru okna.
- Czy konfiguracja ma być zapisana osobno dla przeglądarki i klienta.

## Aktualny stan kodu
`Automator.update()` przechwytuje pierwszy monitor przez `mss.monitors[1]`, a nie konkretne okno gry. Obecne współrzędne nie są definiowane względem obszaru klienta.

## Kierunek rozwoju
- Docelowo projekt ma mieć prosty interfejs okienkowy na Windows do wybierania akcji i ustawiania parametrów.
- Interfejs GUI powstanie w przyszłości; obecny sposób uruchamiania z CLI pozostaje dostępny.
- Logika automatyzacji powinna być oddzielona od GUI i CLI, aby oba sposoby uruchamiania mogły używać tych samych flow.
- Rekomendowany krok techniczny przed GUI to jawny wybór jednego widocznego okna gry i przechwytywanie jego obszaru klienckiego. Wspólna warstwa powinna przeliczać współrzędne między obszarem okna a pozycją kliknięcia na pulpicie. To kierunek, nie zaimplementowana funkcja.

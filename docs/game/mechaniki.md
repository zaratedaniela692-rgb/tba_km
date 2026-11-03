# Mechaniki gry

## Potwierdzone informacje
- Gra ma dwa podstawowe tryby/konteksty: mapę oraz armię.
- Każdy tryb pokazuje inne ekrany i udostępnia inne opcje.
- Część elementów interfejsu określanych jako „przyciski” jest wspólna dla obu trybów.
- Bot ma rozpoznawać bieżący ekran i wybierać akcje dostępne w danym kontekście.

## Do uzupełnienia
Szczegółowe reguły gry, nazwy konkretnych ekranów, przejścia między nimi, ograniczenia akcji i przypadki szczególne należy uzupełniać po opisaniu ich przez użytkowniczkę. Nie zakładaj, że tryb mapy lub armii odpowiada pojedynczemu ekranowi.

## Zasada automatyzacji
Elementy stałe (np. ikony i symbole) rozpoznajemy szablonami OpenCV. Zmienne liczby i teksty odczytujemy OCR z walidacją wyniku. Decyzje podejmujemy lokalnie na podstawie rozpoznanego ekranu i jawnej maszyny stanów.

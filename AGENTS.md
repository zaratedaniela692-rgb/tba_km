# Zasady pracy nad botem Total Battle

## Zasady stałe
1. Przed zmianą kodu przeczytaj kartę ekranu, zaproponuj plan i zadaj pytania. Kod zmieniaj dopiero po akceptacji użytkowniczki.
2. Jedno zadanie naraz, małe zmiany. Nie przepisuj działającego kodu przy okazji.
3. Nie zgaduj współrzędnych na podstawie oglądania obrazu. Korzystaj z `regions.json` i szablonów. Jeśli brakuje zaznaczenia, poproś o jego przygotowanie w `tools/annotate.py`.
4. Współrzędne zapisuj względem obszaru okna gry, nie całego ekranu. Rozdzielczość, DPI i rozmiar okna powinny być zapisane w `docs/game/konfiguracja.md`.
5. Stałe symbole rozpoznawaj szablonami. OCR stosuj do zmiennych liczb i tekstów; przygotuj obraz i waliduj wynik.
6. Koniec listy wykrywaj po braku zmiany obrazu po przewinięciu, nie po stałej liczbie przewinięć.
7. Każdy flow modeluj jako maszynę stanów: stan, warunek rozpoznania, akcja, oczekiwany następny stan, limit czasu i obsługa błędu.
8. Każdy flow powinien mieć tryb dry-run (loguje planowane kliknięcia bez ich wykonywania) i awaryjne zatrzymanie klawiszem.
9. Loguj datę i godzinę. Przy pewności poniżej progu zapisz screen w `debug/` z opisem.
10. Po zmianie uruchom testy i `verify.py`; pokaż wynik. Jeśli test lub narzędzie nie jest dostępne, zgłoś to.
11. Wiedzę z poprawek użytkowniczki dopisz do karty ekranu w sekcji „Wiedza z poprawek” lub do `docs/game/mechaniki.md`.
12. Nie czytaj całych folderów `debug/` ani `screenshots/`. Poproś o konkretne pliki.
13. Po zakończonym kroku zaproponuj commit z opisem. Nie rób push bez zgody.

## Założenia techniczne
- Bot działa lokalnie i wizualnie: obraz gry -> rozpoznanie -> decyzja -> kliknięcie.
- Rozpoznawanie stałych elementów odbywa się przez OpenCV template matching; OCR (Tesseract) służy do zmiennych tekstów i liczb.
- Nie analizujemy screenów modelem AI w czasie działania bota.
- Nie odczytujemy pamięci procesu, nie przechwytujemy ruchu sieciowego, nie wstrzykujemy kodu i nie obchodzimy zabezpieczeń gry.
- Gra ma dwa główne konteksty: mapa i armia. Mają różne ekrany i dostępne akcje; wspólne elementy interfejsu mogą współdzielić wzorce.
- Logowanie i uruchamianie gry pozostaje po stronie użytkowniczki.

## Struktura projektu
- `automate.py` – istniejący wspólny mechanizm przechwytywania ekranu, dopasowywania wzorców, OCR i kliknięć.
- `crypt.py`, `mines.py`, `watchtower_mines.py`, `login.py`, `troops.py`, `chest_counter.py` – istniejące skrypty automatyzujące poszczególne czynności.
- `samples/` – istniejące wzorce używane przez aktualne skrypty. Nie przenoś ich ani nie zastępuj bez uzgodnienia.
- `templates/<ekran>/` – nowe, opisane szablony elementów.
- `regions.json` – obszary i elementy opisane współrzędnymi względem okna gry.
- `docs/game/` – mechaniki gry i konfiguracja środowiska.
- `docs/screens/` – karty rozpoznawanych ekranów.
- `screenshots/<ekran>/` – screeny źródłowe i ich wersje opisane.
- `tests/data/<ekran>/` – screeny regresyjne i oczekiwane wyniki JSON.
- `tools/` – narzędzia pomocnicze, docelowo `annotate.py` i `verify.py`.
- `debug/verify/<ekran>/` – wyniki weryfikacji rozpoznawania.

W Etapie 1 tworzone są tylko katalogi bazowe. Podkatalogi `<ekran>` powstaną po ustaleniu nazw konkretnych ekranów; „mapa” i „armia” są na razie trybami gry, nie zatwierdzonymi nazwami ekranów.

## Uruchamianie i zależności
Uruchamiaj polecenia z katalogu projektu. W PowerShell przykłady:

```powershell
python .\crypt.py --help
python .\crypt.py --type common --min-progress 50
python .\mines.py --help
python .\watchtower_mines.py --help
python .\login.py .\credentials.json
python .\troops.py .\troops.json
python .\chest_counter.py
```

`login.py` wymaga JSON z polami `username` i `password`; `troops.py` wymaga JSON mapującego nazwy jednostek na liczby. `mines.py` i `watchtower_mines.py` udostępniają własne argumenty CLI. Dla `mines.py` kliknięcia są opt-in przez `--click`; sprawdź `--help` przed użyciem innych trybów.

Kod importuje m.in. PyAutoGUI, OpenCV (`cv2`), NumPy, MSS, imutils i pytesseract. Wymagany jest także zainstalowany program Tesseract OCR; niektóre skrypty kopalń używają opcjonalnych bibliotek dźwiękowych. W repozytorium nie ma obecnie manifestu zależności z przypiętymi wersjami.

## Stan przechwytywania obrazu
Aktualne `Automator.update()` przechwytuje pierwszy monitor (`mss.monitors[1]`), a nie wybrane okno gry. Docelowe współrzędne względem okna oraz wybór okna przeglądarki/klienta nie są jeszcze zaimplementowane. Nie zakładaj, że wymagania z sekcji „Zasady stałe” są już spełnione przez istniejący kod.

# Zasady pracy nad botem Total Battle

## Zasady stałe
1. Przed zmianą zachowania przeczytaj właściwy workflow i kartę ekranu, jeśli dotyczy, oraz krótko przedstaw mały plan. Pytaj tylko o nierozstrzygnięte decyzje wpływające na zakres lub ryzyko; wyraźne polecenie wdrożenia wraz z doprecyzowanym zachowaniem jest akceptacją tego zakresu. Nie pytaj ponownie o zgodę na już zatwierdzone kroki.
2. Jedno zadanie naraz, małe zmiany. Nie przepisuj działającego kodu przy okazji.
3. Reguły rozpoznawania ekranu i bezpiecznej automatyzacji gry stosuj z [game-automation.instructions.md](.github/instructions/game-automation.instructions.md).
4. Dowieź mały, użyteczny przyrost funkcjonalności i wykonaj proporcjonalną walidację. Preferuj krótki live check UI w grze, gdy użytkowniczka jawnie autoryzuje konkretny zakres; używaj wąskich testów automatycznych do logiki i krytycznych zabezpieczeń, bez rozbudowywania macierzy fixture'ów dla każdego wariantu ekranu. Pełne `pytest` uruchamiaj przy zmianach przekrojowych lub przed większym etapem; `tools/verify.py` uruchamiaj przy zmianach regionów/szablonów, gdy jest właściwe do sprawdzenia zmiany. Zgłaszaj niewykonaną walidację i znane ograniczenia. Nie pomijaj kontroli potrzebnych, by uniknąć niezamierzonego wydania zasobów, kliknięcia lub zmieszania profili.
5. Zmiany kontraktów i dokumentacji prowadź zgodnie z [workflow-docs.instructions.md](.github/instructions/workflow-docs.instructions.md).
6. Nie czytaj całych folderów `debug/` ani `screenshots/`; wskaż konkretne pliki.
7. Po zakończonym kroku zaproponuj commit z krótkim opisem. Nie rób push bez zgody.
8. Before a behavior change, update its authoritative workflow with the agreed contract, confirmed facts/assumptions, deferred cases, implementation status, and proportionate validation. A clear user request to implement the described behavior is explicit approval; ask first only when a consequential behavior or risk remains unclear. Keep one current status in the area workflow rather than adding a separate progress file per module, and keep the workflow aligned with code and tests.
9. Follow the failure-only game screenshot policy in [game-automation.instructions.md](.github/instructions/game-automation.instructions.md); never repeat an uncertain action to collect evidence.

## Bezpieczeństwo automatyzacji
- Bot działa lokalnie i wizualnie. Nie odczytujemy pamięci procesu, nie przechwytujemy ruchu sieciowego, nie wstrzykujemy kodu ani nie obchodzimy zabezpieczeń gry.
- Nie analizujemy screenów modelem AI w czasie działania bota.
- Logowanie i uruchamianie gry pozostaje po stronie użytkowniczki; profile nie przechowują haseł.
- Nie mieszaj danych ani akcji pomiędzy profilami. Zakres nowych flow gry wymaga osobnej zgody.
- Browser readiness and read-only fixture coverage are separate capabilities; consult the current [client routing contract](docs/game/ui_variants_plan.md) before claiming support. Never enable browser actions from desktop assets.

## Nawigacja po projekcie

For behavior and capability questions, start with the area's workflow and its feature contents; do not routinely inspect code when the documented answer is complete. Inspect the relevant implementation and tests when changing behavior, diagnosing a bug, or resolving missing, contradictory, or stale documentation. A workflow describes the contract; it is not proof of implementation or a passing test run. Screen cards own visual recognition evidence, while shared game facts belong in [mechaniki.md](docs/game/mechaniki.md).

Documentation ownership, the feature-section format, and maintenance rules are defined in [workflow-docs.instructions.md](.github/instructions/workflow-docs.instructions.md#feature-contract-format). The area workflows below have feature contents and scoped contracts. Their status sections distinguish inspected implementation, tests actually executed, live evidence, and unresolved conflicts. Retained historical notes are not additional current contracts; legacy coverage explicitly names unaudited branches. Project structure, AI-assisted workflow optimization, and daily review are tracked in the [AI agent workflow audit and improvement plan](docs/agent_workflow_refactor.md).

| Obszar | Workflow / źródło prawdy | Kod | Testy |
| --- | --- | --- | --- |
| Training army | [Army training workflow](docs/game/army_training_slot_workflow.md) | `army_training_*.py`, `army_training_manager.py`, `army_training_executor.py` | `tests/test_army_training_*.py` |
| Speedups | [Speedup workflow](docs/game/speedup_module_workflow.md) | `speedup*.py` | `tests/test_speedup*.py` |
| Task queue | [Task manager contract](docs/game/task_manager.md); see [task-queue.instructions.md](.github/instructions/task-queue.instructions.md) | `task_controller.py` | `tests/test_task_controller.py` |
| UI variants and client routing | [UI variants plan](docs/game/ui_variants_plan.md) | `ui_variants.py`, `client_router.py` | `tests/test_client_router.py`, `tests/test_browser_army_training.py` |
| Shared resource readings | [Resource reading workflow](docs/game/resource_reading_workflow.md) | `tools/resource_ocr.py` | `tests/test_resource_ocr.py` |
| Legacy mines, Watchtower, crypts | [Legacy automation workflow](docs/game/legacy_automation_workflow.md) | `mines.py`, `watchtower_mines.py`, `crypt.py`, `automate.py` | Recognition tests only; see scoped evidence and gaps in the workflow |
| Screen recognition | [Screen cards](docs/screens/) | `automate.py`, `regions.json`, `templates/` | `tests/data/`, `tools/verify.py` |

Run commands and domain-specific recognition rules are in [game-automation.instructions.md](.github/instructions/game-automation.instructions.md). Test and supervised-run requirements are in [game-tests.instructions.md](.github/instructions/game-tests.instructions.md).

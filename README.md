# Total Battle Automation

## Development Notes

- [UI variants preparation plan](docs/game/ui_variants_plan.md) describes how to preserve the current interface as `legacy` and prepare isolated support for the new interface without implementing it prematurely.

Total Battle is a terrible game that manipulates its players into spending as much money and time on it as possible.
This project contains some scripts intended to reduce the amount of time spent.

The current automation uses the existing desktop-client assets and captures the primary monitor; it does not yet select a game window. Browser support is planned separately and is not implemented. See the [UI variants plan](docs/game/ui_variants_plan.md); browser screenshots, regions, and templates must be verified independently before use.

## Development and Tests

Use the repository root as the working directory. In PowerShell, create/configure the project environment and install the declared Python dependencies with:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements-dev.txt
```

Screen-reading features also require the Tesseract OCR executable. Install it separately and make sure it is on `PATH`, or pass its path through the relevant tool option when available.

Run the focused tests for the code being changed, for example:

```powershell
.\.venv\Scripts\python.exe -m pytest -q .\tests\test_client_router.py
.\.venv\Scripts\python.exe -m pytest -q .\tests\test_speedup_planner.py .\tests\test_speedup_browser.py
.\.venv\Scripts\python.exe -m pytest -q
```

For visual recognition, use the relevant screen fixtures and `tools/verify.py` as described by the area's workflow. A test file or documented command is not evidence that the current code passes; report the command and its actual result. See [AGENTS.md](AGENTS.md) for repository-wide collaboration rules, the applicable [automation instructions](.github/instructions/game-automation.instructions.md) and [test instructions](.github/instructions/game-tests.instructions.md), then the area workflow in [docs/game](docs/game/).

For the AI-agent workflow audit and planned organization improvements, see [Agent Workflow Refactor](docs/agent_workflow_refactor.md). For completed code refactor slices, reasons, and validation results, see the [Project Refactor Log](docs/game/project_refactor_log.md).

The live wrappers are not test-suite commands. `tools/run_army_navigation_live.py` sends Escape and a detected Armia click; `tools/run_army_e2e.py` can modify the local test queue, submit training for 100 Guardsmen, and spend in-game resources. Run a live wrapper only for its documented scope, with the game prepared and explicit authorization for that run. Automated tests must use fixtures or mocked callbacks and must never launch these live wrappers.

## Crypting

The `crypt.py` script runs automatic crypting via the watchtower.
By default the script will recognise common crypts; use the `-t` flag to select rare or epic crypts.
Note that the watchtower needs to be aligned with this selection before running the script.

The script should be started with Carter selected as the only captain while the game is on the worldmap, zoomed in to the maximum 125%.
It takes a careful approach to selecting crypts.
From the watchtower screen, a random one of the visible locations is chosen.
Once the location on the map is loaded, the script will find the location of a crypt according to the `-t` flag.
It will filter out any crypts that have pre-existing blue or red lines over them in order to not steal any crypts.
It will also refuse to march on any rare crypts that are already opened.

Note that the crypt actually marched on may not be the one that was originally selected via the watchtower.
In particular, it may not be one of the same level.

## Troop Selection

The `troops.py` script should be executed while on the troop selection window ahead of an attack.
It must be provided with the location of a JSON file that contains an object with unit names as its keys and numbers as its values.
The available unit names correspond to the images in the `samples/units/` directory.
Note that most lower level units are currently missing.

## Chest Counter

The `chest_counter.py` script is an experimental chest counter implementation that has not been tested in production.
For each chest counted it outputs a JSON object on a single line, which can be processed by other software.
It will also regularly click the help button.

## Login

The `login.py` script will automatically login given a JSON file containing an object with `"username"` and `"password"` keys.
The idea was that this could be combined with other scripts to fully automate workflows running in for instance Xvfb, which would then allow multiple sessions on the same machine.
This concept could use some further thought and convenience scripts, which I may or may not add here later.

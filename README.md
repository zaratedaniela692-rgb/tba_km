# Total Battle Automation

## Development Notes

- [UI variants preparation plan](docs/game/ui_variants_plan.md) describes how to preserve the current interface as `legacy` and prepare isolated support for the new interface without implementing it prematurely.

Total Battle is a terrible game that manipulates its players into spending as much money and time on it as possible.
This project contains some scripts intended to reduce the amount of time spent.

To maximise cross-platform applicability, the scripts are tailored to operate on the web version of the game, running in a browser such as Firefox.
Note that some browsers do not allow number inputs when for example selecting troops.
Sadly the web version of the game will crash relatively often.
To counter this, the scripts will try to refresh the game whenever they feel they got stuck.

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

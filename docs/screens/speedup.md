# Evidence Policy Note (2026-11-09)

Retained historical anchor. The current [evidence policy and implementation limits](../game/speedup_module_workflow.md#calibration-mapping-and-evidence) belong to the workflow: failure-only game screenshots, with explicit calibration/annotation outputs excepted. This card does not define action or persistence behavior.

# Ekran: speedup

Visual recognition card for the desktop speedup dialog. Legacy Polish headings are retained for existing anchors; repository prose below is English.

**Evidence baseline: source inspection 2026-11-10.** No tests were run here, no live game actions were performed and historical images were not re-reviewed in this migration. Recognition rules below describe inspected sources, not newly passing fixture or live results.

Behavior owner: [speedup feature contents](../game/speedup_module_workflow.md#feature-contents). In particular, see [callable runner versus CLI](../game/speedup_module_workflow.md#scope-and-entry-points), [reader contract](../game/speedup_module_workflow.md#timer-and-checkpoint-inventory-reading) and [runner-specific use verification](../game/speedup_module_workflow.md#use-verification-and-result-semantics). The former commands advertised by this card were not an implemented finishing CLI.

## Jak rozpoznać

Reference desktop captures (1920x1080), retained as visual references rather than fresh validation:

| Capture | Visual evidence |
| --- | --- |
| [screenshots/speedup_module/speedup_view.png](../../screenshots/speedup_module/speedup_view.png) | Top of list: 1m, 15m, 1h and following rows |
| [screenshots/speedup_module/speedup_view2.png](../../screenshots/speedup_module/speedup_view2.png) | Middle: 8h, 15h, 1d, 3d |
| [screenshots/speedup_module/speedup_view3.png](../../screenshots/speedup_module/speedup_view3.png) | Lower list: owned 3d/7d/30d and separate 30d Buy offer |
| [screenshots/speedup_module/after_click_7days_speedup.png](../../screenshots/speedup_module/after_click_7days_speedup.png) | Different timer/7d count; filename alone proves neither action mechanics nor causality |
| [screenshots/speedup_module/academy_speeduo_button.png](../../screenshots/speedup_module/academy_speeduo_button.png) | Academy entry button only, not shared-dialog equivalence |
| [screenshots/speedup_module/build_in_city_speedup_button.png](../../screenshots/speedup_module/build_in_city_speedup_button.png) | Building entry button only, not shared-dialog equivalence |

The dialog title template is searched within 8 px of its annotated region at normalized score >=0.95. Current recognition also checks the first 16 template rows; fallback requires score >=0.95 and the same best location as the full template. A title match is not task/account classification. The task-context region is reference geometry, not an implemented task-type detector.

Use buttons are matched inside the inventory viewport at >=0.95. Complete detections are sorted top-to-bottom and paired with checkpoint labels; their fresh rectangles drive quantity crops and click points. Exact mapped count, in-bounds rectangles and offsets consistent within 1 px across rows are required. Uniform translation is accepted; the former absolute 2 px limit is not current recognition behavior. A Buy offer can share a duration label with owned stock; duration alone does not classify ownership.

The sources use desktop 1920x1080 annotations. They do not establish browser recognition or selected-window capture. Capture/input assumptions belong to the [workflow](../game/speedup_module_workflow.md#scope-and-entry-points).

## Elementy

1. `speedup_dialog_anchor`: title "Przyspieszenia"; template recognition, not task identity.
2. `speedup_task_context`: task name/icon and "Pozostalo" area; reference only, no automatic task classification.
3. `speedup_remaining_time`: day/hour timer beside the hourglass. Segmented digit OCR at 6x/10x requires agreement and the verified digit set `1,3,4,6,7`; the taller hourglass is excluded. Other digits/layouts remain uncertain. Pure parser support is broader than image recognition.
4. `speedup_inventory_viewport`: scrolling row area, **including** Use controls; the matcher searches for buttons inside it.
5. `speedup_item_duration`: nominal text on the icon; general duration OCR is unverified. Current duration identity is assigned from checkpoint labels, not read from these tiny glyphs.
6. `speedup_item_quantity`: crop positioned relative to a freshly matched Use button, with 5 px left and 3 px right insets. OCR at 4x/6x using PSM 8 must agree; empty/disagreeing reads fall back to PSM 7 at both scales. Raw readings/status are retained; disagreement is not zero stock.
7. `speedup_purchase_offer`: separate lower row with "Kup"; visually distinct from owned "Uzyj" rows even when both show 30d.
8. `speedup_scroll_track` / `speedup_scroll_thumb`: supporting reference regions. Full thumb-state recognition/threshold is not established; current scrolling uses viewport-image differences instead.
9. `speedup_use_button`: complete "Uzyj" control. Layout verification does not by itself prove a successful use or a decreased quantity; see [verification semantics](../game/speedup_module_workflow.md#use-verification-and-result-semantics).

Implemented recognition and fixture assertions are in [speedup_reader.py](../../speedup_reader.py), [speedup_inventory_reader.py](../../speedup_inventory_reader.py), [speedup_calibration.py](../../speedup_calibration.py), [tests/test_speedup_reader.py](../../tests/test_speedup_reader.py), [tests/test_speedup_inventory_reader.py](../../tests/test_speedup_inventory_reader.py) and [tests/test_speedup_calibration.py](../../tests/test_speedup_calibration.py). Existence of those assertions is not a test result.

## Regiony kandydackie (ekran `speedup` w `regions.json`, układ `speedup_view.png`)

Retained heading anchor. These are annotated reference regions in [regions.json](../../regions.json), not newly measured coordinates. Geometry is in 1920x1080 capture-frame pixels, not selected-window coordinates. Row positions vary with scrolling; static first-row reference geometry is not a reusable absolute click point.

| Element | x, y, w, h | Recognition notes |
| --- | --- | --- |
| `speedup_dialog_anchor` | 900, 250, 120, 24 | Title; historical captures reported scores >=0.997, not rerun here |
| `speedup_task_context` | 716, 278, 232, 70 | Task-dependent name/icon; not a classifier |
| `speedup_remaining_time` | 1064, 322, 110, 22 | Hourglass plus day/hour text such as `13 d.:7 g.` |
| `speedup_inventory_viewport` | 678, 376, 562, 418 | Includes row Use controls |
| `speedup_use_button` | 1050, 445, 145, 27 | First-row reference; historical row spacing 110 px and Buy score about 0.6 |
| `speedup_item_icon` | 723, 396, 72, 72 | Icon begins 49 px above button |
| `speedup_item_duration` | 723, 402, 40, 20 | Tiny duration glyphs; OCR unverified |
| `speedup_item_quantity` | 755, 446, 42, 22 | Reference crop shifted with detected button and inset before OCR |
| `speedup_purchase_offer` | 1050, 746, 145, 27 | Buy reference from lower-list capture |
| `speedup_scroll_track` / `speedup_scroll_thumb` | 1218, 380, 12, 414 / 1218, 392, 12, 62 | Historical thumb y=392/603/716; track bounds/full-state recognition unconfirmed |

Checkpoint map: [speedup_button_map.json](../../speedup_button_map.json). Map rectangles/centers are **viewport-relative**, unlike the frame-relative table above. Recognition validates fresh complete matches rather than blindly reusing stored centers.

## Przejścia

Visual landmarks from the historically reviewed checkpoint set:

| Cumulative step | Visible labels | Complete mapped Use buttons |
| --- | --- | --- |
| 3 | 15m, 1h, 3h, 8h | 4 |
| 11 | 15h, 1d, 3d, clipped 7d row | 3; clipped 7d control omitted |
| 16 | Owned 3d, 7d, 30d and lower Buy offer | 3; Buy excluded |

The repeated 3d row is visible at steps 11 and 16. The complete 7d position is from step 16, not both views. The 1m row is not in this map. Standalone viewport fixture references are [tests/data/speedup/checkpoint_003.png](../../tests/data/speedup/checkpoint_003.png), [tests/data/speedup/checkpoint_011.png](../../tests/data/speedup/checkpoint_011.png) and [tests/data/speedup/checkpoint_016.png](../../tests/data/speedup/checkpoint_016.png).

Viewport change is a recognition signal; whether unchanged means endpoint or landmark mismatch depends on the [runner/calibration contract](../game/speedup_module_workflow.md#scope-and-entry-points). This card does not define navigation commands, execution permission, planning or completion rules. Calibration interfaces and historical capture scope are owned by [calibration and evidence](../game/speedup_module_workflow.md#calibration-mapping-and-evidence).

## Przypadki szczególne

- Owned 30d and a shop 30d can be simultaneously visible; classify the control/layout, not the label alone.
- One viewport does not show all mapped rows. Clipped controls cannot become complete matches by assigning the expected label.
- Quantity crops follow fresh button detections; common translation is different from inconsistent row displacement.
- Matching buttons with `verify_only` provides no observed quantity. General duration OCR is not supplied by that mode or by checkpoint label association.
- Day/hour OCR may reject otherwise valid timers containing digits outside `1,3,4,6,7`; no zero-timer or minute/second fixture support is established by this reader.
- Title recognition does not verify active task, profile, account or the foreground window. Academy/building entry screenshots are insufficient evidence of compatible dialogs.

## Wiedza z poprawek

- 2026-11-06: earlier bot captures reported title detection at (902,255), offset (+2,+5) from annotation (900,250), score 0.9973. This motivated bounded anchor search, not an annotation shift. Historical calibration approval is preserved in the [workflow](../game/speedup_module_workflow.md#scroll-calibration-workflow-approved-2026-11-06).
- 2026-11-07: user-reported 3/11/16 landmarks were subsequently recorded as visually reviewed in existing documentation. Complete-button mapping clarified that step-11 7d is clipped, step-16 7d is complete, 3d repeats, 1m is omitted and the final Buy row is excluded. This correction supersedes the duplicate earlier note implying complete 7d at both checkpoints.
- 2026-11-07: historical dry-run report `7_20261107_200245` recorded timer `10d.:23g.` and four step-3 Use matches at confidence 1.0, but uniform (+2,+4) offset exceeded the old 2 px limit. A later source change uses fresh positions with cross-row offset consistency. Existing notes reported a reread yielding 15m=4853, 1h=5257, 3h=3383, 8h=475; that reread was not repeated here, and the historical run was not an item-use run.
- 2026-11-09: evidence-policy correction moved successful action frames to memory-only processing except explicit calibration outputs; current policy and persistence limits are in the [workflow](../game/speedup_module_workflow.md#calibration-mapping-and-evidence).
- 2026-11-10: source-only migration removed stale finishing CLI claims, distinguished button layout checks from quantity confirmation and retained visual evidence without asserting fresh test success. Planner/authorization history is preserved under [historical workflow anchors](../game/speedup_module_workflow.md#historical-decisions-and-retained-anchors), not maintained as a second screen-card contract.

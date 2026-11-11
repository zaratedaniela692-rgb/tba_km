#!/usr/bin/env python3

import time
import argparse
import os
import pytesseract
import cv2
import math

common_crypts = ["crypts/" + name for name in ["cave", "cog", "dune", "greek", "grotto", "ice", "lava", "rune", "skull", "snake", "temple", "pyramid"]]
rare_crypts = ["crypts/" + name for name in ["left", "right"]]
epic_crypts = ["crypts/" + name for name in ["darktree", "tomb", "labyrinth", "rock", "staired", "spike", "ring", "lighttree", "steppyramid", "epicpyramid", "redtree", "cathedral", "crystal", "palace", "pit", "scorpion", "haunted"]]

def crypt(a):
    if not a.await_samples("watchtower", 2):
        return False
    a.click()
    if not a.await_samples(["crypts_selected", "crypts_unselected"], 2):
        return False
    a.click()
    time.sleep(0.4)
    if not a.await_samples_multi("go_watchtower", 2):
        return False
    if not a.random_multi():
        return False
    a.click()
    time.sleep(0.4)
    if not a.await_samples_multi(crypts, 4):
        return False

    # OCR-based progress filtering: read percent for each detected crypt
    OCR_DEBUG_DIR = "ocr_debug"
    try:
        os.makedirs(OCR_DEBUG_DIR, exist_ok=True)
    except Exception:
        pass

    def read_progress(a, loc, dx=90, dy=0, w=140, h=28, debug=False):
        a.loc = loc
        min_x = -dx - w//2
        max_x = -dx + w//2
        min_y = dy - h//2
        max_y = dy + h//2
        try:
            roi = a.cut(min_x, min_y, max_x, max_y, show=False)
        except Exception:
            return None
        if roi is None or roi.size == 0:
            return None
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        th = cv2.resize(th, (th.shape[1]*2, th.shape[0]*2), interpolation=cv2.INTER_LINEAR)
        if debug:
            ts = int(time.time()*1000)
            fname = f"{OCR_DEBUG_DIR}/{ts}_{int(loc[0])}_{int(loc[1])}.png"
            try:
                cv2.imwrite(fname, th)
            except Exception:
                pass
        config = "--psm 7 -c tessedit_char_whitelist=0123456789%"
        try:
            text = pytesseract.image_to_string(th, config=config).strip()
        except Exception:
            return None
        digits = "".join(ch for ch in text if ch.isdigit())
        if not digits:
            return None
        try:
            return int(digits)
        except Exception:
            return None

    # Build list of OCR readings and candidates
    readings = []
    candidates = []
    for loc in list(a.multi or []):
        pct = read_progress(a, loc, dx=90, dy=0, w=140, h=28, debug=True)
        readings.append((loc, pct))
        if pct is not None and pct >= MIN_PROGRESS:
            candidates.append((loc, pct))

    # Log OCR readings
    print("OCR readings:")
    for loc, pct in readings:
        print(f"  loc={loc} -> {pct}")

    # If a minimum progress threshold was provided and nothing meets it, exit
    if MIN_PROGRESS > 0 and not candidates:
        print(f"No crypts meet threshold {MIN_PROGRESS}%. Exiting.")
        exit(0)

    # If candidates exist, narrow a.multi; otherwise leave a.multi unchanged
    if candidates:
        a.multi = [loc for loc, _ in candidates]
    a.multi_block_color(140, 100, (48, 37, 130))
    a.multi_block_color(140, 100, (254, 74, 32))
    if not a.central_multi():
        return False
    a.click()

    # Verify selected crypt meets OCR threshold before proceeding to 'Go'
    # selected_loc is set by a.click() above (the chosen crypt center)
    selected_loc = (int(a.loc[0]), int(a.loc[1]))

    def _get_pct_for_loc(sel, readings, tol=40):
        best_pct = None
        best_d = float('inf')
        for loc, pct in readings:
            if pct is None:
                continue
            d = math.hypot(loc[0] - sel[0], loc[1] - sel[1])
            if d < best_d:
                best_d = d
                best_pct = pct
        if best_d <= tol:
            return best_pct
        return None

    selected_pct = _get_pct_for_loc(selected_loc, readings, tol=40)
    print(f"Selected crypt approx {selected_loc} -> pct={selected_pct}")

    if MIN_PROGRESS > 0 and (selected_pct is None or selected_pct < MIN_PROGRESS):
        print(f"Selected crypt {selected_loc} has {selected_pct}% (<{MIN_PROGRESS}%). Aborting before Go.")
        return False

    time.sleep(0.3)
    if not a.await_samples("carter_selected", 2):
        return False
    if not a.await_samples("selected", 2):
        return False
    if rare:
        if not a.await_samples("rare_open", 2):
            return False
        a.click()
    if not a.await_samples("explore", 2):
        return False
    a.click(0, 10)
    if not a.await_samples("carter_march", 2):
        return False
    return True

def speedup(a):
    if a.await_samples("carter_march", 2):
        a.click(190, 8)
        if not a.await_samples("speedup", 2):
            return True
        for _ in range(6):
            a.click(360, 36)
        time.sleep(1.5)
        return True
    return False

MIN_PROGRESS = 0
rare = False
crypts = common_crypts


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("-t", "--type", default="common", help="crypt type")
    parser.add_argument(
        "-p", "--min-progress", type=int, default=0,
        help="minimum exploration percent to select crypt (0 = no filtering)",
    )
    args = parser.parse_args(argv)

    global MIN_PROGRESS, crypts, rare
    MIN_PROGRESS = args.min_progress
    rare = args.type == "rare"
    crypt_types = {
        "common": common_crypts,
        "epic": epic_crypts,
        "rare": rare_crypts,
    }
    if args.type not in crypt_types:
        print("Unknown crypt type")
        return 1
    crypts = crypt_types[args.type]

    from automate import Automator

    automator = Automator()
    fails = 0
    last_restart = time.time()
    while True:
        if fails >= 10 or time.time() > last_restart + 900:
            automator.restart_game(True)
            last_restart = time.time()
            fails = 0
        if not speedup(automator):
            if crypt(automator):
                fails = 0
            else:
                fails += 1


if __name__ == "__main__":
    raise SystemExit(main())

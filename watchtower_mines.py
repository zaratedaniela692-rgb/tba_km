#!/usr/bin/env python3


from automate import Automator
import time
import argparse
import os
import numpy as np
import cv2
import math
import signal
import threading
import atexit
import traceback
try:
    import pyautogui
    HAVE_PYAUTOGUI = True
except Exception:
    HAVE_PYAUTOGUI = False


try:
    import winsound
    HAVE_WINSOUND = True
except Exception:
    HAVE_WINSOUND = False


OCR_DEBUG_DIR = "ocr_debug/mines"
try:
    os.makedirs(OCR_DEBUG_DIR, exist_ok=True)
except Exception:
    pass


def ts_log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


# Global stop event used for graceful shutdown (Ctrl+C / SIGTERM)
stop_event = threading.Event()


def _signal_handler(signum, frame):
    ts_log(f"[signal] received {signum}, requesting stop")
    stop_event.set()
    def _force_exit():
        try:
            time.sleep(0.2)
        except Exception:
            pass
        try:
            ts_log('[signal] force exiting now')
        except Exception:
            pass
        os._exit(0)
    t = threading.Thread(target=_force_exit, daemon=True)
    t.start()


def _on_exit():
    stop_event.set()
    ts_log("[exit] cleanup requested")


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)
atexit.register(_on_exit)


def rgb_distance(a, b):
    return math.sqrt(sum((float(x) - float(y)) ** 2 for x, y in zip(a, b)))


def roi_mean(a, loc, dx, dy, w, h):
    a.loc = loc
    min_x = -dx - w//2
    max_x = -dx + w//2
    min_y = dy - h//2
    max_y = dy + h//2
    try:
        roi = a.cut(min_x, min_y, max_x, max_y, show=False)
    except Exception:
        return None, None
    if roi is None or roi.size == 0:
        return None, None
    mean_col = tuple(map(float, reversed(np.mean(roi, axis=(0,1)))))
    return roi, mean_col


def percent_pixels_close(roi, target_rgb, tol=40):
    if roi is None or roi.size == 0:
        return 0.0
    arr = roi.reshape((-1,3))[:, ::-1].astype(float)
    tgt = np.array(target_rgb, dtype=float)
    dists = np.sqrt(np.sum((arr - tgt) ** 2, axis=1))
    return float(np.count_nonzero(dists <= tol)) / float(arr.shape[0])


def play_sound(path=None):
    if HAVE_WINSOUND:
        if path:
            try:
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                return
            except Exception:
                pass
        try:
            winsound.Beep(1000, 400)
        except Exception:
            pass
    else:
        ts_log("[notify] (no winsound)\a")


def on_free_mine_found(loc, args):
    """Called when a free (unoccupied) mine is confirmed (dm_busy NOT detected after clicking Go).

    Executes all actions for a free mine:
      1. Play alert sound for --alert-duration seconds
      [future] 2. Display mine coordinates on screen / overlay
      [future] 3. Send in-game notification to clan members
    """
    ts_log(f"[alert] FREE mine confirmed at {loc} — playing alert for {args.alert_duration}s")
    start = time.time()
    while time.time() - start < args.alert_duration:
        if stop_event.is_set():
            ts_log("[alert] stop requested during alert, aborting")
            break
        play_sound(args.sound)
        if stop_event.wait(timeout=1.0):
            break
    ts_log(f"[alert] alert finished for {loc}")

    # [future] display coordinates
    # [future] send clan notification


def click_watchtower(a, timeout=4):
    """Open the Watchtower and switch to the Mines tab.

    Uses both localized tab patterns:
      - mines_selected_PL   -> mines tab already active, continue without click
      - mines_unselected_PL -> mines tab inactive, click to activate

    Returns True on success, False on failure or stop_event set.
    """
    if stop_event.is_set():
        return False
    if not a.await_samples("watchtower", timeout):
        return False
    ts_log("[step] Found watchtower, clicking to open")
    ts_log(f"       loc={a.loc}")
    if stop_event.is_set():
        ts_log('[stop] stop requested before opening, abort')
        return False
    a.click()

    ts_log('[step] Waiting for mines tab selector (localized)')

    if a.await_samples("mines_selected_PL", 2):
        ts_log(f"[step] mines tab already active at {a.loc}")
    elif a.await_samples("mines_unselected_PL", 2):
        ts_log(f"[step] mines tab found inactive at {a.loc}, clicking to activate")
        if stop_event.is_set():
            ts_log('[stop] stop requested before clicking tab, abort')
            return False
        a.click()
        time.sleep(0.1)
    else:
        ts_log('[step] mines tab selector not found')
        return False

    try:
        a.update()
        stamp = int(time.time() * 1000)
        fname = f"{OCR_DEBUG_DIR}/full_screen_{stamp}.png"
        cv2.imwrite(fname, a.image)
        ts_log(f"       saved full screen debug to {fname}")
    except Exception:
        pass

    return True

def detect_list_and_go(a, args, timeout=2):
    """Detect dm_list entries and go_watchtower candidates and map them.

    Returns (mapped_pairs, list_items, go_candidates).
    """
    list_sample = f"mines/{args.list_pattern}"
    list_path = os.path.join(os.path.dirname(__file__), 'samples', 'mines', f"{args.list_pattern}.png")
    list_items = []
    if os.path.exists(list_path):
        ts_log(f"[step] Looking for list entries with pattern {list_sample}")
        if a.await_samples_multi(list_sample, timeout):
            list_items = list(a.multi or [])
            ts_log(f"[step] found {len(list_items)} list entries:")
            for li in list_items:
                bottom_y = li[1] + args.list_estimated_h/2
                ts_log(f"       dm_list center={li} approx_bottom_y={bottom_y}")
        else:
            ts_log('[step] no list entries found')
    else:
        ts_log(f"[warn] list pattern missing: {list_path}")

    ts_log('[step] Searching for all go_watchtower candidates')
    go_candidates = []
    if a.await_samples_multi("go_watchtower", timeout):
        go_candidates = list(a.multi or [])
        ts_log(f"[step] found {len(go_candidates)} Go candidates:")
        for g in go_candidates:
            bottom_y = g[1] + args.go_estimated_h/2
            ts_log(f"       Go center={g} approx_bottom_y={bottom_y}")
    else:
        ts_log('[step] no go_watchtower candidates found')

    mapped = []
    for li in list_items:
        best = None
        best_dy = None
        li_bottom = li[1] + args.list_estimated_h/2
        for g in go_candidates:
            go_bottom = g[1] + args.go_estimated_h/2
            dy = abs(go_bottom - li_bottom)
            dx = g[0] - li[0]
            if dy <= args.list_y_tol and args.list_min_dx <= dx <= args.list_max_dx:
                if best is None or dy < best_dy:
                    best = g
                    best_dy = dy
        if best is not None:
            mapped.append((li, best))
            ts_log(f"[map] dm_list {li} -> Go {best} (dy={best_dy}, dx={best[0]-li[0]})")
        else:
            ts_log(f"[map] dm_list {li} -> no matching Go (y_tol={args.list_y_tol}, dx range [{args.list_min_dx},{args.list_max_dx}])")

    return mapped, list_items, go_candidates


def scroll_list(a, args):
    """Scroll the watchtower list down using pyautogui.scroll().

    pyautogui.scroll() takes negative values to scroll down.
    Cursor is moved to scroll_x, scroll_y before scrolling.
    """
    if not HAVE_PYAUTOGUI:
        ts_log("[scroll] pyautogui not available — cannot scroll")
        return
    try:
        pyautogui.moveTo(args.scroll_x, args.scroll_y, duration=0.1)
        for _ in range(args.scroll_steps):
            pyautogui.scroll(-1)
            time.sleep(0.05)
        time.sleep(0.15)
        ts_log(f"[scroll] scrolled down {args.scroll_steps} steps at ({args.scroll_x},{args.scroll_y})")
    except Exception as e:
        ts_log(f"[scroll] scroll error: {e}")


def is_scrollbar_visible(a, args):
    """Check if the scrollbar (list_detection.png) is visible at all.

    If not visible — list fits entirely in 4 rows, no scrolling needed.
    Returns (visible: bool, slider_y: float or None)
    """
    try:
        a.update()
        result = a.find('list_detection', threshold=args.list_end_threshold, set_loc=True)
        if result is None:
            return False, None
        return True, a.loc[1]
    except Exception as e:
        ts_log(f"[scroll] scrollbar check error: {e}")
        return False, None


def is_list_end(slider_y, args):
    """Return True if the scrollbar has reached the bottom position."""
    return slider_y >= args.list_end_y


def _post_click_handle(a, args, go_loc):
    """Post-click logic: wait, optional confirm pattern, then check dm_busy.

    dm_busy detected  -> mine OCCUPIED -> re-open watchtower -> return False
    dm_busy NOT found -> mine FREE ->
                            1. on_free_mine_found() [alert + future actions]
                            2. re-open watchtower for next entry
                         -> return True

    NOTE: This is the ONLY place where alert logic is allowed to trigger.
          No alert should ever fire from the watchtower screen directly.
    """
    try:
        if args.post_click_wait and args.post_click_wait > 0:
            if stop_event.wait(timeout=args.post_click_wait):
                ts_log('[stop] stop requested during post-click wait')
                return False
        else:
            time.sleep(0.2)
    except Exception:
        time.sleep(0.2)

    # optional post-click pattern + confirm
    if args.post_click_pattern:
        try:
            if a.await_samples(args.post_click_pattern, 2):
                ts_log(f"       post-click pattern '{args.post_click_pattern}' detected at {a.loc}")
                if args.click_confirm:
                    if args.click_confirm_pattern:
                        if a.await_samples(args.click_confirm_pattern, 1):
                            a.click()
                            ts_log(f"       clicked confirm pattern '{args.click_confirm_pattern}'")
                    else:
                        a.click()
                        ts_log("       clicked confirm at current loc")
        except Exception as e:
            ts_log("       post-click check error:", e)

    # check dm_busy to determine mine state
    try:
        a.update()

        # debug: save screenshot before dm_busy check
        try:
            stamp = int(time.time() * 1000)
            fname = f"{OCR_DEBUG_DIR}/dm_busy_check_{stamp}_{int(go_loc[0])}_{int(go_loc[1])}.png"
            cv2.imwrite(fname, a.image)
            ts_log(f"       [debug] saved dm_busy check screenshot to {fname}")
        except Exception as e:
            ts_log(f"       [debug] could not save screenshot: {e}")

        # await_samples does not support threshold — use find() with explicit threshold instead
        matched = False
        deadline = time.time() + 2
        while time.time() < deadline:
            a.update()
            result = a.find('mines/dm_busy', threshold=args.dm_busy_threshold, set_loc=True)
            if result is not None:
                matched = True
                break
            time.sleep(0.1)
        ts_log(f"       dm_busy match result: {matched} (threshold={args.dm_busy_threshold})")
        if matched:
            ts_log(f"       dm_busy matched at loc={a.loc}")

        if matched:
            # dm_busy visible = mine is OCCUPIED
            ts_log("       dm_busy detected -> mine OCCUPIED, skipping silently")
            ts_log("[step] Re-opening watchtower for next entry")
            if not stop_event.is_set():
                if not click_watchtower(a, timeout=4):
                    ts_log("[warn] could not re-open watchtower; continuing anyway")
            return False
        else:
            # dm_busy NOT visible = mine is FREE
            ts_log("       dm_busy NOT detected -> mine FREE")
            # step 1: alert + future actions (only allowed trigger point)
            on_free_mine_found(go_loc, args)
            # step 2: re-open watchtower for next entry
            ts_log("[step] Re-opening watchtower for next entry")
            if not stop_event.is_set():
                if not click_watchtower(a, timeout=4):
                    ts_log("[warn] could not re-open watchtower; continuing anyway")
            return True
    except Exception as _e:
        ts_log(f'[warn] error while checking dm_busy after click: {_e}')
        ts_log(f'[warn] traceback: {traceback.format_exc()}')
        if not stop_event.is_set():
            click_watchtower(a, timeout=4)
        return False


def iterate_go_sequence(a, args, mapped, list_items, go_candidates, timeout=3):
    """Process Go candidates sequentially.

    For each candidate: click Go, then check dm_busy to determine mine state.
    dm_busy found     -> OCCUPIED -> re-open watchtower -> next
    dm_busy not found -> FREE     -> alert -> re-open watchtower -> next

    Returns True if at least one free mine was found, False otherwise.
    """
    if stop_event.is_set():
        return False

    # SAFETY: only click Go buttons that are explicitly mapped to a dm_list entry.
    # Never click Go without a confirmed dm_list pair.
    if not mapped:
        ts_log(f"[map] no dm_list->Go pairs found (dm_list={len(list_items)}, go={len(go_candidates)}) — skipping batch")
        return False

    work = [(li, go) for li, go in mapped]

    found_any = False
    for li, go_loc in work:
        if stop_event.is_set():
            ts_log('[stop] stop requested, aborting sequential iteration')
            return False

        ts_log(f"[step] Sequential check Go {go_loc} (list_item={li})")
        check_loc = go_loc

        # optional pre-check (overlay template and/or color)
        occupied = False
        if args.use_overlay_template:
            a.loc = check_loc
            ol = a.find("mines/dm_busy", threshold=args.dm_busy_threshold, set_loc=False)
            overlay_found = ol is not None
            ts_log(f"       overlay_template -> {overlay_found}")
            if overlay_found:
                occupied = True

        if not occupied and args.occupied_color is not None:
            a.loc = check_loc
            roi, mean_col = roi_mean(a, check_loc, dx=args.color_dx, dy=args.color_dy, w=args.color_w, h=args.color_h)
            pct = percent_pixels_close(roi, args.occupied_color, tol=args.color_tol)
            ts_log(f"       color pct_close={pct:.4f} (threshold={args.percent_threshold}) mean_col={mean_col}")
            if pct >= args.percent_threshold:
                occupied = True
            if args.debug or args.dry_run:
                ts = int(time.time() * 1000)
                try:
                    fname = f"{OCR_DEBUG_DIR}/{ts}_{int(check_loc[0])}_{int(check_loc[1])}.png"
                    cv2.imwrite(fname, roi)
                    ts_log(f"       saved debug ROI to {fname}")
                except Exception:
                    pass

        if occupied:
            ts_log("       -> pre-check: occupied, skipping")
            continue

        if args.dry_run:
            ts_log("       -> dry-run: would click Go")
            continue

        if stop_event.is_set():
            ts_log('[stop] stop requested, skipping click')
            continue

        if args.click:
            click_x = int(round(go_loc[0] + args.go_click_dx))
            click_y = int(round(go_loc[1] + args.go_click_dy))
            click_point = (click_x, click_y)
            ts_log(f"       clicking at {click_point} (dx={args.go_click_dx},dy={args.go_click_dy})")
            a.loc = click_point
            a.click()
            ts_log("       clicked")

            if args.debug:
                try:
                    a.update()
                    cx = int(click_point[0]); cy = int(click_point[1])
                    w = 48; h = 32
                    roi = a.cut(-w//2 + (cx - a.loc[0]), -h//2 + (cy - a.loc[1]), w//2 + (cx - a.loc[0]), h//2 + (cy - a.loc[1]), show=False)
                    ts = int(time.time() * 1000)
                    fname = f"{OCR_DEBUG_DIR}/click_{ts}_{cx}_{cy}.png"
                    cv2.imwrite(fname, roi)
                    ts_log(f"       saved click debug ROI to {fname}")
                except Exception:
                    pass

            ok = _post_click_handle(a, args, go_loc)
            if ok:
                found_any = True

            time.sleep(0.1)

    return bool(found_any)


def scroll_to_top(a, args):
    """Scroll the watchtower list back to the top position.

    Scrolls up in steps until scrollbar reaches top (Y <= args.list_top_y)
    or max attempts reached.
    """
    if not HAVE_PYAUTOGUI:
        ts_log("[scroll] pyautogui not available — cannot scroll to top")
        return
    ts_log("[scroll] resetting list to top...")
    pyautogui.moveTo(args.scroll_x, args.scroll_y, duration=0.1)
    for attempt in range(args.scroll_top_max_attempts):
        visible, slider_y = is_scrollbar_visible(a, args)
        if not visible or slider_y <= args.list_top_y:
            y_str = f"{slider_y:.1f}" if visible else "n/a"
            ts_log(f"[scroll] list at top (Y={y_str}, attempt={attempt})")
            return
        for _ in range(4):
            pyautogui.scroll(1)
            time.sleep(0.05)
        time.sleep(0.1)
    ts_log(f"[scroll] scroll_to_top: reached max attempts ({args.scroll_top_max_attempts})")


def mines(a, args):
    """Main mines loop — scans full watchtower list including scrolling.

    Flow:
      1. Open watchtower + switch to Mines tab
      2. Process current visible batch (up to 4 entries):
         - detect dm_list + Go candidates
         - click each Go, check dm_busy, alarm if free
         - watchtower is re-opened after each Go click (list position preserved)
      3. Check if scrollbar (list_detection.png) is visible:
         - NOT visible -> list fits in 4 rows, end iteration
         - VISIBLE + slider Y >= list_end_y -> bottom reached, end iteration
         - VISIBLE + slider Y < list_end_y -> scroll down 8 steps, repeat from 2
    """
    if stop_event.is_set():
        return False

    if not click_watchtower(a, timeout=4):
        ts_log("[step] watchtower not found, skipping iteration")
        return False

    found_any = False
    scroll_iter = 0

    while not stop_event.is_set():
        # --- check scrollbar BEFORE processing (skip if already at bottom) ---
        visible, slider_y = is_scrollbar_visible(a, args)

        # --- process current visible batch ---
        mapped, list_items, go_candidates = detect_list_and_go(a, args, timeout=2)

        if not list_items:
            ts_log("[scroll] no dm_list entries on current view — skipping batch, moving to next")
        elif mapped or go_candidates:
            ok = iterate_go_sequence(a, args, mapped, list_items, go_candidates, timeout=2)
            if ok:
                found_any = True
        else:
            ts_log("[scroll] no Go candidates on current view")

        # --- check if we can scroll further ---
        if not visible:
            ts_log("[scroll] scrollbar not visible — list fits in 4 rows, FULL LIST SCANNED")
            scroll_to_top(a, args)
            break

        ts_log(f"[scroll] scrollbar visible at Y={slider_y:.1f} (end threshold Y>={args.list_end_y})")

        if is_list_end(slider_y, args):
            ts_log(f"[scroll] scrollbar at bottom (Y={slider_y:.1f}) — FULL LIST SCANNED, done")
            scroll_to_top(a, args)
            break

        # --- scroll down to next batch ---
        scroll_iter += 1
        ts_log(f"[scroll] moving to next batch (scroll #{scroll_iter})")
        scroll_list(a, args)

        if scroll_iter >= args.scroll_max_iter:
            ts_log(f"[scroll] reached max scroll iterations ({args.scroll_max_iter}), stopping")
            break

        if scroll_iter >= args.scroll_max_iter:
            ts_log(f"[scroll] reached max scroll iterations ({args.scroll_max_iter}), stopping")
            break

    ts_log(f"[step] iteration complete — {'free mine found' if found_any else 'all occupied or none'}, waiting {args.loop_sleep}s")
    return found_any


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--loop-sleep', type=float, default=45.0, help='seconds to wait between full scan iterations (default: 30)')
    parser.add_argument('--dry-run', action='store_true', dest='dry_run', help='do not click, only log and save ROIs')
    parser.add_argument('--debug', action='store_true', help='save debug ROIs')
    parser.add_argument('--click', action='store_true', help='click the Go button for each mine candidate')
    parser.add_argument('--sound', default=None, help='path to wav file to play on free mine (default: beep)')
    parser.add_argument('--alert-duration', type=float, default=15.0, dest='alert_duration',
        help='seconds to play alert sound when a free mine is confirmed (default: 15)')
    parser.add_argument('--dm-busy-threshold', type=float, default=0.08, dest='dm_busy_threshold',
        help='matching threshold for dm_busy pattern (lower = more strict, default: 0.08)')
    parser.add_argument('--use-overlay-template', action='store_true', dest='use_overlay_template',
        help='use mines/dm_busy template as pre-check before clicking Go')
    parser.add_argument('--occupied-color', default=None, help='occupied marker color as R,G,B (e.g. 254,74,32)')
    parser.add_argument('--color-tol', type=int, default=40, dest='color_tol', help='color distance tolerance')
    parser.add_argument('--percent-threshold', type=float, default=0.02, dest='percent_threshold', help='fraction of pixels close to occupied color to consider occupied')
    parser.add_argument('--color-dx', type=int, default=0, dest='color_dx', help='dx offset for color ROI')
    parser.add_argument('--color-dy', type=int, default=0, dest='color_dy', help='dy offset for color ROI')
    parser.add_argument('--color-w', type=int, default=80, dest='color_w', help='width of color ROI')
    parser.add_argument('--color-h', type=int, default=40, dest='color_h', help='height of color ROI')
    parser.add_argument('--scale', type=float, default=1.0, help='Automator scale')
    parser.add_argument('--post-click-wait', type=float, default=1.0, help='seconds to wait after clicking Go before checking dm_busy')
    parser.add_argument('--post-click-pattern', default=None, help='optional sample name to wait-for after clicking each Go')
    parser.add_argument('--click-confirm', action='store_true', help='if set and --post-click-pattern matches, click the located confirm element')
    parser.add_argument('--click-confirm-pattern', default=None, help='optional sample name to click as confirmation after --post-click-pattern is found')
    parser.add_argument('--go-click-dx', type=int, default=6, help='X offset when clicking Go (px)')
    parser.add_argument('--go-click-dy', type=int, default=2, help='Y offset when clicking Go (px)')
    parser.add_argument('--list-pattern', default='dm_list', help='pattern name in samples/mines for list entries')
    parser.add_argument('--list-y-tol', type=int, default=45, help='max vertical distance (pixels) to match list item -> Go')
    parser.add_argument('--list-min-dx', type=int, default=250, help='minimum X offset (Go.x - list.x) to consider (px)')
    parser.add_argument('--list-max-dx', type=int, default=650, help='maximum X offset (Go.x - list.x) to consider (px)')
    parser.add_argument('--list-estimated-h', type=int, default=40, help='estimated height of list item (px)')
    parser.add_argument('--go-estimated-h', type=int, default=32, help='estimated height of Go button (px)')
    parser.add_argument('--sequential-mode', action='store_true', dest='sequential_mode', help='process Go candidates sequentially (always on when mapped pairs found)')
    parser.add_argument('--scroll-x', type=int, default=1216, dest='scroll_x',
        help='X coordinate for mouse cursor during scroll (default: 1216 — over Go buttons)')
    parser.add_argument('--scroll-y', type=int, default=600, dest='scroll_y',
        help='Y coordinate for mouse cursor during scroll (default: 600 — middle of list)')
    parser.add_argument('--scroll-steps', type=int, default=8, dest='scroll_steps',
        help='number of mouse wheel clicks per scroll step (default: 8 = one full batch of 4 entries)')
    parser.add_argument('--scroll-max-iter', type=int, default=20, dest='scroll_max_iter',
        help='max scroll iterations before giving up (default: 20)')
    parser.add_argument('--list-end-y', type=int, default=770, dest='list_end_y',
        help='Y coordinate threshold: scrollbar at or below this = end of list (default: 770)')
    parser.add_argument('--list-top-y', type=int, default=465, dest='list_top_y',
        help='Y coordinate threshold: scrollbar at or above this = top of list (default: 465)')
    parser.add_argument('--scroll-top-max-attempts', type=int, default=15, dest='scroll_top_max_attempts',
        help='max scroll-up attempts when resetting list to top (default: 15)')
    parser.add_argument('--list-end-threshold', type=float, default=0.08, dest='list_end_threshold',
        help='matching threshold for list_detection pattern (default: 0.08)')
    args = parser.parse_args()

    if args.occupied_color is not None:
        try:
            parts = [int(x) for x in args.occupied_color.split(',')]
            args.occupied_color = tuple(parts)
        except Exception:
            ts_log('Invalid --occupied-color format, expected R,G,B')
            args.occupied_color = None

    a = Automator(scale=args.scale)
    fails = 0
    last_restart = time.time()
    try:
        while True:
            if stop_event.is_set():
                ts_log('[stop] main stop_event set, exiting')
                break

            if fails >= 10 or time.time() > last_restart + 900:
                a.restart_game(True)
                last_restart = time.time()
                fails = 0
            try:
                ok = mines(a, args)
                if ok:
                    fails = 0
                else:
                    fails += 1
            except Exception as e:
                ts_log('Error in mines loop:', e)
                fails += 1

            ts_log(f"[loop] sleeping {args.loop_sleep}s before next iteration")
            if stop_event.wait(timeout=args.loop_sleep):
                ts_log('[stop] stop_event set during sleep, exiting main loop')
                break
    finally:
        ts_log('[exit] main loop terminating')
#!/usr/bin/env python3


from automate import Automator
import time
import argparse
import os
import numpy as np
import cv2
import math
import signal
import threading
import atexit
import traceback
try:
    import pyautogui
    HAVE_PYAUTOGUI = True
except Exception:
    HAVE_PYAUTOGUI = False


try:
    import winsound
    HAVE_WINSOUND = True
except Exception:
    HAVE_WINSOUND = False


OCR_DEBUG_DIR = "ocr_debug/mines"
try:
    os.makedirs(OCR_DEBUG_DIR, exist_ok=True)
except Exception:
    pass


def ts_log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


# Global stop event used for graceful shutdown (Ctrl+C / SIGTERM)
stop_event = threading.Event()


def _signal_handler(signum, frame):
    ts_log(f"[signal] received {signum}, requesting stop")
    stop_event.set()
    def _force_exit():
        try:
            time.sleep(0.2)
        except Exception:
            pass
        try:
            ts_log('[signal] force exiting now')
        except Exception:
            pass
        os._exit(0)
    t = threading.Thread(target=_force_exit, daemon=True)
    t.start()


def _on_exit():
    stop_event.set()
    ts_log("[exit] cleanup requested")


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)
atexit.register(_on_exit)


def rgb_distance(a, b):
    return math.sqrt(sum((float(x) - float(y)) ** 2 for x, y in zip(a, b)))


def roi_mean(a, loc, dx, dy, w, h):
    a.loc = loc
    min_x = -dx - w//2
    max_x = -dx + w//2
    min_y = dy - h//2
    max_y = dy + h//2
    try:
        roi = a.cut(min_x, min_y, max_x, max_y, show=False)
    except Exception:
        return None, None
    if roi is None or roi.size == 0:
        return None, None
    mean_col = tuple(map(float, reversed(np.mean(roi, axis=(0,1)))))
    return roi, mean_col


def percent_pixels_close(roi, target_rgb, tol=40):
    if roi is None or roi.size == 0:
        return 0.0
    arr = roi.reshape((-1,3))[:, ::-1].astype(float)
    tgt = np.array(target_rgb, dtype=float)
    dists = np.sqrt(np.sum((arr - tgt) ** 2, axis=1))
    return float(np.count_nonzero(dists <= tol)) / float(arr.shape[0])


def play_sound(path=None):
    if HAVE_WINSOUND:
        if path:
            try:
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                return
            except Exception:
                pass
        try:
            winsound.Beep(1000, 400)
        except Exception:
            pass
    else:
        ts_log("[notify] (no winsound)\a")


def on_free_mine_found(loc, args):
    """Called when a free (unoccupied) mine is confirmed (dm_busy NOT detected after clicking Go).

    Executes all actions for a free mine:
      1. Play alert sound for --alert-duration seconds
      [future] 2. Display mine coordinates on screen / overlay
      [future] 3. Send in-game notification to clan members
    """
    ts_log(f"[alert] FREE mine confirmed at {loc} — playing alert for {args.alert_duration}s")
    start = time.time()
    while time.time() - start < args.alert_duration:
        if stop_event.is_set():
            ts_log("[alert] stop requested during alert, aborting")
            break
        play_sound(args.sound)
        if stop_event.wait(timeout=1.0):
            break
    ts_log(f"[alert] alert finished for {loc}")

    # [future] display coordinates
    # [future] send clan notification


def click_watchtower(a, timeout=4):
    """Open the Watchtower and switch to the Mines tab.

    Uses both localized tab patterns:
      - mines_selected_PL   -> mines tab already active, continue without click
      - mines_unselected_PL -> mines tab inactive, click to activate

    Returns True on success, False on failure or stop_event set.
    """
    if stop_event.is_set():
        return False
    if not a.await_samples("watchtower", timeout):
        return False
    ts_log("[step] Found watchtower, clicking to open")
    ts_log(f"       loc={a.loc}")
    if stop_event.is_set():
        ts_log('[stop] stop requested before opening, abort')
        return False
    a.click()

    ts_log('[step] Waiting for mines tab selector (localized)')

    if a.await_samples("mines_selected_PL", 2):
        ts_log(f"[step] mines tab already active at {a.loc}")
    elif a.await_samples("mines_unselected_PL", 2):
        ts_log(f"[step] mines tab found inactive at {a.loc}, clicking to activate")
        if stop_event.is_set():
            ts_log('[stop] stop requested before clicking tab, abort')
            return False
        a.click()
        time.sleep(0.1)
    else:
        ts_log('[step] mines tab selector not found')
        return False

    try:
        a.update()
        stamp = int(time.time() * 1000)
        fname = f"{OCR_DEBUG_DIR}/full_screen_{stamp}.png"
        cv2.imwrite(fname, a.image)
        ts_log(f"       saved full screen debug to {fname}")
    except Exception:
        pass

    return True

def detect_list_and_go(a, args, timeout=2):
    """Detect dm_list entries and go_watchtower candidates and map them.

    Returns (mapped_pairs, list_items, go_candidates).
    """
    list_sample = f"mines/{args.list_pattern}"
    list_path = os.path.join(os.path.dirname(__file__), 'samples', 'mines', f"{args.list_pattern}.png")
    list_items = []
    if os.path.exists(list_path):
        ts_log(f"[step] Looking for list entries with pattern {list_sample}")
        if a.await_samples_multi(list_sample, timeout):
            list_items = list(a.multi or [])
            ts_log(f"[step] found {len(list_items)} list entries:")
            for li in list_items:
                bottom_y = li[1] + args.list_estimated_h/2
                ts_log(f"       dm_list center={li} approx_bottom_y={bottom_y}")
        else:
            ts_log('[step] no list entries found')
    else:
        ts_log(f"[warn] list pattern missing: {list_path}")

    ts_log('[step] Searching for all go_watchtower candidates')
    go_candidates = []
    if a.await_samples_multi("go_watchtower", timeout):
        go_candidates = list(a.multi or [])
        ts_log(f"[step] found {len(go_candidates)} Go candidates:")
        for g in go_candidates:
            bottom_y = g[1] + args.go_estimated_h/2
            ts_log(f"       Go center={g} approx_bottom_y={bottom_y}")
    else:
        ts_log('[step] no go_watchtower candidates found')

    mapped = []
    for li in list_items:
        best = None
        best_dy = None
        li_bottom = li[1] + args.list_estimated_h/2
        for g in go_candidates:
            go_bottom = g[1] + args.go_estimated_h/2
            dy = abs(go_bottom - li_bottom)
            dx = g[0] - li[0]
            if dy <= args.list_y_tol and args.list_min_dx <= dx <= args.list_max_dx:
                if best is None or dy < best_dy:
                    best = g
                    best_dy = dy
        if best is not None:
            mapped.append((li, best))
            ts_log(f"[map] dm_list {li} -> Go {best} (dy={best_dy}, dx={best[0]-li[0]})")
        else:
            ts_log(f"[map] dm_list {li} -> no matching Go (y_tol={args.list_y_tol}, dx range [{args.list_min_dx},{args.list_max_dx}])")

    return mapped, list_items, go_candidates


def scroll_list(a, args):
    """Scroll the watchtower list down using pyautogui.scroll().

    pyautogui.scroll() takes negative values to scroll down.
    Cursor is moved to scroll_x, scroll_y before scrolling.
    """
    if not HAVE_PYAUTOGUI:
        ts_log("[scroll] pyautogui not available — cannot scroll")
        return
    try:
        pyautogui.moveTo(args.scroll_x, args.scroll_y, duration=0.1)
        for _ in range(args.scroll_steps):
            pyautogui.scroll(-1)
            time.sleep(0.05)
        time.sleep(0.15)
        ts_log(f"[scroll] scrolled down {args.scroll_steps} steps at ({args.scroll_x},{args.scroll_y})")
    except Exception as e:
        ts_log(f"[scroll] scroll error: {e}")


def is_scrollbar_visible(a, args):
    """Check if the scrollbar (list_detection.png) is visible at all.

    If not visible — list fits entirely in 4 rows, no scrolling needed.
    Returns (visible: bool, slider_y: float or None)
    """
    try:
        a.update()
        result = a.find('list_detection', threshold=args.list_end_threshold, set_loc=True)
        if result is None:
            return False, None
        return True, a.loc[1]
    except Exception as e:
        ts_log(f"[scroll] scrollbar check error: {e}")
        return False, None


def is_list_end(slider_y, args):
    """Return True if the scrollbar has reached the bottom position."""
    return slider_y >= args.list_end_y


def _post_click_handle(a, args, go_loc):
    """Post-click logic: wait, optional confirm pattern, then check dm_busy.

    dm_busy detected  -> mine OCCUPIED -> re-open watchtower -> return False
    dm_busy NOT found -> mine FREE ->
                            1. on_free_mine_found() [alert + future actions]
                            2. re-open watchtower for next entry
                         -> return True

    NOTE: This is the ONLY place where alert logic is allowed to trigger.
          No alert should ever fire from the watchtower screen directly.
    """
    try:
        if args.post_click_wait and args.post_click_wait > 0:
            if stop_event.wait(timeout=args.post_click_wait):
                ts_log('[stop] stop requested during post-click wait')
                return False
        else:
            time.sleep(0.2)
    except Exception:
        time.sleep(0.2)

    # optional post-click pattern + confirm
    if args.post_click_pattern:
        try:
            if a.await_samples(args.post_click_pattern, 2):
                ts_log(f"       post-click pattern '{args.post_click_pattern}' detected at {a.loc}")
                if args.click_confirm:
                    if args.click_confirm_pattern:
                        if a.await_samples(args.click_confirm_pattern, 1):
                            a.click()
                            ts_log(f"       clicked confirm pattern '{args.click_confirm_pattern}'")
                    else:
                        a.click()
                        ts_log("       clicked confirm at current loc")
        except Exception as e:
            ts_log("       post-click check error:", e)

    # check dm_busy to determine mine state
    try:
        a.update()

        # debug: save screenshot before dm_busy check
        try:
            stamp = int(time.time() * 1000)
            fname = f"{OCR_DEBUG_DIR}/dm_busy_check_{stamp}_{int(go_loc[0])}_{int(go_loc[1])}.png"
            cv2.imwrite(fname, a.image)
            ts_log(f"       [debug] saved dm_busy check screenshot to {fname}")
        except Exception as e:
            ts_log(f"       [debug] could not save screenshot: {e}")

        # await_samples does not support threshold — use find() with explicit threshold instead
        matched = False
        deadline = time.time() + 2
        while time.time() < deadline:
            a.update()
            result = a.find('mines/dm_busy', threshold=args.dm_busy_threshold, set_loc=True)
            if result is not None:
                matched = True
                break
            time.sleep(0.1)
        ts_log(f"       dm_busy match result: {matched} (threshold={args.dm_busy_threshold})")
        if matched:
            ts_log(f"       dm_busy matched at loc={a.loc}")

        if matched:
            # dm_busy visible = mine is OCCUPIED
            ts_log("       dm_busy detected -> mine OCCUPIED, skipping silently")
            ts_log("[step] Re-opening watchtower for next entry")
            if not stop_event.is_set():
                if not click_watchtower(a, timeout=4):
                    ts_log("[warn] could not re-open watchtower; continuing anyway")
            return False
        else:
            # dm_busy NOT visible = mine is FREE
            ts_log("       dm_busy NOT detected -> mine FREE")
            # step 1: alert + future actions (only allowed trigger point)
            on_free_mine_found(go_loc, args)
            # step 2: re-open watchtower for next entry
            ts_log("[step] Re-opening watchtower for next entry")
            if not stop_event.is_set():
                if not click_watchtower(a, timeout=4):
                    ts_log("[warn] could not re-open watchtower; continuing anyway")
            return True
    except Exception as _e:
        ts_log(f'[warn] error while checking dm_busy after click: {_e}')
        ts_log(f'[warn] traceback: {traceback.format_exc()}')
        if not stop_event.is_set():
            click_watchtower(a, timeout=4)
        return False


def iterate_go_sequence(a, args, mapped, list_items, go_candidates, timeout=3):
    """Process Go candidates sequentially.

    For each candidate: click Go, then check dm_busy to determine mine state.
    dm_busy found     -> OCCUPIED -> re-open watchtower -> next
    dm_busy not found -> FREE     -> alert -> re-open watchtower -> next

    Returns True if at least one free mine was found, False otherwise.
    """
    if stop_event.is_set():
        return False

    # SAFETY: only click Go buttons that are explicitly mapped to a dm_list entry.
    # Never click Go without a confirmed dm_list pair.
    if not mapped:
        ts_log(f"[map] no dm_list->Go pairs found (dm_list={len(list_items)}, go={len(go_candidates)}) — skipping batch")
        return False

    work = [(li, go) for li, go in mapped]

    found_any = False
    for li, go_loc in work:
        if stop_event.is_set():
            ts_log('[stop] stop requested, aborting sequential iteration')
            return False

        ts_log(f"[step] Sequential check Go {go_loc} (list_item={li})")
        check_loc = go_loc

        # optional pre-check (overlay template and/or color)
        occupied = False
        if args.use_overlay_template:
            a.loc = check_loc
            ol = a.find("mines/dm_busy", threshold=args.dm_busy_threshold, set_loc=False)
            overlay_found = ol is not None
            ts_log(f"       overlay_template -> {overlay_found}")
            if overlay_found:
                occupied = True

        if not occupied and args.occupied_color is not None:
            a.loc = check_loc
            roi, mean_col = roi_mean(a, check_loc, dx=args.color_dx, dy=args.color_dy, w=args.color_w, h=args.color_h)
            pct = percent_pixels_close(roi, args.occupied_color, tol=args.color_tol)
            ts_log(f"       color pct_close={pct:.4f} (threshold={args.percent_threshold}) mean_col={mean_col}")
            if pct >= args.percent_threshold:
                occupied = True
            if args.debug or args.dry_run:
                ts = int(time.time() * 1000)
                try:
                    fname = f"{OCR_DEBUG_DIR}/{ts}_{int(check_loc[0])}_{int(check_loc[1])}.png"
                    cv2.imwrite(fname, roi)
                    ts_log(f"       saved debug ROI to {fname}")
                except Exception:
                    pass

        if occupied:
            ts_log("       -> pre-check: occupied, skipping")
            continue

        if args.dry_run:
            ts_log("       -> dry-run: would click Go")
            continue

        if stop_event.is_set():
            ts_log('[stop] stop requested, skipping click')
            continue

        if args.click:
            click_x = int(round(go_loc[0] + args.go_click_dx))
            click_y = int(round(go_loc[1] + args.go_click_dy))
            click_point = (click_x, click_y)
            ts_log(f"       clicking at {click_point} (dx={args.go_click_dx},dy={args.go_click_dy})")
            a.loc = click_point
            a.click()
            ts_log("       clicked")

            if args.debug:
                try:
                    a.update()
                    cx = int(click_point[0]); cy = int(click_point[1])
                    w = 48; h = 32
                    roi = a.cut(-w//2 + (cx - a.loc[0]), -h//2 + (cy - a.loc[1]), w//2 + (cx - a.loc[0]), h//2 + (cy - a.loc[1]), show=False)
                    ts = int(time.time() * 1000)
                    fname = f"{OCR_DEBUG_DIR}/click_{ts}_{cx}_{cy}.png"
                    cv2.imwrite(fname, roi)
                    ts_log(f"       saved click debug ROI to {fname}")
                except Exception:
                    pass

            ok = _post_click_handle(a, args, go_loc)
            if ok:
                found_any = True

            time.sleep(0.1)

    return bool(found_any)


def scroll_to_top(a, args):
    """Scroll the watchtower list back to the top position.

    Scrolls up in steps until scrollbar reaches top (Y <= args.list_top_y)
    or max attempts reached.
    """
    if not HAVE_PYAUTOGUI:
        ts_log("[scroll] pyautogui not available — cannot scroll to top")
        return
    ts_log("[scroll] resetting list to top...")
    pyautogui.moveTo(args.scroll_x, args.scroll_y, duration=0.1)
    for attempt in range(args.scroll_top_max_attempts):
        visible, slider_y = is_scrollbar_visible(a, args)
        if not visible or slider_y <= args.list_top_y:
            y_str = f"{slider_y:.1f}" if visible else "n/a"
            ts_log(f"[scroll] list at top (Y={y_str}, attempt={attempt})")
            return
        for _ in range(4):
            pyautogui.scroll(1)
            time.sleep(0.05)
        time.sleep(0.1)
    ts_log(f"[scroll] scroll_to_top: reached max attempts ({args.scroll_top_max_attempts})")


def mines(a, args):
    """Main mines loop — scans full watchtower list including scrolling.

    Flow:
      1. Open watchtower + switch to Mines tab
      2. Process current visible batch (up to 4 entries):
         - detect dm_list + Go candidates
         - click each Go, check dm_busy, alarm if free
         - watchtower is re-opened after each Go click (list position preserved)
      3. Check if scrollbar (list_detection.png) is visible:
         - NOT visible -> list fits in 4 rows, end iteration
         - VISIBLE + slider Y >= list_end_y -> bottom reached, end iteration
         - VISIBLE + slider Y < list_end_y -> scroll down 8 steps, repeat from 2
    """
    if stop_event.is_set():
        return False

    if not click_watchtower(a, timeout=4):
        ts_log("[step] watchtower not found, skipping iteration")
        return False

    found_any = False
    scroll_iter = 0

    while not stop_event.is_set():
        # --- check scrollbar BEFORE processing (skip if already at bottom) ---
        visible, slider_y = is_scrollbar_visible(a, args)

        # --- process current visible batch ---
        mapped, list_items, go_candidates = detect_list_and_go(a, args, timeout=2)

        if not list_items:
            ts_log("[scroll] no dm_list entries on current view — skipping batch, moving to next")
        elif mapped or go_candidates:
            ok = iterate_go_sequence(a, args, mapped, list_items, go_candidates, timeout=2)
            if ok:
                found_any = True
        else:
            ts_log("[scroll] no Go candidates on current view")

        # --- check if we can scroll further ---
        if not visible:
            ts_log("[scroll] scrollbar not visible — list fits in 4 rows, FULL LIST SCANNED")
            scroll_to_top(a, args)
            break

        ts_log(f"[scroll] scrollbar visible at Y={slider_y:.1f} (end threshold Y>={args.list_end_y})")

        if is_list_end(slider_y, args):
            ts_log(f"[scroll] scrollbar at bottom (Y={slider_y:.1f}) — FULL LIST SCANNED, done")
            scroll_to_top(a, args)
            break

        # --- scroll down to next batch ---
        scroll_iter += 1
        ts_log(f"[scroll] moving to next batch (scroll #{scroll_iter})")
        scroll_list(a, args)

        if scroll_iter >= args.scroll_max_iter:
            ts_log(f"[scroll] reached max scroll iterations ({args.scroll_max_iter}), stopping")
            break

        if scroll_iter >= args.scroll_max_iter:
            ts_log(f"[scroll] reached max scroll iterations ({args.scroll_max_iter}), stopping")
            break

    ts_log(f"[step] iteration complete — {'free mine found' if found_any else 'all occupied or none'}, waiting {args.loop_sleep}s")
    return found_any


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--loop-sleep', type=float, default=45.0, help='seconds to wait between full scan iterations (default: 30)')
    parser.add_argument('--dry-run', action='store_true', dest='dry_run', help='do not click, only log and save ROIs')
    parser.add_argument('--debug', action='store_true', help='save debug ROIs')
    parser.add_argument('--click', action='store_true', help='click the Go button for each mine candidate')
    parser.add_argument('--sound', default=None, help='path to wav file to play on free mine (default: beep)')
    parser.add_argument('--alert-duration', type=float, default=15.0, dest='alert_duration',
        help='seconds to play alert sound when a free mine is confirmed (default: 15)')
    parser.add_argument('--dm-busy-threshold', type=float, default=0.08, dest='dm_busy_threshold',
        help='matching threshold for dm_busy pattern (lower = more strict, default: 0.08)')
    parser.add_argument('--use-overlay-template', action='store_true', dest='use_overlay_template',
        help='use mines/dm_busy template as pre-check before clicking Go')
    parser.add_argument('--occupied-color', default=None, help='occupied marker color as R,G,B (e.g. 254,74,32)')
    parser.add_argument('--color-tol', type=int, default=40, dest='color_tol', help='color distance tolerance')
    parser.add_argument('--percent-threshold', type=float, default=0.02, dest='percent_threshold', help='fraction of pixels close to occupied color to consider occupied')
    parser.add_argument('--color-dx', type=int, default=0, dest='color_dx', help='dx offset for color ROI')
    parser.add_argument('--color-dy', type=int, default=0, dest='color_dy', help='dy offset for color ROI')
    parser.add_argument('--color-w', type=int, default=80, dest='color_w', help='width of color ROI')
    parser.add_argument('--color-h', type=int, default=40, dest='color_h', help='height of color ROI')
    parser.add_argument('--scale', type=float, default=1.0, help='Automator scale')
    parser.add_argument('--post-click-wait', type=float, default=1.0, help='seconds to wait after clicking Go before checking dm_busy')
    parser.add_argument('--post-click-pattern', default=None, help='optional sample name to wait-for after clicking each Go')
    parser.add_argument('--click-confirm', action='store_true', help='if set and --post-click-pattern matches, click the located confirm element')
    parser.add_argument('--click-confirm-pattern', default=None, help='optional sample name to click as confirmation after --post-click-pattern is found')
    parser.add_argument('--go-click-dx', type=int, default=6, help='X offset when clicking Go (px)')
    parser.add_argument('--go-click-dy', type=int, default=2, help='Y offset when clicking Go (px)')
    parser.add_argument('--list-pattern', default='dm_list', help='pattern name in samples/mines for list entries')
    parser.add_argument('--list-y-tol', type=int, default=45, help='max vertical distance (pixels) to match list item -> Go')
    parser.add_argument('--list-min-dx', type=int, default=250, help='minimum X offset (Go.x - list.x) to consider (px)')
    parser.add_argument('--list-max-dx', type=int, default=650, help='maximum X offset (Go.x - list.x) to consider (px)')
    parser.add_argument('--list-estimated-h', type=int, default=40, help='estimated height of list item (px)')
    parser.add_argument('--go-estimated-h', type=int, default=32, help='estimated height of Go button (px)')
    parser.add_argument('--sequential-mode', action='store_true', dest='sequential_mode', help='process Go candidates sequentially (always on when mapped pairs found)')
    parser.add_argument('--scroll-x', type=int, default=1216, dest='scroll_x',
        help='X coordinate for mouse cursor during scroll (default: 1216 — over Go buttons)')
    parser.add_argument('--scroll-y', type=int, default=600, dest='scroll_y',
        help='Y coordinate for mouse cursor during scroll (default: 600 — middle of list)')
    parser.add_argument('--scroll-steps', type=int, default=8, dest='scroll_steps',
        help='number of mouse wheel clicks per scroll step (default: 8 = one full batch of 4 entries)')
    parser.add_argument('--scroll-max-iter', type=int, default=20, dest='scroll_max_iter',
        help='max scroll iterations before giving up (default: 20)')
    parser.add_argument('--list-end-y', type=int, default=770, dest='list_end_y',
        help='Y coordinate threshold: scrollbar at or below this = end of list (default: 770)')
    parser.add_argument('--list-top-y', type=int, default=465, dest='list_top_y',
        help='Y coordinate threshold: scrollbar at or above this = top of list (default: 465)')
    parser.add_argument('--scroll-top-max-attempts', type=int, default=15, dest='scroll_top_max_attempts',
        help='max scroll-up attempts when resetting list to top (default: 15)')
    parser.add_argument('--list-end-threshold', type=float, default=0.08, dest='list_end_threshold',
        help='matching threshold for list_detection pattern (default: 0.08)')
    args = parser.parse_args()

    if args.occupied_color is not None:
        try:
            parts = [int(x) for x in args.occupied_color.split(',')]
            args.occupied_color = tuple(parts)
        except Exception:
            ts_log('Invalid --occupied-color format, expected R,G,B')
            args.occupied_color = None

    a = Automator(scale=args.scale)
    fails = 0
    last_restart = time.time()
    try:
        while True:
            if stop_event.is_set():
                ts_log('[stop] main stop_event set, exiting')
                break

            if fails >= 10 or time.time() > last_restart + 900:
                a.restart_game(True)
                last_restart = time.time()
                fails = 0
            try:
                ok = mines(a, args)
                if ok:
                    fails = 0
                else:
                    fails += 1
            except Exception as e:
                ts_log('Error in mines loop:', e)
                fails += 1

            ts_log(f"[loop] sleeping {args.loop_sleep}s before next iteration")
            if stop_event.wait(timeout=args.loop_sleep):
                ts_log('[stop] stop_event set during sleep, exiting main loop')
                break
    finally:
        ts_log('[exit] main loop terminating')

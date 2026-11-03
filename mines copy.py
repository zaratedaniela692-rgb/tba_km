#!/usr/bin/env python3


from automate import Automator
import time
import argparse
import os
import sys
import re
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


try:
    import pygame
    pygame.mixer.init()
    HAVE_PYGAME = True
except Exception:
    HAVE_PYGAME = False


OCR_DEBUG_DIR = "ocr_debug/mines"
try:
    os.makedirs(OCR_DEBUG_DIR, exist_ok=True)
except Exception:
    pass

# ---------------------------------------------------------------------------
# Supported mine types
# ---------------------------------------------------------------------------
VALID_MINE_TYPES = ['dm', 'ws', 'sm']


def ts_log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


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


def play_sound(path=None, volume=1.0):
    if HAVE_PYGAME and path:
        try:
            snd = pygame.mixer.Sound(path)
            snd.set_volume(max(0.0, min(1.0, volume)))
            snd.play()
            return
        except Exception as e:
            ts_log(f"[sound] pygame error: {e}, falling back to winsound")
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
    ts_log(f"[alert] FREE mine confirmed at {loc} — playing alert for {args.alert_duration}s")
    start = time.time()
    while time.time() - start < args.alert_duration:
        if stop_event.is_set():
            ts_log("[alert] stop requested during alert, aborting")
            break
        play_sound(args.sound, volume=args.alert_volume)
        if stop_event.wait(timeout=1.0):
            break
    ts_log(f"[alert] alert finished for {loc}")



# ---------------------------------------------------------------------------
# OCR helpers — read distance and resources from a record
# All offsets are relative to go_watchtower center.
# go_watchtower template size: 165x46px
# TODO: calibrate resource offsets after first live test
# ---------------------------------------------------------------------------


def read_distance(a, go_loc):
    """
    Reads distance value (e.g. '285km') from record.
    ROI covers only the numeric value — language-independent.
    Offset from go_watchtower center: x=(-16,+84) y=(-61,-33)
    """
    a.loc = (float(go_loc[0]), float(go_loc[1]))
    try:
        raw = a.read(-16, -61, +84, -33)
        match = re.search(r'[\d.,]+\s*km', raw, re.IGNORECASE)
        if match:
            return match.group(0).replace(' ', '')
        digits = re.search(r'[\d.,]+', raw)
        return digits.group(0) if digits else raw.strip()
    except Exception as e:
        ts_log(f"[ocr] odleglosc error: {e}")
        return None



def read_resources(a, go_loc):
    """
    Reads available resources (e.g. '5K', '4.67K', '20K') from record.
    Offset from go_watchtower center: x=(-331,-196) y=(-17,+17)
    NOTE: offsets require calibration after first live test.
    TODO: add per-type decimal correction and M/K handling when needed.
    """
    a.loc = (float(go_loc[0]), float(go_loc[1]))
    try:
        raw = a.read(-331, -17, -196, +17)
        match = re.search(r'[\d.,]+\s*[KkMm]?', raw)
        return match.group(0).replace(' ', '') if match else raw.strip()
    except Exception as e:
        ts_log(f"[ocr] zasoby error: {e}")
        return None



def extract_record_info(a, go_loc):
    """
    Reads all available info from a watchtower mine record.
    Returns dict: {'odleglosc': '285km', 'zasoby': '5K'}
    """
    return {
        'odleglosc': read_distance(a, go_loc),
        'zasoby':    read_resources(a, go_loc),
    }



def click_watchtower(a, timeout=4):
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




def is_public_mine_ocr(a, go_loc, args):
    """
    Sprawdza czy rekord to kopalnia publiczna przez OCR fragmentu
    nad ikoną zasobów. Prywatne mają tam napis (np. 'Wybudował gracz'),
    publiczne mają puste tło — OCR nie zwraca tekstu.
    Punkt odniesienia: go_loc (centrum przycisku Przejdź) — tak samo jak read_resources.
    Fail-safe: jeśli OCR się wysypie, zakłada publiczną (nie pomijamy).
    Offsety kalibruj przez --player-label-debug i obserwację logów + zapisanych ROI.
    """
    a.loc = (float(go_loc[0]), float(go_loc[1]))
    try:
        # zapisz ROI do debugowania gdy --player-label-debug lub --debug
        if getattr(args, 'player_label_debug', False) or getattr(args, 'debug', False):
            try:
                roi = a.cut(
                    args.player_label_x1, args.player_label_y1,
                    args.player_label_x2, args.player_label_y2,
                    show=False
                )
                if roi is not None and roi.size > 0:
                    stamp = int(time.time() * 1000)
                    fname = f"{OCR_DEBUG_DIR}/player_label_{stamp}_{int(go_loc[0])}_{int(go_loc[1])}.png"
                    cv2.imwrite(fname, roi)
                    ts_log(f"[filter] saved player label ROI to {fname}")
            except Exception as e:
                ts_log(f"[filter] could not save ROI: {e}")

        raw = a.read(
            args.player_label_x1,
            args.player_label_y1,
            args.player_label_x2,
            args.player_label_y2
        )
        text = raw.strip()
        # odfiltruj artefakty OCR (pojedyncze litery/cyfry to szum, nie prawdziwy tekst)
        real_text = re.sub(r'[^a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ ]', '', text).strip()
        is_real = len(real_text) >= 3
        ts_log(f"[filter] OCR player label raw='{text}' cleaned='{real_text}' len={len(real_text)} "
               f"loc={go_loc} roi=({args.player_label_x1},{args.player_label_y1},"
               f"{args.player_label_x2},{args.player_label_y2})")
        if is_real:
            ts_log(f"[filter] -> prywatna (tekst: '{real_text}'), pomijam")
            return False
        ts_log(f"[filter] -> publiczna (brak tekstu / tylko szum), bierzemy")
        return True
    except Exception as e:
        ts_log(f"[filter] OCR player label error: {e} -> zakładam publiczna")
        return True


def detect_list_and_go(a, args, timeout=2):
    list_sample = f"mines/{args.list_pattern}"
    list_path = os.path.join(os.path.dirname(__file__), 'samples', 'mines', f"{args.list_pattern}.png")
    list_items = []
    if os.path.exists(list_path):
        ts_log(f"[step] Looking for list entries with pattern {list_sample}")
        _t0 = time.time()
        if a.await_samples_multi(list_sample, timeout):
            ts_log(f"[timing] await ws_list took {time.time()-_t0:.3f}s")
            list_items = list(a.multi or [])
            ts_log(f"[step] found {len(list_items)} list entries:")
            for li in list_items:
                bottom_y = li[1] + args.list_estimated_h/2
                ts_log(f"       {args.list_pattern} center={li} approx_bottom_y={bottom_y}")
        else:
            ts_log(f"[timing] await ws_list took {time.time()-_t0:.3f}s (not found)")
            ts_log('[step] no list entries found')
    else:
        ts_log(f"[warn] list pattern missing: {list_path}")


    ts_log('[step] Searching for all go_watchtower candidates')
    go_candidates = []
    _t1 = time.time()
    if a.await_samples_multi("go_watchtower", timeout):
        ts_log(f"[timing] await go_watchtower took {time.time()-_t1:.3f}s")
        go_candidates = list(a.multi or [])
        ts_log(f"[step] found {len(go_candidates)} Go candidates:")
        for g in go_candidates:
            bottom_y = g[1] + args.go_estimated_h/2
            ts_log(f"       Go center={g} approx_bottom_y={bottom_y}")
    else:
        ts_log(f"[timing] await go_watchtower took {time.time()-_t1:.3f}s (not found)")
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
            ts_log(f"[map] {args.list_pattern} {li} -> Go {best} (dy={best_dy}, dx={best[0]-li[0]})")
        else:
            ts_log(f"[map] {args.list_pattern} {li} -> no matching Go (y_tol={args.list_y_tol}, dx range [{args.list_min_dx},{args.list_max_dx}])")


    # --- filter private mines via OCR player label (relative to go_loc) ---
    if mapped:
        filtered_mapped = []
        for li, go_loc in mapped:
            if is_public_mine_ocr(a, go_loc, args):
                filtered_mapped.append((li, go_loc))
        if len(filtered_mapped) < len(mapped):
            ts_log(f"[filter] {len(mapped) - len(filtered_mapped)} prywatne pominięte, {len(filtered_mapped)} publicznych zostaje")
        mapped = filtered_mapped

    return mapped, list_items, go_candidates



def scroll_list(a, args):
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
    return slider_y >= args.list_end_y



def _post_click_handle(a, args, go_loc):
    try:
        if args.post_click_wait and args.post_click_wait > 0:
            if stop_event.wait(timeout=args.post_click_wait):
                ts_log('[stop] stop requested during post-click wait')
                return False
        else:
            time.sleep(0.2)
    except Exception:
        time.sleep(0.2)


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
            ts_log(f"       post-click check error: {e}")


    try:
        a.update()


        try:
            stamp = int(time.time() * 1000)
            fname = f"{OCR_DEBUG_DIR}/{args.mine_type}_busy_check_{stamp}_{int(go_loc[0])}_{int(go_loc[1])}.png"
            cv2.imwrite(fname, a.image)
            ts_log(f"       [debug] saved {args.mine_type}_busy check screenshot to {fname}")
        except Exception as e:
            ts_log(f"       [debug] could not save screenshot: {e}")


        matched = False
        deadline = time.time() + 2
        while time.time() < deadline:
            a.update()
            result = a.find(args.busy_pattern, threshold=args.dm_busy_threshold, set_loc=True)
            if result is not None:
                matched = True
                break
            time.sleep(0.1)
        ts_log(f"       {args.mine_type}_busy match result: {matched} (threshold={args.dm_busy_threshold})")
        if matched:
            ts_log(f"       {args.mine_type}_busy matched at loc={a.loc}")


        if matched:
            ts_log(f"       {args.mine_type}_busy detected -> mine OCCUPIED, skipping silently")
            ts_log("[step] Re-opening watchtower for next entry")
            if not stop_event.is_set():
                if not click_watchtower(a, timeout=4):
                    ts_log("[warn] could not re-open watchtower; continuing anyway")
            return False
        else:
            ts_log(f"       {args.mine_type}_busy NOT detected -> mine FREE")
            on_free_mine_found(go_loc, args)
            ts_log("[step] Re-opening watchtower for next entry")
            if not stop_event.is_set():
                if not click_watchtower(a, timeout=4):
                    ts_log("[warn] could not re-open watchtower; continuing anyway")
            return True
    except Exception as _e:
        ts_log(f'[warn] error while checking {args.mine_type}_busy after click: {_e}')
        ts_log(f'[warn] traceback: {traceback.format_exc()}')
        if not stop_event.is_set():
            click_watchtower(a, timeout=4)
        return False



def iterate_go_sequence(a, args, mapped, list_items, go_candidates, timeout=3):
    if stop_event.is_set():
        return False


    if not mapped:
        ts_log(f"[map] no {args.list_pattern}->Go pairs found ({args.list_pattern}={len(list_items)}, go={len(go_candidates)}) — skipping batch")
        return False


    found_any = False
    for li, go_loc in mapped:
        if stop_event.is_set():
            ts_log('[stop] stop requested, aborting sequential iteration')
            return False


        # --- read record info before clicking ---
        info = extract_record_info(a, go_loc)
        ts_log(f"[step] Sequential check Go {go_loc} (list_item={li})")
        ts_log(f"       [record] odleglosc={info['odleglosc']} zasoby={info['zasoby']}")


        check_loc = go_loc
        occupied = False


        if args.use_overlay_template:
            a.loc = check_loc
            ol = a.find(args.busy_pattern, threshold=args.dm_busy_threshold, set_loc=False)
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
    if stop_event.is_set():
        return False


    if not click_watchtower(a, timeout=4):
        ts_log("[step] watchtower not found, skipping iteration")
        return False


    found_any = False
    scroll_iter = 0


    while not stop_event.is_set():
        _ts = time.time()
        visible, slider_y = is_scrollbar_visible(a, args)
        ts_log(f"[timing] is_scrollbar_visible took {time.time()-_ts:.3f}s")
        mapped, list_items, go_candidates = detect_list_and_go(a, args, timeout=0.8)


        if not list_items:
            ts_log(f"[scroll] no {args.list_pattern} entries on current view — skipping batch, moving to next")
        elif mapped or go_candidates:
            ok = iterate_go_sequence(a, args, mapped, list_items, go_candidates, timeout=0.8)
            if ok:
                found_any = True
        else:
            ts_log("[scroll] no Go candidates on current view")


        if not visible:
            ts_log("[scroll] scrollbar not visible — list fits in 4 rows, FULL LIST SCANNED")
            scroll_to_top(a, args)
            break


        ts_log(f"[scroll] scrollbar visible at Y={slider_y:.1f} (end threshold Y>={args.list_end_y})")


        if is_list_end(slider_y, args):
            ts_log(f"[scroll] scrollbar at bottom (Y={slider_y:.1f}) — FULL LIST SCANNED, done")
            scroll_to_top(a, args)
            break


        scroll_iter += 1
        ts_log(f"[scroll] moving to next batch (scroll #{scroll_iter})")
        scroll_list(a, args)


        if scroll_iter >= args.scroll_max_iter:
            ts_log(f"[scroll] reached max scroll iterations ({args.scroll_max_iter}), stopping")
            break


    ts_log(f"[step] iteration complete — {'free mine found' if found_any else 'all occupied or none'}, waiting {args.loop_sleep}s")
    return found_any



if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    # --- mine type ---
    parser.add_argument(
        '--type',
        default='dm',
        dest='mine_type',
        choices=VALID_MINE_TYPES,
        help=f"Typ kopalni: {', '.join(VALID_MINE_TYPES)}"
    )

    parser.add_argument('--loop-sleep', type=float, default=30.0)
    parser.add_argument('--dry-run', action='store_true', dest='dry_run')
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--click', action='store_true')
    parser.add_argument('--sound', default=r'C:\Windows\Media\alarm01.wav')
    parser.add_argument('--alert-volume', type=float, default=1.0, dest='alert_volume')
    parser.add_argument('--test-sound', type=float, default=0.0, dest='test_sound')
    parser.add_argument('--alert-duration', type=float, default=15.0, dest='alert_duration')
    parser.add_argument('--dm-busy-threshold', type=float, default=0.08, dest='dm_busy_threshold')
    parser.add_argument('--use-overlay-template', action='store_true', dest='use_overlay_template')
    parser.add_argument('--occupied-color', default=None)
    parser.add_argument('--color-tol', type=int, default=40, dest='color_tol')
    parser.add_argument('--percent-threshold', type=float, default=0.02, dest='percent_threshold')
    parser.add_argument('--color-dx', type=int, default=0, dest='color_dx')
    parser.add_argument('--color-dy', type=int, default=0, dest='color_dy')
    parser.add_argument('--color-w', type=int, default=80, dest='color_w')
    parser.add_argument('--color-h', type=int, default=40, dest='color_h')
    parser.add_argument('--scale', type=float, default=1.0)
    parser.add_argument('--post-click-wait', type=float, default=1.0)
    parser.add_argument('--post-click-pattern', default=None)
    parser.add_argument('--click-confirm', action='store_true')
    parser.add_argument('--click-confirm-pattern', default=None)
    parser.add_argument('--go-click-dx', type=int, default=6)
    parser.add_argument('--go-click-dy', type=int, default=2)
    parser.add_argument('--list-y-tol', type=int, default=45)
    parser.add_argument('--list-min-dx', type=int, default=250)
    parser.add_argument('--list-max-dx', type=int, default=650)
    parser.add_argument('--list-estimated-h', type=int, default=40)
    parser.add_argument('--go-estimated-h', type=int, default=32)
    parser.add_argument('--sequential-mode', action='store_true', dest='sequential_mode')
    parser.add_argument('--scroll-x', type=int, default=1216, dest='scroll_x')
    parser.add_argument('--scroll-y', type=int, default=600, dest='scroll_y')
    parser.add_argument('--scroll-steps', type=int, default=6, dest='scroll_steps')
    parser.add_argument('--scroll-max-iter', type=int, default=20, dest='scroll_max_iter')
    parser.add_argument('--list-end-y', type=int, default=770, dest='list_end_y')
    parser.add_argument('--list-top-y', type=int, default=465, dest='list_top_y')
    parser.add_argument('--scroll-top-max-attempts', type=int, default=15, dest='scroll_top_max_attempts')
    parser.add_argument('--list-end-threshold', type=float, default=0.08, dest='list_end_threshold')
    # --- OCR player label offsets (kalibruj przez --dry-run --debug) ---
    parser.add_argument('--player-label-x1', type=int, default=-340, dest='player_label_x1',
                        help='OCR player label offset x1 od centrum list_item')
    parser.add_argument('--player-label-y1', type=int, default=-34,  dest='player_label_y1',
                        help='OCR player label offset y1 od centrum list_item')
    parser.add_argument('--player-label-x2', type=int, default=-185, dest='player_label_x2',
                        help='OCR player label offset x2 od centrum list_item')
    parser.add_argument('--player-label-y2', type=int, default=-17,  dest='player_label_y2',
                        help='OCR player label offset y2 od centrum list_item')
    parser.add_argument('--player-label-debug', action='store_true', dest='player_label_debug',
                        help='Zapisuje ROI player label do ocr_debug/mines/ dla każdego rekordu')
    parser.add_argument('--once', action='store_true',
                        help='Jednorazowe przejście przez listę, kończy się z kodem 0 (znaleziono) lub 1 (nie znaleziono)')
    args = parser.parse_args()

    # --- derive per-type file patterns from mine_type ---
    args.list_pattern = f"{args.mine_type}_list"
    args.busy_pattern = f"mines/{args.mine_type}_busy"
    ts_log(f"[init] mine_type={args.mine_type}  list_pattern={args.list_pattern}  busy_pattern={args.busy_pattern}")

    if args.occupied_color is not None:
        try:
            parts = [int(x) for x in args.occupied_color.split(',')]
            args.occupied_color = tuple(parts)
        except Exception:
            ts_log('Invalid --occupied-color format, expected R,G,B')
            args.occupied_color = None


    a = Automator(scale=args.scale)


    if args.test_sound > 0:
        ts_log(f"[test-sound] playing for {args.test_sound}s (volume={args.alert_volume})")
        ts_log(f"[test-sound] sound: {args.sound or 'default beep'}")
        start = time.time()
        while time.time() - start < args.test_sound:
            play_sound(args.sound, volume=args.alert_volume)
            if stop_event.wait(timeout=1.0):
                break
        ts_log("[test-sound] done — exiting")
        sys.exit(0)


    fails = 0
    last_restart = time.time()
    try:
        while True:
            if stop_event.is_set():
                ts_log('[stop] main stop_event set, exiting')
                break

            if not args.once:
                if fails >= 10 or time.time() > last_restart + 900:
                    a.restart_game(True)
                    last_restart = time.time()
                    fails = 0
            try:
                ok = mines(a, args)
                if args.once:
                    if ok:
                        ts_log('[once] Znaleziono wolną kopalnię — exit 0')
                        sys.exit(0)
                    else:
                        ts_log('[once] Przeszedłem całą listę, nie znaleziono — exit 1')
                        sys.exit(1)
                if ok:
                    fails = 0
                else:
                    fails += 1
            except Exception as e:
                ts_log(f'Error in mines loop: {e}')
                if args.once:
                    ts_log('[once] Błąd podczas jednorazowego przejścia — exit 2')
                    sys.exit(2)
                fails += 1

            ts_log(f"[loop] sleeping {args.loop_sleep}s before next iteration")
            if stop_event.wait(timeout=args.loop_sleep):
                ts_log('[stop] stop_event set during sleep, exiting main loop')
                break
    finally:
        ts_log('[exit] main loop terminating')

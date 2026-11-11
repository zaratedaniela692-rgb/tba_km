

def test_evidence_capture_saves_only_the_selected_frames(tmp_path):
    import numpy as np

    from speedup_run import EvidenceCapture

    capture = EvidenceCapture(lambda: (np.zeros((4, 4, 3), dtype=np.uint8), (0, 0)), tmp_path, indexes=(0, 2))

    for _ in range(4):
        capture()

    assert capture.saved == ["frame_000.png", "frame_002.png"]
    assert sorted(path.name for path in tmp_path.iterdir()) == capture.saved
    assert capture.latest is not None and capture.errors == []


def test_scan_and_use_confirmation_phrases_are_distinct():
    from speedup_run import SCAN_CONFIRMATION, USE_CONFIRMATION

    assert SCAN_CONFIRMATION == "SCAN SPEEDUP LIST FROM TOP"
    assert USE_CONFIRMATION == "USE OWNED SPEEDUPS FROM TOP"
    assert SCAN_CONFIRMATION != USE_CONFIRMATION

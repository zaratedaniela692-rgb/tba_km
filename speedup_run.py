"""Passive evidence helpers and confirmation constants for Speed Up test scenarios.

This module intentionally has no live CLI. Item-use execution semantics must be
resolved before a standalone runner can be reintroduced.
"""

from pathlib import Path

import cv2

SCAN_CONFIRMATION = "SCAN SPEEDUP LIST FROM TOP"
USE_CONFIRMATION = "USE OWNED SPEEDUPS FROM TOP"
EVIDENCE_CAPTURE_INDEXES = (0, 3, 11, 16)


class EvidenceCapture:
	"""Keep the latest captured frame and save only selected checkpoint frames."""

	def __init__(self, capture_fn, run_dir, indexes=EVIDENCE_CAPTURE_INDEXES):
		self.capture_fn = capture_fn
		self.run_dir = Path(run_dir)
		self.indexes = frozenset(indexes)
		self.latest = None
		self.count = 0
		self.saved = []
		self.errors = []

	def __call__(self):
		captured = self.capture_fn()
		self.latest = captured[0]
		if self.count in self.indexes:
			path = self.run_dir / f"frame_{self.count:03d}.png"
			destination = self.saved if cv2.imwrite(str(path), self.latest) else self.errors
			destination.append(path.name)
		self.count += 1
		return captured

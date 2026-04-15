import sys
import os
import numpy as np
import soundfile as sf

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QFileDialog, QMessageBox, QToolBar, QLabel
)

import pyqtgraph as pg

import pyrubberband as pyrb

def midi_to_note_name(midi_val: float) -> str:
    """Convert MIDI note number to a note name like A4, C#3."""
    note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    m = int(round(midi_val))
    m = max(0, min(127, m))
    name = note_names[m % 12]
    octave = (m // 12) - 1
    return f"{name}{octave}"


class NoteAxisItem(pg.AxisItem):
    """Axis that labels major ticks as musical note names."""

    def tickStrings(self, values, scale, spacing):
        # Only label major-ish ticks to avoid clutter.
        # With tick spacing set to major=12, this typically labels octaves (C notes).
        out = []
        for v in values:
            # Show labels only for integer MIDI values
            if abs(v - round(v)) < 1e-6:
                out.append(midi_to_note_name(v))
            else:
                out.append("")
        return out

# NEW (Milestone 2)
import parselmouth

def to_mono(audio: np.ndarray) -> np.ndarray:
    if audio.ndim == 1:
        return audio.astype(np.float32, copy=False)
    return audio.mean(axis=1).astype(np.float32, copy=False)


def decimate_for_plot(audio: np.ndarray, max_points: int = 200_000) -> tuple[np.ndarray, int]:
    """
    Returns (decimated_audio, step)
    """
    n = audio.shape[0]
    if n <= max_points:
        return audio, 1
    step = int(np.ceil(n / max_points))
    return audio[::step], step


# ---- Milestone 3: Segments and draggable blobs ----

def _round_to_int(x: float) -> int:
    return int(np.round(x))


class PitchSegment:
    def __init__(self, start_t: float, end_t: float, base_midi: float):
        self.start_t = float(start_t)
        self.end_t = float(end_t)
        self.base_midi = float(base_midi)
        self.offset = 0.0  # semitones to apply (set by dragging)

    @property
    def midi(self) -> float:
        return self.base_midi + self.offset

    def duration(self) -> float:
        return self.end_t - self.start_t


 # --- Draggable segment rectangles for blobs ---

class SegmentRect(pg.QtWidgets.QGraphicsRectItem):
    """Draggable rectangle representing a pitch segment."""

    def __init__(self, segment: PitchSegment, parent_window: "MainWindow"):
        super().__init__()
        self.segment = segment
        self.parent_window = parent_window

        self.setAcceptHoverEvents(True)
        # We don't rely on Qt selection for visuals; hover/drag controls the border.

        self._dragging = False
        self._drag_start_scene_pos = None
        self._drag_start_offset = 0.0
        self._hovered = False

        # Visual style
        self._pen_normal = pg.mkPen(255, 255, 255, 140, width=1)
        self._pen_hover = pg.mkPen(255, 255, 255, 220, width=2)
        self._pen_selected = pg.mkPen(255, 255, 255, 255, width=3)
        self._brush = pg.mkBrush(120, 170, 255, 70)

        self.setPen(self._pen_normal)
        self.setBrush(self._brush)

        # Label inside blob (note name + offset)
        self.text = pg.TextItem("", anchor=(0, 0))
        self.text.setZValue(self.zValue() + 1)
        self.parent_window.pitch_vb.addItem(self.text)
        # Let mouse/hover events pass through the text to the rectangle
        self.text.setAcceptHoverEvents(False)
        try:
            self.text.setAcceptedMouseButtons(Qt.NoButton)
        except Exception:
            pass

        self.update_geometry_and_label()

    def hoverEnterEvent(self, ev):
        self._hovered = True
        if not self._dragging:
            self.setPen(self._pen_hover)
        super().hoverEnterEvent(ev)

    def hoverLeaveEvent(self, ev):
        self._hovered = False
        if not self._dragging:
            self.setPen(self._pen_normal)
        super().hoverLeaveEvent(ev)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            mods = ev.modifiers()

            # Cmd-click (mac) or Ctrl-click to split the blob at the click time
            if mods & (Qt.KeyboardModifier.MetaModifier | Qt.KeyboardModifier.ControlModifier):
                view_pt = self.parent_window.pitch_vb.mapSceneToView(ev.scenePos())
                split_t = float(view_pt.x())
                self.parent_window.split_segment(self.segment, split_t)
                # Ensure the click is visible to the user even if split is rejected by edge checks
                self.parent_window._update_status_for_selected_segment(self.segment)
                ev.accept()
                return

            # Normal drag
            self._dragging = True
            self._drag_start_scene_pos = ev.scenePos()
            self._drag_start_offset = float(self.segment.offset)
            self.setPen(self._pen_selected)
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._dragging:
            # Convert scene delta to view delta in the pitch ViewBox
            p0 = self.parent_window.pitch_vb.mapSceneToView(self._drag_start_scene_pos)
            p1 = self.parent_window.pitch_vb.mapSceneToView(ev.scenePos())
            dy = p1.y() - p0.y()

            # Up/down drag = semitone offset (1 unit per MIDI)
            new_offset = self._drag_start_offset + dy

            # Snap to semitone steps (integer). Hold Option for fine control.
            mods = QApplication.keyboardModifiers()
            if mods & Qt.AltModifier:
                snapped = new_offset
            else:
                snapped = float(_round_to_int(new_offset))

            # Clamp to reasonable range
            snapped = float(np.clip(snapped, -24, 24))

            if snapped != self.segment.offset:
                self.segment.offset = snapped
                self.update_geometry_and_label()
                self.parent_window._update_status_for_selected_segment(self.segment)
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._dragging:
            self._dragging = False
            # After dragging, show hover pen only if we're still hovering
            self.setPen(self._pen_hover if self._hovered else self._pen_normal)
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def itemChange(self, change, value):
        return super().itemChange(change, value)

    def update_geometry_and_label(self):
        # Draw a 1-semitone-tall rectangle centered on the segment's current midi value.
        y_center = self.segment.midi
        y0 = y_center - 0.5
        y1 = y_center + 0.5

        x0 = self.segment.start_t
        x1 = self.segment.end_t

        # Ensure Qt updates the item's shape/bounding rect correctly
        self.prepareGeometryChange()
        self.setRect(pg.QtCore.QRectF(x0, y0, x1 - x0, y1 - y0))
        self.update()

        cur_name = midi_to_note_name(self.segment.midi)
        self.text.setText(cur_name)
        # Position label near the left edge of the rect, slightly above center
        self.text.setPos(x0 + 0.01, y_center - 0.35)

    def remove_text(self):
        try:
            self.parent_window.pitch_vb.removeItem(self.text)
        except Exception:
            pass


class MainWindow(QMainWindow):
    def _base_midi_for_time_range(self, start_t: float, end_t: float, fallback: float) -> float:
        """Compute quantized base MIDI for the given time range from the current MIDI curve."""
        if self.midi_times is None or self.midi_curve is None:
            return float(fallback)
        times = self.midi_times
        midi = self.midi_curve
        mask = (times >= start_t) & (times < end_t) & np.isfinite(midi)
        vals = midi[mask]
        if vals.size == 0:
            return float(fallback)
        return float(_round_to_int(np.median(vals)))

    def _redraw_segments(self):
        """Remove and recreate all blob graphics from self.segments."""
        # Remove existing items
        for it in getattr(self, "segment_items", []):
            try:
                self.pitch_vb.removeItem(it)
            except Exception:
                pass
            try:
                it.remove_text()
            except Exception:
                pass
        self.segment_items = []

        # Recreate
        for seg in self.segments:
            rect = SegmentRect(seg, self)
            rect.setZValue(-5)
            # Force a clean visual state (prevents "sticky" hover pen after redraw)
            rect._hovered = False
            rect._dragging = False
            rect.setPen(rect._pen_normal)

            # Nudge Qt to refresh hover state for this new item
            rect.setAcceptHoverEvents(False)
            rect.setAcceptHoverEvents(True)

            self.pitch_vb.addItem(rect)
            self.segment_items.append(rect)

        # After bulk redraw, ensure no stale hover remains
        QApplication.processEvents()

        self.clear_segments_action.setEnabled(len(self.segments) > 0)

    def split_segment(self, seg: PitchSegment, split_t: float):
        """Split a segment into two at split_t (Cmd-click)."""
        if seg not in self.segments:
            return

        # Only split if split_t is safely inside the segment
        min_piece_s = 0.06  # prevent tiny unusable blobs
        if split_t <= seg.start_t + min_piece_s or split_t >= seg.end_t - min_piece_s:
            self.info.setText("Split point too close to edge. Cmd-click nearer the middle of the blob.")
            return

        i = self.segments.index(seg)

        # Keep the exact same pitch at the moment of splitting (no vertical jump)
        # Both new segments inherit the original base + offset.
        s1 = PitchSegment(seg.start_t, split_t, seg.base_midi)
        s2 = PitchSegment(split_t, seg.end_t, seg.base_midi)

        s1.offset = float(seg.offset)
        s2.offset = float(seg.offset)

        # Replace in list
        self.segments[i:i+1] = [s1, s2]

        self._redraw_segments()
        self.info.setText("Segment split. Drag each piece independently. (Cmd-click again to split further.)")

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PitchBlob (MVP) — Waveform + MIDI Pitch Curve")

        self.sr: int | None = None
        self.audio: np.ndarray | None = None  # mono
        self.path: str | None = None

        # Analysis params (tuned for vocals-ish; adjust later if needed)
        self.hop_length = 256

        # Praat pitch range (Hz) for typical vocals
        self.pitch_floor_hz = 65.0     # ~C2
        self.pitch_ceiling_hz = 1046.0 # ~C6

        self.midi_times: np.ndarray | None = None
        self.midi_curve: np.ndarray | None = None
        self.f0_hz: np.ndarray | None = None
        self.voiced_mask: np.ndarray | None = None  # per-frame bool aligned to self.midi_times

        # Segmentation / blobs
        self.segments: list[PitchSegment] = []
        self.segment_items: list["SegmentRect"] = []

        # ---- Plot: waveform + second Y axis for MIDI curve ----
        pg.setConfigOptions(antialias=True)
        self.plot = pg.PlotWidget(axisItems={"right": NoteAxisItem(orientation="right")})
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        self.plot.setLabel("left", "Amplitude")
        self.plot.setLabel("bottom", "Time", units="s")

        # Waveform curve (left axis)
        self.wave_curve = self.plot.plot([], [], pen=pg.mkPen(width=1))

        # Right axis for MIDI pitch
        self.plot.showAxis("right")
        self.plot.getAxis("right").setLabel("Pitch (MIDI)")
        right_axis = self.plot.getAxis("right")
        right_axis.setTickSpacing(major=12, minor=1)  # major = octave, minor = semitone

        # Create a second ViewBox that shares X with the main plot,
        # but has its own Y scale (MIDI).
        self.pitch_vb = pg.ViewBox()
        self.plot.scene().addItem(self.pitch_vb)
        self.plot.getAxis("right").linkToView(self.pitch_vb)
        self.pitch_vb.setXLink(self.plot)

        # Pitch curve drawn into pitch_vb
        self.pitch_curve_item = pg.PlotDataItem([], [], pen=pg.mkPen(width=2))
        self.pitch_vb.addItem(self.pitch_curve_item)

        # Draw horizontal "piano key" lines (1 per semitone) inside the pitch ViewBox
        self.pitch_grid_lines = []
        self.pitch_vb.sigYRangeChanged.connect(self._on_pitch_yrange_changed)

        # Keep ViewBoxes aligned
        self.plot.getViewBox().sigResized.connect(self._update_views)

        # Status label
        self.info = QLabel("Open a WAV file to begin.")
        self.info.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # Layout
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.plot, stretch=1)
        layout.addWidget(self.info, stretch=0)
        self.setCentralWidget(central)

        # Toolbar
        tb = QToolBar("Main")
        self.addToolBar(tb)

        open_action = tb.addAction("Open WAV…")
        open_action.triggered.connect(self.open_wav)

        tb.addSeparator()

        self.compute_pitch_action = tb.addAction("Compute Pitch (MIDI)")
        self.compute_pitch_action.triggered.connect(self.compute_pitch)
        self.compute_pitch_action.setEnabled(False)

        self.toggle_pitch_action = tb.addAction("Show/Hide Pitch")
        self.toggle_pitch_action.triggered.connect(self.toggle_pitch)
        self.toggle_pitch_action.setEnabled(False)

        tb.addSeparator()

        self.zoom_all_action = tb.addAction("Zoom to Fit")
        self.zoom_all_action.triggered.connect(self.zoom_to_fit)
        self.zoom_all_action.setEnabled(False)

        self.pitch_visible = True

        self.segment_action = tb.addAction("Make Segments")
        self.segment_action.triggered.connect(self.make_segments)
        self.segment_action.setEnabled(False)

        self.clear_segments_action = tb.addAction("Clear Segments")
        self.clear_segments_action.triggered.connect(self.clear_segments)
        self.clear_segments_action.setEnabled(False)

        tb.addSeparator()
        self.export_action = tb.addAction("Export WAV…")
        self.export_action.triggered.connect(self.export_wav)
        self.export_action.setEnabled(False)

    def _update_views(self):
        # Keep pitch ViewBox geometry matched to main plot
        self.pitch_vb.setGeometry(self.plot.getViewBox().sceneBoundingRect())
        self.pitch_vb.linkedViewChanged(self.plot.getViewBox(), self.pitch_vb.XAxis)

    def _on_pitch_yrange_changed(self):
        # Called when the pitch ViewBox y-range changes (zoom/pan or setYRange)
        yr = self.pitch_vb.viewRange()[1]
        self._update_pitch_grid(yr[0], yr[1])

    def _update_pitch_grid(self, y_min: float, y_max: float):
        # Remove old lines
        for ln in getattr(self, "pitch_grid_lines", []):
            try:
                self.pitch_vb.removeItem(ln)
            except Exception:
                pass
        self.pitch_grid_lines = []

        # Clamp to valid MIDI range
        lo = max(0, int(np.floor(y_min)))
        hi = min(127, int(np.ceil(y_max)))

        # Avoid drawing too many lines if zoomed way out
        if hi - lo > 200:
            return

        for m in range(lo, hi + 1):
            # Thicker line every octave boundary (C notes)
            is_octave = (m % 12) == 0
            pen = pg.mkPen(200, 200, 200, 80, width=2) if is_octave else pg.mkPen(200, 200, 200, 35, width=1)
            ln = pg.InfiniteLine(pos=m, angle=0, pen=pen)
            ln.setZValue(-10)  # keep behind pitch curve
            self.pitch_vb.addItem(ln)
            self.pitch_grid_lines.append(ln)

    def open_wav(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open audio file",
            "",
            "Audio (*.wav *.aif *.aiff);;All files (*)"
        )
        if not path:
            return

        try:
            audio, sr = sf.read(path, always_2d=False)
        except Exception as e:
            QMessageBox.critical(self, "Could not open audio", str(e))
            return

        mono = to_mono(audio)

        if mono.size == 0 or sr <= 0:
            QMessageBox.critical(self, "Invalid file", "Audio file seems invalid.")
            return

        self.path = path
        self.sr = int(sr)
        self.audio = mono

        # Reset pitch display
        self.midi_times = None
        self.midi_curve = None
        self.f0_hz = None
        self.voiced_mask = None
        self.pitch_curve_item.setData([], [])

        self.clear_segments()

        # Plot waveform (decimated for speed)
        y, step = decimate_for_plot(self.audio)
        x = (np.arange(y.shape[0]) * step) / self.sr
        self.wave_curve.setData(x, y)

        duration = self.audio.shape[0] / self.sr
        self.info.setText(
            f"Loaded: {path.split('/')[-1]}  |  {self.sr} Hz  |  {duration:.2f} s   "
            f"(Ready to compute pitch)"
        )

        self.compute_pitch_action.setEnabled(True)
        self.toggle_pitch_action.setEnabled(True)
        self.zoom_all_action.setEnabled(True)
        self.zoom_to_fit()
        self.segment_action.setEnabled(False)
        self.clear_segments_action.setEnabled(False)
        self.export_action.setEnabled(True)

    def compute_pitch(self):
        if self.audio is None or self.sr is None:
            return

        self.info.setText("Computing pitch with Praat (this may take a moment)…")
        QApplication.processEvents()

        try:
            snd = parselmouth.Sound(self.audio, sampling_frequency=self.sr)

            pitch = snd.to_pitch_ac(
                time_step=self.hop_length / self.sr,  # seconds per frame
                pitch_floor=self.pitch_floor_hz,
                pitch_ceiling=self.pitch_ceiling_hz
            )

            times = pitch.xs()                 # frame times (seconds)
            f0_hz = pitch.selected_array["frequency"]  # 0 for unvoiced

            self.f0_hz = f0_hz.astype(np.float32, copy=False)
            self.voiced_mask = (f0_hz > 0)

            # Convert Hz -> MIDI, keep unvoiced as NaN
            midi = np.full_like(f0_hz, np.nan, dtype=np.float32)
            voiced = f0_hz > 0
            midi[voiced] = 69.0 + 12.0 * np.log2(f0_hz[voiced] / 440.0)

            midi_smooth = self._nan_median_smooth(midi, window=9)

            self.midi_times = times
            self.midi_curve = midi_smooth

            mask = np.isfinite(midi_smooth)
            self.pitch_curve_item.setData(times[mask], midi_smooth[mask])

            if np.any(mask):
                lo = float(np.nanpercentile(midi_smooth, 5)) - 1.5
                hi = float(np.nanpercentile(midi_smooth, 95)) + 1.5

                # Snap view to whole-semitone boundaries so it looks like note "boxes"
                lo_i = np.floor(lo)
                hi_i = np.ceil(hi)
                self.pitch_vb.setYRange(float(lo_i), float(hi_i))

            dur = self.audio.shape[0] / self.sr
            self.info.setText(f"Pitch computed (Praat). | Duration: {dur:.2f} s")
            self.zoom_to_fit()

            self.segment_action.setEnabled(True)

        except Exception as e:
            QMessageBox.critical(self, "Pitch computation failed", str(e))
            self.info.setText("Pitch computation failed. Tell me the error text.")
        
    def _nan_median_smooth(self, arr: np.ndarray, window: int = 9) -> np.ndarray:
        """
        Median smooth that ignores NaNs by operating only on finite values.
        Keeps NaNs as NaNs.
        """
        if window < 3 or window % 2 == 0:
            return arr

        out = arr.copy()
        half = window // 2
        n = len(arr)
        for i in range(n):
            a = max(0, i - half)
            b = min(n, i + half + 1)
            chunk = arr[a:b]
            chunk = chunk[np.isfinite(chunk)]
            if chunk.size:
                out[i] = np.median(chunk)
        return out

    def toggle_pitch(self):
        self.pitch_visible = not self.pitch_visible
        self.pitch_curve_item.setVisible(self.pitch_visible)
        self.plot.getAxis("right").setVisible(self.pitch_visible)
        # Segments live in the pitch view; toggle them too
        for it in getattr(self, "segment_items", []):
            it.setVisible(self.pitch_visible)
            try:
                it.text.setVisible(self.pitch_visible)
            except Exception:
                pass

    def clear_segments(self):
        # Remove graphics items
        for it in getattr(self, "segment_items", []):
            try:
                self.pitch_vb.removeItem(it)
            except Exception:
                pass
            try:
                it.remove_text()
            except Exception:
                pass
        self.segment_items = []
        self.segments = []
        if hasattr(self, "clear_segments_action"):
            self.clear_segments_action.setEnabled(False)

    def _update_status_for_selected_segment(self, seg: PitchSegment):
        base = midi_to_note_name(seg.base_midi)
        cur = midi_to_note_name(seg.midi)
        sign = "+" if seg.offset > 0 else ""
        self.info.setText(
            f"Selected: {base}  →  {cur}   (offset {sign}{int(seg.offset)} st)"
        )

    def make_segments(self):
        """Auto-split the MIDI curve into stable pitch segments and draw blobs."""
        if self.midi_times is None or self.midi_curve is None:
            return

        self.clear_segments()

        times = self.midi_times
        midi = self.midi_curve

        # Basic voiced mask
        voiced = np.isfinite(midi)
        if not np.any(voiced):
            self.info.setText("No voiced pitch detected to segment.")
            return

        # --- Parameters for segmentation (tuned for vocals; tweak later) ---
        min_segment_len_s = 0.08   # 80 ms
        gap_split_s = 0.04         # split if unvoiced gap > 40 ms
        jump_split_st = 0.9        # split if pitch jumps >= ~1 semitone
        stable_window = 3          # frames for local stability checks

        dt = float(np.median(np.diff(times))) if len(times) > 1 else (self.hop_length / self.sr)

        segments: list[PitchSegment] = []

        # Walk through frames and build segments
        start_idx = None
        last_voiced_idx = None
        last_midi = None

        for i in range(len(times)):
            if not voiced[i]:
                # if we were in a segment, consider splitting on a long enough gap
                if start_idx is not None and last_voiced_idx is not None:
                    gap = times[i] - times[last_voiced_idx]
                    if gap >= gap_split_s:
                        seg = self._finalize_segment(times, midi, start_idx, last_voiced_idx)
                        if seg is not None:
                            segments.append(seg)
                        start_idx = None
                        last_voiced_idx = None
                        last_midi = None
                continue

            # voiced frame
            if start_idx is None:
                start_idx = i
                last_voiced_idx = i
                last_midi = midi[i]
                continue

            # Decide whether to split due to a pitch jump
            cur_m = float(midi[i])
            if last_midi is not None:
                if abs(cur_m - float(last_midi)) >= jump_split_st:
                    seg = self._finalize_segment(times, midi, start_idx, last_voiced_idx)
                    if seg is not None:
                        segments.append(seg)
                    start_idx = i

            last_voiced_idx = i
            last_midi = cur_m

        # Close final segment
        if start_idx is not None and last_voiced_idx is not None:
            seg = self._finalize_segment(times, midi, start_idx, last_voiced_idx)
            if seg is not None:
                segments.append(seg)

        # Filter short segments and merge very short adjacent ones if needed
        filtered: list[PitchSegment] = []
        for seg in segments:
            if seg.duration() >= min_segment_len_s:
                filtered.append(seg)

        # If filtering removed everything, fall back to a single coarse segment over voiced region
        if not filtered:
            vi = np.where(voiced)[0]
            seg = self._finalize_segment(times, midi, int(vi[0]), int(vi[-1]))
            if seg is not None:
                filtered = [seg]

        self.segments = filtered

        self._redraw_segments()
        self.info.setText(f"Created {len(self.segments)} segments. Drag blobs up/down to set pitch offsets.")

    def _finalize_segment(self, times: np.ndarray, midi: np.ndarray, i0: int, i1: int) -> PitchSegment | None:
        # Inclusive frame indices i0..i1
        if i1 <= i0:
            return None
        seg_m = midi[i0:i1+1]
        seg_m = seg_m[np.isfinite(seg_m)]
        if seg_m.size == 0:
            return None

        base = float(np.median(seg_m))

        # Expand end time to include one frame step, so rectangles match playback better
        dt = float(np.median(np.diff(times))) if len(times) > 1 else 0.0
        start_t = float(times[i0])
        end_t = float(times[i1] + dt)

        # Quantize base pitch to nearest semitone so boxes center on a note row
        base_q = float(_round_to_int(base))

        return PitchSegment(start_t=start_t, end_t=end_t, base_midi=base_q)

    def zoom_to_fit(self):
        # Auto-range waveform
        self.plot.enableAutoRange(x=True, y=True)

        # Pitch viewbox already linked to X; keep it aligned
        self._update_views()

    def _median_midi_in_range(self, start_t: float, end_t: float) -> float | None:
        """Median detected MIDI in [start_t, end_t), ignoring unvoiced frames."""
        if self.midi_times is None or self.midi_curve is None:
            return None
        times = self.midi_times
        midi = self.midi_curve
        mask = (times >= start_t) & (times < end_t) & np.isfinite(midi)
        vals = midi[mask]
        if vals.size == 0:
            return None
        return float(np.median(vals))

    def _time_to_sample(self, t: float) -> int:
        if self.sr is None or self.audio is None:
            return 0
        return int(np.clip(round(t * self.sr), 0, self.audio.shape[0]))

    def _segment_voiced_envelope(self, start_t: float, end_t: float) -> np.ndarray | None:
        """Return per-sample voiced weight (0..1) for the segment based on voiced frames."""
        if self.audio is None or self.sr is None:
            return None
        if self.midi_times is None or self.voiced_mask is None:
            return None

        s0 = self._time_to_sample(start_t)
        s1 = self._time_to_sample(end_t)
        if s1 <= s0:
            return None

        hop = self.hop_length
        idx = np.arange(s0, s1)
        frame_idx = np.clip(idx // hop, 0, len(self.voiced_mask) - 1)
        w = self.voiced_mask[frame_idx].astype(np.float32)

        # Soften edges a bit (simple moving average)
        if w.size > 8:
            k = 9
            kernel = np.ones(k, dtype=np.float32) / k
            w = np.convolve(w, kernel, mode="same")
        return np.clip(w, 0.0, 1.0)

    def _apply_fades(self, x: np.ndarray, sr: int, fade_ms: float = 25.0) -> np.ndarray:
        """Apply short cosine fades at both ends to avoid clicks."""
        if x.size == 0:
            return x
        fade_n = int(sr * (fade_ms / 1000.0))
        fade_n = max(1, min(fade_n, x.size // 2))
        t = np.linspace(0, np.pi / 2, fade_n, dtype=np.float32)
        fade = np.sin(t) ** 2
        y = x.astype(np.float32, copy=True)
        y[:fade_n] *= fade
        y[-fade_n:] *= fade[::-1]
        return y

    def export_wav(self):
        if self.audio is None or self.sr is None:
            return

        if not self.segments:
            QMessageBox.information(self, "Nothing to export", "No segments found. Click Make Segments and edit blobs first.")
            return

        if self.midi_times is None or self.midi_curve is None:
            QMessageBox.information(self, "Need pitch first", "Compute Pitch (MIDI) before exporting so the app can map blobs to real pitch.")
            return

        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export corrected WAV",
            (os.path.splitext(self.path)[0] + "_corrected.wav") if self.path else "corrected.wav",
            "WAV (*.wav)"
        )
        if not out_path:
            return

        self.info.setText("Rendering corrected audio…")
        QApplication.processEvents()

        y = self.audio.astype(np.float32, copy=True)
        sr = int(self.sr)

        for seg in self.segments:
            # Compute the shift needed to move the segment's *actual* pitch to the blob's target pitch.
            target_midi = float(seg.midi)
            orig_midi = self._median_midi_in_range(seg.start_t, seg.end_t)

            # If we can't estimate original pitch for this region, fall back to offset-based shifting.
            if orig_midi is None:
                n_steps = int(round(seg.offset))
            else:
                n_steps = int(round(target_midi - float(orig_midi)))

            if n_steps == 0:
                continue

            s0 = self._time_to_sample(seg.start_t)
            s1 = self._time_to_sample(seg.end_t)
            if s1 <= s0 + 8:
                continue

            chunk = self.audio[s0:s1].astype(np.float32, copy=False)

            try:
                shifted = pyrb.pitch_shift(chunk, sr, n_steps)
            except Exception as e:
                QMessageBox.critical(self, "Pitch shift failed", f"Rubber Band failed while shifting a segment: {e}")
                self.info.setText("Export failed.")
                return

            if shifted.shape[0] < (s1 - s0):
                pad = (s1 - s0) - shifted.shape[0]
                shifted = np.pad(shifted, (0, pad), mode="constant")
            elif shifted.shape[0] > (s1 - s0):
                shifted = shifted[: (s1 - s0)]

            shifted = self._apply_fades(shifted, sr, fade_ms=25.0)

            w = self._segment_voiced_envelope(seg.start_t, seg.end_t)
            if w is None:
                y[s0:s1] = shifted
            else:
                orig = self.audio[s0:s1].astype(np.float32, copy=False)
                w = 0.15 + 0.85 * w
                y[s0:s1] = (1.0 - w) * orig + w * shifted

        try:
            sf.write(out_path, y, sr, subtype="FLOAT")
        except Exception as e:
            QMessageBox.critical(self, "Write failed", str(e))
            self.info.setText("Export failed.")
            return

        self.info.setText(f"Exported: {os.path.basename(out_path)}")


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.resize(1100, 650)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
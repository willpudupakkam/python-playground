

"""note-guesser.py

Plays a randomly chosen piano key (A0..C8) as a synthesized tone, then waits for you
to press the same key on a MIDI-connected digital piano.

Dependencies:
  pip install numpy sounddevice mido python-rtmidi

Notes:
- Your digital piano must be connected and recognized as a MIDI input device.
- This uses simple synthesis (harmonics + envelope) to make the tone less "sine-like".
"""

from __future__ import annotations

import random
import sys
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

try:
    import mido
except ImportError as e:
    raise SystemExit(
        "Missing dependency 'mido'. Install with: pip install mido python-rtmidi"
    ) from e


# 88-key piano range: A0 (MIDI 21) to C8 (MIDI 108)
PIANO_LOW_MIDI = 21
PIANO_HIGH_MIDI = 108


NOTE_NAMES_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def midi_to_freq(midi_note: int) -> float:
    """Convert MIDI note number to frequency in Hz (A4=440)."""
    return 440.0 * (2.0 ** ((midi_note - 69) / 12.0))


def midi_to_name(midi_note: int) -> str:
    """Convert MIDI note number to a name like C4, F#3."""
    name = NOTE_NAMES_SHARP[midi_note % 12]
    octave = (midi_note // 12) - 1
    return f"{name}{octave}"


def _envelope(n: int, sr: int, attack_s: float = 0.01, decay_s: float = 0.12) -> np.ndarray:
    """Simple attack/decay envelope to reduce clicks and mimic percussive sound."""
    env = np.ones(n, dtype=np.float32)

    attack_n = max(1, int(sr * attack_s))
    decay_n = max(1, int(sr * decay_s))

    # Attack: ramp up from 0 to 1
    a = np.linspace(0.0, 1.0, attack_n, endpoint=True, dtype=np.float32)
    env[:attack_n] = a

    # Decay: exponential-ish down to ~0.2 (then hold)
    d = np.linspace(0.0, 1.0, decay_n, endpoint=True, dtype=np.float32)
    decay_curve = (0.2 + 0.8 * np.exp(-4.0 * d)).astype(np.float32)
    end = min(n, attack_n + decay_n)
    env[attack_n:end] = decay_curve[: end - attack_n]

    return env


def synth_pianoish_tone(freq: float, duration_s: float, sr: int) -> np.ndarray:
    """Generate a slightly more piano-like tone using harmonics + envelope."""
    n = int(sr * duration_s)
    t = np.arange(n, dtype=np.float32) / sr

    # Add a few harmonics (amplitudes roughly decreasing).
    # This isn't a real piano model, but it's more pleasant than a pure sine.
    wave = (
        1.00 * np.sin(2 * np.pi * freq * t)
        + 0.45 * np.sin(2 * np.pi * 2 * freq * t)
        + 0.25 * np.sin(2 * np.pi * 3 * freq * t)
        + 0.12 * np.sin(2 * np.pi * 4 * freq * t)
    ).astype(np.float32)

    env = _envelope(n, sr)
    wave *= env

    # Normalize safely
    peak = float(np.max(np.abs(wave)) + 1e-9)
    wave /= peak

    return wave


def play_midi_note(midi_note: int, duration_s: float = 0.8, sr: int = 44100, volume: float = 0.25) -> None:
    """Synthesize and play a note."""
    freq = midi_to_freq(midi_note)
    wave = synth_pianoish_tone(freq, duration_s, sr)
    sd.play((volume * wave).astype(np.float32), samplerate=sr)
    sd.wait()


@dataclass(frozen=True)
class GuessResult:
    target_midi: int
    played_midi: int

    @property
    def correct(self) -> bool:
        return self.target_midi == self.played_midi


def choose_midi_input() -> str:
    inputs = mido.get_input_names()
    if not inputs:
        raise SystemExit(
            "No MIDI input devices found.\n"
            "- Make sure your digital piano is connected (USB/MIDI).\n"
            "- On Windows/macOS, ensure drivers are installed if required.\n"
            "- Then re-run this script."
        )

    if len(inputs) == 1:
        return inputs[0]

    print("Available MIDI input ports:")
    for i, name in enumerate(inputs):
        print(f"  [{i}] {name}")

    while True:
        choice = input("Choose a port number: ").strip()
        if choice.isdigit() and 0 <= int(choice) < len(inputs):
            return inputs[int(choice)]
        print("Invalid selection. Try again.")


def wait_for_note_on(inport: "mido.ports.BaseInput") -> int:
    """Block until we receive a NOTE_ON with velocity > 0; return MIDI note number."""
    while True:
        msg = inport.receive()  # blocking
        if msg.type == "note_on" and getattr(msg, "velocity", 0) > 0:
            return int(msg.note)


def run_game(rounds: int | None = None) -> None:
    port_name = choose_midi_input()
    print(f"Using MIDI input: {port_name}")

    # Open MIDI input
    with mido.open_input(port_name) as inport:
        round_idx = 0
        while True:
            if rounds is not None and round_idx >= rounds:
                print("Done!")
                return

            target = random.randint(PIANO_LOW_MIDI, PIANO_HIGH_MIDI)
            target_name = midi_to_name(target)

            print("\nListen...")
            play_midi_note(target)
            print("Now play the SAME key on your digital piano...")

            played = wait_for_note_on(inport)
            played_name = midi_to_name(played)

            result = GuessResult(target_midi=target, played_midi=played)

            if result.correct:
                print(f"✅ Correct! You played {played_name}.")
            else:
                print(f"❌ Wrong. You played {played_name}, but the note was {target_name}.")

            round_idx += 1

            # Simple terminal control between rounds
            cmd = input("Press Enter for next round, or type 'q' to quit: ").strip().lower()
            if cmd in {"q", "quit", "exit"}:
                return


if __name__ == "__main__":
    # Optional: pass number of rounds as first arg, e.g. `python note-guesser.py 10`
    arg_rounds = None
    if len(sys.argv) >= 2:
        try:
            arg_rounds = int(sys.argv[1])
        except ValueError:
            raise SystemExit("Usage: python note-guesser.py [num_rounds]")

    run_game(rounds=arg_rounds)
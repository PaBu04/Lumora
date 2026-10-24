"""Key, chords and the sound character of the keys from transcribed notes."""

import numpy as np

from lsg.audio import harmony


def _chord(t: float, d: float, pitches, s: float = 0.8) -> list[list[float]]:
    return [[t, s, d, p] for p in pitches]


def test_key_and_chords_with_degrees():
    beats = np.arange(0, 16.0, 0.5)  # 120 bpm, 8 bars
    downbeats = beats[::4]
    keys, bass = [], []
    for bar, (triad, root) in enumerate([((60, 64, 67), 48), ((65, 69, 72), 53), ((67, 71, 74), 55), ((60, 64, 67), 48)] * 2):
        t = bar * 2.0
        keys += _chord(t, 1.9, triad)
        bass.append([t, 0.9, 1.9, root - 12])
    h = harmony.harmony(np.array(keys), np.array(bass), beats, downbeats, 16.0)
    assert h["key"] == "C Dur" and h["mode"] == "major" and h["confidence"] > 0.3
    names = [c[2] for c in h["chords"]]
    degrees = [c[3] for c in h["chords"]]
    assert names[:4] == ["C", "F", "G", "C"] and degrees[:4] == ["I", "IV", "V", "I"]
    # chords change on the bar lines
    assert [c[0] for c in h["chords"][:4]] == [0.0, 2.0, 4.0, 6.0]
    events = harmony.chord_events(h)
    assert [e[3] for e in events[:3]] == [60, 65, 67]


def test_minor_key():
    beats = np.arange(0, 8.0, 0.5)
    keys = (
        _chord(0, 1.9, (57, 60, 64)) + _chord(2, 1.9, (62, 65, 69)) + _chord(4, 1.9, (64, 68, 71)) + _chord(6, 1.9, (57, 60, 64))
    )
    h = harmony.harmony(np.array(keys), np.array([[0, 0.9, 1.9, 45], [6, 0.9, 1.9, 45]]), beats, beats[::4], 8.0)
    assert h["key"] == "A Moll"
    assert [c[2] for c in h["chords"]][:3] == ["Am", "Dm", "E"] and h["chords"][0][3] == "i"


def test_character_stabs_pads_arpeggios():
    notes = []
    for k in range(4):  # short chord hits
        notes += _chord(k * 0.5, 0.15, (60, 64, 67))
    notes += _chord(3.0, 4.0, (48, 55))  # a held two-note pad
    for k in range(8):  # an even run of single notes going up and down
        notes.append([8.0 + 0.125 * k, 0.7, 0.1, [60, 64, 67, 72, 67, 64, 60, 64][k]])
    ch = harmony.character(np.array(sorted(notes)), beat=0.5)
    assert len(ch["stab"]) == 4 and ch["stab"][0][3] == 67
    assert len(ch["pad"]) == 1 and abs(ch["pad"][0][0] - 3.0) < 0.3 and ch["pad"][0][2] > 3
    assert len(ch["arp"]) == 1 and abs(ch["arp"][0][0] - 8.0) < 0.01

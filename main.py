#!/usr/bin/env python3
"""spin77 — desktop hula-mouse lab wired to Loola33 commit previews."""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import random
import struct
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, List, Optional, Tuple

DEFAULT_ADDRESS_A = "0xc6a1adf4514AF877B3c50EA013207debd86556A0"
DEFAULT_ADDRESS_B = "0xfEC24D86eA08A9B11a1d8561b1077CA824365C0F"
DEFAULT_ADDRESS_C = "0xba427533aCB317C99953F123d9Cf0E8B58babC4c"

CHAIN_ID_DEFAULT = 1


@dataclasses.dataclass
class SpinSample:
    x: float
    y: float
    t_ms: int


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def keccak256(data: bytes) -> bytes:
    try:
        from Crypto.Hash import keccak as _k  # type: ignore
        h = _k.new(digest_bits=256)
        h.update(data)
        return h.digest()
    except Exception:
        return hashlib.sha3_256(data).digest()


def pack_u256_u256_u256_u256(a: int, b: int, c: int, d: int) -> bytes:
    return struct.pack(">QQQQ", a & ((1 << 64) - 1), b & ((1 << 64) - 1), c & ((1 << 64) - 1), d & ((1 << 64) - 1))


class HulaSim:
    def __init__(self, seed: int) -> None:
        self._rng = random.Random(seed)

    def wobble(self, t: float) -> Tuple[float, float]:
        a = 0.18 + 0.04 * self._rng.random()
        b = 0.22 + 0.05 * self._rng.random()
        return (a * math.sin(t * b), a * math.cos(t * (b + 0.07)))


class MouseTrailRecorder:
    def __init__(self) -> None:
        self.samples: List[SpinSample] = []

    def push(self, x: float, y: float) -> None:
        self.samples.append(SpinSample(x=x, y=y, t_ms=int(time.time() * 1000)))

    def digest_path_hash(self) -> bytes:
        buf = bytearray()
        for s in self.samples[-4096:]:
            buf.extend(struct.pack(">ffq", s.x, s.y, s.t_ms))
        return keccak256(bytes(buf))


def solidity_like_commit(
    score: int,
    cursor_steps: int,
    wobble_seed: int,
    path_hash: bytes,
    nonce: bytes,
    epoch: int,
    who: str,
    salt2: bytes,
    salt3: bytes,
) -> bytes:
    who_b = bytes.fromhex(who[2:]) if who.startswith("0x") else bytes.fromhex(who)

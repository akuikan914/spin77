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
    body = abi_encode_packed(score, cursor_steps, wobble_seed, path_hash, nonce, epoch, who_b, salt2, salt3)
    return keccak256(body)


def abi_encode_packed(
    score: int,
    cursor_steps: int,
    wobble_seed: int,
    path_hash: bytes,
    nonce: bytes,
    epoch: int,
    who: bytes,
    salt2: bytes,
    salt3: bytes,
) -> bytes:
    return (
        score.to_bytes(32, "big", signed=False)
        + cursor_steps.to_bytes(32, "big", signed=False)
        + wobble_seed.to_bytes(32, "big", signed=False)
        + path_hash
        + nonce
        + epoch.to_bytes(32, "big", signed=False)
        + who
        + salt2
        + salt3
    )


class Spin77App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("spin77")
        self.geometry("980x640")
        self._rec = MouseTrailRecorder()
        self._sim = HulaSim(seed=int(time.time()) % 1_000_000)
        self._salt2 = bytes.fromhex("5a316b95a6129e2b04020eda5e59a23433833a841910f01589b7189aea020537")
        self._salt3 = bytes.fromhex("c588a684a322fd0927cc3a87e3f1dc892974f28c627f1790412f2ebd30d19b63")
        self._epoch = 1
        self._who = DEFAULT_ADDRESS_A
        self._build()

    def _build(self) -> None:
        top = ttk.Frame(self)
        top.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(top, bg="#0b1020", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Motion>", self._on_move)
        self.canvas.bind("<Button-1>", self._on_click)
        bot = ttk.Frame(self)
        bot.pack(fill=tk.X)
        self.lbl = ttk.Label(bot, text="trace the hoop with your mouse")
        self.lbl.pack(side=tk.LEFT, padx=8, pady=6)
        ttk.Button(bot, text="Preview commit", command=self._preview).pack(side=tk.RIGHT, padx=6, pady=6)
        ttk.Button(bot, text="Copy deploy args", command=self._copy_deploy).pack(side=tk.RIGHT, padx=6, pady=6)
        self._draw_hoop()

    def _draw_hoop(self) -> None:
        self.canvas.delete("hoop")
        w = int(self.canvas.winfo_width() or 900)
        h = int(self.canvas.winfo_height() or 520)
        cx, cy = w // 2, h // 2
        r = int(min(w, h) * 0.28)
        wx, wy = self._sim.wobble(time.time() * 0.8)
        self.canvas.create_oval(cx - r + wx * r, cy - r + wy * r, cx + r + wx * r, cy + r + wy * r, outline="#6ad7ff", width=3, tags="hoop")
        self.after(33, self._draw_hoop)

    def _on_move(self, e: tk.Event) -> None:
        self._rec.push(float(e.x), float(e.y))

    def _on_click(self, e: tk.Event) -> None:
        self._rec.push(float(e.x), float(e.y))

    def _preview(self) -> None:
        path = self._rec.digest_path_hash()
        score = min(999_999, max(1, len(self._rec.samples) * 13))
        steps = min(50_000, max(1, len(self._rec.samples)))
        wobble = int(time.time() * 1000) % 1_000_000_007
        nonce = keccak256(struct.pack(">Q", int(time.time() * 1000)))
        c = solidity_like_commit(score, steps, wobble, path, nonce, self._epoch, self._who, self._salt2, self._salt3)
        self.lbl.config(text="commit 0x" + c.hex())

    def _copy_deploy(self) -> None:
        s = json.dumps([DEFAULT_ADDRESS_A, DEFAULT_ADDRESS_B, DEFAULT_ADDRESS_C], indent=2)
        self.clipboard_clear()
        self.clipboard_append(s)
        self.lbl.config(text="copied constructor tuple")


def cmd_print_deploy_args() -> int:
    print(json.dumps({"constructor": [DEFAULT_ADDRESS_A, DEFAULT_ADDRESS_B, DEFAULT_ADDRESS_C]}, indent=2))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="spin77")
    p.add_argument("--deploy-args", action="store_true", help="print default constructor addresses")
    args = p.parse_args(argv)
    if args.deploy_args:
        return cmd_print_deploy_args()
    app = Spin77App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

def _spin77_noise_1(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 2) + 1 * 1e-6

def _spin77_noise_2(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 3) + 2 * 1e-6

def _spin77_noise_3(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 4) + 3 * 1e-6

def _spin77_noise_4(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 5) + 4 * 1e-6

def _spin77_noise_5(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 6) + 5 * 1e-6

def _spin77_noise_6(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 7) + 6 * 1e-6

def _spin77_noise_7(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 8) + 7 * 1e-6

def _spin77_noise_8(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 9) + 8 * 1e-6

def _spin77_noise_9(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 10) + 9 * 1e-6

def _spin77_noise_10(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 11) + 10 * 1e-6

def _spin77_noise_11(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 12) + 11 * 1e-6

def _spin77_noise_12(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 13) + 12 * 1e-6

def _spin77_noise_13(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 14) + 13 * 1e-6

def _spin77_noise_14(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 15) + 14 * 1e-6

def _spin77_noise_15(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 16) + 15 * 1e-6

def _spin77_noise_16(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 17) + 16 * 1e-6

def _spin77_noise_17(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 1) + 17 * 1e-6

def _spin77_noise_18(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 2) + 18 * 1e-6

def _spin77_noise_19(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 3) + 19 * 1e-6

def _spin77_noise_20(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 4) + 20 * 1e-6

def _spin77_noise_21(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 5) + 21 * 1e-6

def _spin77_noise_22(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 6) + 22 * 1e-6

def _spin77_noise_23(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 7) + 23 * 1e-6

def _spin77_noise_24(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 8) + 24 * 1e-6

def _spin77_noise_25(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 9) + 25 * 1e-6

def _spin77_noise_26(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 10) + 26 * 1e-6

def _spin77_noise_27(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 11) + 27 * 1e-6

def _spin77_noise_28(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 12) + 28 * 1e-6

def _spin77_noise_29(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 13) + 29 * 1e-6

def _spin77_noise_30(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 14) + 30 * 1e-6

def _spin77_noise_31(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 15) + 0 * 1e-6

def _spin77_noise_32(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 16) + 1 * 1e-6

def _spin77_noise_33(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 17) + 2 * 1e-6

def _spin77_noise_34(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 1) + 3 * 1e-6

def _spin77_noise_35(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 2) + 4 * 1e-6

def _spin77_noise_36(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 3) + 5 * 1e-6

def _spin77_noise_37(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 4) + 6 * 1e-6

def _spin77_noise_38(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 5) + 7 * 1e-6

def _spin77_noise_39(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 6) + 8 * 1e-6

def _spin77_noise_40(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 7) + 9 * 1e-6

def _spin77_noise_41(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 8) + 10 * 1e-6

def _spin77_noise_42(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 9) + 11 * 1e-6

def _spin77_noise_43(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 10) + 12 * 1e-6

def _spin77_noise_44(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 11) + 13 * 1e-6

def _spin77_noise_45(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 12) + 14 * 1e-6

def _spin77_noise_46(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 13) + 15 * 1e-6

def _spin77_noise_47(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 14) + 16 * 1e-6

def _spin77_noise_48(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 15) + 17 * 1e-6

def _spin77_noise_49(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 16) + 18 * 1e-6

def _spin77_noise_50(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 17) + 19 * 1e-6

def _spin77_noise_51(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 1) + 20 * 1e-6

def _spin77_noise_52(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 2) + 21 * 1e-6

def _spin77_noise_53(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 3) + 22 * 1e-6

def _spin77_noise_54(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 4) + 23 * 1e-6

def _spin77_noise_55(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 5) + 24 * 1e-6

def _spin77_noise_56(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 6) + 25 * 1e-6

def _spin77_noise_57(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 7) + 26 * 1e-6

def _spin77_noise_58(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 8) + 27 * 1e-6

def _spin77_noise_59(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 9) + 28 * 1e-6

def _spin77_noise_60(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 10) + 29 * 1e-6

def _spin77_noise_61(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 11) + 30 * 1e-6

def _spin77_noise_62(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 12) + 0 * 1e-6

def _spin77_noise_63(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 13) + 1 * 1e-6

def _spin77_noise_64(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 14) + 2 * 1e-6

def _spin77_noise_65(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 15) + 3 * 1e-6

def _spin77_noise_66(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 16) + 4 * 1e-6

def _spin77_noise_67(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 17) + 5 * 1e-6

def _spin77_noise_68(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 1) + 6 * 1e-6

def _spin77_noise_69(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 2) + 7 * 1e-6

def _spin77_noise_70(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 3) + 8 * 1e-6

def _spin77_noise_71(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 4) + 9 * 1e-6

def _spin77_noise_72(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 5) + 10 * 1e-6

def _spin77_noise_73(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 6) + 11 * 1e-6

def _spin77_noise_74(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 7) + 12 * 1e-6

def _spin77_noise_75(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 8) + 13 * 1e-6

def _spin77_noise_76(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 9) + 14 * 1e-6

def _spin77_noise_77(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 10) + 15 * 1e-6

def _spin77_noise_78(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 11) + 16 * 1e-6

def _spin77_noise_79(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 12) + 17 * 1e-6

def _spin77_noise_80(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 13) + 18 * 1e-6

def _spin77_noise_81(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 14) + 19 * 1e-6

def _spin77_noise_82(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 15) + 20 * 1e-6

def _spin77_noise_83(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 16) + 21 * 1e-6

def _spin77_noise_84(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 17) + 22 * 1e-6

def _spin77_noise_85(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 1) + 23 * 1e-6

def _spin77_noise_86(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 2) + 24 * 1e-6

def _spin77_noise_87(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 3) + 25 * 1e-6

def _spin77_noise_88(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 4) + 26 * 1e-6

def _spin77_noise_89(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 5) + 27 * 1e-6

def _spin77_noise_90(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 6) + 28 * 1e-6

def _spin77_noise_91(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 7) + 29 * 1e-6

def _spin77_noise_92(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 8) + 30 * 1e-6

def _spin77_noise_93(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 9) + 0 * 1e-6

def _spin77_noise_94(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 10) + 1 * 1e-6

def _spin77_noise_95(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 11) + 2 * 1e-6

def _spin77_noise_96(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 12) + 3 * 1e-6

def _spin77_noise_97(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 13) + 4 * 1e-6

def _spin77_noise_98(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 14) + 5 * 1e-6

def _spin77_noise_99(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 15) + 6 * 1e-6

def _spin77_noise_100(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 16) + 7 * 1e-6

def _spin77_noise_101(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 17) + 8 * 1e-6

def _spin77_noise_102(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 1) + 9 * 1e-6

def _spin77_noise_103(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 2) + 10 * 1e-6

def _spin77_noise_104(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 3) + 11 * 1e-6

def _spin77_noise_105(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 4) + 12 * 1e-6

def _spin77_noise_106(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 5) + 13 * 1e-6

def _spin77_noise_107(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 6) + 14 * 1e-6

def _spin77_noise_108(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 7) + 15 * 1e-6

def _spin77_noise_109(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 8) + 16 * 1e-6

def _spin77_noise_110(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 9) + 17 * 1e-6

def _spin77_noise_111(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 10) + 18 * 1e-6

def _spin77_noise_112(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 11) + 19 * 1e-6

def _spin77_noise_113(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 12) + 20 * 1e-6

def _spin77_noise_114(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 13) + 21 * 1e-6

def _spin77_noise_115(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 14) + 22 * 1e-6

def _spin77_noise_116(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 15) + 23 * 1e-6

def _spin77_noise_117(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 16) + 24 * 1e-6

def _spin77_noise_118(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 17) + 25 * 1e-6

def _spin77_noise_119(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 1) + 26 * 1e-6

def _spin77_noise_120(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 2) + 27 * 1e-6

def _spin77_noise_121(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 3) + 28 * 1e-6

def _spin77_noise_122(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 4) + 29 * 1e-6

def _spin77_noise_123(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 5) + 30 * 1e-6

def _spin77_noise_124(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 6) + 0 * 1e-6

def _spin77_noise_125(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 7) + 1 * 1e-6

def _spin77_noise_126(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 8) + 2 * 1e-6

def _spin77_noise_127(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 9) + 3 * 1e-6

def _spin77_noise_128(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 10) + 4 * 1e-6

def _spin77_noise_129(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 11) + 5 * 1e-6

def _spin77_noise_130(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 12) + 6 * 1e-6

def _spin77_noise_131(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 13) + 7 * 1e-6

def _spin77_noise_132(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 14) + 8 * 1e-6

def _spin77_noise_133(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 15) + 9 * 1e-6

def _spin77_noise_134(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 16) + 10 * 1e-6

def _spin77_noise_135(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 17) + 11 * 1e-6

def _spin77_noise_136(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 1) + 12 * 1e-6

def _spin77_noise_137(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 2) + 13 * 1e-6

def _spin77_noise_138(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 3) + 14 * 1e-6

def _spin77_noise_139(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 4) + 15 * 1e-6

def _spin77_noise_140(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 5) + 16 * 1e-6

def _spin77_noise_141(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 6) + 17 * 1e-6

def _spin77_noise_142(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 7) + 18 * 1e-6

def _spin77_noise_143(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 8) + 19 * 1e-6

def _spin77_noise_144(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 9) + 20 * 1e-6

def _spin77_noise_145(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 10) + 21 * 1e-6

def _spin77_noise_146(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 11) + 22 * 1e-6

def _spin77_noise_147(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 12) + 23 * 1e-6

def _spin77_noise_148(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 13) + 24 * 1e-6

def _spin77_noise_149(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 14) + 25 * 1e-6

def _spin77_noise_150(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 15) + 26 * 1e-6

def _spin77_noise_151(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 16) + 27 * 1e-6

def _spin77_noise_152(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 17) + 28 * 1e-6

def _spin77_noise_153(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 1) + 29 * 1e-6

def _spin77_noise_154(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 2) + 30 * 1e-6

def _spin77_noise_155(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 3) + 0 * 1e-6

def _spin77_noise_156(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 4) + 1 * 1e-6

def _spin77_noise_157(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 5) + 2 * 1e-6

def _spin77_noise_158(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 6) + 3 * 1e-6

def _spin77_noise_159(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 7) + 4 * 1e-6

def _spin77_noise_160(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 8) + 5 * 1e-6

def _spin77_noise_161(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 9) + 6 * 1e-6

def _spin77_noise_162(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 10) + 7 * 1e-6

def _spin77_noise_163(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 11) + 8 * 1e-6

def _spin77_noise_164(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 12) + 9 * 1e-6

def _spin77_noise_165(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 13) + 10 * 1e-6

def _spin77_noise_166(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 14) + 11 * 1e-6

def _spin77_noise_167(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 15) + 12 * 1e-6

def _spin77_noise_168(u: float, v: float) -> float:

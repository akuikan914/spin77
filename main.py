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
    return math.sin(u * 13) * math.cos(v * 16) + 13 * 1e-6

def _spin77_noise_169(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 17) + 14 * 1e-6

def _spin77_noise_170(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 1) + 15 * 1e-6

def _spin77_noise_171(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 2) + 16 * 1e-6

def _spin77_noise_172(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 3) + 17 * 1e-6

def _spin77_noise_173(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 4) + 18 * 1e-6

def _spin77_noise_174(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 5) + 19 * 1e-6

def _spin77_noise_175(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 6) + 20 * 1e-6

def _spin77_noise_176(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 7) + 21 * 1e-6

def _spin77_noise_177(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 8) + 22 * 1e-6

def _spin77_noise_178(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 9) + 23 * 1e-6

def _spin77_noise_179(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 10) + 24 * 1e-6

def _spin77_noise_180(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 11) + 25 * 1e-6

def _spin77_noise_181(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 12) + 26 * 1e-6

def _spin77_noise_182(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 13) + 27 * 1e-6

def _spin77_noise_183(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 14) + 28 * 1e-6

def _spin77_noise_184(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 15) + 29 * 1e-6

def _spin77_noise_185(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 16) + 30 * 1e-6

def _spin77_noise_186(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 17) + 0 * 1e-6

def _spin77_noise_187(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 1) + 1 * 1e-6

def _spin77_noise_188(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 2) + 2 * 1e-6

def _spin77_noise_189(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 3) + 3 * 1e-6

def _spin77_noise_190(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 4) + 4 * 1e-6

def _spin77_noise_191(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 5) + 5 * 1e-6

def _spin77_noise_192(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 6) + 6 * 1e-6

def _spin77_noise_193(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 7) + 7 * 1e-6

def _spin77_noise_194(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 8) + 8 * 1e-6

def _spin77_noise_195(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 9) + 9 * 1e-6

def _spin77_noise_196(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 10) + 10 * 1e-6

def _spin77_noise_197(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 11) + 11 * 1e-6

def _spin77_noise_198(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 12) + 12 * 1e-6

def _spin77_noise_199(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 13) + 13 * 1e-6

def _spin77_noise_200(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 14) + 14 * 1e-6

def _spin77_noise_201(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 15) + 15 * 1e-6

def _spin77_noise_202(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 16) + 16 * 1e-6

def _spin77_noise_203(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 17) + 17 * 1e-6

def _spin77_noise_204(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 1) + 18 * 1e-6

def _spin77_noise_205(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 2) + 19 * 1e-6

def _spin77_noise_206(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 3) + 20 * 1e-6

def _spin77_noise_207(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 4) + 21 * 1e-6

def _spin77_noise_208(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 5) + 22 * 1e-6

def _spin77_noise_209(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 6) + 23 * 1e-6

def _spin77_noise_210(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 7) + 24 * 1e-6

def _spin77_noise_211(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 8) + 25 * 1e-6

def _spin77_noise_212(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 9) + 26 * 1e-6

def _spin77_noise_213(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 10) + 27 * 1e-6

def _spin77_noise_214(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 11) + 28 * 1e-6

def _spin77_noise_215(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 12) + 29 * 1e-6

def _spin77_noise_216(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 13) + 30 * 1e-6

def _spin77_noise_217(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 14) + 0 * 1e-6

def _spin77_noise_218(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 15) + 1 * 1e-6

def _spin77_noise_219(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 16) + 2 * 1e-6

def _spin77_noise_220(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 17) + 3 * 1e-6

def _spin77_noise_221(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 1) + 4 * 1e-6

def _spin77_noise_222(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 2) + 5 * 1e-6

def _spin77_noise_223(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 3) + 6 * 1e-6

def _spin77_noise_224(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 4) + 7 * 1e-6

def _spin77_noise_225(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 5) + 8 * 1e-6

def _spin77_noise_226(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 6) + 9 * 1e-6

def _spin77_noise_227(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 7) + 10 * 1e-6

def _spin77_noise_228(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 8) + 11 * 1e-6

def _spin77_noise_229(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 9) + 12 * 1e-6

def _spin77_noise_230(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 10) + 13 * 1e-6

def _spin77_noise_231(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 11) + 14 * 1e-6

def _spin77_noise_232(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 12) + 15 * 1e-6

def _spin77_noise_233(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 13) + 16 * 1e-6

def _spin77_noise_234(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 14) + 17 * 1e-6

def _spin77_noise_235(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 15) + 18 * 1e-6

def _spin77_noise_236(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 16) + 19 * 1e-6

def _spin77_noise_237(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 17) + 20 * 1e-6

def _spin77_noise_238(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 1) + 21 * 1e-6

def _spin77_noise_239(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 2) + 22 * 1e-6

def _spin77_noise_240(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 3) + 23 * 1e-6

def _spin77_noise_241(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 4) + 24 * 1e-6

def _spin77_noise_242(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 5) + 25 * 1e-6

def _spin77_noise_243(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 6) + 26 * 1e-6

def _spin77_noise_244(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 7) + 27 * 1e-6

def _spin77_noise_245(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 8) + 28 * 1e-6

def _spin77_noise_246(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 9) + 29 * 1e-6

def _spin77_noise_247(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 10) + 30 * 1e-6

def _spin77_noise_248(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 11) + 0 * 1e-6

def _spin77_noise_249(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 12) + 1 * 1e-6

def _spin77_noise_250(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 13) + 2 * 1e-6

def _spin77_noise_251(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 14) + 3 * 1e-6

def _spin77_noise_252(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 15) + 4 * 1e-6

def _spin77_noise_253(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 16) + 5 * 1e-6

def _spin77_noise_254(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 17) + 6 * 1e-6

def _spin77_noise_255(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 1) + 7 * 1e-6

def _spin77_noise_256(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 2) + 8 * 1e-6

def _spin77_noise_257(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 3) + 9 * 1e-6

def _spin77_noise_258(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 4) + 10 * 1e-6

def _spin77_noise_259(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 5) + 11 * 1e-6

def _spin77_noise_260(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 6) + 12 * 1e-6

def _spin77_noise_261(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 7) + 13 * 1e-6

def _spin77_noise_262(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 8) + 14 * 1e-6

def _spin77_noise_263(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 9) + 15 * 1e-6

def _spin77_noise_264(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 10) + 16 * 1e-6

def _spin77_noise_265(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 11) + 17 * 1e-6

def _spin77_noise_266(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 12) + 18 * 1e-6

def _spin77_noise_267(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 13) + 19 * 1e-6

def _spin77_noise_268(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 14) + 20 * 1e-6

def _spin77_noise_269(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 15) + 21 * 1e-6

def _spin77_noise_270(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 16) + 22 * 1e-6

def _spin77_noise_271(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 17) + 23 * 1e-6

def _spin77_noise_272(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 1) + 24 * 1e-6

def _spin77_noise_273(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 2) + 25 * 1e-6

def _spin77_noise_274(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 3) + 26 * 1e-6

def _spin77_noise_275(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 4) + 27 * 1e-6

def _spin77_noise_276(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 5) + 28 * 1e-6

def _spin77_noise_277(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 6) + 29 * 1e-6

def _spin77_noise_278(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 7) + 30 * 1e-6

def _spin77_noise_279(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 8) + 0 * 1e-6

def _spin77_noise_280(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 9) + 1 * 1e-6

def _spin77_noise_281(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 10) + 2 * 1e-6

def _spin77_noise_282(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 11) + 3 * 1e-6

def _spin77_noise_283(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 12) + 4 * 1e-6

def _spin77_noise_284(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 13) + 5 * 1e-6

def _spin77_noise_285(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 14) + 6 * 1e-6

def _spin77_noise_286(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 15) + 7 * 1e-6

def _spin77_noise_287(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 16) + 8 * 1e-6

def _spin77_noise_288(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 17) + 9 * 1e-6

def _spin77_noise_289(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 1) + 10 * 1e-6

def _spin77_noise_290(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 2) + 11 * 1e-6

def _spin77_noise_291(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 3) + 12 * 1e-6

def _spin77_noise_292(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 4) + 13 * 1e-6

def _spin77_noise_293(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 5) + 14 * 1e-6

def _spin77_noise_294(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 6) + 15 * 1e-6

def _spin77_noise_295(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 7) + 16 * 1e-6

def _spin77_noise_296(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 8) + 17 * 1e-6

def _spin77_noise_297(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 9) + 18 * 1e-6

def _spin77_noise_298(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 10) + 19 * 1e-6

def _spin77_noise_299(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 11) + 20 * 1e-6

def _spin77_noise_300(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 12) + 21 * 1e-6

def _spin77_noise_301(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 13) + 22 * 1e-6

def _spin77_noise_302(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 14) + 23 * 1e-6

def _spin77_noise_303(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 15) + 24 * 1e-6

def _spin77_noise_304(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 16) + 25 * 1e-6

def _spin77_noise_305(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 17) + 26 * 1e-6

def _spin77_noise_306(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 1) + 27 * 1e-6

def _spin77_noise_307(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 2) + 28 * 1e-6

def _spin77_noise_308(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 3) + 29 * 1e-6

def _spin77_noise_309(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 4) + 30 * 1e-6

def _spin77_noise_310(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 5) + 0 * 1e-6

def _spin77_noise_311(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 6) + 1 * 1e-6

def _spin77_noise_312(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 7) + 2 * 1e-6

def _spin77_noise_313(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 8) + 3 * 1e-6

def _spin77_noise_314(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 9) + 4 * 1e-6

def _spin77_noise_315(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 10) + 5 * 1e-6

def _spin77_noise_316(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 11) + 6 * 1e-6

def _spin77_noise_317(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 12) + 7 * 1e-6

def _spin77_noise_318(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 13) + 8 * 1e-6

def _spin77_noise_319(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 14) + 9 * 1e-6

def _spin77_noise_320(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 15) + 10 * 1e-6

def _spin77_noise_321(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 16) + 11 * 1e-6

def _spin77_noise_322(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 17) + 12 * 1e-6

def _spin77_noise_323(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 1) + 13 * 1e-6

def _spin77_noise_324(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 2) + 14 * 1e-6

def _spin77_noise_325(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 3) + 15 * 1e-6

def _spin77_noise_326(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 4) + 16 * 1e-6

def _spin77_noise_327(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 5) + 17 * 1e-6

def _spin77_noise_328(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 6) + 18 * 1e-6

def _spin77_noise_329(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 7) + 19 * 1e-6

def _spin77_noise_330(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 8) + 20 * 1e-6

def _spin77_noise_331(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 9) + 21 * 1e-6

def _spin77_noise_332(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 10) + 22 * 1e-6

def _spin77_noise_333(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 11) + 23 * 1e-6

def _spin77_noise_334(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 12) + 24 * 1e-6

def _spin77_noise_335(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 13) + 25 * 1e-6

def _spin77_noise_336(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 14) + 26 * 1e-6

def _spin77_noise_337(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 15) + 27 * 1e-6

def _spin77_noise_338(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 16) + 28 * 1e-6

def _spin77_noise_339(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 17) + 29 * 1e-6

def _spin77_noise_340(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 1) + 30 * 1e-6

def _spin77_noise_341(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 2) + 0 * 1e-6

def _spin77_noise_342(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 3) + 1 * 1e-6

def _spin77_noise_343(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 4) + 2 * 1e-6

def _spin77_noise_344(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 5) + 3 * 1e-6

def _spin77_noise_345(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 6) + 4 * 1e-6

def _spin77_noise_346(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 7) + 5 * 1e-6

def _spin77_noise_347(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 8) + 6 * 1e-6

def _spin77_noise_348(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 9) + 7 * 1e-6

def _spin77_noise_349(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 10) + 8 * 1e-6

def _spin77_noise_350(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 11) + 9 * 1e-6

def _spin77_noise_351(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 12) + 10 * 1e-6

def _spin77_noise_352(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 13) + 11 * 1e-6

def _spin77_noise_353(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 14) + 12 * 1e-6

def _spin77_noise_354(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 15) + 13 * 1e-6

def _spin77_noise_355(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 16) + 14 * 1e-6

def _spin77_noise_356(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 17) + 15 * 1e-6

def _spin77_noise_357(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 1) + 16 * 1e-6

def _spin77_noise_358(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 2) + 17 * 1e-6

def _spin77_noise_359(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 3) + 18 * 1e-6

def _spin77_noise_360(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 4) + 19 * 1e-6

def _spin77_noise_361(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 5) + 20 * 1e-6

def _spin77_noise_362(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 6) + 21 * 1e-6

def _spin77_noise_363(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 7) + 22 * 1e-6

def _spin77_noise_364(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 8) + 23 * 1e-6

def _spin77_noise_365(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 9) + 24 * 1e-6

def _spin77_noise_366(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 10) + 25 * 1e-6

def _spin77_noise_367(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 11) + 26 * 1e-6

def _spin77_noise_368(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 12) + 27 * 1e-6

def _spin77_noise_369(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 13) + 28 * 1e-6

def _spin77_noise_370(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 14) + 29 * 1e-6

def _spin77_noise_371(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 15) + 30 * 1e-6

def _spin77_noise_372(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 16) + 0 * 1e-6

def _spin77_noise_373(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 17) + 1 * 1e-6

def _spin77_noise_374(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 1) + 2 * 1e-6

def _spin77_noise_375(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 2) + 3 * 1e-6

def _spin77_noise_376(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 3) + 4 * 1e-6

def _spin77_noise_377(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 4) + 5 * 1e-6

def _spin77_noise_378(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 5) + 6 * 1e-6

def _spin77_noise_379(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 6) + 7 * 1e-6

def _spin77_noise_380(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 7) + 8 * 1e-6

def _spin77_noise_381(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 8) + 9 * 1e-6

def _spin77_noise_382(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 9) + 10 * 1e-6

def _spin77_noise_383(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 10) + 11 * 1e-6

def _spin77_noise_384(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 11) + 12 * 1e-6

def _spin77_noise_385(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 12) + 13 * 1e-6

def _spin77_noise_386(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 13) + 14 * 1e-6

def _spin77_noise_387(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 14) + 15 * 1e-6

def _spin77_noise_388(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 15) + 16 * 1e-6

def _spin77_noise_389(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 16) + 17 * 1e-6

def _spin77_noise_390(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 17) + 18 * 1e-6

def _spin77_noise_391(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 1) + 19 * 1e-6

def _spin77_noise_392(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 2) + 20 * 1e-6

def _spin77_noise_393(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 3) + 21 * 1e-6

def _spin77_noise_394(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 4) + 22 * 1e-6

def _spin77_noise_395(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 5) + 23 * 1e-6

def _spin77_noise_396(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 6) + 24 * 1e-6

def _spin77_noise_397(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 7) + 25 * 1e-6

def _spin77_noise_398(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 8) + 26 * 1e-6

def _spin77_noise_399(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 9) + 27 * 1e-6

def _spin77_noise_400(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 10) + 28 * 1e-6

def _spin77_noise_401(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 11) + 29 * 1e-6

def _spin77_noise_402(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 12) + 30 * 1e-6

def _spin77_noise_403(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 13) + 0 * 1e-6

def _spin77_noise_404(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 14) + 1 * 1e-6

def _spin77_noise_405(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 15) + 2 * 1e-6

def _spin77_noise_406(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 16) + 3 * 1e-6

def _spin77_noise_407(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 17) + 4 * 1e-6

def _spin77_noise_408(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 1) + 5 * 1e-6

def _spin77_noise_409(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 2) + 6 * 1e-6

def _spin77_noise_410(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 3) + 7 * 1e-6

def _spin77_noise_411(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 4) + 8 * 1e-6

def _spin77_noise_412(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 5) + 9 * 1e-6

def _spin77_noise_413(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 6) + 10 * 1e-6

def _spin77_noise_414(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 7) + 11 * 1e-6

def _spin77_noise_415(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 8) + 12 * 1e-6

def _spin77_noise_416(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 9) + 13 * 1e-6

def _spin77_noise_417(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 10) + 14 * 1e-6

def _spin77_noise_418(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 11) + 15 * 1e-6

def _spin77_noise_419(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 12) + 16 * 1e-6

def _spin77_noise_420(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 13) + 17 * 1e-6

def _spin77_noise_421(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 14) + 18 * 1e-6

def _spin77_noise_422(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 15) + 19 * 1e-6

def _spin77_noise_423(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 16) + 20 * 1e-6

def _spin77_noise_424(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 17) + 21 * 1e-6

def _spin77_noise_425(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 1) + 22 * 1e-6

def _spin77_noise_426(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 2) + 23 * 1e-6

def _spin77_noise_427(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 3) + 24 * 1e-6

def _spin77_noise_428(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 4) + 25 * 1e-6

def _spin77_noise_429(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 5) + 26 * 1e-6

def _spin77_noise_430(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 6) + 27 * 1e-6

def _spin77_noise_431(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 7) + 28 * 1e-6

def _spin77_noise_432(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 8) + 29 * 1e-6

def _spin77_noise_433(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 9) + 30 * 1e-6

def _spin77_noise_434(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 10) + 0 * 1e-6

def _spin77_noise_435(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 11) + 1 * 1e-6

def _spin77_noise_436(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 12) + 2 * 1e-6

def _spin77_noise_437(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 13) + 3 * 1e-6

def _spin77_noise_438(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 14) + 4 * 1e-6

def _spin77_noise_439(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 15) + 5 * 1e-6

def _spin77_noise_440(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 16) + 6 * 1e-6

def _spin77_noise_441(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 17) + 7 * 1e-6

def _spin77_noise_442(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 1) + 8 * 1e-6

def _spin77_noise_443(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 2) + 9 * 1e-6

def _spin77_noise_444(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 3) + 10 * 1e-6

def _spin77_noise_445(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 4) + 11 * 1e-6

def _spin77_noise_446(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 5) + 12 * 1e-6

def _spin77_noise_447(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 6) + 13 * 1e-6

def _spin77_noise_448(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 7) + 14 * 1e-6

def _spin77_noise_449(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 8) + 15 * 1e-6

def _spin77_noise_450(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 9) + 16 * 1e-6

def _spin77_noise_451(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 10) + 17 * 1e-6

def _spin77_noise_452(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 11) + 18 * 1e-6

def _spin77_noise_453(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 12) + 19 * 1e-6

def _spin77_noise_454(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 13) + 20 * 1e-6

def _spin77_noise_455(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 14) + 21 * 1e-6

def _spin77_noise_456(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 15) + 22 * 1e-6

def _spin77_noise_457(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 16) + 23 * 1e-6

def _spin77_noise_458(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 17) + 24 * 1e-6

def _spin77_noise_459(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 1) + 25 * 1e-6

def _spin77_noise_460(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 2) + 26 * 1e-6

def _spin77_noise_461(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 3) + 27 * 1e-6

def _spin77_noise_462(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 4) + 28 * 1e-6

def _spin77_noise_463(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 5) + 29 * 1e-6

def _spin77_noise_464(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 6) + 30 * 1e-6

def _spin77_noise_465(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 7) + 0 * 1e-6

def _spin77_noise_466(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 8) + 1 * 1e-6

def _spin77_noise_467(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 9) + 2 * 1e-6

def _spin77_noise_468(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 10) + 3 * 1e-6

def _spin77_noise_469(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 11) + 4 * 1e-6

def _spin77_noise_470(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 12) + 5 * 1e-6

def _spin77_noise_471(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 13) + 6 * 1e-6

def _spin77_noise_472(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 14) + 7 * 1e-6

def _spin77_noise_473(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 15) + 8 * 1e-6

def _spin77_noise_474(u: float, v: float) -> float:
    return math.sin(u * 7) * math.cos(v * 16) + 9 * 1e-6

def _spin77_noise_475(u: float, v: float) -> float:
    return math.sin(u * 8) * math.cos(v * 17) + 10 * 1e-6

def _spin77_noise_476(u: float, v: float) -> float:
    return math.sin(u * 9) * math.cos(v * 1) + 11 * 1e-6

def _spin77_noise_477(u: float, v: float) -> float:
    return math.sin(u * 10) * math.cos(v * 2) + 12 * 1e-6

def _spin77_noise_478(u: float, v: float) -> float:
    return math.sin(u * 11) * math.cos(v * 3) + 13 * 1e-6

def _spin77_noise_479(u: float, v: float) -> float:
    return math.sin(u * 12) * math.cos(v * 4) + 14 * 1e-6

def _spin77_noise_480(u: float, v: float) -> float:
    return math.sin(u * 13) * math.cos(v * 5) + 15 * 1e-6

def _spin77_noise_481(u: float, v: float) -> float:
    return math.sin(u * 1) * math.cos(v * 6) + 16 * 1e-6

def _spin77_noise_482(u: float, v: float) -> float:
    return math.sin(u * 2) * math.cos(v * 7) + 17 * 1e-6

def _spin77_noise_483(u: float, v: float) -> float:
    return math.sin(u * 3) * math.cos(v * 8) + 18 * 1e-6

def _spin77_noise_484(u: float, v: float) -> float:
    return math.sin(u * 4) * math.cos(v * 9) + 19 * 1e-6

def _spin77_noise_485(u: float, v: float) -> float:
    return math.sin(u * 5) * math.cos(v * 10) + 20 * 1e-6

def _spin77_noise_486(u: float, v: float) -> float:
    return math.sin(u * 6) * math.cos(v * 11) + 21 * 1e-6

def _spin77_noise_487(u: float, v: float) -> float:

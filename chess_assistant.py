#!/usr/bin/env python3
"""
Chess.com Live Assistant — Brave / Firefox
==========================================
Author : https://github.com/aplatogg
Cara pakai (Brave):
  1. Buka Brave dengan:
       brave.exe --remote-debugging-port=9222
  2. Login Chess.com -> buka game
  3. Jalankan:
       python chess_assistant.py --browser brave [--auto-play]
"""

import asyncio
import argparse
import logging
import math
import os
import queue
import random
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

import chess
import chess.engine
import tkinter as tk
from tkinter import font as tkfont
from playwright.async_api import async_playwright, Page, Browser

__version__ = "1.0.0"

# ─── Config ───────────────────────────────────────────────────────────────────
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("CHESS_ASSISTANT_DATA_DIR", Path.home() / ".chess-assistant")).expanduser()
BRAVE_EXE = os.environ.get(
    "CHESS_ASSISTANT_BRAVE", r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
)
FIREFOX_EXE = os.environ.get("CHESS_ASSISTANT_FIREFOX", r"C:\Program Files\Mozilla Firefox\firefox.exe")
DEFAULT_CDP_PORT = 9222
STOCKFISH_CANDIDATES = [
    APP_DIR / "stockfish.exe",
    APP_DIR / "stockfish" / "stockfish.exe",
    Path("stockfish.exe"),
]

log = logging.getLogger(__name__)


def setup_logging(debug: bool = False) -> None:
    """Configure rotating file and console logging. Called from main(), never on import."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            RotatingFileHandler(
                DATA_DIR / "chess_assistant.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
            ),
            logging.StreamHandler(),
        ],
    )
    log.setLevel(level)
    logging.getLogger("chess.engine").setLevel(logging.CRITICAL)
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


# ─── Opening book ─────────────────────────────────────────────────────────────
_OPENING_TREE = {
    # First moves
    ("e2e4",): "King's Pawn",
    ("d2d4",): "Queen's Pawn",
    ("c2c4",): "English Opening",
    ("g1f3",): "Reti Opening",
    ("b2b3",): "Nimzowitsch-Larsen",
    ("f2f4",): "Bird's Opening",
    ("b2b4",): "Polish Opening",
    # e4 responses
    ("e2e4","e7e5"): "Open Game",
    ("e2e4","c7c5"): "Sicilian Defense",
    ("e2e4","e7e6"): "French Defense",
    ("e2e4","c7c6"): "Caro-Kann Defense",
    ("e2e4","d7d5"): "Scandinavian Defense",
    ("e2e4","g8f6"): "Alekhine Defense",
    ("e2e4","d7d6"): "Pirc Defense",
    ("e2e4","g7g6"): "Modern Defense",
    # Open Game
    ("e2e4","e7e5","g1f3"): "King's Knight",
    ("e2e4","e7e5","f2f4"): "King's Gambit",
    ("e2e4","e7e5","g1f3","g8f6"): "Petrov Defense",
    ("e2e4","e7e5","g1f3","b8c6"): "Three Knights",
    ("e2e4","e7e5","g1f3","b8c6","f1b5"): "Spanish (Ruy Lopez)",
    ("e2e4","e7e5","g1f3","b8c6","f1b5","a7a6"): "Spanish: Morphy",
    ("e2e4","e7e5","g1f3","b8c6","f1b5","a7a6","a1b1"): "Spanish: Main Line",
    ("e2e4","e7e5","g1f3","b8c6","f1c4"): "Italian Game",
    ("e2e4","e7e5","g1f3","b8c6","f1c4","f8c5"): "Giuoco Piano",
    ("e2e4","e7e5","g1f3","b8c6","f1c4","g8f6"): "Two Knights Defense",
    ("e2e4","e7e5","g1f3","b8c6","d2d4"): "Scotch Game",
    # Sicilian
    ("e2e4","c7c5","g1f3"): "Sicilian: Open",
    ("e2e4","c7c5","b1c3"): "Sicilian: Closed",
    ("e2e4","c7c5","g1f3","d7d6"): "Sicilian: Classical",
    ("e2e4","c7c5","g1f3","b8c6"): "Sicilian: Classical",
    ("e2e4","c7c5","g1f3","e7e6"): "Sicilian: Kan",
    ("e2e4","c7c5","g1f3","d7d6","d2d4","c5d4","f3d4","g8f6","b1c3","a7a6"): "Sicilian: Najdorf",
    ("e2e4","c7c5","g1f3","d7d6","d2d4","c5d4","f3d4","g8f6","b1c3","g7g6"): "Sicilian: Dragon",
    ("e2e4","c7c5","g1f3","d7d6","d2d4","c5d4","f3d4","g8f6","b1c3","e7e6"): "Sicilian: Scheveningen",
    # French
    ("e2e4","e7e6","d2d4"): "French Defense",
    ("e2e4","e7e6","d2d4","d7d5","b1c3"): "French: Classical",
    ("e2e4","e7e6","d2d4","d7d5","e4e5"): "French: Advance",
    ("e2e4","e7e6","d2d4","d7d5","e4d5"): "French: Exchange",
    ("e2e4","e7e6","d2d4","d7d5","b1d2"): "French: Tarrasch",
    # Caro-Kann
    ("e2e4","c7c6","d2d4","d7d5"): "Caro-Kann",
    ("e2e4","c7c6","d2d4","d7d5","b1c3"): "Caro-Kann: Classical",
    ("e2e4","c7c6","d2d4","d7d5","e4e5"): "Caro-Kann: Advance",
    ("e2e4","c7c6","d2d4","d7d5","e4d5"): "Caro-Kann: Exchange",
    # d4 systems
    ("d2d4","d7d5","c2c4"): "Queen's Gambit",
    ("d2d4","d7d5","c2c4","d5c4"): "Queen's Gambit Accepted",
    ("d2d4","d7d5","c2c4","e7e6"): "Queen's Gambit Declined",
    ("d2d4","d7d5","c2c4","c7c6"): "Slav Defense",
    ("d2d4","d7d5","c2c4","c7c6","g1f3","g8f6"): "Slav Defense",
    ("d2d4","f7f5"): "Dutch Defense",
    ("d2d4","g8f6","c2c4"): "Indian Defense",
    ("d2d4","g8f6","c2c4","g7g6"): "King's Indian",
    ("d2d4","g8f6","c2c4","g7g6","b1c3","f8g7"): "King's Indian Defense",
    ("d2d4","g8f6","c2c4","e7e6"): "Indian: e6",
    ("d2d4","g8f6","c2c4","e7e6","g1f3"): "Queen's Indian",
    ("d2d4","g8f6","c2c4","e7e6","b1c3","f8b4"): "Nimzo-Indian Defense",
    ("d2d4","g8f6","c2c4","c7c5"): "Benoni Defense",
    ("d2d4","g8f6","c2c4","c7c5","d4d5"): "Modern Benoni",
    # English
    ("c2c4","e7e5"): "English: Reversed Sicilian",
    ("c2c4","c7c5"): "English: Symmetrical",
    ("c2c4","g8f6"): "English: Indian",
    ("c2c4","g8f6","b1c3","d7d5"): "English: Reversed QGD",
}

def get_opening_name(moves: list) -> str:
    """Return deepest opening match for the given UCI move list."""
    for i in range(min(len(moves), 12), 0, -1):
        name = _OPENING_TREE.get(tuple(moves[:i]))
        if name:
            return name
    return ""


# ─── Data models ──────────────────────────────────────────────────────────────
@dataclass
class MoveInfo:
    uci: str; san: str; score: float; mate: Optional[int]; depth: int

@dataclass
class AnalysisResult:
    fen: str; turn: str
    top_moves: list  = field(default_factory=list)
    pv:        list  = field(default_factory=list)
    eval_score: float = 0.0
    mate:       Optional[int] = None
    depth:      int  = 0
    game_over:  bool = False
    result:     str  = ""
    opening:    str  = ""
    time_left:  Optional[float] = None
    win_prob:   float = 50.0


def _score_to_winpct(score: float, mate: Optional[int]) -> float:
    """Convert centipawn score to win probability % (white's perspective)."""
    if mate is not None:
        return 100.0 if mate > 0 else 0.0
    return 1.0 / (1.0 + math.exp(-score * 0.37)) * 100.0


# ─── JavaScript ───────────────────────────────────────────────────────────────
_JS_IS_GAME = r"""
() => {
    if (!/chess\.com\/(play|game|live|daily)\//i.test(location.href)) return false;
    return document.querySelectorAll('.piece').length >= 10;
}
"""

_JS_READ_BOARD = r"""
() => {
    function detectTurn() {
        const nodes = document.querySelectorAll('[data-node-index]');
        if (nodes.length) return nodes.length % 2 === 0 ? 'w' : 'b';
        const brd = document.querySelector('chess-board') || document.querySelector('wc-chess-board');
        const flipped = brd ? (brd.flipped || brd._flipped || brd.hasAttribute('flipped') || false) : false;
        const botRun = document.querySelector('[class*="clock-bottom"][class*="running"]') ||
                       document.querySelector('[class*="player-component-bottom"][class*="countdown"]');
        const topRun = document.querySelector('[class*="clock-top"][class*="running"]') ||
                       document.querySelector('[class*="player-component-top"][class*="countdown"]');
        if (botRun) return flipped ? 'b' : 'w';
        if (topRun) return flipped ? 'w' : 'b';
        if (brd && brd.turn !== undefined) {
            const bt = String(brd.turn || '');
            if (bt) return bt.toLowerCase().startsWith('b') ? 'b' : 'w';
        }
        return null;
    }
    const board = document.querySelector('chess-board') ||
                  document.querySelector('wc-chess-board') ||
                  document.querySelector('[class*="board-layout-chessboard"]');
    const g = board ? (board.game || board._game) : null;
    if (g) {
        const fnFen = g.getFEN || g.fen || g.getFen;
        if (typeof fnFen === 'function') {
            try {
                const raw = fnFen.call(g);
                if (raw && raw.split('/').length === 8) {
                    const parts = raw.split(' ');
                    let turn = (parts[1] === 'w' || parts[1] === 'b') ? parts[1] : null;
                    if (!turn) {
                        const tp = g.getTurn || g.turn;
                        if (typeof tp === 'function') { const r = tp.call(g); if (r) turn = r[0].toLowerCase(); }
                        else if (typeof tp === 'string' && tp) turn = tp[0].toLowerCase();
                    }
                    if (!turn) turn = detectTurn();
                    const fnO = g.isGameOver || g.isOver;
                    const ov = typeof fnO === 'function' ? fnO.call(g) : false;
                    return { fen: parts[0]+' '+(turn||'w')+' - - 0 1', turn, over: ov, src: 'api' };
                }
            } catch(e) {}
        }
    }
    const MAP = {'wp':'P','wr':'R','wn':'N','wb':'B','wq':'Q','wk':'K',
                 'bp':'p','br':'r','bn':'n','bb':'b','bq':'q','bk':'k'};
    const grid = {};
    document.querySelectorAll('.piece').forEach(el => {
        const cls = [...el.classList];
        const type = cls.find(c => /^[wb][prnbqk]$/.test(c));
        const sq   = cls.find(c => /^square-\d\d$/.test(c));
        if (!type || !sq) return;
        grid[(parseInt(sq.slice(-2,-1))-1)+','+(parseInt(sq.slice(-1))-1)] = MAP[type] || '?';
    });
    if (Object.keys(grid).length < 2) return null;
    let fen = '';
    for (let r = 7; r >= 0; r--) {
        let e = 0;
        for (let f = 0; f < 8; f++) {
            const p = grid[f+','+r];
            if (p) { if (e) { fen += e; e = 0; } fen += p; } else { e++; }
        }
        if (e) fen += e;
        if (r > 0) fen += '/';
    }
    const turn = detectTurn() || 'w';
    const over = !!document.querySelector('[class*="GameOver"],[class*="game-over"]');
    return { fen: fen+' '+turn+' - - 0 1', turn, over, src: 'dom' };
}
"""

_JS_GET_COLOR = r"""
() => {
    const b = document.querySelector('chess-board') || document.querySelector('wc-chess-board') ||
              document.querySelector('[class*="board-layout-chessboard"]');
    if (b) {
        if (b.flipped !== undefined) return b.flipped ? 'black' : 'white';
        if (b._flipped !== undefined) return b._flipped ? 'black' : 'white';
        const a = b.getAttribute('board-orientation') || '';
        if (a) return a.toLowerCase().includes('black') ? 'black' : 'white';
    }
    return document.querySelector('[class*="board"][class*="flipped"]') ? 'black' : 'white';
}
"""

_JS_BOARD_FLIP = r"""
() => {
    const b = document.querySelector('chess-board') || document.querySelector('wc-chess-board') ||
              document.querySelector('[class*="board-layout-chessboard"]');
    if (!b) return false;
    return !!(b.flipped || b._flipped || b.hasAttribute('flipped') ||
              (b.getAttribute('board-orientation')||'').toLowerCase().includes('black') ||
              document.querySelector('[class*="board"][class*="flipped"]'));
}
"""

# flip passed as 3rd param so both clicks in a move use the same value
_JS_SQUARE_COORDS = r"""
([file, rank, flip]) => {
    const board = document.querySelector('chess-board') || document.querySelector('wc-chess-board') ||
                  document.querySelector('[class*="board-layout-chessboard"]') ||
                  document.querySelector('[class*="ChessBoard"]') ||
                  document.querySelector('.piece')?.closest('[class*="oard"]');
    if (!board) return null;
    const rect = board.getBoundingClientRect();
    const sqW = rect.width / 8, sqH = rect.height / 8;
    const cx = flip ? rect.left + (8 - file + 0.5) * sqW : rect.left + (file - 0.5) * sqW;
    const cy = flip ? rect.top  + (rank - 0.5) * sqH     : rect.top  + (8 - rank + 0.5) * sqH;
    return { x: Math.round(cx), y: Math.round(cy) };
}
"""

_JS_PROMO_QUEEN = r"""
() => {
    for (const s of ['[data-piece="wQ"]','[data-piece="bQ"]','[class*="promotion"] [class*="queen"]']) {
        const el = document.querySelector(s);
        if (el) { el.click(); return true; }
    }
    return false;
}
"""

# Returns our remaining time in seconds, or null
_JS_GET_TIME = r"""
() => {
    const b = document.querySelector('chess-board') || document.querySelector('wc-chess-board');
    const flipped = !!(b && (b.flipped || b._flipped || b.hasAttribute('flipped')));
    // Our clock is bottom when not flipped, top when flipped
    const side = flipped ? 'top' : 'bottom';
    const sels = [
        `[class*="clock-${side}"] .clock-time-monospace`,
        `[class*="clock-${side}"] [class*="time"]`,
        `[class*="player-${side}"] [class*="time"]`,
        `[class*="clock"][class*="${side}"] [class*="time"]`,
    ];
    for (const sel of sels) {
        const el = document.querySelector(sel);
        if (!el) continue;
        const t = el.textContent.trim().replace(/[^0-9:.]/g,'');
        const parts = t.split(':');
        if (parts.length === 3) return +parts[0]*3600 + +parts[1]*60 + parseFloat(parts[2]);
        if (parts.length === 2) return +parts[0]*60 + parseFloat(parts[1]);
        const s = parseFloat(t);
        if (!isNaN(s) && s >= 0) return s;
    }
    return null;
}
"""

# Returns array of UCI move strings for the game so far
_JS_GET_MOVES = r"""
() => {
    const board = document.querySelector('chess-board') || document.querySelector('wc-chess-board') ||
                  document.querySelector('[class*="board-layout-chessboard"]');
    const g = board ? (board.game || board._game) : null;
    if (!g) return [];
    try {
        for (const fn of ['getHistory','history','getMoveList']) {
            const f = g[fn];
            if (!f) continue;
            let h;
            try { h = typeof f === 'function' ? f.call(g, {verbose:true}) : f; } catch(e) { continue; }
            if (!Array.isArray(h) || !h.length) continue;
            if (h[0] && h[0].from && h[0].to)
                return h.map(m => m.from + m.to + (m.promotion || ''));
        }
    } catch(e) {}
    return [];
}
"""

# Inject silent Web Audio to prevent background-tab throttling
_JS_ANTI_THROTTLE = r"""
() => {
    if (window._chessKeepalive) return 'already';
    try {
        const ac = new (window.AudioContext || window.webkitAudioContext)();
        const buf = ac.createBuffer(1, 1, 22050);
        const src = ac.createBufferSource();
        src.buffer = buf; src.loop = true;
        src.connect(ac.destination);
        src.start(0);
        window._chessKeepalive = src;
        return 'ok';
    } catch(e) { return 'err:' + e.message; }
}
"""


# ─── Board reader ──────────────────────────────────────────────────────────────
class BoardReader:
    def __init__(self, page: Page):
        self._p = page
        self._last_mouse_pos: tuple = (800, 500)   # start near board center

    async def is_game(self) -> bool:
        try:   return bool(await self._p.evaluate(_JS_IS_GAME))
        except Exception: return False

    async def read(self) -> Optional[dict]:
        try:
            d = await self._p.evaluate(_JS_READ_BOARD)
            if not d or len((d.get("fen","")).split("/")) < 8:
                return None
            return d
        except Exception as e:
            log.debug(f"read: {e}")
            return None

    async def color(self) -> str:
        try:   return await self._p.evaluate(_JS_GET_COLOR) or "white"
        except Exception: return "white"

    async def get_time(self) -> Optional[float]:
        try:
            v = await self._p.evaluate(_JS_GET_TIME)
            return float(v) if v is not None else None
        except Exception: return None

    async def get_moves(self) -> list:
        try:
            moves = await self._p.evaluate(_JS_GET_MOVES)
            return moves if isinstance(moves, list) else []
        except Exception: return []

    async def inject_anti_throttle(self):
        try:
            res = await self._p.evaluate(_JS_ANTI_THROTTLE)
            log.info("Anti-throttle: %s", res)
        except Exception as e:
            log.debug("Anti-throttle inject failed: %s", e)

    async def _get_flip(self) -> bool:
        try:   return bool(await self._p.evaluate(_JS_BOARD_FLIP))
        except Exception: return False

    async def _mouse_bezier(self, tx: float, ty: float):
        """Move mouse via quadratic bezier curve to simulate human hand movement."""
        sx, sy = self._last_mouse_pos
        # random control point offset — makes the path arc naturally
        cx = (sx + tx) / 2 + random.uniform(-70, 70)
        cy = (sy + ty) / 2 + random.uniform(-70, 70)
        steps = random.randint(8, 16)
        for i in range(1, steps + 1):
            t = i / steps
            x = (1 - t) ** 2 * sx + 2 * (1 - t) * t * cx + t ** 2 * tx
            y = (1 - t) ** 2 * sy + 2 * (1 - t) * t * cy + t ** 2 * ty
            await self._p.mouse.move(x, y)
            await asyncio.sleep(random.uniform(0.006, 0.018))
        self._last_mouse_pos = (tx, ty)

    async def _click_square(self, file: int, rank: int, flip: bool):
        """CDP mouse click with natural bezier movement — works in background tab."""
        coords = await self._p.evaluate(_JS_SQUARE_COORDS, [file, rank, flip])
        if coords and coords.get('x') and coords.get('y'):
            tx = float(coords['x']) + random.uniform(-4, 4)
            ty = float(coords['y']) + random.uniform(-4, 4)
            await self._mouse_bezier(tx, ty)
            await self._p.mouse.down()
            await asyncio.sleep(random.uniform(0.04, 0.11))   # hold like a human
            await self._p.mouse.up()
            log.debug("mouse click (%.0f,%.0f) file=%d rank=%d flip=%s", tx, ty, file, rank, flip)
        else:
            log.warning("no board coords for file=%d rank=%d — fallback", file, rank)
            await self._p.evaluate(
                "([f,r])=>{"
                "const el=document.querySelector(`.square-${f}${r}`);"
                "if(!el)return;"
                "const r2=el.getBoundingClientRect();"
                "const cx=r2.left+r2.width/2,cy=r2.top+r2.height/2;"
                "for(const t of['pointerdown','mousedown','pointerup','mouseup','click']){"
                "el.dispatchEvent(new PointerEvent(t,{bubbles:true,clientX:cx,clientY:cy,buttons:1}));}}",
                [file, rank]
            )

    async def click_move(self, uci: str, clr: str):
        if len(uci) < 4: return
        fm = {'a':1,'b':2,'c':3,'d':4,'e':5,'f':6,'g':7,'h':8}
        sf, sr = fm.get(uci[0],0), int(uci[1])
        df, dr = fm.get(uci[2],0), int(uci[3])
        if not sf or not df: return
        # Read flip ONCE — both clicks use same value to prevent inconsistency
        flip = await self._get_flip()
        log.debug("click_move %s flip=%s", uci, flip)
        await self._click_square(sf, sr, flip)
        await asyncio.sleep(0.13 + random.uniform(0, 0.08))
        await self._click_square(df, dr, flip)
        if len(uci) == 5 and uci[4] == 'q':
            await asyncio.sleep(0.35)
            await self._p.evaluate(_JS_PROMO_QUEEN)


# ─── Async Stockfish engine ────────────────────────────────────────────────────
class Engine:
    def __init__(self, path: str, multipv: int = 5):
        self._path   = path
        self._mpv    = multipv
        self._engine = None
        self._transport = None

    async def _spawn(self):
        self._transport, self._engine = await chess.engine.popen_uci(self._path)
        await self._engine.configure({"Threads": 1, "Hash": 32})

    async def start(self):
        await self._spawn()
        log.info("Stockfish ready: %s", self._path)

    async def stop(self):
        if self._engine:
            try: await self._engine.quit()
            except Exception: pass
            self._engine = None

    @staticmethod
    def _sanitize_fen(fen: str) -> str:
        parts = fen.split()
        if len(parts) >= 3:
            parts[2] = '-'
        if len(parts) < 6:
            parts += (['-'] * (4 - len(parts)) + ['0', '1'])[:6 - len(parts)]
        return ' '.join(parts[:6])

    async def analyze(self, fen: str, depth: int) -> AnalysisResult:
        fen = self._sanitize_fen(fen)
        blank = AnalysisResult(fen=fen, turn="white", game_over=True)
        if not self._engine:
            try:
                log.info("Engine dead — restarting…")
                await self._spawn()
            except Exception as e:
                log.error("Engine restart failed: %s", e)
                return blank
        try:
            board = chess.Board(fen)
        except Exception:
            return blank

        turn = "white" if board.turn == chess.WHITE else "black"
        if board.is_game_over():
            return AnalysisResult(fen=fen, turn=turn, game_over=True, result=board.result())

        time_cap = 1.5 if depth <= 10 else 2.5
        try:
            infos = await self._engine.analyse(
                board,
                chess.engine.Limit(depth=depth, time=time_cap),
                multipv=self._mpv,
            )
        except Exception as e:
            log.warning("Engine analyse: %s", e)
            self._engine = None
            return AnalysisResult(fen=fen, turn=turn)

        top_moves, pv_sans = [], []
        for i, info in enumerate(infos or []):
            pv = info.get("pv", [])
            sc = info.get("score")
            if not pv or sc is None: continue
            move = pv[0]
            uci  = move.uci()
            try:   san = board.san(move)
            except Exception: san = uci
            cp = (99999. if (sc.is_mate() and (sc.white().mate() or 0) > 0) else
                  -99999. if sc.is_mate() else
                  (sc.white().score() or 0) / 100.)
            if i == 0:
                tmp = board.copy()
                for mv in pv[:16]:
                    try: pv_sans.append(tmp.san(mv)); tmp.push(mv)
                    except Exception: break
            top_moves.append(MoveInfo(
                uci=uci, san=san, score=cp,
                mate=sc.white().mate() if sc.is_mate() else None,
                depth=info.get("depth", depth),
            ))

        return AnalysisResult(
            fen=fen, turn=turn,
            top_moves=top_moves, pv=pv_sans,
            eval_score=top_moves[0].score if top_moves else 0.,
            mate=top_moves[0].mate  if top_moves else None,
            depth=infos[0].get("depth", depth) if infos else 0,
        )


# ─── Overlay UI ───────────────────────────────────────────────────────────────
class OverlayUI:
    W, H   = 335, 465
    BG     = "#1e1e2e"; HDR = "#313244"; FG = "#cdd6f4"
    MUTED  = "#585b70"; BLUE = "#89b4fa"
    GREEN  = "#a6e3a1"; RED = "#f38ba8"; YELL = "#f9e2af"
    ORANGE = "#fab387"; DARK   = "#181825"

    _PIECE_NAME = {'K':'Raja','Q':'Ratu','R':'Benteng','B':'Gajah','N':'Kuda','P':'Bidak'}

    def __init__(self, ui_q, auto_flag, depth_ref, shutdown_ev, last_fen_ref, natural_flag):
        self._q   = ui_q
        self._a   = auto_flag
        self._d   = depth_ref
        self._ev  = shutdown_ev
        self._lfr = last_fen_ref
        self._nat = natural_flag
        self.root = None

    def build(self):
        r = tk.Tk()
        self.root = r
        r.title("Chess Assistant")
        r.geometry(f"{self.W}x{self.H}+15+15")
        r.configure(bg=self.BG)
        r.attributes("-topmost", True)
        r.resizable(False, False)
        r.protocol("WM_DELETE_WINDOW", self._close)

        mono  = tkfont.Font(family="Consolas", size=10)
        bold  = tkfont.Font(family="Consolas", size=10, weight="bold")
        small = tkfont.Font(family="Consolas", size=9)
        big   = tkfont.Font(family="Consolas", size=13, weight="bold")
        tiny  = tkfont.Font(family="Consolas", size=8)

        # Header
        hdr = tk.Frame(r, bg=self.HDR, height=30)
        hdr.pack(fill=tk.X); hdr.pack_propagate(False)
        tk.Label(hdr, text="♟ Chess.com Assistant",
                 bg=self.HDR, fg=self.BLUE, font=bold).pack(side=tk.LEFT, padx=8)
        self._dot = tk.Label(hdr, text="●", bg=self.HDR, fg=self.MUTED, font=bold)
        self._dot.pack(side=tk.RIGHT, padx=8)

        # Eval bar + score
        ef = tk.Frame(r, bg=self.BG)
        ef.pack(fill=tk.X, padx=8, pady=(8,0))
        self._bar = tk.Canvas(ef, height=20, bg="#2a2a3d",
                               highlightthickness=1, highlightbackground=self.MUTED)
        self._bar.pack(fill=tk.X)
        self._eval_lbl = tk.Label(ef, text="—", bg=self.BG, fg=self.FG, font=big, anchor=tk.CENTER)
        self._eval_lbl.pack(fill=tk.X)

        # Opening name
        self._opening_lbl = tk.Label(r, text="", bg=self.BG, fg=self.YELL,
                                      font=tiny, anchor=tk.CENTER)
        self._opening_lbl.pack(fill=tk.X, padx=8)

        # Best move + AUTO + MODE buttons
        bf = tk.Frame(r, bg=self.BG)
        bf.pack(fill=tk.X, padx=8, pady=(2,0))
        tk.Label(bf, text="Best:", bg=self.BG, fg=self.MUTED, font=small).pack(side=tk.LEFT)
        self._best = tk.Label(bf, text="—", bg=self.BG, fg=self.GREEN, font=bold)
        self._best.pack(side=tk.LEFT, padx=5)
        init_auto_txt = "AUTO: ON"  if self._a[0] else "AUTO: OFF"
        init_auto_col = self.GREEN  if self._a[0] else self.RED
        self._abtn = tk.Button(bf, text=init_auto_txt, bg=self.HDR, fg=init_auto_col,
                                font=small, relief=tk.FLAT, padx=6,
                                cursor="hand2", command=self._toggle_auto)
        self._abtn.pack(side=tk.RIGHT)
        init_mode_txt = "NAT" if self._nat[0] else "BOT"
        init_mode_col = self.BLUE if self._nat[0] else self.ORANGE
        self._mbtn = tk.Button(bf, text=init_mode_txt, bg=self.HDR, fg=init_mode_col,
                                font=small, relief=tk.FLAT, padx=6,
                                cursor="hand2", command=self._toggle_mode)
        self._mbtn.pack(side=tk.RIGHT, padx=(0, 4))

        # Time left label
        self._time_lbl = tk.Label(r, text="", bg=self.BG, fg=self.MUTED, font=tiny, anchor=tk.W)
        self._time_lbl.pack(fill=tk.X, padx=8)

        # Top moves
        tk.Label(r, text="Top moves:", bg=self.BG, fg=self.MUTED,
                 font=small, anchor=tk.W).pack(fill=tk.X, padx=8, pady=(4,0))
        mf = tk.Frame(r, bg=self.BG); mf.pack(fill=tk.X, padx=8)
        self._mlbls = []
        for _ in range(5):
            l = tk.Label(mf, text="", bg=self.BG, fg=self.FG, font=mono, anchor=tk.W)
            l.pack(fill=tk.X); self._mlbls.append(l)

        # Divider + PV
        tk.Frame(r, bg=self.MUTED, height=1).pack(fill=tk.X, padx=8, pady=5)
        tk.Label(r, text="Principal variation:", bg=self.BG, fg=self.MUTED,
                 font=small, anchor=tk.W).pack(fill=tk.X, padx=8)
        self._pv = tk.Text(r, height=4, bg=self.DARK, fg=self.YELL,
                            font=small, relief=tk.FLAT, wrap=tk.WORD,
                            state=tk.DISABLED, padx=4, pady=3)
        self._pv.pack(fill=tk.X, padx=8, pady=(0,4))

        # Footer
        ft = tk.Frame(r, bg=self.HDR)
        ft.pack(fill=tk.X, side=tk.BOTTOM)
        tk.Label(ft, text="Depth:", bg=self.HDR, fg=self.MUTED,
                 font=small).pack(side=tk.LEFT, padx=(8,2), pady=4)
        self._dv = tk.IntVar(value=self._d[0])
        self._dv.trace_add("write", lambda *_: self._sync_depth())
        tk.Spinbox(ft, from_=5, to=30, textvariable=self._dv, width=3,
                   bg=self.HDR, fg=self.FG, font=small,
                   relief=tk.FLAT, buttonbackground=self.HDR).pack(side=tk.LEFT)
        self._info = tk.Label(ft, text="Waiting…", bg=self.HDR, fg=self.MUTED, font=small)
        self._info.pack(side=tk.LEFT, padx=8)

        # Watermark
        wm = tk.Label(r, text="by github.com/aplatogg",
                      bg=self.BG, fg=self.MUTED, font=tiny, anchor=tk.CENTER)
        wm.pack(fill=tk.X, pady=(0, 3))

        r.after(80, self._poll)

    def _close(self):
        log.info("Overlay closed → shutdown")
        self._ev.set()
        try: self.root.destroy()
        except Exception: pass

    def _sync_depth(self):
        try: self._d[0] = self._dv.get()
        except Exception: pass

    def _toggle_auto(self):
        self._a[0] = not self._a[0]
        on = self._a[0]
        self._abtn.config(text="AUTO: ON" if on else "AUTO: OFF",
                           fg=self.GREEN if on else self.RED)
        if on:
            self._lfr[0] = ""
        log.info("Auto-play %s", "ON" if on else "OFF")

    def _toggle_mode(self):
        self._nat[0] = not self._nat[0]
        nat = self._nat[0]
        self._mbtn.config(text="NAT" if nat else "BOT",
                           fg=self.BLUE if nat else self.ORANGE)
        log.info("Mode: %s", "NATURAL" if nat else "BOT")

    def _poll(self):
        if self._ev.is_set(): return
        try:
            while True: self._render(self._q.get_nowait())
        except queue.Empty: pass
        if self.root and not self._ev.is_set():
            self.root.after(80, self._poll)

    @staticmethod
    def _fmt_move(m) -> str:
        uci = m.uci; san = m.san
        if len(uci) < 4: return uci
        frm, to = uci[:2], uci[2:4]
        if uci[4:5] == 'q': return f"Bidak {frm}->{to}=Ratu"
        if san and san[0].upper() in 'KQRBN' and san[0].isupper():
            name = OverlayUI._PIECE_NAME.get(san[0], san[0])
        else:
            name = 'Bidak'
        return f"{name} {frm}->{to}"

    def _render(self, a: AnalysisResult):
        self._dot.config(fg=self.GREEN if not a.game_over else self.RED)
        # Opening name
        self._opening_lbl.config(text=a.opening if a.opening else "")
        # Time left
        if a.time_left is not None:
            m, s = divmod(int(a.time_left), 60)
            self._time_lbl.config(
                text=f"⏱ {m}:{s:02d}" if m else f"⏱ {a.time_left:.1f}s",
                fg=self.RED if a.time_left < 30 else self.MUTED
            )
        else:
            self._time_lbl.config(text="")

        if a.game_over:
            self._eval_lbl.config(text=a.result or "Game Over", fg=self.MUTED)
            self._best.config(text="—")
            self._info.config(text="Game finished — waiting for next…")
            self._draw_bar(0., None)
            for l in self._mlbls: l.config(text="")
            self._set_pv("Game over.")
            return
        if a.mate is not None:
            mate_str = f"M{abs(a.mate)}" if a.mate >= 0 else f"-M{abs(a.mate)}"
            lbl = f"{mate_str}  {a.win_prob:.0f}%"
            col = self.GREEN if a.mate > 0 else self.RED
        else:
            lbl = f"{a.eval_score:+.2f}  {a.win_prob:.0f}%"
            col = self.GREEN if a.eval_score >= 0 else self.RED
        self._eval_lbl.config(text=lbl, fg=col)
        self._draw_bar(a.eval_score, a.mate)
        if a.top_moves:
            self._best.config(text=self._fmt_move(a.top_moves[0]), fg=self.GREEN)
        else:
            self._best.config(text="—", fg=self.MUTED)
        for i, l in enumerate(self._mlbls):
            if i < len(a.top_moves):
                m  = a.top_moves[i]
                sc = (f"M{abs(m.mate)}" if m.mate is not None and m.mate >= 0
                      else f"-M{abs(m.mate)}" if m.mate is not None
                      else f"{m.score:+.2f}")
                l.config(text=f"  {i+1}. {self._fmt_move(m):<14} {sc:>7}   d{m.depth}")
            else:
                l.config(text="")
        self._set_pv("  ".join(a.pv) if a.pv else "—")
        self._info.config(text=f"d{a.depth} · {'Putih' if a.turn=='white' else 'Hitam'} jalan")

    def _draw_bar(self, score, mate):
        self._bar.update_idletasks()
        w = self._bar.winfo_width() or (self.W - 16)
        ratio = (1. if mate and mate > 0 else 0. if mate and mate < 0
                 else (max(-8., min(8., score)) + 8.) / 16.)
        wp = int(w * ratio)
        self._bar.delete("all")
        self._bar.create_rectangle(0, 0, wp, 20, fill="#e8e8e8", outline="")
        self._bar.create_rectangle(wp, 0, w, 20, fill="#1a1a1a", outline="")
        if 2 <= wp <= w - 2:
            self._bar.create_line(wp, 0, wp, 20, fill="#777", width=1)

    def _set_pv(self, text):
        self._pv.config(state=tk.NORMAL)
        self._pv.delete("1.0", tk.END)
        self._pv.insert(tk.END, text)
        self._pv.config(state=tk.DISABLED)

    def run(self):
        self.build()
        self.root.mainloop()


# ─── Main assistant ────────────────────────────────────────────────────────────
class ChessAssistant:
    POLL = 0.7

    def __init__(self, browser, launch, depth, auto_play, port, stockfish=None):
        self._browser  = browser
        self._launch   = launch
        self._auto     = [auto_play]
        self._depth    = [depth]
        self._port     = port
        self._stockfish = Path(stockfish).expanduser() if stockfish else None
        self._ui_q     = queue.Queue(maxsize=3)
        self._shutdown = threading.Event()
        self._engine: Optional[Engine] = None
        self._last_fen_ref  = [""]
        self._last_color    = "white"
        self._last_play_ts  = 0.
        self._throttle_done = False
        self._natural       = [True]  # True=humanlike, False=bot speed

    @staticmethod
    def _calc_depth(base: int, time_left: Optional[float]) -> int:
        """Reduce analysis depth when time is short."""
        if time_left is None:
            return base
        if time_left < 10:  return 8
        if time_left < 30:  return 12
        if time_left < 60:  return 15
        return base

    @staticmethod
    def _human_think_time(result: AnalysisResult, time_left: Optional[float]) -> float:
        """Return human-like think delay (NAT mode): flat 2–5 seconds random."""
        if time_left is not None and time_left < 10:
            return random.uniform(0.5, 1.5)   # panik, waktu habis
        return random.uniform(2.0, 5.0)

    @staticmethod
    def _bot_think_time(time_left: Optional[float]) -> float:
        """Fast bot-like delay — near instant like an engine."""
        if time_left is not None and time_left < 15:
            return random.uniform(0.1, 0.3)   # critical time
        return random.uniform(0.2, 0.9)

    @staticmethod
    def _pick_move(result: AnalysisResult) -> str:
        """NAT mode: ~80% top-move rate — human-like accuracy."""
        moves = result.top_moves
        if not moves:
            return ""
        n = len(moves)
        r = random.random()
        # 80% top, 16% 2nd, 4% 3rd
        if n >= 2 and r > 0.80:
            diff1 = abs(moves[0].score - moves[1].score)
            if diff1 < 1.5:
                if n >= 3 and r > 0.96:
                    diff2 = abs(moves[0].score - moves[2].score)
                    if diff2 < 2.0:
                        return moves[2].uci
                return moves[1].uci
        return moves[0].uci

    @staticmethod
    def _pick_move_bot(result: AnalysisResult) -> str:
        """BOT mode: ~93% top-move rate — engine-like but not perfect."""
        moves = result.top_moves
        if not moves:
            return ""
        n = len(moves)
        r = random.random()
        # 93% top, 6% 2nd, 1% 3rd
        if n >= 2 and r > 0.93:
            diff1 = abs(moves[0].score - moves[1].score)
            if diff1 < 0.8:
                if n >= 3 and r > 0.99:
                    diff2 = abs(moves[0].score - moves[2].score)
                    if diff2 < 1.2:
                        return moves[2].uci
                return moves[1].uci
        return moves[0].uci

    def _find_sf(self):
        if self._stockfish:
            if self._stockfish.exists():
                return str(self._stockfish)
            raise FileNotFoundError(f"Stockfish not found at --stockfish path: {self._stockfish}")
        for candidate in STOCKFISH_CANDIDATES:
            if candidate.exists():
                return str(candidate)
        found = shutil.which("stockfish")
        if found:
            return found
        raise FileNotFoundError(
            "stockfish.exe not found. Put it in the project folder, install it on PATH, or pass --stockfish PATH."
        )

    def _run_ui(self):
        ui = OverlayUI(self._ui_q, self._auto, self._depth, self._shutdown, self._last_fen_ref, self._natural)
        ui.run()
        self._shutdown.set()

    async def _get_browser(self, pw):
        if not self._launch and self._browser != "firefox":
            cdp = f"http://localhost:{self._port}"
            log.info("Connecting to %s", cdp)
            try:
                br = await pw.chromium.connect_over_cdp(cdp)
                log.info("Connected to the existing browser")
                return br
            except Exception as exc:
                raise ConnectionError(
                    f"Could not connect to Brave on {cdp}.\n"
                    f'Start Brave with: "{BRAVE_EXE}" --remote-debugging-port={self._port} '
                    f'--user-data-dir="{DATA_DIR / "brave-profile"}"\n'
                    "or run with --launch to open a dedicated profile."
                ) from exc

        if self._browser == "firefox":
            br = await pw.firefox.launch(
                headless=False,
                executable_path=FIREFOX_EXE if Path(FIREFOX_EXE).exists() else None,
            )
        else:
            exe = BRAVE_EXE if Path(BRAVE_EXE).exists() else None
            profile = DATA_DIR / "brave-profile"
            profile.mkdir(parents=True, exist_ok=True)
            args = ["--disable-blink-features=AutomationControlled", f"--user-data-dir={profile}"]
            br = await pw.chromium.launch(headless=False, executable_path=exe, args=args)
        ctx = await br.new_context(viewport={"width": 1400, "height": 900})
        page = await ctx.new_page()
        await page.goto("https://www.chess.com/play/online", wait_until="domcontentloaded")
        return br

    async def _find_chess_tab(self, browser: Browser) -> Optional[Page]:
        for ctx in browser.contexts:
            for page in ctx.pages:
                try:
                    if "chess.com" in page.url:
                        return page
                except Exception: pass
        return None

    async def run(self):
        sf_path = self._find_sf()
        self._engine = Engine(sf_path, multipv=5)
        await self._engine.start()

        threading.Thread(target=self._run_ui, daemon=True).start()
        await asyncio.sleep(1.)

        try:
            async with async_playwright() as pw:
                while not self._shutdown.is_set():
                    # ── Connect / reconnect ───────────────────────────────────
                    try:
                        browser = await self._get_browser(pw)
                    except Exception as e:
                        log.error("Gagal connect: %s — retry 5s…", e)
                        await asyncio.sleep(5.)
                        continue

                    log.info("Monitor started. Buka game Chess.com di Brave.")
                    current_page: Optional[Page] = None
                    reader: Optional[BoardReader] = None
                    self._throttle_done = False
                    disconnected = False

                    # ── Per-session game loop ─────────────────────────────────
                    while not self._shutdown.is_set():
                      try:
                        tab = await self._find_chess_tab(browser)
                        if tab is None:
                            if current_page is not None:
                                log.info("Tab Chess.com hilang — menunggu…")
                                current_page = None; reader = None
                                self._last_fen_ref[0] = ""
                                self._throttle_done = False
                            await asyncio.sleep(2.)
                            continue

                        if tab is not current_page:
                            log.info("Tab Chess.com: %s", tab.url)
                            current_page = tab
                            reader = BoardReader(tab)
                            self._last_fen_ref[0] = ""
                            self._throttle_done = False

                        if not self._throttle_done:
                            await reader.inject_anti_throttle()
                            self._throttle_done = True

                        if not await reader.is_game():
                            await asyncio.sleep(1.5)
                            continue

                        data = await reader.read()
                        if not data:
                            await asyncio.sleep(self.POLL)
                            continue

                        fen = data.get("fen", "")
                        if not fen or fen == self._last_fen_ref[0]:
                            await asyncio.sleep(self.POLL)
                            continue

                        self._last_fen_ref[0] = fen
                        self._last_color = await reader.color()
                        time_left = await reader.get_time()
                        depth = self._calc_depth(self._depth[0], time_left)
                        moves = await reader.get_moves()
                        opening = get_opening_name(moves)
                        move_num = len(moves)

                        _src = data.get("src","?"); _turn = data.get("turn","?")
                        log.info("Analyze d=%d src=%s turn=%s color=%s time=%s opening=%s | %s",
                                 depth, _src, _turn, self._last_color,
                                 f"{time_left:.0f}s" if time_left else "?",
                                 opening or "-", fen[:40])

                        result = await self._engine.analyze(fen, depth)
                        result.opening  = opening
                        result.time_left = time_left
                        result.win_prob = _score_to_winpct(result.eval_score, result.mate)

                        try:
                            self._ui_q.put_nowait(result)
                        except queue.Full:
                            try: self._ui_q.get_nowait(); self._ui_q.put_nowait(result)
                            except queue.Empty: pass

                        # Auto-play
                        if self._auto[0] and not result.game_over and result.top_moves:
                            our = ((self._last_color == "white" and result.turn == "white") or
                                   (self._last_color == "black" and result.turn == "black"))
                            since = time.monotonic() - self._last_play_ts
                            if not our:
                                log.debug("Auto-play skip: not our turn (color=%s turn=%s)",
                                          self._last_color, result.turn)
                            elif since <= 1.5:
                                log.debug("Auto-play skip: cooldown %.1fs", since)
                            else:
                                if move_num < 10:
                                    # Opening phase: always top move, fast like a human who knows theory
                                    uci = result.top_moves[0].uci
                                    dl  = random.uniform(1.0, 2.2)
                                    log.info("Auto-play [OPENING %d]: %s think=%.1fs", move_num+1, uci, dl)
                                elif self._natural[0]:
                                    uci = self._pick_move(result)
                                    dl  = self._human_think_time(result, time_left)
                                    log.info("Auto-play [NAT]: %s think=%.1fs", uci, dl)
                                else:
                                    uci = self._pick_move_bot(result)
                                    dl  = self._bot_think_time(time_left)
                                    log.info("Auto-play [BOT]: %s think=%.2fs", uci, dl)
                                await asyncio.sleep(dl)
                                cur = await reader.read()
                                cur_fen = cur.get("fen","") if cur else ""
                                if cur_fen and cur_fen != fen:
                                    log.info("Auto-play abort: position changed before click")
                                    self._last_fen_ref[0] = ""
                                    continue
                                try:
                                    await reader.click_move(uci, self._last_color)
                                    self._last_play_ts = time.monotonic()
                                except Exception as ce:
                                    log.warning("Click move failed: %s", ce)
                                self._last_fen_ref[0] = ""
                                await asyncio.sleep(1.0)
                                continue

                        await asyncio.sleep(self.POLL)

                      except asyncio.CancelledError:
                          raise
                      except Exception as e:
                          err = str(e).lower()
                          if any(k in err for k in ("target closed", "connection refused",
                                                     "disconnected", "browser closed",
                                                     "websocket", "cdp")):
                              log.warning("Browser terputus: %s — reconnect 5s…", e)
                              disconnected = True
                              break
                          log.error("Loop error: %s", e, exc_info=True)
                          await asyncio.sleep(2.)

                    # Close current browser session
                    try: await browser.close()
                    except Exception: pass

                    if disconnected and not self._shutdown.is_set():
                        self._last_fen_ref[0] = ""
                        self._throttle_done   = False
                        log.info("Reconnecting…")
                        await asyncio.sleep(5.)
        finally:
            await self._engine.stop()
            log.info("Shutdown.")


# ─── CLI ──────────────────────────────────────────────────────────────────────
def main():
    # When running as a compiled exe, skip argparse and use safe defaults.
    if getattr(sys, 'frozen', False):
        setup_logging()
        asyncio.run(ChessAssistant(
            browser="brave", launch=False, depth=18, auto_play=True, port=DEFAULT_CDP_PORT
        ).run())
        return
    p = argparse.ArgumentParser(description="Chess.com Assistant")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--browser", default="brave", choices=["brave", "firefox"])
    p.add_argument("--launch", action="store_true", help="Open a dedicated browser profile instead of connecting")
    p.add_argument("--port", type=int, default=DEFAULT_CDP_PORT, choices=range(1, 65536), metavar="1-65535")
    p.add_argument("--depth", type=int, default=18, choices=range(5, 31), metavar="5-30")
    p.add_argument("--stockfish", type=Path, default=None, help="Path to the Stockfish executable")
    p.add_argument("--debug", action="store_true", help="Enable verbose logging")
    p.add_argument("--auto-play", action="store_true")
    args = p.parse_args()
    setup_logging(args.debug)
    log.info("browser=%s launch=%s depth=%d auto=%s", args.browser, args.launch, args.depth, args.auto_play)
    asyncio.run(ChessAssistant(
        args.browser, args.launch, args.depth, args.auto_play, args.port, args.stockfish
    ).run())

if __name__ == "__main__":
    main()

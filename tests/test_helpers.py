import random
from pathlib import Path

import pytest

from chess_assistant import (
    APP_DIR,
    DATA_DIR,
    AnalysisResult,
    ChessAssistant,
    Engine,
    MoveInfo,
    _score_to_winpct,
    get_opening_name,
)


def make_moves(*scores: float) -> list[MoveInfo]:
    return [
        MoveInfo(uci=f"move{index}", san=f"m{index}", score=score, mate=None, depth=18)
        for index, score in enumerate(scores)
    ]


def make_result(*scores: float) -> AnalysisResult:
    return AnalysisResult(
        fen="8/8/8/8/8/8/8/8 w - - 0 1",
        turn="white",
        top_moves=make_moves(*scores),
    )


def test_paths_are_portable():
    assert (APP_DIR / "chess_assistant.py").exists()
    assert DATA_DIR != Path(r"F:\Claude Normal\File")


def test_opening_book_returns_deepest_match():
    assert get_opening_name([]) == ""
    assert get_opening_name(["e2e4"]) == "King's Pawn"
    assert get_opening_name(["e2e4", "c7c5"]) == "Sicilian Defense"
    assert get_opening_name(["a2a3"]) == ""


def test_score_to_win_percentage():
    assert _score_to_winpct(0.0, None) == pytest.approx(50.0)
    assert _score_to_winpct(0.0, 3) == 100.0
    assert _score_to_winpct(0.0, -2) == 0.0


def test_analysis_depth_shrinks_with_the_clock():
    assert ChessAssistant._calc_depth(18, None) == 18
    assert ChessAssistant._calc_depth(18, 5) == 8
    assert ChessAssistant._calc_depth(18, 20) == 12
    assert ChessAssistant._calc_depth(18, 45) == 15
    assert ChessAssistant._calc_depth(18, 120) == 18


def test_think_time_ranges(monkeypatch):
    monkeypatch.setattr(random, "uniform", lambda low, high: low)
    assert ChessAssistant._human_think_time(make_result(), 5) == 0.5
    assert ChessAssistant._human_think_time(make_result(), 120) == 2.0
    assert ChessAssistant._bot_think_time(5) == 0.1
    assert ChessAssistant._bot_think_time(120) == 0.2


def test_move_picker_without_moves_is_empty():
    assert ChessAssistant._pick_move(make_result()) == ""
    assert ChessAssistant._pick_move_bot(make_result()) == ""


def test_natural_picker_prefers_a_close_second_move(monkeypatch):
    monkeypatch.setattr(random, "random", lambda: 0.90)
    assert ChessAssistant._pick_move(make_result(0.2, 0.1, 0.0)) == "move1"


def test_natural_picker_keeps_the_top_move_when_the_gap_is_large(monkeypatch):
    monkeypatch.setattr(random, "random", lambda: 0.99)
    assert ChessAssistant._pick_move(make_result(0.5, -1.5)) == "move0"


def test_bot_picker_prefers_a_close_second_move(monkeypatch):
    monkeypatch.setattr(random, "random", lambda: 0.95)
    assert ChessAssistant._pick_move_bot(make_result(0.2, 0.1)) == "move1"


def test_sanitize_fen_drops_castling_rights():
    assert Engine._sanitize_fen("8/8/8/8/8/8/8/8 w KQkq - 0 1") == "8/8/8/8/8/8/8/8 w - - 0 1"


def test_explicit_stockfish_path(tmp_path):
    engine = tmp_path / "stockfish.exe"
    engine.write_bytes(b"")
    assistant = ChessAssistant("brave", False, 18, False, 9222, stockfish=engine)
    assert assistant._find_sf() == str(engine)


def test_missing_stockfish_path_is_reported(tmp_path):
    assistant = ChessAssistant("brave", False, 18, False, 9222, stockfish=tmp_path / "missing.exe")
    with pytest.raises(FileNotFoundError, match="--stockfish"):
        assistant._find_sf()

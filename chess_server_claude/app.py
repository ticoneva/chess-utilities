"""
Chess Puzzle Generator - Flask Backend
A web interface for viewing PGN files with puzzle mode for practicing blunders, mistakes, and inaccuracies.
"""

import argparse
import json
import os
from datetime import datetime
from io import StringIO
from queue import Queue
from threading import Thread
from typing import Dict, List, Optional, Any

from flask import Flask, render_template, request, jsonify, session, Response, stream_with_context

import chess
import chess.pgn
import chess.engine

# Critical constants
STOCKFISH_PATH = "/opt/network/apps/chess/stockfish/stockfish-ubuntu-x86-64-avx2"
DEFAULT_PORT = 5001

# Classification thresholds (centipawns)
BLUNDER_THRESHOLD = 300
MISTAKE_THRESHOLD = 100
INACCURACY_THRESHOLD = 50

app = Flask(__name__)
app.secret_key = "chess_puzzle_generator_secret_key_2024"

# In-memory session storage
games_db: Dict[str, "GameState"] = {}


class GameState:
    """Manages sessions, game state, and analysis for PGN games."""

    def __init__(self, pgn_string: str):
        """Parse PGN and prepare game data."""
        self.pgn_string = pgn_string
        self.games: List[Dict[str, Any]] = []
        self.current_game_index = 0
        self.current_node: Optional[chess.pgn.GameNode] = None
        self.current_ply: int = 0
        self.total_plies: int = 0

        # Per-game puzzles storage (lazy analysis)
        self._game_puzzles: Dict[int, List[Dict[str, Any]]] = {}
        self._game_analyzed: Dict[int, bool] = {}

        # Queue for streaming puzzle analysis results
        self._analysis_queue: Optional[Queue] = None
        self._analyzing: bool = False

        # Default settings
        self.settings = {
            "show_evaluation": True,
            "show_best_moves": True,
            "num_best_moves": 3,
            "time_limit": 0.5,  # For real-time analysis during navigation
            "puzzle_time_limit": 0.1,  # For puzzle preparation/analysis
            "threads": 4,
        }

        # Puzzle mode settings
        self.puzzle_settings = {
            "puzzle_mode": False,
            "success_criterion": "top3",  # top3, best, any
            "current_puzzle_index": -1,
            "min_class": "blunder",  # inaccuracy, mistake, blunder
            "classification_mode": "wdl",  # eval or wdl
        }

        # Parse games
        self._parse_games(pgn_string)

    def _parse_games(self, pgn_string: str) -> None:
        """Parse multiple games from PGN string."""
        pgn_io = StringIO(pgn_string)

        while True:
            game = chess.pgn.read_game(pgn_io)
            if game is None:
                break

            headers = {
                "white": game.headers.get("White", "?"),
                "black": game.headers.get("Black", "?"),
                "event": game.headers.get("Event", "?"),
                "date": game.headers.get("Date", "?"),
                "result": game.headers.get("Result", "*"),
                "white_elo": game.headers.get("WhiteElo", ""),
                "black_elo": game.headers.get("BlackElo", ""),
            }

            # Convert game to move list, capturing NAGs for annotations
            board = game.board()
            move_list = []
            node = game
            ply = 0
            has_annotations = False

            while node.variations:
                node = node.variations[0]
                move = node.move
                nags = node.nags if node.nags else set()

                # Check for blunder (NAG 4), mistake (NAG 2), or inaccuracy (NAG 6)
                classification_from_nag = None
                if 4 in nags:  # ?? blunder
                    classification_from_nag = "blunder"
                    has_annotations = True
                elif 2 in nags:  # ? mistake
                    classification_from_nag = "mistake"
                    has_annotations = True
                elif 6 in nags:  # ?! inaccuracy
                    classification_from_nag = "inaccuracy"
                    has_annotations = True

                move_list.append({
                    "san": board.san(move),
                    "uci": move.uci(),
                    "ply": ply,
                    "comment": node.comment,
                    "nags": nags,
                    "classification_from_nag": classification_from_nag,
                })
                board.push(move)
                ply += 1

            self.games.append({
                "headers": headers,
                "moves": move_list,
                "total_plies": len(move_list),
                "has_annotations": has_annotations,  # Track if PGN had annotations
                "pgn_game": game,  # Store original game for PGN export
            })

    def _load_current_game(self) -> None:
        """Load current game moves (without analysis for speed)."""
        if self.current_game_index >= len(self.games):
            return

        game_data = self.games[self.current_game_index]
        board = chess.Board()
        self.moves: List[Dict[str, Any]] = []

        for move_info in game_data["moves"]:
            self.moves.append(move_info)
            board.push(chess.Move.from_uci(move_info["uci"]))

        self.total_plies = len(self.moves)
        self.current_ply = 0
        self.current_node = board

    def _analyze_game_moves(self, game_index: int, send_progress: bool = False) -> None:
        """Find blunders/mistakes/inaccuracies for a specific game using Stockfish."""
        if game_index in self._game_analyzed and self._game_analyzed[game_index]:
            # Already analyzed
            if send_progress and self._analysis_queue:
                self._analysis_queue.put({
                    "type": "game_complete",
                    "game_index": game_index,
                    "puzzles": self._game_puzzles.get(game_index, []),
                })
            return

        if game_index >= len(self.games):
            return

        if send_progress and self._analysis_queue:
            self._analysis_queue.put({
                "type": "game_start",
                "game_index": game_index,
                "game_name": self.games[game_index]["headers"]["white"] + " vs " + self.games[game_index]["headers"]["black"],
            })

        game_data = self.games[game_index]
        moves: List[Dict[str, Any]] = game_data["moves"]

        if not moves:
            self._game_puzzles[game_index] = []
            self._game_analyzed[game_index] = True
            if send_progress and self._analysis_queue:
                self._analysis_queue.put({
                    "type": "game_complete",
                    "game_index": game_index,
                    "puzzles": [],
                })
            return

        # Check if PGN already has annotations (blunders, mistakes, inaccuracies)
        if game_data.get("has_annotations", False):
            # Use existing annotations instead of running engine
            puzzles = self._extract_puzzles_from_annotations(game_index, moves, send_progress)
            self._game_puzzles[game_index] = puzzles
            self._game_analyzed[game_index] = True
            if send_progress and self._analysis_queue:
                self._analysis_queue.put({
                    "type": "game_complete",
                    "game_index": game_index,
                    "puzzles": puzzles,
                })
            return

        board = chess.Board()
        puzzles = []

        with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
            engine.configure({"Skill Level": 20, "Threads": self.settings["threads"]})
            time_limit = chess.engine.Limit(time=self.settings["puzzle_time_limit"])

            for i, move_info in enumerate(moves):
                move = chess.Move.from_uci(move_info["uci"])

                # Send progress update for current move
                if send_progress and self._analysis_queue:
                    self._analysis_queue.put({
                        "type": "move_progress",
                        "game_index": game_index,
                        "move_number": i,
                        "move_san": move_info["san"],
                        "total_moves": len(moves),
                    })

                # Analyze before the move
                info = engine.analyse(board, time_limit)
                score = info.get("score")
                before_cp = score.white().score(mate_score=10000) if score else 0
                before_eval = before_cp / 100.0

                # Get WDL if available (from white's perspective, in thousandths)
                if score and hasattr(score, "wdl"):
                    wdl = score.wdl()
                    try:
                        if hasattr(wdl, 'white') and callable(wdl.white):
                            white_wdl = wdl.white()
                            # Stockfish WDL sums to 1000, so raw counts are already in thousandths (‰)
                            before_wdl = (white_wdl.wins, white_wdl.draws, white_wdl.losses)
                        else:
                            before_wdl = None
                    except:
                        before_wdl = None
                else:
                    before_wdl = None

                # Make the move
                board.push(move)

                # Analyze after the move
                info = engine.analyse(board, time_limit)
                score = info.get("score")
                after_cp = score.white().score(mate_score=10000) if score else 0
                after_eval = after_cp / 100.0

                # Get WDL after move (from white's perspective, in thousandths)
                if score and hasattr(score, "wdl"):
                    wdl = score.wdl()
                    try:
                        if hasattr(wdl, 'white') and callable(wdl.white):
                            white_wdl = wdl.white()
                            after_wdl = (white_wdl.wins, white_wdl.draws, white_wdl.losses)
                        else:
                            after_wdl = None
                    except:
                        after_wdl = None
                else:
                    after_wdl = None

                # Classify move based on classification mode
                classification = None
                classification_mode = self.puzzle_settings.get("classification_mode", "wdl")

                # Calculate evaluation change (always compute for storage)
                if i % 2 == 0:  # White's move
                    eval_change = before_eval - after_eval
                else:  # Black's move
                    eval_change = after_eval - before_eval

                # For puzzle analysis, always use eval-based (more consistent)
                # WDL mode is only for navigation highlighting
                BLUNDER_THRESHOLD = 300  # cp
                MISTAKE_THRESHOLD = 100  # cp
                INACCURACY_THRESHOLD = 50  # cp

                if eval_change >= BLUNDER_THRESHOLD / 100.0:
                    classification = "blunder"
                elif eval_change >= MISTAKE_THRESHOLD / 100.0:
                    classification = "mistake"
                elif eval_change >= INACCURACY_THRESHOLD / 100.0:
                    classification = "inaccuracy"

                # Store puzzle if classified
                if classification:
                    # Get best moves at the position before the move
                    board.pop()  # Go back to before the move
                    best_moves_info = self._get_best_moves(board, engine, time_limit)
                    board.push(move)  # Put the move back

                    puzzles.append({
                        "ply": i,
                        "san": move_info["san"],
                        "uci": move_info["uci"],
                        "before_eval": before_eval,
                        "after_eval": after_eval,
                        "eval_change": eval_change,
                        "classification": classification,
                        "game_index": game_index,
                        "best_moves": best_moves_info,
                    })

        self._game_puzzles[game_index] = puzzles
        self._game_analyzed[game_index] = True

        # Send progress update if streaming
        if send_progress and self._analysis_queue:
            self._analysis_queue.put({
                "type": "game_complete",
                "game_index": game_index,
                "puzzles": puzzles,
            })

    def _extract_puzzles_from_annotations(self, game_index: int, moves: List[Dict[str, Any]], send_progress: bool = False) -> List[Dict[str, Any]]:
        """Extract puzzles from existing PGN annotations (NAGs) without running engine."""
        puzzles = []

        for i, move_info in enumerate(moves):
            # Send progress update (only for a few moves to avoid spam)
            if send_progress and self._analysis_queue and i % 10 == 0:
                self._analysis_queue.put({
                    "type": "move_progress",
                    "game_index": game_index,
                    "move_number": i,
                    "move_san": move_info["san"],
                    "total_moves": len(moves),
                })

            classification = move_info.get("classification_from_nag")
            if classification:
                puzzles.append({
                    "ply": i,
                    "san": move_info["san"],
                    "uci": move_info["uci"],
                    "before_eval": 0,
                    "after_eval": 0,
                    "eval_change": 0,
                    "classification": classification,
                    "game_index": game_index,
                    "best_moves": [],  # Will be fetched on demand when user clicks puzzle
                    "from_annotation": True,
                })

        return puzzles

    def analyze_games_async(self, min_class: str) -> Queue:
        """Analyze all games asynchronously and return a queue for progress updates."""
        class_priority = {"blunder": 3, "mistake": 2, "inaccuracy": 1}
        min_priority = class_priority.get(min_class, 1)

        # Start analysis in background thread
        self._analysis_queue = Queue()
        self._analyzing = True

        def analyze_thread():
            for game_idx in range(len(self.games)):
                if not self._analyzing:
                    break
                if game_idx not in self._game_analyzed or not self._game_analyzed[game_idx]:
                    self._analyze_game_moves(game_idx, send_progress=True)

            # Send complete signal
            self._analysis_queue.put({
                "type": "complete",
                "total_games": len(self.games),
            })
            self._analyzing = False

        Thread(target=analyze_thread, daemon=True).start()
        return self._analysis_queue

    def get_puzzles_for_game(
        self, game_index: int, min_class: str
    ) -> List[Dict[str, Any]]:
        """Get filtered puzzles for a specific game."""
        class_priority = {"blunder": 3, "mistake": 2, "inaccuracy": 1}
        min_priority = class_priority.get(min_class, 1)

        puzzles = self._game_puzzles.get(game_index, [])
        return [
            p for p in puzzles
            if class_priority.get(p["classification"], 0) >= min_priority
        ]

    def _get_best_moves(
        self, board: chess.Board, engine: Any, time_limit
    ) -> List[Dict[str, Any]]:
        """Get top moves with scores for a position."""
        num_moves = self.settings["num_best_moves"]
        if num_moves == 0:
            return []

        best_moves = []
        seen_moves = set()

        # Get principal variation (PV) info
        info = engine.analyse(board, time_limit, multipv=num_moves)

        for pv_info in info:
            if "pv" not in pv_info:
                continue

            score = pv_info.get("score")
            if not score:
                continue

            if score.relative.mate():
                cp = score.relative.mate() * 100
            else:
                cp = score.relative.score(mate_score=10000)

            move_san = board.san(pv_info["pv"][0])
            move_uci = pv_info["pv"][0].uci()

            if move_uci in seen_moves:
                continue
            seen_moves.add(move_uci)

            best_moves.append({
                "san": move_san,
                "uci": move_uci,
                "score": cp / 100.0,
            })

        return best_moves

    def get_filtered_puzzles(self, min_class: str) -> List[Dict[str, Any]]:
        """Filter puzzles by minimum classification (existing analyzed games only)."""
        class_priority = {"blunder": 3, "mistake": 2, "inaccuracy": 1}
        min_priority = class_priority.get(min_class, 1)

        # Only return puzzles from games that have been analyzed
        all_puzzles = []
        for game_idx in range(len(self.games)):
            if game_idx in self._game_analyzed and self._game_analyzed[game_idx]:
                all_puzzles.extend(self._game_puzzles.get(game_idx, []))

        return [
            p for p in all_puzzles
            if class_priority.get(p["classification"], 0) >= min_priority
        ]

    def analyze_position(self, fen: str) -> Dict[str, Any]:
        """Get Stockfish evaluation, WDL, and best moves for a given position."""
        board = chess.Board(fen)

        with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
            engine.configure({"Skill Level": 20, "Threads": self.settings["threads"]})
            time_limit = chess.engine.Limit(time=self.settings["time_limit"])

            info = engine.analyse(board, time_limit)
            score = info.get("score")

            if score:
                if score.relative.mate():
                    eval_score = score.relative.mate() * 100
                else:
                    eval_score = score.relative.score(mate_score=10000)
            else:
                eval_score = 0

            # Get WDL
            if score and hasattr(score, "wdl"):
                wdl = score.wdl()
                try:
                    win_chance = wdl.win_chance()
                    draw_chance = wdl.draw_chance()
                    loss_chance = wdl.loss_chance()
                    wdl_pcts = (win_chance, draw_chance, loss_chance)
                except:
                    wdl_pcts = None
            else:
                wdl_pcts = None

            # Get best moves
            best_moves = self._get_best_moves(board, engine, time_limit)

            return {
                "evaluation": eval_score / 100.0,
                "wdl": wdl_pcts,
                "best_moves": best_moves,
            }

    def get_board_at_ply(self, ply: int) -> chess.Board:
        """Get board state at specific ply."""
        board = chess.Board()
        # Use game data directly if moves not loaded
        if hasattr(self, 'moves') and self.moves:
            moves = self.moves
        else:
            moves = self.games[self.current_game_index]["moves"]
        for i in range(ply):
            if i < len(moves):
                board.push(chess.Move.from_uci(moves[i]["uci"]))
        return board

    def get_fen_at_ply(self, ply: int) -> str:
        """Get FEN string at specific ply."""
        board = self.get_board_at_ply(ply)
        return board.fen()

    def get_puzzle_start_position(self, puzzle_index: int) -> Dict[str, Any]:
        """Get the state before a puzzle move."""
        filtered = self.get_filtered_puzzles(self.puzzle_settings["min_class"])
        if puzzle_index >= len(filtered):
            return None

        puzzle = filtered[puzzle_index]
        ply = puzzle["ply"]

        # Load the game containing this puzzle
        game_index = puzzle["game_index"]
        if game_index >= len(self.games):
            return None

        self.current_game_index = game_index
        self._load_current_game()

        # Now get the FEN at the puzzle's ply
        fen = self.get_fen_at_ply(ply)

        # If puzzle has no best_moves (from annotation), fetch them now
        if not puzzle.get("best_moves"):
            board = self.get_board_at_ply(ply)
            with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
                engine.configure({"Skill Level": 20, "Threads": self.settings["threads"]})
                time_limit = chess.engine.Limit(time=self.settings["puzzle_time_limit"])
                puzzle["best_moves"] = self._get_best_moves(board, engine, time_limit)

        return {
            "fen": fen,
            "ply": ply,
            "puzzle": puzzle,
        }

    def check_puzzle_move(
        self, puzzle_index: int, move_uci: str
    ) -> Dict[str, Any]:
        """Check if user's move meets success criteria."""
        filtered = self.get_filtered_puzzles(self.puzzle_settings["min_class"])
        if puzzle_index >= len(filtered):
            return {"correct": False, "message": "Invalid puzzle"}

        puzzle = filtered[puzzle_index]
        criterium = self.puzzle_settings["success_criterion"]

        # Analyze moves at the puzzle position
        board = self.get_board_at_ply(puzzle["ply"])
        move = chess.Move.from_uci(move_uci)

        try:
            board.push(move)
        except ValueError:
            return {"correct": False, "message": "Illegal move"}

        with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
            engine.configure({"Skill Level": 20, "Threads": self.settings["threads"]})
            time_limit = chess.engine.Limit(time=1.0)  # Use 1 second for puzzle checking

            # Pop the move to analyze the position
            board.pop()

            # Get SAN notation for the user's move
            move_san = board.san(move)

            best_moves_info = self._get_best_moves(board, engine, time_limit)

            # Evaluate the position before user's move
            info_before = engine.analyse(board, time_limit)
            score_before = info_before.get("score")
            if score_before and score_before.relative.mate():
                before_cp = score_before.relative.mate() * 100
            else:
                before_cp = score_before.relative.score(mate_score=10000) if score_before else 0
            before_eval = before_cp / 100.0

            # Evaluate after user's move
            board.push(move)
            info_after = engine.analyse(board, time_limit)
            score_after = info_after.get("score")

            if score_after and score_after.relative.mate():
                after_cp = score_after.relative.mate() * 100
            else:
                after_cp = score_after.white().score(mate_score=10000) if score_after else 0

            after_eval = after_cp / 100.0

            # Get continuation moves (PV) after user's move
            continuation = []
            if "pv" in info_after:
                temp_board = board.copy()
                for i, pv_move in enumerate(info_after["pv"][:8]):  # Limit to 8 moves
                    try:
                        san = temp_board.san(pv_move)
                        continuation.append(san)
                        temp_board.push(pv_move)
                    except:
                        break

            # Calculate eval change (positive = bad for player who just moved)
            # For the player who just made a move (now opponent to move):
            # If was white, white made move, eval = before - after
            # If was black, black made move, eval = after - before
            if board.turn == chess.BLACK:  # White moved
                eval_change = before_eval - after_eval
            else:  # Black moved
                eval_change = after_eval - before_eval

            # Check success criteria
            correct = False
            message = ""

            move_found = False
            move_score = None
            move_rank = None

            for i, mv in enumerate(best_moves_info):
                if mv["uci"] == move_uci:
                    move_found = True
                    move_score = mv["score"]
                    move_rank = i + 1
                    break

            if criterium == "best":
                if move_found and move_rank == 1:
                    correct = True
                    message = f"Correct! {move_san} is the best move."
                else:
                    message = f"{move_san} is not the best move. Try again."

            elif criterium == "top3":
                if move_found and move_rank <= 3:
                    # Also check it's not an inaccuracy
                    if eval_change >= INACCURACY_THRESHOLD / 100.0:
                        message = f"{move_san} is in top 3 but still an inaccuracy. Try again."
                    else:
                        correct = True
                        message = f"Correct! {move_san} is a good move (rank {move_rank})."
                else:
                    message = f"{move_san} is not among the top 3 moves. Try again."

            else:  # any (any good move)
                if eval_change < INACCURACY_THRESHOLD / 100.0:
                    correct = True
                    message = f"Correct! {move_san} is a good move."
                else:
                    message = f"{move_san} is an inaccuracy or worse. Try again."

        return {
            "correct": correct,
            "message": message,
            "move_san": move_san,
            "move_rank": move_rank,
            "move_score": move_score,
            "best_moves": best_moves_info,
            "eval_change": eval_change,
            "continuation": continuation,
        }


# Flask Routes


@app.route("/")
def index():
    """Render main page."""
    return render_template("index.html")


@app.route("/upload_pgn", methods=["POST"])
def upload_pgn():
    """Upload and parse PGN file."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    try:
        pgn_string = file.read().decode("utf-8")
    except UnicodeDecodeError:
        return jsonify({"error": "Invalid PGN file encoding"}), 400

    # Create new game state
    session_id = str(datetime.now().timestamp())
    game_state = GameState(pgn_string)
    games_db[session_id] = game_state

    session["session_id"] = session_id

    return jsonify({
        "session_id": session_id,
        "num_games": len(game_state.games),
    })


@app.route("/game_info")
def game_info():
    """Get game info for selected game."""
    session_id = session.get("session_id")
    if session_id not in games_db:
        return jsonify({"error": "No active session"}), 404

    game_state = games_db[session_id]
    game_index = int(request.args.get("game", 0))

    if game_index >= len(game_state.games):
        return jsonify({"error": "Invalid game index"}), 400

    game_state.current_game_index = game_index
    game_state._load_current_game()

    game = game_state.games[game_index]

    return jsonify({
        "game_index": game_index,
        "headers": game["headers"],
        "total_plies": game["total_plies"],
    })


@app.route("/board")
def board():
    """Get board state at specific move."""
    session_id = session.get("session_id")
    if session_id not in games_db:
        return jsonify({"error": "No active session"}), 404

    game_state = games_db[session_id]
    ply = int(request.args.get("ply", 0))

    # Ensure game is loaded
    if not hasattr(game_state, 'moves') or game_state.moves is None:
        game_state._load_current_game()

    if ply < 0 or ply > game_state.total_plies:
        return jsonify({"error": "Invalid ply"}), 400

    game_state.current_ply = ply
    fen = game_state.get_fen_at_ply(ply)

    # Get puzzles for current game for move classification
    game_index = game_state.current_game_index
    puzzles = game_state._game_puzzles.get(game_index, [])
    # Create a map from ply to classification
    ply_classifications = {}
    for p in puzzles:
        ply_classifications[p["ply"]] = p["classification"]

    # Get current move info
    move_info = None
    move_list = []
    for i, mv in enumerate(game_state.moves):
        if i == ply:
            move_info = {k: v for k, v in mv.items() if k not in ("nags", "classification_from_nag")}
        # Add classification to move data, excluding non-JSON fields
        move_data = {k: v for k, v in mv.items() if k not in ("nags", "classification_from_nag")}
        move_data["classification"] = ply_classifications.get(i)
        move_list.append(move_data)

    return jsonify({
        "fen": fen,
        "ply": ply,
        "total_plies": game_state.total_plies,
        "current_move": move_info,
        "move_list": move_list,
        "move_classifications": ply_classifications,  # Also send full map for updating
    })


def analyze_position_with_time_limit(game_state: GameState, fen: str, time_limit: float) -> Dict[str, Any]:
    """Analyze a position with a specific time limit."""
    board = chess.Board(fen)

    with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
        engine.configure({"Skill Level": 20, "Threads": game_state.settings["threads"]})
        limit = chess.engine.Limit(time=time_limit)

        info = engine.analyse(board, limit)
        score = info.get("score")

        if score:
            if score.relative.mate():
                eval_score = score.relative.mate() * 100
            else:
                eval_score = score.relative.score(mate_score=10000)
        else:
            eval_score = 0

        # Flip score if it's black's turn, so display is always from white's perspective
        if score and board.turn == chess.BLACK:
            eval_score = -eval_score

        # Get WDL (always from white's perspective for consistency)
        wdl_pcts = None
        if score and hasattr(score, "wdl"):
            try:
                wdl = score.wdl()
                # chess 1.11.2+: PovWdl object - call white() to get WDL from white's perspective
                if hasattr(wdl, 'white') and callable(wdl.white):
                    white_wdl = wdl.white()
                    # Stockfish WDL sums to 1000, so raw counts are already in thousandths (‰)
                    win_chance = white_wdl.wins
                    draw_chance = white_wdl.draws
                    loss_chance = white_wdl.losses
                # chess < 1.11.2: direct attributes (unlikely with SF18)
                elif hasattr(wdl, 'wins') and hasattr(wdl, 'draws') and hasattr(wdl, 'losses'):
                    win_chance = wdl.wins
                    draw_chance = wdl.draws
                    loss_chance = wdl.losses
                else:
                    raise AttributeError("No WDL access method found")

                wdl_pcts = (win_chance, draw_chance, loss_chance)
                print(f"WDL (white perspective, ‰): win={win_chance:.0f}, draw={draw_chance:.0f}, loss={loss_chance:.0f}")
            except Exception as e:
                import traceback
                print(f"WDL error: {e}")
                traceback.print_exc()
                wdl_pcts = None

        # Get best moves
        best_moves = game_state._get_best_moves_for_limit(board, engine, limit)

        return {
            "evaluation": eval_score / 100.0,
            "wdl": wdl_pcts,
            "best_moves": best_moves,
        }


def _get_best_moves_for_limit(self, board: chess.Board, engine: Any, time_limit) -> List[Dict[str, Any]]:
    """Get top moves with scores for a position using a specific time limit."""
    num_moves = self.settings["num_best_moves"]
    if num_moves == 0:
        return []

    best_moves = []
    seen_moves = set()

    # Get principal variation (PV) info
    info = engine.analyse(board, time_limit, multipv=num_moves)

    for pv_info in info:
        if "pv" not in pv_info:
            continue

        score = pv_info.get("score")
        if not score:
            continue

        if score.relative.mate():
            cp = score.relative.mate() * 100
        else:
            cp = score.relative.score(mate_score=10000)

        move_san = board.san(pv_info["pv"][0])
        move_uci = pv_info["pv"][0].uci()

        if move_uci in seen_moves:
            continue
        seen_moves.add(move_uci)

        # Flip score if it's black's turn, so display is always from white's perspective
        if board.turn == chess.BLACK:
            cp = -cp

        best_moves.append({
            "san": move_san,
            "uci": move_uci,
            "score": cp / 100.0,
        })

    return best_moves


# Monkey patch the method into GameState
GameState._get_best_moves_for_limit = _get_best_moves_for_limit


@app.route("/analyze_quick")
def analyze_quick():
    """Quick analysis with 0.01s time limit for fast navigation."""
    session_id = session.get("session_id")
    if session_id not in games_db:
        return jsonify({"error": "No active session"}), 404

    game_state = games_db[session_id]

    if not game_state.settings["show_evaluation"]:
        return jsonify({"disabled": True})

    fen = request.args.get("fen")

    if fen:
        result = analyze_position_with_time_limit(game_state, fen, 0.01)
    else:
        # Use current position
        fen = game_state.get_fen_at_ply(game_state.current_ply)
        result = analyze_position_with_time_limit(game_state, fen, 0.01)

    # Only include best moves if enabled
    if not game_state.settings["show_best_moves"]:
        result["best_moves"] = []

    result["quick"] = True  # Mark as quick analysis
    return jsonify(result)


@app.route("/analyze")
def analyze():
    """Analyze position with Stockfish (full time limit)."""
    session_id = session.get("session_id")
    if session_id not in games_db:
        return jsonify({"error": "No active session"}), 404

    game_state = games_db[session_id]

    if not game_state.settings["show_evaluation"]:
        return jsonify({"disabled": True})

    fen = request.args.get("fen")

    if fen:
        result = analyze_position_with_time_limit(game_state, fen, game_state.settings["time_limit"])
    else:
        # Use current position
        fen = game_state.get_fen_at_ply(game_state.current_ply)
        result = analyze_position_with_time_limit(game_state, fen, game_state.settings["time_limit"])

    # Only include best moves if enabled
    if not game_state.settings["show_best_moves"]:
        result["best_moves"] = []

    result["quick"] = False  # Mark as full analysis
    return jsonify(result)


@app.route("/puzzles")
def puzzles():
    """Get filtered blunders/mistakes/inaccuracies (existing analysis only)."""
    session_id = session.get("session_id")
    if session_id not in games_db:
        return jsonify({"error": "No active session"}), 404

    game_state = games_db[session_id]
    min_class = request.args.get("min_class", "inaccuracy")

    puzzles = game_state.get_filtered_puzzles(min_class)

    return jsonify({
        "puzzles": puzzles,
        "total": len(puzzles),
        "current_puzzle_index": game_state.puzzle_settings["current_puzzle_index"],
        "total_games": len(game_state.games),
    })


@app.route("/puzzles_stream")
def puzzles_stream():
    """Stream puzzle analysis progress via SSE."""
    session_id = session.get("session_id")
    if session_id not in games_db:
        return jsonify({"error": "No active session"}), 404

    game_state = games_db[session_id]
    min_class = request.args.get("min_class", "inaccuracy")

    class_priority = {"blunder": 3, "mistake": 2, "inaccuracy": 1}
    min_priority = class_priority.get(min_class, 1)

    def generate():
        # Start async analysis
        queue = game_state.analyze_games_async(min_class)

        # Send initial state (already analyzed games)
        for game_idx in range(len(game_state.games)):
            if game_idx in game_state._game_analyzed and game_state._game_analyzed[game_idx]:
                puzzles = [
                    p for p in game_state._game_puzzles.get(game_idx, [])
                    if class_priority.get(p["classification"], 0) >= min_priority
                ]
                if puzzles:
                    game_name = game_state.games[game_idx]["headers"]["white"] + " vs " + game_state.games[game_idx]["headers"]["black"]
                    payload = {"game_index": game_idx, "puzzles": puzzles, "game_name": game_name}
                    yield "event: game_complete\n"
                    yield "data: " + json.dumps(payload) + "\n"
                    yield "\n"

        # Send start signal for new analysis
        payload = {"total_games": len(game_state.games)}
        yield "event: analysis_start\n"
        yield "data: " + json.dumps(payload) + "\n"
        yield "\n"

        # Stream analysis progress
        while True:
            try:
                message = queue.get(timeout=1)
                if message["type"] == "complete":
                    yield "event: complete\n"
                    yield "data: " + json.dumps(message) + "\n"
                    yield "\n"
                    send_complete = True
                    break

                elif message["type"] == "game_complete":
                    puzzles = [
                        p for p in message["puzzles"]
                        if class_priority.get(p["classification"], 0) >= min_priority
                    ]
                    game_name = game_state.games[message["game_index"]]["headers"]["white"] + " vs " + game_state.games[message["game_index"]]["headers"]["black"]
                    payload = {"game_index": message["game_index"], "puzzles": puzzles, "game_name": game_name}
                    yield "event: game_complete\n"
                    yield "data: " + json.dumps(payload) + "\n"
                    yield "\n"

                elif message["type"] == "game_start":
                    payload = {"game_index": message["game_index"], "game_name": message["game_name"]}
                    yield "event: game_start\n"
                    yield "data: " + json.dumps(payload) + "\n"
                    yield "\n"


                elif message["type"] == "move_progress":
                    yield "event: move_progress\n"
                    yield "data: " + json.dumps(message) + "\n"
                    yield "\n"
            except:
                if not game_state._analyzing:
                    break
                continue

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


@app.route("/goto_puzzle")
def goto_puzzle():
    """Navigate to specific puzzle position."""
    session_id = session.get("session_id")
    if session_id not in games_db:
        return jsonify({"error": "No active session"}), 404

    game_state = games_db[session_id]
    puzzle_index = int(request.args.get("puzzle", 0))

    result = game_state.get_puzzle_start_position(puzzle_index)

    if result is None:
        return jsonify({"error": "Invalid puzzle index"}), 400

    game_state.puzzle_settings["current_puzzle_index"] = puzzle_index
    game_state.current_ply = result["ply"]

    return jsonify(result)


@app.route("/puzzle_check", methods=["POST"])
def puzzle_check():
    """Check user's move in puzzle mode."""
    session_id = session.get("session_id")
    if session_id not in games_db:
        return jsonify({"error": "No active session"}), 404

    game_state = games_db[session_id]
    data = request.get_json()

    puzzle_index = game_state.puzzle_settings["current_puzzle_index"]
    move_uci = data.get("move")

    if not move_uci:
        return jsonify({"error": "No move provided"}), 400

    try:
        result = game_state.check_puzzle_move(puzzle_index, move_uci)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # If correct and there's a next puzzle, advance
    if result["correct"]:
        filtered = game_state.get_filtered_puzzles(
            game_state.puzzle_settings["min_class"]
        )
        next_index = puzzle_index + 1
        if next_index < len(filtered):
            result["next_puzzle"] = next_index
        else:
            result["next_puzzle"] = None

    return jsonify(result)


@app.route("/puzzle_settings", methods=["POST"])
def puzzle_settings():
    """Update puzzle mode settings."""
    session_id = session.get("session_id")
    if session_id not in games_db:
        return jsonify({"error": "No active session"}), 404

    game_state = games_db[session_id]
    data = request.get_json()

    if "puzzle_mode" in data:
        game_state.puzzle_settings["puzzle_mode"] = data["puzzle_mode"]
    if "success_criterion" in data:
        game_state.puzzle_settings["success_criterion"] = data["success_criterion"]
    if "min_class" in data:
        game_state.puzzle_settings["min_class"] = data["min_class"]
    if "classification_mode" in data:
        game_state.puzzle_settings["classification_mode"] = data["classification_mode"]

    return jsonify({"success": True})


@app.route("/settings", methods=["POST"])
def settings():
    """Update general settings."""
    session_id = session.get("session_id")
    if session_id not in games_db:
        return jsonify({"error": "No active session"}), 404

    game_state = games_db[session_id]
    data = request.get_json()

    if "show_evaluation" in data:
        game_state.settings["show_evaluation"] = data["show_evaluation"]
    if "show_best_moves" in data:
        game_state.settings["show_best_moves"] = data["show_best_moves"]
    if "num_best_moves" in data:
        game_state.settings["num_best_moves"] = data["num_best_moves"]
    if "time_limit" in data:
        game_state.settings["time_limit"] = float(data["time_limit"])
    if "puzzle_time_limit" in data:
        game_state.settings["puzzle_time_limit"] = float(data["puzzle_time_limit"])

    return jsonify({"success": True})


@app.route("/load_sample")
def load_sample():
    """Load sample.pgn file."""
    sample_path = os.path.join(
        os.path.dirname(__file__), "..", "sample.pgn"
    )

    if not os.path.exists(sample_path):
        return jsonify({"error": "Sample file not found"}), 404

    try:
        with open(sample_path, "r") as f:
            pgn_string = f.read()
    except Exception as e:
        return jsonify({"error": f"Failed to read sample file: {e}"}), 400

    # Create new game state
    session_id = str(datetime.now().timestamp())
    game_state = GameState(pgn_string)
    games_db[session_id] = game_state

    session["session_id"] = session_id

    return jsonify({
        "session_id": session_id,
        "num_games": len(game_state.games),
    })


@app.route("/download_annotated_pgn")
def download_annotated_pgn():
    """Download PGN with annotations (blunder/mistake/inaccuracy) added."""
    session_id = session.get("session_id")
    if session_id not in games_db:
        return jsonify({"error": "No active session"}), 404

    game_state = games_db[session_id]
    min_class = request.args.get("min_class", "inaccuracy")

    # Ensure all games are analyzed
    class_priority = {"blunder": 3, "mistake": 2, "inaccuracy": 1}
    min_priority = class_priority.get(min_class, 1)

    # Build annotated PGN
    pgn_output = StringIO()

    for game_idx, game_data in enumerate(game_state.games):
        # Get puzzles for this game
        puzzles = game_state._game_puzzles.get(game_idx, [])
        puzzle_by_ply = {p["ply"]: p for p in puzzles}

        # Build game with annotations
        game = chess.pgn.Game()

        # Copy headers with proper capitalization
        header_mapping = {
            "white": "White",
            "black": "Black",
            "event": "Event",
            "date": "Date",
            "result": "Result",
            "white_elo": "WhiteElo",
            "black_elo": "BlackElo",
        }
        for key, value in game_data["headers"].items():
            pgn_key = header_mapping.get(key, key.capitalize())
            if value and value != "?":
                game.headers[pgn_key] = value

        # Add moves with annotations
        board = chess.Board()
        node = game

        for i, move_info in enumerate(game_data["moves"]):
            move = chess.Move.from_uci(move_info["uci"])
            node = node.add_main_variation(move)

            # Add NAG annotation if this move was classified
            if i in puzzle_by_ply:
                puzzle = puzzle_by_ply[i]
                classification = puzzle["classification"]
                if class_priority.get(classification, 0) >= min_priority:
                    if classification == "blunder":
                        node.nags.add(4)  # ??
                    elif classification == "mistake":
                        node.nags.add(2)  # ?
                    elif classification == "inaccuracy":
                        node.nags.add(6)  # ?!

        # Write game to output
        pgn_output.write(str(game))
        pgn_output.write("\n\n")

    # Return as downloadable file
    from flask import Response
    return Response(
        pgn_output.getvalue(),
        mimetype="application/x-chess-pgn",
        headers={
            "Content-Disposition": "attachment; filename=annotated_games.pgn"
        }
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chess Puzzle Generator Server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"Port to run the server on (default: {DEFAULT_PORT})")
    parser.add_argument("--debug", action="store_true",
                        help="Run in debug mode")
    args = parser.parse_args()

    app.run(host="0.0.0.0", port=args.port, debug=args.debug)
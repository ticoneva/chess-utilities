"""
Chess Puzzle Generator - Flask Backend
A web interface for viewing PGN files with puzzle mode for practicing blunders, mistakes, and inaccuracies.
"""

import argparse
import json
import os
from datetime import datetime
from io import StringIO
from typing import Dict, List, Optional, Any

from flask import Flask, render_template, request, jsonify, session

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

        # Default settings
        self.settings = {
            "show_evaluation": True,
            "show_best_moves": True,
            "num_best_moves": 3,
            "time_limit": 0.5,
            "threads": 4,
        }

        # Puzzle mode settings
        self.puzzle_settings = {
            "puzzle_mode": False,
            "success_criterion": "top3",  # top3, best, any
            "current_puzzle_index": -1,
            "min_class": "blunder",  # inaccuracy, mistake, blunder
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

            # Convert game to move list
            board = game.board()
            move_list = []
            node = game
            ply = 0

            while node.variations:
                node = node.variations[0]
                move = node.move
                move_list.append({
                    "san": board.san(move),
                    "uci": move.uci(),
                    "ply": ply,
                    "comment": node.comment,
                })
                board.push(move)
                ply += 1

            self.games.append({
                "headers": headers,
                "moves": move_list,
                "total_plies": len(move_list),
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

    def _analyze_game_moves(self, game_index: int) -> None:
        """Find blunders/mistakes/inaccuracies for a specific game using Stockfish."""
        if game_index in self._game_analyzed and self._game_analyzed[game_index]:
            # Already analyzed
            return

        if game_index >= len(self.games):
            return

        game_data = self.games[game_index]
        moves: List[Dict[str, Any]] = game_data["moves"]

        if not moves:
            self._game_puzzles[game_index] = []
            self._game_analyzed[game_index] = True
            return

        board = chess.Board()
        puzzles = []

        with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
            engine.configure({"Skill Level": 20, "Threads": self.settings["threads"]})
            time_limit = chess.engine.Limit(time=self.settings["time_limit"])

            for i, move_info in enumerate(moves):
                move = chess.Move.from_uci(move_info["uci"])

                # Analyze before the move
                info = engine.analyse(board, time_limit)
                score = info.get("score")
                before_cp = score.relative.score(mate_score=10000) if score else 0
                before_eval = before_cp / 100.0

                # Get WDL if available
                if score and hasattr(score, "wdl"):
                    wdl = score.wdl()
                    try:
                        before_wdl = (wdl.win_chance(), wdl.draw_chance(), wdl.loss_chance())
                    except:
                        before_wdl = None
                else:
                    before_wdl = None

                # Make the move
                board.push(move)

                # Analyze after the move
                info = engine.analyse(board, time_limit)
                score = info.get("score")
                after_cp = score.relative.score(mate_score=10000) if score else 0
                after_eval = after_cp / 100.0

                # Get WDL after move
                if score and hasattr(score, "wdl"):
                    wdl = score.wdl()
                    try:
                        after_wdl = (wdl.win_chance(), wdl.draw_chance(), wdl.loss_chance())
                    except:
                        after_wdl = None
                else:
                    after_wdl = None

                # Calculate evaluation change
                # For white moves: white made the move, so positive change = bad for white
                # For black moves: black made the move, so positive change = bad for black
                # We want the change in the perspective of the player who made the move
                if i % 2 == 0:  # White's move
                    eval_change = before_eval - after_eval
                else:  # Black's move
                    eval_change = after_eval - before_eval

                # Classify move
                classification = None
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
        """Filter puzzles by minimum classification (with lazy analysis)."""
        class_priority = {"blunder": 3, "mistake": 2, "inaccuracy": 1}
        min_priority = class_priority.get(min_class, 1)

        # Analyze all games that haven't been analyzed yet (lazy loading)
        for game_idx in range(len(self.games)):
            if game_idx not in self._game_analyzed or not self._game_analyzed[game_idx]:
                self._analyze_game_moves(game_idx)

        # Collect all puzzles from all games
        all_puzzles = []
        for game_idx in range(len(self.games)):
            if game_idx in self._game_puzzles:
                all_puzzles.extend(self._game_puzzles[game_idx])

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
        for i in range(ply):
            if i < len(self.moves):
                board.push(chess.Move.from_uci(self.moves[i]["uci"]))
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
        fen = self.get_fen_at_ply(ply)
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
            time_limit = chess.engine.Limit(time=self.settings["time_limit"])

            # Pop the move to analyze the position
            board.pop()
            best_moves_info = self._get_best_moves(board, engine, time_limit)

            # Evaluate after user's move
            board.push(move)
            info = engine.analyse(board, time_limit)
            score = info.get("score")

            if score and score.relative.mate():
                after_cp = score.relative.mate() * 100
            else:
                after_cp = score.relative.score(mate_score=10000) if score else 0

            after_eval = after_cp / 100.0

        # Get the original position eval before the blunder move
        board.pop()  # Back to before user move
        info2 = engine.analyse(board, time_limit)
        score2 = info2.get("score")

        if score2 and score2.relative.mate():
            before_cp = score2.relative.mate() * 100
        else:
            before_cp = score2.relative.score(mate_score=10000) if score2 else 0

        before_eval = before_cp / 100.0

        # Calculate eval change (positive = bad for player who just moved)
        current_turn = board.turn
        board.push(move)
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
                message = "Correct! You found the best move."
            else:
                message = "Not the best move. Try again."

        elif criterium == "top3":
            if move_found and move_rank <= 3:
                # Also check it's not an inaccuracy
                board.pop()
                base_score = before_cp
                board.push(move)
                info3 = engine.analyse(board, time_limit)
                score3 = info3.get("score")
                if score3 and score3.relative.mate():
                    new_cp = score3.relative.mate() * 100
                else:
                    new_cp = score3.relative.score(mate_score=10000) if score3 else 0
                new_eval = new_cp / 100.0

                # Change in perspective of the player who made the move
                if board.turn == chess.BLACK:  # White made move
                    change = before_eval - new_eval
                else:  # Black made move
                    change = new_eval - before_eval

                if change >= INACCURACY_THRESHOLD / 100.0:
                    message = "Move is top 3 but still an inaccuracy. Try again."
                else:
                    correct = True
                    message = "Correct! Good move (in top 3)."
                board.pop()
            else:
                message = "Not in top 3 moves. Try again."

        else:  # any (any good move)
            board.pop()
            if eval_change < INACCURACY_THRESHOLD / 100.0:
                correct = True
                message = "Correct! That's a good move."
            else:
                message = "That's an inaccuracy or worse. Try again."

        return {
            "correct": correct,
            "message": message,
            "move_rank": move_rank,
            "move_score": move_score,
            "best_moves": best_moves_info,
            "eval_change": eval_change,
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

    if ply < 0 or ply > game_state.total_plies:
        return jsonify({"error": "Invalid ply"}), 400

    game_state.current_ply = ply
    fen = game_state.get_fen_at_ply(ply)

    # Get current move info
    move_info = None
    move_list = []
    for i, mv in enumerate(game_state.moves):
        if i == ply:
            move_info = mv
        move_list.append(mv)

    return jsonify({
        "fen": fen,
        "ply": ply,
        "total_plies": game_state.total_plies,
        "current_move": move_info,
        "move_list": move_list,
    })


@app.route("/analyze")
def analyze():
    """Analyze position with Stockfish."""
    session_id = session.get("session_id")
    if session_id not in games_db:
        return jsonify({"error": "No active session"}), 404

    game_state = games_db[session_id]

    if not game_state.settings["show_evaluation"]:
        return jsonify({"disabled": True})

    fen = request.args.get("fen")

    if fen:
        result = game_state.analyze_position(fen)
    else:
        # Use current position
        fen = game_state.get_fen_at_ply(game_state.current_ply)
        result = game_state.analyze_position(fen)

    # Only include best moves if enabled
    if not game_state.settings["show_best_moves"]:
        result["best_moves"] = []

    return jsonify(result)


@app.route("/puzzles")
def puzzles():
    """Get filtered blunders/mistakes/inaccuracies."""
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
    })


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

    result = game_state.check_puzzle_move(puzzle_index, move_uci)

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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chess Puzzle Generator Server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"Port to run the server on (default: {DEFAULT_PORT})")
    parser.add_argument("--debug", action="store_true",
                        help="Run in debug mode")
    args = parser.parse_args()

    app.run(host="0.0.0.0", port=args.port, debug=args.debug)
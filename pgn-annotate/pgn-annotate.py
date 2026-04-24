#!/usr/bin/env python3
"""
PGN Annotation Tool - Analyzes chess games with Stockfish and adds blunder/mistake/inaccuracy notations.

Usage:
    python pgn-annotate.py --input game.pgn --output annotated.pgn [options]

Features:
    - Parallel processing of games across multiple processes
    - Per-instance Stockfish thread control
    - User-specifiable analysis time per move
"""

import argparse
import os
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from io import StringIO

import chess
import chess.pgn
import chess.engine


# Classification thresholds (in centipawns)
BLUNDER_THRESHOLD = 300    # >= 3.00 pawn advantage lost
MISTAKE_THRESHOLD = 100    # >= 1.00 pawn advantage lost
INACCURACY_THRESHOLD = 50  # >= 0.50 pawn advantage lost

# NAG codes for annotations
NAG_BLUNDER = 4      # ??
NAG_MISTAKE = 2      # ?
NAG_INACCURACY = 6   # ?!


@dataclass
class AnalysisResult:
    """Result of analyzing a single game."""
    game_index: int
    annotated_moves: List[Dict[str, Any]]
    total_moves: int
    blunders: int
    mistakes: int
    inaccuracies: int


def analyze_single_game(
    pgn_string: str,
    game_index: int,
    time_per_move: float,
    stockfish_threads: int,
    stockfish_path: str,
) -> AnalysisResult:
    """
    Analyze a single game with Stockfish and return annotated moves.

    Args:
        pgn_string: The full PGN content
        game_index: Index of the game to analyze (0-based)
        time_per_move: Time in seconds to spend analyzing each move
        stockfish_threads: Number of threads for Stockfish
        stockfish_path: Path to Stockfish executable

    Returns:
        AnalysisResult with annotated moves and statistics
    """
    # Parse PGN and get the specific game
    pgn_io = StringIO(pgn_string)
    game_count = 0
    target_game = None

    while True:
        game = chess.pgn.read_game(pgn_io)
        if game is None:
            break
        if game_count == game_index:
            target_game = game
            break
        game_count += 1

    if target_game is None:
        raise ValueError(f"Game index {game_index} not found in PGN file")

    # Extract moves from the game
    moves_data = []
    board = target_game.board()
    node = target_game

    while node.variations:
        node = node.variations[0]
        move = node.move
        moves_data.append({
            "move": move,
            "node": node,
            "san": board.san(move),
        })
        board.push(move)

    # Analyze each move with Stockfish
    annotated_moves = []
    blunders = 0
    mistakes = 0
    inaccuracies = 0

    with chess.engine.SimpleEngine.popen_uci(stockfish_path) as engine:
        engine.configure({
            "Threads": stockfish_threads,
            "Skill Level": 20,
        })
        time_limit = chess.engine.Limit(time=time_per_move)

        # Reset board for analysis
        board = target_game.board()

        for i, move_data in enumerate(moves_data):
            move = move_data["move"]
            san = move_data["san"]
            node = move_data["node"]

            # Analyze position before the move
            info_before = engine.analyse(board, time_limit)
            score_before = info_before.get("score")
            before_cp = score_before.white().score(mate_score=10000) if score_before else 0

            # Make the move
            board.push(move)

            # Analyze position after the move
            info_after = engine.analyse(board, time_limit)
            score_after = info_after.get("score")
            after_cp = score_after.white().score(mate_score=10000) if score_after else 0

            # Calculate evaluation change (from the perspective of the player who just moved)
            if i % 2 == 0:  # White's move
                eval_change = before_cp - after_cp
            else:  # Black's move
                eval_change = after_cp - before_cp

            # Classify the move
            classification = None
            nag = None

            if eval_change >= BLUNDER_THRESHOLD:
                classification = "blunder"
                nag = NAG_BLUNDER
                blunders += 1
            elif eval_change >= MISTAKE_THRESHOLD:
                classification = "mistake"
                nag = NAG_MISTAKE
                mistakes += 1
            elif eval_change >= INACCURACY_THRESHOLD:
                classification = "inaccuracy"
                nag = NAG_INACCURACY
                inaccuracies += 1

            # Store annotation
            annotated_moves.append({
                "san": san,
                "uci": move.uci(),
                "before_eval": before_cp / 100.0,
                "after_eval": after_cp / 100.0,
                "eval_change": eval_change / 100.0,
                "classification": classification,
                "nag": nag,
            })

            # Add NAG to the node if there's a classification
            if nag is not None:
                node.nags.add(nag)

    return AnalysisResult(
        game_index=game_index,
        annotated_moves=annotated_moves,
        total_moves=len(moves_data),
        blunders=blunders,
        mistakes=mistakes,
        inaccuracies=inaccuracies,
    )


def load_pgn_games(pgn_path: str) -> Tuple[str, int]:
    """
    Load PGN file and count games.

    Args:
        pgn_path: Path to the PGN file

    Returns:
        Tuple of (pgn_content, game_count)
    """
    with open(pgn_path, "r") as f:
        pgn_content = f.read()

    # Count games
    pgn_io = StringIO(pgn_content)
    game_count = 0
    while chess.pgn.read_game(pgn_io) is not None:
        game_count += 1

    return pgn_content, game_count


def save_annotated_pgn(
    pgn_path: str,
    output_path: str,
    results: List[AnalysisResult],
) -> None:
    """
    Save annotated PGN to file.

    Args:
        pgn_path: Original PGN file path
        output_path: Output file path for annotated PGN
        results: List of analysis results
    """
    with open(pgn_path, "r") as f:
        pgn_content = f.read()

    pgn_io = StringIO(pgn_content)
    output_io = StringIO()

    game_index = 0
    result_map = {r.game_index: r for r in results}

    while True:
        game = chess.pgn.read_game(pgn_io)
        if game is None:
            break

        if game_index in result_map:
            result = result_map[game_index]

            # Apply annotations to the game
            node = game
            move_idx = 0
            for move_annotation in result.annotated_moves:
                if node.variations:
                    node = node.variations[0]
                    if move_annotation["nag"] is not None:
                        node.nags.add(move_annotation["nag"])
                    move_idx += 1

        # Write game to output
        game = chess.pgn.read_game(StringIO(pgn_content.split("\n\n")[0] if game_index == 0 else pgn_content))
        game_index += 1

    # Re-read and write with proper annotations
    pgn_io = StringIO(pgn_content)
    output_games = []

    game_index = 0
    result_map = {r.game_index: r for r in results}

    while True:
        game = chess.pgn.read_game(pgn_io)
        if game is None:
            break

        if game_index in result_map:
            result = result_map[game_index]

            # Apply annotations to the game
            node = game
            for move_annotation in result.annotated_moves:
                if node.variations:
                    node = node.variations[0]
                    if move_annotation["nag"] is not None:
                        node.nags.add(move_annotation["nag"])

        output_games.append(game)
        game_index += 1

    # Write all games to output file
    with open(output_path, "w") as f:
        for game in output_games:
            game.accept(chess.pgn.FileExporter(f))


def process_games_parallel(
    pgn_path: str,
    output_path: str,
    num_processes: int,
    time_per_move: float,
    stockfish_threads: int,
    stockfish_path: str,
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    Process all games in a PGN file using parallel processing.

    Args:
        pgn_path: Path to input PGN file
        output_path: Path to output annotated PGN file
        num_processes: Number of parallel processes
        time_per_move: Time in seconds per move analysis
        stockfish_threads: Number of threads per Stockfish instance
        stockfish_path: Path to Stockfish executable
        verbose: Whether to print progress

    Returns:
        Dictionary with analysis statistics
    """
    if verbose:
        print(f"Loading PGN file: {pgn_path}")

    pgn_content, total_games = load_pgn_games(pgn_path)

    if verbose:
        print(f"Found {total_games} games to analyze")
        print(f"Configuration:")
        print(f"  - Parallel processes: {num_processes}")
        print(f"  - Stockfish threads per process: {stockfish_threads}")
        print(f"  - Time per move: {time_per_move}s")
        print(f"  - Stockfish path: {stockfish_path}")
        print()

    start_time = time.time()
    results = []

    # Create list of game indices to process
    game_indices = list(range(total_games))

    with ProcessPoolExecutor(max_workers=num_processes) as executor:
        # Submit all analysis tasks
        future_to_index = {
            executor.submit(
                analyze_single_game,
                pgn_content,
                game_index,
                time_per_move,
                stockfish_threads,
                stockfish_path,
            ): game_index
            for game_index in game_indices
        }

        # Collect results as they complete
        for future in as_completed(future_to_index):
            game_index = future_to_index[future]
            try:
                result = future.result()
                results.append(result)

                if verbose:
                    print(f"Game {game_index + 1}/{total_games} analyzed: "
                          f"{result.blunders} blunders, {result.mistakes} mistakes, "
                          f"{result.inaccuracies} inaccuracies")
            except Exception as e:
                print(f"Error analyzing game {game_index}: {e}", file=sys.stderr)

    # Sort results by game index
    results.sort(key=lambda r: r.game_index)

    # Save annotated PGN
    if verbose:
        print(f"\nSaving annotated PGN to: {output_path}")

    save_annotated_pgn(pgn_path, output_path, results)

    # Calculate statistics
    total_time = time.time() - start_time
    total_blunders = sum(r.blunders for r in results)
    total_mistakes = sum(r.mistakes for r in results)
    total_inaccuracies = sum(r.inaccuracies for r in results)
    total_moves = sum(r.total_moves for r in results)

    stats = {
        "total_games": total_games,
        "total_moves": total_moves,
        "total_blunders": total_blunders,
        "total_mistakes": total_mistakes,
        "total_inaccuracies": total_inaccuracies,
        "total_time": total_time,
        "avg_time_per_move": total_time / total_moves if total_moves > 0 else 0,
    }

    return stats


def find_stockfish() -> str:
    """Try to find Stockfish executable."""
    # Common paths to check
    common_paths = [
        "/usr/local/bin/stockfish",
        "/usr/bin/stockfish",
        "/opt/stockfish/stockfish",
        os.path.expanduser("~/stockfish"),
        "stockfish",  # Will search PATH
    ]

    for path in common_paths:
        if os.path.exists(path) or shutil.which(path):
            return path

    raise FileNotFoundError(
        "Stockfish not found. Please install Stockfish or specify the path "
        "using --stockfish-path option."
    )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Analyze PGN chess games with Stockfish and add blunder/mistake/inaccuracy notations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage with defaults
  python pgn-annotate.py --input games.pgn --output annotated.pgn

  # Custom parallel processing and analysis time
  python pgn-annotate.py --input games.pgn --output annotated.pgn \\
      --processes 4 --threads 2 --time 1.0

  # Quick analysis
  python pgn-annotate.py --input games.pgn --output annotated.pgn \\
      --time 0.25 --processes 8

Classification thresholds (fixed):
  - Blunder (??):   >= 3.00 pawn evaluation loss
  - Mistake (?):    >= 1.00 pawn evaluation loss
  - Inaccuracy (?!): >= 0.50 pawn evaluation loss
        """
    )

    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Input PGN file path"
    )

    parser.add_argument(
        "--output", "-o",
        required=True,
        help="Output PGN file path (annotated)"
    )

    parser.add_argument(
        "--processes", "-p",
        type=int,
        default=4,
        help="Number of parallel processes for game analysis (default: 4)"
    )

    parser.add_argument(
        "--threads", "-t",
        type=int,
        default=2,
        help="Number of CPU threads per Stockfish instance (default: 2)"
    )

    parser.add_argument(
        "--time",
        type=float,
        default=0.5,
        help="Time in seconds to spend analyzing each move (default: 0.5)"
    )

    parser.add_argument(
        "--stockfish-path",
        type=str,
        default=None,
        help="Path to Stockfish executable (default: auto-detect)"
    )

    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress progress output"
    )

    args = parser.parse_args()

    # Validate input file
    if not os.path.exists(args.input):
        print(f"Error: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    # Find Stockfish
    stockfish_path = args.stockfish_path or find_stockfish()

    if not os.path.exists(stockfish_path):
        print(f"Error: Stockfish not found at: {stockfish_path}", file=sys.stderr)
        sys.exit(1)

    # Validate arguments
    if args.processes < 1:
        print("Error: --processes must be at least 1", file=sys.stderr)
        sys.exit(1)

    if args.threads < 1:
        print("Error: --threads must be at least 1", file=sys.stderr)
        sys.exit(1)

    if args.time <= 0:
        print("Error: --time must be positive", file=sys.stderr)
        sys.exit(1)

    # Run analysis
    try:
        stats = process_games_parallel(
            pgn_path=args.input,
            output_path=args.output,
            num_processes=args.processes,
            time_per_move=args.time,
            stockfish_threads=args.threads,
            stockfish_path=stockfish_path,
            verbose=not args.quiet,
        )

        if not args.quiet:
            print("\n" + "=" * 50)
            print("Analysis Complete!")
            print("=" * 50)
            print(f"Games analyzed:    {stats['total_games']}")
            print(f"Total moves:       {stats['total_moves']}")
            print(f"Blunders (??):     {stats['total_blunders']}")
            print(f"Mistakes (?):      {stats['total_mistakes']}")
            print(f"Inaccuracies (?!): {stats['total_inaccuracies']}")
            print(f"Total time:        {stats['total_time']:.2f}s")
            print(f"Avg time/move:     {stats['avg_time_per_move']:.3f}s")
            print(f"Output saved to:   {args.output}")
            print("=" * 50)

    except Exception as e:
        print(f"Error during analysis: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

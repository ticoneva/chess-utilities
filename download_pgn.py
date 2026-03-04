#!/usr/bin/env python3
"""Download all games for a chess.com username from Chess.com API and save PGN files."""

import argparse
import json
import os
from datetime import datetime
import urllib.request


def download_chess_games(
    username,
    output_file=None,
    start_date=None,
    end_date=None,
    max_games_per_file=None,
    verbose=True,
):
    """
    Download all chess games for a given username from Chess.com.

    Args:
        username: Chess.com username
        output_file: Path to save PGN file(s). If None, uses {username}.pgn.
                     If max_games_per_file is specified, files will be named
                     {output_file_base}-1.pgn, {output_file_base}-2.pgn, etc.
        start_date: Start date as datetime object. Defaults to Jan 1, 2025.
        end_date: End date as datetime object. Defaults to current date.
        max_games_per_file: Maximum number of games per file. If None, all games
                          are saved to a single file.
        verbose: Whether to print progress messages.

    Returns:
        dict: Summary with total games and output file(s) created.

    Raises:
        ValueError: If username does not exist on Chess.com.
    """
    # Check if username exists first
    try:
        profile_url = f"https://api.chess.com/pub/player/{username}"
        with urllib.request.urlopen(profile_url) as response:
            profile_data = json.loads(response.read().decode())
        if verbose:
            print(f"Username '{username}' found: {profile_data.get('name', username)}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ValueError(f"Username '{username}' does not exist on Chess.com")
        raise
    except Exception as e:
        raise RuntimeError(f"Error checking username: {e}")

    # Set default output path
    if output_file is None:
        output_file = os.path.join(os.getcwd(), f"{username}.pgn")

    # Set default dates
    if start_date is None:
        start_date = datetime(2025, 1, 1)
    if end_date is None:
        end_date = datetime.now()

    all_pgns = []

    date = start_date
    while date <= end_date:
        year = date.year
        month = date.month
        url = f"https://api.chess.com/pub/player/{username}/games/{year}/{month:02d}"

        if verbose:
            print(f"Fetching {year}-{month:02d}...")

        try:
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read().decode())

            games = data.get('games', [])
            if verbose:
                print(f"  Found {len(games)} games")

            # Extract PGNs from this month
            for game in games:
                pgn = game.get('pgn')
                if pgn:
                    all_pgns.append(pgn)

        except urllib.error.HTTPError as e:
            if e.code == 404:
                if verbose:
                    print(f"  No games found (404)")
            else:
                if verbose:
                    print(f"  HTTP Error: {e}")
        except Exception as e:
            if verbose:
                print(f"  Error: {e}")

        # Move to next month
        if date.month == 12:
            date = date.replace(year=date.year + 1, month=1)
        else:
            date = date.replace(month=date.month + 1)

    # Save PGNs to file(s)
    output_files = []
    if verbose:
        print(f"\nSaving {len(all_pgns)} games...")

    if max_games_per_file is None or len(all_pgns) <= max_games_per_file:
        # Save all games to single file
        combined_pgn = "\n\n".join(all_pgns)
        with open(output_file, 'w') as f:
            f.write(combined_pgn)
        output_files.append(output_file)
        if verbose:
            print(f"  Saved to: {output_file}")
    else:
        # Split into multiple files
        base_path = os.path.splitext(output_file)[0]
        num_parts = (len(all_pgns) + max_games_per_file - 1) // max_games_per_file

        for i in range(num_parts):
            start_idx = i * max_games_per_file
            end_idx = start_idx + max_games_per_file
            part_pgns = all_pgns[start_idx:end_idx]

            part_filename = f"{base_path}-{i + 1}.pgn"
            part_content = "\n\n".join(part_pgns)

            with open(part_filename, 'w') as f:
                f.write(part_content)
            output_files.append(part_filename)

            if verbose:
                games_in_part = len(part_pgns)
                print(f"  Saved {games_in_part} games to: {part_filename}")

    result = {
        'total_games': len(all_pgns),
        'output_files': output_files,
    }

    if verbose:
        print(f"\nDone! Summary:")
        print(f"  Total games: {result['total_games']}")
        print(f"  Output files: {len(result['output_files'])}")
        for f in result['output_files']:
            print(f"    - {f}")

    return result


def main():
    """Command-line interface for downloading chess games."""
    parser = argparse.ArgumentParser(
        description="Download all chess games for a Chess.com username.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s joj0108goat
  %(prog)s magnuscarlsen --output-file all_games.pgn
  %(prog)s username --start-date 2024-01-01 --end-date 2024-12-31
  %(prog)s username --max-games 100
        """,
    )
    parser.add_argument(
        'username',
        help='Chess.com username'
    )
    parser.add_argument(
        '--output-file',
        help='Path to save PGN file (default: ./<username>.pgn)',
        default=None,
    )
    parser.add_argument(
        '--start-date',
        help='Start date (YYYY-MM-DD format, default: 2025-01-01)',
        default=None,
    )
    parser.add_argument(
        '--end-date',
        help='End date (YYYY-MM-DD format, default: today)',
        default=None,
    )
    parser.add_argument(
        '--max-games',
        type=int,
        help='Maximum games per file. If exceeded, splits into multiple files '
             '(e.g., username-1.pgn, username-2.pgn)',
        default=None,
    )
    parser.add_argument(
        '--quiet',
        '-q',
        action='store_true',
        help='Suppress progress messages',
    )

    args = parser.parse_args()

    # Parse dates if provided
    start_date = None
    end_date = None
    date_format = "%Y-%m-%d"

    if args.start_date:
        try:
            start_date = datetime.strptime(args.start_date, date_format)
        except ValueError:
            parser.error(f"Invalid start date format. Use YYYY-MM-DD")

    if args.end_date:
        try:
            end_date = datetime.strptime(args.end_date, date_format)
        except ValueError:
            parser.error(f"Invalid end date format. Use YYYY-MM-DD")

    try:
        download_chess_games(
            username=args.username,
            output_file=args.output_file,
            start_date=start_date,
            end_date=end_date,
            max_games_per_file=args.max_games,
            verbose=not args.quiet,
        )
    except ValueError as e:
        print(f"Error: {e}")
        exit(1)
    except Exception as e:
        print(f"Error: {e}")
        exit(1)


if __name__ == "__main__":
    main()
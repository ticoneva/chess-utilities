"""Test script to verify download_pgn.py is importable as a module."""

from download_pgn import download_chess_games
from datetime import datetime

# Test importing and calling the function
print("Testing importable module functionality...")
print("=" * 50)

try:
    # Test with a non-existent username
    print("\n1. Testing error handling for non-existent user...")
    try:
        result = download_chess_games(
            username="thisusernamedoesnotexist12345",
            verbose=True
        )
    except ValueError as e:
        print(f"✓ Error handling works: {e}")

    # Test with valid username (single file, no split)
    print("\n2. Testing with valid username (single file)...")
    result = download_chess_games(
        username="joj0108goat",
        start_date=datetime(2025, 1, 1),
        end_date=datetime(2025, 1, 31),
        output_file="test_single.pgn",
        verbose=True
    )
    print(f"✓ Successfully imported and called function")
    print(f"  Total games: {result['total_games']}")
    print(f"  Output files: {result['output_files']}")

    # Test with max_games_per_file (split)
    print("\n3. Testing with max_games_per_file=2 (split)...")
    result = download_chess_games(
        username="joj0108goat",
        start_date=datetime(2025, 1, 1),
        end_date=datetime(2025, 1, 31),
        output_file="test_split.pgn",
        max_games_per_file=2,
        verbose=True
    )
    print(f"✓ Successfully split games into multiple files")
    print(f"  Total games: {result['total_games']}")
    print(f"  Output files: {result['output_files']}")

except ImportError as e:
    print(f"✗ Import failed: {e}")
except Exception as e:
    print(f"✗ Error: {e}")

print("\n" + "=" * 50)
print("Test complete!")
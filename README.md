# Chess.com PGN Downloader

A command-line tool and Python module for downloading chess games from Chess.com API and saving them as PGN files.

## Features

- Download all games for any Chess.com username
- Optionally split large collections into multiple files (e.g., `username-1.pgn`, `username-2.pgn`)
- Customizable date ranges
- Informative error messages for non-existent usernames
- Works as both a CLI command and importable Python module

## Installation

No installation required. Ensure you have Python 3.x installed.

## Usage

### Command Line

Basic usage - downloads all games to `username.pgn`:

```bash
./download-pgn <username>
```

Examples:

```bash
# Download magnuscarlsen's games
./download-pgn magnuscarlsen

# Download to custom output file
./download-pgn joj0108goat --output-file ./my_games.pgn

# Set date range
./download-pgn username --start-date 2024-01-01 --end-date 2024-12-31

# Split into files with max 100 games each
./download-pgn username --max-games 100

# Quiet mode (suppress progress messages)
./download-pgn username -q
```

Command-line options:

| Option | Description |
|--------|-------------|
| `username` | Chess.com username (required) |
| `--output-file` | Path to save PGN file (default: `./<username>.pgn`) |
| `--start-date` | Start date in YYYY-MM-DD format (default: 2025-01-01) |
| `--end-date` | End date in YYYY-MM-DD format (default: today) |
| `--max-games` | Maximum games per file. Splits into multiple files if exceeded |
| `--quiet`, `-q` | Suppress progress messages |

### Python Module

Import and use programmatically:

```python
from download_pgn import download_chess_games
from datetime import datetime

# Download all games to single file
result = download_chess_games(
    username="magnuscarlsen",
    output_file="./games.pgn",
    verbose=True
)

# Download with date range
result = download_chess_games(
    username="username",
    start_date=datetime(2024, 1, 1),
    end_date=datetime(2024, 12, 31),
    verbose=True
)

# Split into multiple files with max 500 games each
result = download_chess_games(
    username="username",
    max_games_per_file=500,
    verbose=True
)

# Access results
print(f"Total games: {result['total_games']}")
print(f"Output files: {result['output_files']}")
```

## Function Reference

### `download_chess_games()`

```python
download_chess_games(
    username,
    output_file=None,
    start_date=None,
    end_date=None,
    max_games_per_file=None,
    verbose=True
)
```

**Parameters:**

- `username` (str, required): Chess.com username
- `output_file` (str, optional): Path to save PGN file(s). Defaults to `./<username>.pgn`.
- `start_date` (datetime, optional): Start date. Defaults to Jan 1, 2025.
- `end_date` (datetime, optional): End date. Defaults to current date.
- `max_games_per_file` (int, optional): Maximum games per file. If None or games ≤ limit, saves to single file.
- `verbose` (bool, optional): Print progress messages. Defaults to True.

**Returns:**

Dict with keys:
- `total_games`: Total number of games downloaded
- `output_files`: List of created file paths

**Raises:**

- `ValueError`: If username does not exist on Chess.com

## Error Handling

The script validates usernames before downloading. For example:

```bash
$ ./download-pgn nonexistentuser12345
Error: Username 'nonexistentuser12345' does not exist on Chess.com
```

## Files

- `download_pgn.py` - Main Python script
- `download-pgn` - Symlink for easy CLI access
- `test_import.py` - Example/test script for module usage

## License

This project is provided as-is for educational and personal use.
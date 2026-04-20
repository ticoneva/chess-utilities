# Chess Puzzle Generator

A web application for viewing PGN chess games and practicing puzzles based on blunders, mistakes, and inaccuracies detected by Stockfish engine analysis.

## Features

- **PGN Upload**: Load PGN files via file picker or from the server's remote set library
- **Multiple Puzzle Sets**: Load and switch between multiple PGN sets with a tabbed interface
- **Real-time Analysis**: Live Stockfish evaluation with WDL percentages and best moves display
- **Puzzle Mode**: Practice finding the best moves in positions where blunders/mistakes occurred
- **Remote Sets**: Share puzzle sets via URL hash links — no database required
- **Admin Upload**: Password-protected page for adding new puzzle sets to the server
- **Responsive Design**: Works on desktop and mobile

## Quick Start

### Prerequisites

- Python 3.8+
- Stockfish engine installed
- Python packages: `flask`, `python-chess`

### Installation

```bash
cd chess_server_claude
pip install -r requirements.txt
```

### Running

```bash
python app.py                                    # Default port 5001
python app.py --port 8080                        # Custom port
python app.py --pgn-dir /path/to/pgns            # Custom PGN directory for remote sets
CHESS_ADMIN_PASSWORD=secret python app.py         # Enable admin uploads
```

Open `http://localhost:5001` in your browser.

### CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--port` | 5001 | Server port |
| `--debug` | off | Enable Flask debug mode |
| `--threads` | 4 | Stockfish analysis threads |
| `--pgn-dir` | `./pgn` | Directory for remote puzzle set PGN files |

## Usage

### Loading Games

1. **Upload**: Click "Choose File" and select a PGN file, then "Upload File"
2. **Sample**: Click "Load Sample PGN" for a built-in example
3. **Remote Set**: Visit `http://host:port/#set=<hash>` (hash provided by admin)

### Puzzle Mode

1. Click the "Puzzles" button in the header
2. Select minimum classification: Blunders, Mistakes+, or Inaccuracies+
3. Choose success criterion: Best move, Top 3, or Any good move
4. Make your move on the board to check if it's correct

### Remote Puzzle Sets

Remote sets are PGN files stored in the server's `pgn/` directory. They are accessible only via direct URL hash links — no public listing.

**To add a new remote set:**

1. **Via admin page**: Go to `/admin`, enter the admin password, and upload a PGN file. The shareable link is displayed after upload.
2. **Manually**: Place a `.pgn` file in the `pgn/` directory, then click "Re-scan" on the admin page or call `POST /rescan_sets`.

**To share a set**: Give the recipient the URL in the form `http://host:port/#set=<hash>`. The hash is derived from the filename (SHA-256, first 8 hex characters), so it's deterministic and never changes for a given file.

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Flask (Python) |
| PGN Parsing | python-chess |
| Engine | Stockfish |
| Frontend | Vanilla JS, Bootstrap 5.3.0 |
| Board | Chessboard.js + Chess.js |
| Persistence | Browser localStorage |

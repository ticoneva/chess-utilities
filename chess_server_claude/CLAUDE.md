# Chess Puzzle Generator

A Flask web application for viewing PGN chess games and practicing puzzles based on blunders, mistakes, and inaccuracies.

## Project Structure

```
chess_server_claude/
├── app.py              # Flask backend with PGN parsing and Stockfish analysis
├── templates/
│   └── index.html      # Single-page frontend (HTML + embedded JavaScript)
├── requirements.txt    # Python dependencies (flask, chess)
└── CLAUDE.md           # This file
```

## Technology Stack

- **Backend**: Flask (Python) with `chess` library for PGN parsing and game logic
- **Frontend**: Single-page HTML with vanilla JavaScript, Bootstrap 5.3.0
- **Board Visualization**: Chessboard.js + Chess.js (via CDN)
- **Engine Analysis**: Stockfish (installed at `/opt/network/apps/chess/stockfish/stockfish-ubuntu-x86-64-avx2`)

## Running the Server

```bash
cd chess_server_claude
python app.py
```

The server runs on port 5001 by default. Use `--port` flag to change.

## Key Features

1. **PGN Upload**: Upload PGN files to view and analyze games
2. **Game Navigation**: Navigate through moves with arrow keys or buttons
3. **Engine Analysis**: Real-time Stockfish evaluation with best moves display
4. **Puzzle Mode**: Practice positions where mistakes were made (blunders/mistakes/inaccuracies)
5. **Anonymous Mode**: Hide player names and event names for blind analysis
6. **Browser Storage**: Games and settings persist across page reloads via localStorage

## Architecture Notes

### Backend (app.py)

- `GameState` class manages session state, PGN parsing, and puzzle analysis
- Uses Server-Sent Events (SSE) for streaming puzzle analysis progress
- Classification thresholds: Blunder (300cp), Mistake (100cp), Inaccuracy (50cp)
- Supports both evaluation-based and WDL-based move classification

### Frontend (templates/index.html)

- All JavaScript is embedded in the HTML template
- Key global variables: `game`, `board`, `currentPly`, `currentGameIndex`, `puzzleMode`, `anonymousMode`
- State persistence via `saveStateToStorage()` and `loadStateFromStorage()`
- Puzzle list uses `rebuildPuzzleResults()` to re-render when settings change

### Key API Endpoints

- `POST /upload_pgn` - Upload PGN file
- `GET /game_info?game=<index>` - Get game headers and metadata
- `GET /board?ply=<n>` - Get board position at move n
- `POST /analyze_puzzles` - Start puzzle analysis (SSE stream)
- `POST /goto_puzzle` - Navigate to puzzle position

## Anonymous Mode

When enabled, the UI hides identifying information:
- Games listed as "Game 1", "Game 2", etc.
- Player names replaced with "White" and "Black"
- Event names and dates hidden
- Puzzles show "Puzzle X" and "Move N" format

The `anonymousMode` variable controls this globally. Call `updateGameListDisplay()` and `rebuildPuzzleResults()` when it changes.

## Code Conventions

- JavaScript uses single quotes for strings in most places
- HTML templates use double quotes for attributes
- Fetch API used for HTTP requests (not jQuery)
- CSS classes follow Bootstrap conventions

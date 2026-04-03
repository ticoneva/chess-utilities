# Chess Puzzle Generator - Complete Documentation

## Overview

A Flask web application for viewing PGN chess games and practicing puzzles based on blunders, mistakes, and inaccuracies detected by Stockfish engine analysis.

## Project Structure

```
chess_server_claude/
├── app.py                 # Flask backend with GameState class and API endpoints
├── templates/
│   └── index.html        # Single-page frontend (HTML + embedded JavaScript + CSS)
├── requirements.txt      # Python dependencies
└── CLAUDE.md            # This documentation
```

## Technology Stack

| Component | Technology |
|-----------|------------|
| Backend | Flask (Python) |
| PGN Parsing | `python-chess` library |
| Engine Analysis | Stockfish (path: `/opt/network/apps/chess/stockfish/stockfish-ubuntu-x86-64-avx2`) |
| Frontend | Vanilla JavaScript, Bootstrap 5.3.0 |
| Chess Board | Chessboard.js + Chess.js (CDN) |
| State Persistence | localStorage (browser) |

## Running the Server

```bash
cd chess_server_claude
python app.py              # Default port 5001
python app.py --port 8080  # Custom port
```

## Core Constants

```python
STOCKFISH_PATH = "/opt/network/apps/chess/stockfish/stockfish-ubuntu-x86-64-avx2"
DEFAULT_PORT = 5001

# Classification thresholds (centipawns)
BLUNDER_THRESHOLD = 300    # >= 3.0 pawn advantage lost
MISTAKE_THRESHOLD = 100    # >= 1.0 pawn advantage lost
INACCURACY_THRESHOLD = 50  # >= 0.5 pawn advantage lost
```

## Key Features

### 1. PGN Upload & Game Navigation
- Upload PGN files via file picker
- Load sample PGN for testing
- Navigate games with arrow keys or on-board buttons
- Flip board button for viewing from either side

### 2. Real-time Engine Analysis
- Live Stockfish evaluation during navigation
- Best moves display (configurable count: 1-5)
- Evaluation bar showing position assessment
- WDL (Win/Draw/Loss) percentages

### 3. Puzzle Mode
- Automatic detection of blunders, mistakes, and inaccuracies
- Three success criteria:
  - **Best move**: Must play the exact top move
  - **Top 3**: Must play any of the top 3 moves
  - **Any good move**: Must play a move that doesn't lose significant advantage
- Three minimum classifications:
  - **Blunders Only**: Only positions with >= 3.0 cp loss
  - **Mistakes+**: Includes mistakes (>= 1.0 cp) and blunders
  - **Inaccuracies+**: Includes inaccuracies (>= 0.5 cp), mistakes, and blunders

### 4. Move Classification Display
- **Blunder**: Red border, severe evaluation drop
- **Mistake**: Orange border, moderate evaluation drop
- **Inaccuracy**: Yellow border, minor evaluation drop
- Current puzzle: Green background highlight
- Completed puzzle: Light grey background with grey text

### 5. Settings & Persistence
- Anonymous mode (hide player names)
- Auto-advance to next puzzle after correct answer
- Show/hide evaluation bar
- Show/hide best moves panel
- Puzzle order: Ascending, Descending, or Random (seeded for reproducibility)
- All settings saved to localStorage and restored on page reload

### 6. Browser Storage
- Game state persistence across page reloads
- Puzzle progress tracking (completed puzzles)
- Settings persistence
- Puzzle analysis caching (avoids re-analysis on reload)

## Architecture

### Backend (app.py)

#### GameState Class
Manages session state, PGN parsing, and puzzle analysis.

**Key Attributes:**
- `games`: List of parsed game data (headers, moves)
- `current_game_index`: Currently selected game
- `current_ply`: Current move position in the game
- `_game_puzzles`: Per-game puzzle storage (lazy-loaded)
- `_game_analyzed`: Track which games have been analyzed
- `settings`: Engine and display settings
- `puzzle_settings`: Puzzle mode configuration

**Key Methods:**
- `_parse_games()`: Parse PGN string into game objects
- `_analyze_game_moves()`: Run Stockfish analysis on a game
- `_extract_puzzles_from_annotations()`: Extract puzzles from existing NAG annotations
- `get_filtered_puzzles()`: Filter puzzles by minimum classification
- `check_puzzle_move()`: Validate user's move in puzzle mode
- `get_best_moves_for_puzzle()`: Fetch best moves for a specific puzzle position

#### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/upload_pgn` | POST | Upload and parse PGN file |
| `/load_sample` | GET | Load sample.pgn file |
| `/game_info?game=<n>` | GET | Get game headers and metadata |
| `/board?ply=<n>` | GET | Get board position and move list at ply n |
| `/analyze_quick` | POST | Quick analysis for move highlighting |
| `/analyze` | POST | Full analysis with best moves |
| `/puzzles_stream` | GET (SSE) | Stream puzzle analysis progress |
| `/reanalyze_stream` | GET (SSE) | Stream forced re-analysis |
| `/puzzle_check` | POST | Check user's move in puzzle mode |
| `/puzzle_settings` | POST | Update puzzle mode settings |
| `/settings` | POST | Update general settings |
| `/goto_puzzle` | POST | Navigate to puzzle position |
| `/restore_session` | POST | Restore session from saved PGN |
| `/download_annotated_pgn` | GET | Download PGN with engine annotations |

#### Server-Sent Events (SSE)

Used for streaming analysis progress:
- `analysis_start`: Analysis beginning
- `game_start`: Game analysis starting
- `move_progress`: Move being analyzed
- `game_complete`: Game analysis finished
- `complete`: All games analyzed

### Frontend (templates/index.html)

#### Global Variables
```javascript
var board = null;           // Chessboard.js instance
var game = null;            // Chess.js instance
var currentPly = 0;         // Current move position
var currentGameIndex = -1;  // Currently selected game
var puzzleMode = false;     // Puzzle mode flag
var anonymousMode = false;  // Anonymous mode flag
var hideMoveList = false;   // Hide move list flag
var autoAdvancePuzzle = false;  // Auto-advance after correct answer
var selectedPlayers = new Set();  // Player filter
var completedPuzzles = new Set();  // Track completed puzzles
var puzzleRandomSeed = null;  // Seed for random puzzle order
```

#### Key Functions
- `onDrop()`: Handle piece moves, trigger puzzle check in puzzle mode
- `checkPuzzleMove()`: Validate user's move against best moves
- `goToPuzzle(index)`: Navigate to specific puzzle
- `loadPuzzles()`: Load and analyze puzzles (uses cache if available)
- `rebuildPuzzleResults()`: Re-render puzzle list with current settings
- `saveStateToStorage()`: Save state to localStorage
- `loadStateFromStorage()`: Restore state from localStorage
- `runBackgroundAnalysis()`: Run server analysis in background for cached puzzles

#### State Persistence
State is saved to localStorage with key `chessPuzzleGeneratorState`:
```javascript
{
    pgn_string: string,
    current_game_index: number,
    current_ply: number,
    settings: {
        show_evaluation: boolean,
        show_best_moves: boolean,
        num_best_moves: number,
        time_limit: number,
        puzzle_time_limit: number,
        anonymous_mode: boolean,
        hide_move_list: boolean,
        auto_advance_puzzle: boolean,
        selected_players: string[],
        puzzle_panel_visible: boolean
    },
    puzzle_settings: {
        puzzle_mode: boolean,
        success_criterion: string,
        current_puzzle_index: number,
        min_class: string,
        classification_mode: string,
        puzzle_sort: string,
        random_seed: number,
        completed_puzzles: number[]
    }
}
```

#### Puzzle Cache
Analysis results are cached separately with key `chessPuzzleCache_<hash>_<minClass>`:
```javascript
{
    gamesWithPuzzles: {
        [gameIndex]: {
            puzzles: Puzzle[],
            game_name: string
        }
    },
    timestamp: number,
    minClass: string
}
```

## Move Classification Logic

### Evaluation-based Classification (used for puzzle analysis)
```python
if eval_change >= 3.0:    classification = "blunder"
elif eval_change >= 1.0:  classification = "mistake"
elif eval_change >= 0.5:  classification = "inaccuracy"
```

### WDL-based Classification (used for navigation highlighting)
```python
if wdl_change >= 250:     classification = "blunder"
elif wdl_change >= 100:   classification = "mistake"
elif wdl_change >= 50:    classification = "inaccuracy"
```

### Eval Change Calculation
- White's move: `eval_change = before_eval - after_eval`
- Black's move: `eval_change = after_eval - before_eval`
- Positive = bad for player who just moved

## Puzzle Check Flow

1. User makes a move via drag-and-drop
2. `onDrop()` captures FEN before move and calls `checkPuzzleMove()`
3. `checkPuzzleMove()` sends move to `/puzzle_check` endpoint
4. Server compares user's move against best moves
5. Response includes:
   - `correct`: Whether move meets success criterion
   - `move_quality`: "best", "top3", "good", or null
   - `move_san`: SAN notation of user's move
   - `move_rank`: Rank of user's move (1-3 if found)
   - `best_moves`: Array of best moves with scores
   - `continuation`: PV line after user's move
6. Frontend displays result message and shows continuation if available
7. On correct answer: marks puzzle as completed, optionally advances to next

## Sidebar Toggle Behavior

Three sidebars with responsive behavior:
- **Files panel** (left): Load PGN and game list
- **Settings panel** (left): Settings controls
- **Puzzle panel** (right): Puzzle list and options

Mobile mode (width < 768px):
- Sidebars hidden by default
- Toggle buttons in header show/hide panels
- Panels appear above the board when opened

Desktop mode (width >= 768px):
- Sidebars visible by default
- Toggle buttons collapse/expand panels
- Panels appear on sides of board

Panel visibility state is saved to localStorage and restored on reload.

## Anonymous Mode

When enabled:
- Games listed as "Game 1", "Game 2", etc.
- Player names replaced with "White" and "Black"
- Event names and dates hidden
- Puzzles show "Puzzle X" and "Move N" format
- Downloaded PGN has anonymized headers

## Testing with Playwright

```bash
# Navigate to page
playwright-cli goto http://localhost:5001

# Take snapshot
playwright-cli snapshot

# Click element
playwright-cli click <ref>

# Check console
playwright-cli console

# Resize for mobile testing
playwright-cli resize 375 812
```

## Common Issues & Solutions

### "Checking..." stuck after move
- Ensure background analysis runs when using cached puzzles
- Check that server-side session has puzzle data

### Evaluation bar not restoring
- Use AbortController for pending fetch requests during continuation playback

### Puzzle jumping back to start
- Ensure no duplicate `goToPuzzle()` calls in completion logic

### Panels not showing on mobile
- Use inline `style.display` for toggling (not Bootstrap classes)
- Order classes: panels should have `order-1` for mobile, board `order-3`

### Auto-advance not following puzzle sort order
- The frontend calculates next puzzle index from `window.allPuzzles` (sorted array)
- Backend's `next_puzzle` response is ignored for auto-advance since it uses unsorted order
- This ensures auto-advance respects ascending, descending, or random sort settings

## Recent Changes (Git History)

- `0808635` - Fix auto-advance puzzle order to respect sort settings
- `c922a4a` - Save and restore puzzle panel visibility state
- `b123a14` - Change completed puzzle background to light grey
- `19bcd27` - Fix puzzle completion: remove duplicate goToPuzzle and update UI
- `036b828` - Run background analysis when using cached puzzle results
- `0cf1fa9` - Cache puzzle analysis results to avoid re-analysis on page reload
- `73b7337` - Add margin between Show Answer and Reset Progress buttons
- `a6cf5e3` - Style completed puzzles with pale grey font color

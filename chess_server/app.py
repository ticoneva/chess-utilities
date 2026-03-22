from flask import Flask, render_template, request, jsonify, send_from_directory
import chess
import chess.engine
import chess.pgn
import io
import json
import os
from datetime import datetime

app = Flask(__name__)

# Stockfish engine path
STOCKFISH_PATH = "/opt/network/apps/chess/stockfish/stockfish-ubuntu-x86-64-avx2"

# Move classification thresholds (centipawns)
THRESHOLDS = {
    'blunder': 300,      # > 300 centipawns worse
    'mistake': 100,      # > 100 centipawns worse
    'inaccuracy': 50     # > 50 centipawns worse
}

# Store games in memory
games_db = {}

class GameState:
    def __init__(self, pgn_string):
        self.games = []
        self.current_game_idx = 0
        self.current_move_idx = -1
        self.board = None
        self.move_list = []
        self.puzzles = []
        self.current_puzzle_idx = 0
        self.puzzle_active = False
        self.time_limit = 0.1
        self.show_evaluation = True
        self.show_best_moves = True
        self.num_best_moves = 3
        self.puzzle_success_criteria = 'top3'
        
        self._parse_games(pgn_string)
        self._load_current_game()
    
    def _parse_games(self, pgn_string):
        """Parse games from PGN string."""
        pgn = io.StringIO(pgn_string)
        while True:
            game = chess.pgn.read_game(pgn)
            if game is None:
                break
            self.games.append(game)
    
    def _load_current_game(self):
        """Load the current game state."""
        if self.games:
            self.move_list = list(self.games[self.current_game_idx].mainline_moves())
            self.board = self.games[self.current_game_idx].board()
            self._analyze_all_moves()
        else:
            self.move_list = []
            self.board = chess.Board()
    
    def go_to_move(self, move_idx, game_idx=None):
        """Navigate to a specific move."""
        if game_idx is not None:
            if 0 <= game_idx < len(self.games):
                self.current_game_idx = game_idx
                self._load_current_game()
        
        self.board = self.games[self.current_game_idx].board()
        for i in range(move_idx + 1):
            self.board.push(self.move_list[i])
        self.current_move_idx = move_idx
    
    def analyze_position(self):
        """Analyze the current position with Stockfish."""
        if not self.show_evaluation:
            return None
        
        try:
            with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
                info = engine.analyse(self.board, chess.engine.Limit(time=self.time_limit))
                
                result = {
                    'score': None,
                    'wdl': None,
                    'best_moves': []
                }
                
                # Get score
                if 'score' in info:
                    score = info['score']
                    if score.relative:
                        if score.relative.mate():
                            result['score'] = f"M{score.relative.mate()}"
                        else:
                            result['score'] = score.relative.cp() / 100
                
                # Get WDL
                if 'score' in info and info['score'].wdl():
                    wdl = info['score'].wdl().relative
                    result['wdl'] = {
                        'win': wdl.wins() / 1000,
                        'draw': wdl.draws() / 1000,
                        'loss': wdl.losses() / 1000
                    }
                
                # Get best moves
                if self.show_best_moves:
                    limit = chess.engine.Limit(time=self.time_limit)
                    
                    # Try to get top moves
                    result['best_moves'] = []
                    board_copy = self.board.copy()
                    
                    for i in range(min(self.num_best_moves + 5, len(list(board_copy.legal_moves)))):
                        analysis_result = engine.analyse(board_copy, limit, multipv=i+1)
                        if 'pv' in analysis_result and len(analysis_result['pv']) > 0:
                            move = analysis_result['pv'][0]
                            move_score = analysis_result['score']
                            if move_score.relative:
                                if move_score.relative.mate():
                                    score_str = f"M{move_score.relative.mate()}"
                                else:
                                    score_str = f"{move_score.relative.cp() / 100:+.2f}"
                            else:
                                score_str = "0.00"
                            
                            result['best_moves'].append({
                                'move': board_copy.san(move),
                                'score': score_str
                            })
                        else:
                            break
                    
                    result['best_moves'] = result['best_moves'][:self.num_best_moves]
                
                return result
        except Exception as e:
            print(f"Error analyzing position: {e}")
            return None
    
    def _analyze_all_moves(self):
        """Analyze all moves to find blunders, mistakes, and inaccuracies."""
        self.puzzles = []
        board = self.games[self.current_game_idx].board()
        
        try:
            with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
                for i, move in enumerate(self.move_list):
                    before_info = engine.analyse(board, chess.engine.Limit(time=self.time_limit))
                    before_score = before_info.get('score', None)
                    
                    board.push(move)
                    
                    after_info = engine.analyse(board, chess.engine.Limit(time=self.time_limit))
                    after_score = after_info.get('score', None)
                    
                    if before_score and after_score:
                        move_number = i + 1
                        is_white_move = (move_number % 2 == 1)
                        
                        if before_score.relative and after_score.relative:
                            if is_white_move:
                                before_mover_cp = before_score.relative.cp() if not before_score.relative.mate() else 10000
                            else:
                                before_mover_cp = -before_score.relative.cp() if not before_score.relative.mate() else -10000
                            
                            if after_score.relative:
                                if is_white_move:
                                    after_mover_cp = -after_score.relative.cp() if not after_score.relative.mate() else 10000
                                else:
                                    after_mover_cp = after_score.relative.cp() if not after_score.relative.mate() else -10000
                            else:
                                after_mover_cp = 0
                            
                            eval_change = after_mover_cp - before_mover_cp
                            
                            move_class = None
                            if before_score.relative.mate():
                                mate_in = before_score.relative.mate()
                                if (is_white_move and mate_in < 0) or (not is_white_move and mate_in > 0):
                                    move_class = 'blunder'
                            elif eval_change >= THRESHOLDS['blunder']:
                                move_class = 'blunder'
                            elif eval_change >= THRESHOLDS['mistake']:
                                move_class = 'mistake'
                            elif eval_change >= THRESHOLDS['inaccuracy']:
                                move_class = 'inaccuracy'
                            
                            if move_class:
                                self.puzzles.append({
                                    'game_idx': self.current_game_idx,
                                    'move_idx': i - 1 if i > 0 else -1,
                                    'blunder_move_idx': i,
                                    'move_label': f"{(i + 2) // 2}. {'White' if is_white_move else 'Black'}",
                                    'classification': move_class,
                                    'eval_change': eval_change,
                                    'san': board.san(move)
                                })
                    
                    board.pop()
                    
        except Exception as e:
            print(f"Error analyzing moves: {e}")
    
    def get_all_blunders(self):
        """Get all blunders, mistakes, and inaccuracies from all games."""
        all_puzzles = []
        
        # Add current game's puzzles
        for puzzle in self.puzzles:
            game = self.games[puzzle['game_idx']]
            puzzle.update({
                'white': game.headers.get('White', 'White'),
                'black': game.headers.get('Black', 'Black'),
                'event': game.headers.get('Event', ''),
                'date': game.headers.get('Date', '')
            })
            all_puzzles.append(puzzle)
        
        return all_puzzles
    
    def get_filtered_puzzles(self, min_class='inaccuracy'):
        """Get filtered puzzles based on minimum classification."""
        all_puzzles = self.get_all_blunders()
        hierarchy = ['inaccuracy', 'mistake', 'blunder']
        
        if min_class not in hierarchy:
            return all_puzzles
        
        min_idx = hierarchy.index(min_class)
        return [p for p in all_puzzles if hierarchy.index(p['classification']) >= min_idx]


@app.route('/')
def index():
    """Render the main page."""
    return render_template('index.html')


@app.route('/upload_pgn', methods=['POST'])
def upload_pgn():
    """Upload and parse a PGN file."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    try:
        pgn_content = file.read().decode('utf-8')
        session_id = str(datetime.now().timestamp())
        
        games_db[session_id] = GameState(pgn_content)
        
        game_list = []
        for i, game in enumerate(games_db[session_id].games):
            game_list.append({
                'index': i,
                'white': game.headers.get('White', 'White'),
                'black': game.headers.get('Black', 'Black'),
                'result': game.headers.get('Result', '*'),
                'event': game.headers.get('Event', ''),
                'date': game.headers.get('Date', '')
            })
        
        return jsonify({
            'session_id': session_id,
            'games': game_list
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/game_info')
def game_info():
    """Get information about the current game."""
    session_id = request.args.get('session_id')
    game_idx = int(request.args.get('game_idx', 0))
    
    if session_id not in games_db:
        return jsonify({'error': 'Session not found'}), 404
    
    state = games_db[session_id]
    
    if 0 <= game_idx < len(state.games):
        state.go_to_move(-1, game_idx)
        
        game = state.games[game_idx]
        move_list = []
        node = game
        while not node.is_end():
            next_node = node.variation(0)
            move = node.board().san(next_node.move)
            move_list.append(move)
            node = next_node
        
        return jsonify({
            'game': {
                'index': game_idx,
                'white': game.headers.get('White', 'White'),
                'black': game.headers.get('Black', 'Black'),
                'result': game.headers.get('Result', '*'),
                'event': game.headers.get('Event', ''),
                'date': game.headers.get('Date', '')
            },
            'move_list': move_list,
            'total_moves': len(move_list)
        })
    
    return jsonify({'error': 'Invalid game index'}), 400


@app.route('/board')
def get_board():
    """Get the current board state."""
    session_id = request.args.get('session_id')
    move_idx = request.args.get('move_idx', type=int)
    game_idx = request.args.get('game_idx', type=int)
    
    if session_id not in games_db:
        return jsonify({'error': 'Session not found'}), 404
    
    state = games_db[session_id]
    
    if game_idx is not None:
        if 0 <= game_idx < len(state.games):
            state.go_to_move(-1, game_idx)
        else:
            return jsonify({'error': 'Invalid game index'}), 400
    
    if move_idx is not None:
        state.go_to_move(move_idx)
    
    return jsonify({
        'fen': state.board.fen(),
        'move_idx': state.current_move_idx,
        'turn': 'white' if state.board.turn == chess.WHITE else 'black',
        'castling': {
            'K': state.board.has_kingside_castling_rights(chess.WHITE),
            'Q': state.board.has_queenside_castling_rights(chess.WHITE),
            'k': state.board.has_kingside_castling_rights(chess.BLACK),
            'q': state.board.has_queenside_castling_rights(chess.BLACK)
        },
        'is_check': state.board.is_check(),
        'is_checkmate': state.board.is_checkmate(),
        'is_stalemate': state.board.is_stalemate()
    })


@app.route('/analyze')
def analyze():
    """Analyze the current position with Stockfish."""
    session_id = request.args.get('session_id')
    
    if session_id not in games_db:
        return jsonify({'error': 'Session not found'}), 404
    
    state = games_db[session_id]
    
    state.show_evaluation = request.args.get('show_evaluation', 'true').lower() == 'true'
    state.show_best_moves = request.args.get('show_best_moves', 'true').lower() == 'true'
    state.num_best_moves = int(request.args.get('num_best_moves', 3))
    state.time_limit = float(request.args.get('time_limit', 0.1))
    
    result = state.analyze_position()
    
    if result:
        return jsonify(result)
    else:
        return jsonify({'error': 'Analysis failed'}), 500


@app.route('/puzzles')
def get_puzzles():
    """Get all blunders, mistakes, and inaccuracies."""
    session_id = request.args.get('session_id')
    min_class = request.args.get('min_class', 'inaccuracy')
    
    if session_id not in games_db:
        return jsonify({'error': 'Session not found'}), 404
    
    state = games_db[session_id]
    
    puzzles = state.get_filtered_puzzles(min_class)
    
    games_dict = {}
    for puzzle in puzzles:
        game_idx = puzzle['game_idx']
        if game_idx not in games_dict:
            game = state.games[game_idx]
            games_dict[game_idx] = {
                'game_idx': game_idx,
                'white': game.headers.get('White', 'White'),
                'black': game.headers.get('Black', 'Black'),
                'event': game.headers.get('Event', ''),
                'date': game.headers.get('Date', ''),
                'puzzles': []
            }
        games_dict[game_idx]['puzzles'].append(puzzle)
    
    return jsonify(list(games_dict.values()))


@app.route('/goto_puzzle')
def goto_puzzle():
    """Go to a specific puzzle position."""
    session_id = request.args.get('session_id')
    game_idx = int(request.args.get('game_idx'))
    move_idx = int(request.args.get('move_idx'))
    
    if session_id not in games_db:
        return jsonify({'error': 'Session not found'}), 404
    
    state = games_db[session_id]
    state.go_to_move(move_idx, game_idx)
    state.puzzle_active = True
    
    return jsonify({
        'game_idx': game_idx,
        'move_idx': move_idx,
        'fen': state.board.fen()
    })


@app.route('/puzzle_check', methods=['POST'])
def puzzle_check():
    """Check if the user's move is correct in puzzle mode."""
    session_id = request.form.get('session_id')
    move_san = request.form.get('move')
    
    if session_id not in games_db:
        return jsonify({'error': 'Session not found'}), 404
    
    state = games_db[session_id]
    
    if not state.puzzle_active:
        return jsonify({'error': 'Puzzle mode not active'}), 400
    
    state.show_evaluation = True
    state.show_best_moves = True
    result = state.analyze_position()
    
    if not result or 'best_moves' not in result:
        return jsonify({'error': 'Failed to analyze position'}), 500
    
    best_moves = result['best_moves']
    
    is_correct = False
    move_in_best = False
    
    for i, best_move in enumerate(best_moves):
        if best_move['move'] == move_san:
            move_in_best = True
            if state.puzzle_success_criteria == 'any':
                is_correct = True
            elif state.puzzle_success_criteria == 'best' and i == 0:
                is_correct = True
            elif state.puzzle_success_criteria == 'top3' and i < 3:
                is_correct = True
            break
    
    if not is_correct and move_in_best:
        try:
            with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
                before_info = engine.analyse(state.board, chess.engine.Limit(time=state.time_limit))
                before_score = before_info.get('score', None)
                
                move = state.board.parse_san(move_san)
                state.board.push(move)
                
                after_info = engine.analyse(state.board, chess.engine.Limit(time=state.time_limit))
                after_score = after_info.get('score', None)
                
                if before_score and after_score and before_score.relative and after_score.relative:
                    is_white_move = state.board.turn == chess.BLACK
                    if is_white_move:
                        before_cp = before_score.relative.cp() if not before_score.relative.mate() else 10000
                        after_cp = -after_score.relative.cp() if not after_score.relative.mate() else 10000
                    else:
                        before_cp = -before_score.relative.cp() if not before_score.relative.mate() else -10000
                        after_cp = after_score.relative.cp() if not after_score.relative.mate() else -10000
                    
                    eval_change = after_cp - before_cp
                    
                    if eval_change < THRESHOLDS['inaccuracy']:
                        is_correct = True
                
                state.board.pop()
        except Exception as e:
            print(f"Error checking move: {e}")
    
    return jsonify({
        'is_correct': is_correct,
        'move_in_best': move_in_best,
        'best_moves': best_moves
    })


@app.route('/puzzle_settings', methods=['POST'])
def update_puzzle_settings():
    """Update puzzle mode settings."""
    session_id = request.form.get('session_id')
    success_criteria = request.form.get('success_criteria', 'top3')
    
    if session_id not in games_db:
        return jsonify({'error': 'Session not found'}), 404
    
    state = games_db[session_id]
    state.puzzle_success_criteria = success_criteria
    
    return jsonify({'success': True})


@app.route('/settings', methods=['POST'])
def update_settings():
    """Update general settings."""
    session_id = request.form.get('session_id')
    show_evaluation = request.form.get('show_evaluation', 'true')
    show_best_moves = request.form.get('show_best_moves', 'true')
    num_best_moves = int(request.form.get('num_best_moves', 3))
    time_limit = float(request.form.get('time_limit', 0.1))
    
    if session_id not in games_db:
        return jsonify({'error': 'Session not found'}), 404
    
    state = games_db[session_id]
    state.show_evaluation = show_evaluation.lower() == 'true'
    state.show_best_moves = show_best_moves.lower() == 'true'
    state.num_best_moves = num_best_moves
    state.time_limit = time_limit
    
    return jsonify({'success': True})


@app.route('/load_sample')
def load_sample():
    """Load the sample.pgn file."""
    try:
        sample_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'sample.pgn')
        with open(sample_path, 'r', encoding='utf-8') as f:
            pgn_content = f.read()
        
        session_id = str(datetime.now().timestamp())
        games_db[session_id] = GameState(pgn_content)
        
        game_list = []
        for i, game in enumerate(games_db[session_id].games):
            game_list.append({
                'index': i,
                'white': game.headers.get('White', 'White'),
                'black': game.headers.get('Black', 'Black'),
                'result': game.headers.get('Result', '*'),
                'event': game.headers.get('Event', ''),
                'date': game.headers.get('Date', '')
            })
        
        return jsonify({
            'session_id': session_id,
            'games': game_list
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5001)
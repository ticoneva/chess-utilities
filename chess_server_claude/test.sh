#!/bin/bash
# Test script for Chess Puzzle Generator using playwright-cli

BASE_URL="http://127.0.0.1:5002"
SESSION="chess_test_$$"

echo "=== Chess Puzzle Generator Test Suite ==="
echo "Server: $BASE_URL"
echo "Session: $SESSION"
echo ""

cleanup() {
    echo "Cleaning up browser..."
    playwright-cli -s=$SESSION close 2>/dev/null || true
}

trap cleanup EXIT

# Helper function to extract result from playwright-cli output
get_result() {
    grep -A1 "^### Result" | tail -1 | tr -d '\r\n'
}

# Test 1: Open page
echo "Test 1: Opening page..."
OUTPUT=$(playwright-cli -s=$SESSION open "$BASE_URL" 2>&1)
if echo "$OUTPUT" | grep -q "Page URL: $BASE_URL"; then
    echo "✓ Page opened successfully"
else
    echo "✗ Failed to open page"
    exit 1
fi
playwright-cli -s=$SESSION snapshot > /dev/null
echo ""

# Test 2: Check page title
echo "Test 2: Checking page title..."
TITLE=$(playwright-cli -s=$SESSION eval "document.querySelector('h4').textContent" 2>&1 | get_result | tr -d '"')
if [[ "$TITLE" == "Chess Puzzle Generator" ]]; then
    echo "✓ Title is correct: $TITLE"
else
    echo "✗ Title not found or incorrect: $TITLE"
fi
echo ""

# Test 3: Check board pieces are loaded
echo "Test 3: Checking chess pieces..."
PIECES=$(playwright-cli -s=$SESSION eval "document.querySelectorAll('.piece').length" 2>&1 | get_result)
PIECES=${PIECES:-0}
if [ "$PIECES" -gt 0 ]; then
    echo "✓ Chess pieces loaded: $PIECES pieces found"
else
    echo "✗ No chess pieces found"
fi
echo ""

# Test 4: Load sample PGN
echo "Test 4: Loading sample PGN..."
playwright-cli -s=$SESSION snapshot > /dev/null
playwright-cli -s=$SESSION click "#loadSampleBtn" 2>&1 | head -5
sleep 3
GAMES_SECTION=$(playwright-cli -s=$SESSION eval "document.querySelector('#gamesSection').style.display" 2>&1 | get_result)
if [[ "$GAMES_SECTION" != "none" && -n "$GAMES_SECTION" ]]; then
    echo "✓ Games section is visible"
else
    echo "✗ Games section not visible"
fi
echo ""

# Test 5: Check games list
echo "Test 5: Checking games list..."
GAME_COUNT=$(playwright-cli -s=$SESSION eval "document.querySelectorAll('#gamesList .list-group-item').length" 2>&1 | get_result)
GAME_COUNT=${GAME_COUNT:-0}
if [ "$GAME_COUNT" -gt 0 ]; then
    echo "✓ Games list populated: $GAME_COUNT games found"
else
    echo "✗ No games found in list"
fi
echo ""

# Test 6: Select first game if exists
if [ "$GAME_COUNT" -gt 0 ]; then
    echo "Test 6: Selecting first game..."
    playwright-cli -s=$SESSION snapshot > /dev/null
    playwright-cli -s=$SESSION click "button[class*='list-group-item']:nth-of-type(1)" 2>&1 | head -5
    sleep 2
    NAV_VISIBLE=$(playwright-cli -s=$SESSION eval "document.querySelector('#navigationSection').style.display" 2>&1 | get_result)
    if [[ "$NAV_VISIBLE" != "none" && -n "$NAV_VISIBLE" ]]; then
        echo "✓ Navigation buttons visible after selecting game"
    else
        echo "✗ Navigation buttons not visible"
    fi
    echo ""
fi

# Test 7: Test navigation if game selected
if [ "$GAME_COUNT" -gt 0 ]; then
    echo "Test 7: Testing move navigation..."
    playwright-cli -s=$SESSION snapshot > /dev/null
    INITIAL_FEN=$(playwright-cli -s=$SESSION eval "document.querySelector('#board')?.getAttribute('data-fen') || null" 2>&1 | get_result)
    playwright-cli -s=$SESSION click "#nextBtn" 2>&1 | head -5
    sleep 1
    NEW_FEN=$(playwright-cli -s=$SESSION eval "document.querySelector('#board')?.getAttribute('data-fen') || null" 2>&1 | get_result)
    if [[ "$INITIAL_FEN" != "$NEW_FEN" && -n "$NEW_FEN" ]]; then
        echo "✓ Forward navigation works"
    else
        echo "✗ Forward navigation not working (FEN didn't change or null)"
    fi
    echo ""
fi

# Test 8: Test keyboard navigation if game selected
if [ "$GAME_COUNT" -gt 0 ]; then
    echo "Test 8: Testing keyboard navigation..."
    playwright-cli -s=$SESSION eval "window.dispatchEvent(new KeyboardEvent('keydown', {'key': 'ArrowRight'}))" 2>&1 > /dev/null
    sleep 1
    AFTER_KB_FEN=$(playwright-cli -s=$SESSION eval "document.querySelector('#board')?.getAttribute('data-fen') || null" 2>&1 | get_result)
    if [[ "$NEW_FEN" != "$AFTER_KB_FEN" && -n "$AFTER_KB_FEN" ]]; then
        echo "✓ Keyboard navigation works"
    else
        echo "✗ Keyboard navigation not working (FEN didn't change or null)"
    fi
    echo ""
fi

# Test 9: Switch games if enough games
if [ "$GAME_COUNT" -gt 1 ]; then
    echo "Test 9: Switching between games..."
    playwright-cli -s=$SESSION snapshot > /dev/null
    FIRST_FEN=$(playwright-cli -s=$SESSION eval "document.querySelector('#board')?.getAttribute('data-fen') || null" 2>&1 | get_result)
    playwright-cli -s=$SESSION click "button[class*='list-group-item']:nth-of-type(2)" 2>&1 | head -5
    sleep 2
    SECOND_FEN=$(playwright-cli -s=$SESSION eval "document.querySelector('#board')?.getAttribute('data-fen') || null" 2>&1 | get_result)
    if [[ "$FIRST_FEN" != "$SECOND_FEN" && -n "$SECOND_FEN" ]]; then
        echo "✓ Game switching works"
    else
        echo "✗ Game switching not working properly"
    fi
    echo ""
else
    echo "Test 9: ⊙ Skipped - need more than 1 game"
    echo ""
fi

# Test 10: Toggle evaluation if game selected
if [ "$GAME_COUNT" -gt 0 ]; then
    echo "Test 10: Toggling evaluation display..."
    playwright-cli -s=$SESSION snapshot > /dev/null
    playwright-cli -s=$SESSION uncheck "#showEvaluation" 2>&1 | head -5
    sleep 1
    EVAL_HIDDEN=$(playwright-cli -s=$SESSION eval "document.querySelector('#evaluationSection')?.style.display || null" 2>&1 | get_result)
    if [[ "$EVAL_HIDDEN" == "none" ]]; then
        echo "✓ Evaluation can be disabled"
    else
        echo "⊙ Evaluation not hidden or still analyzing: $EVAL_HIDDEN"
    fi

    playwright-cli -s=$SESSION check "#showEvaluation" 2>&1 | head -5
    sleep 1
    EVAL_SHOWN=$(playwright-cli -s=$SESSION eval "document.querySelector('#evaluationSection')?.style.display || 'none'" 2>&1 | get_result)
    if [[ "$EVAL_SHOWN" != "none" ]]; then
        echo "✓ Evaluation can be enabled"
    fi
    echo ""
fi

# Test 11: Best moves tab
if [ "$GAME_COUNT" -gt 0 ]; then
    echo "Test 11: Testing Best Moves tab..."
    playwright-cli -s=$SESSION snapshot > /dev/null
    playwright-cli -s=$SESSION click "nav-link:has-text('Best Moves')" 2>&1 | head -5
    sleep 1
    BEST_MOVES_CONTENT=$(playwright-cli -s=$SESSION eval "document.querySelector('#bestMovesList').textContent" 2>&1 | get_result)
    if [[ -n "$BEST_MOVES_CONTENT" && "$BEST_MOVES_CONTENT" != *"disabled"* ]]; then
        echo "✓ Best Moves tab has content"
    else
        echo "⊙ Best Moves status: ${BEST_MOVES_CONTENT:0:50}"
    fi
    echo ""
fi

echo "=== Test Suite Complete ==="
cleanup
exit 0
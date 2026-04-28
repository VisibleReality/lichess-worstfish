"""
Some example classes for people who want to create a homemade bot.

With these classes, bot makers will not have to implement the UCI or XBoard interfaces themselves.
"""
import logging
import numbers
import os
import random
import sys
from typing import Optional

import chess
from chess.engine import PlayResult, Limit

from lib import model
from lib.engine_wrapper import MinimalEngine
from lib.lichess_types import MOVE, HOMEMADE_ARGS_TYPE

# Use this logger variable to print messages to the console or log files.
# logger.info("message") will always print "message" to the console or log file.
# logger.debug("message") will only print "message" if verbose logging is enabled.
logger = logging.getLogger(__name__)

if sys.platform == "win32":
    stockfish_path = "engines\\stockfish.exe"
    fairy_stockfish_path = "engines\\fairy-stockfish.exe"
else:
    stockfish_path = "engines/stockfish"
    fairy_stockfish_path = "engines/fairy-stockfish"


class ExampleEngine(MinimalEngine):
    """An example engine that all homemade engines inherit."""


# Bot names and ideas from tom7's excellent eloWorld video

class RandomMove(ExampleEngine):
    """Get a random move."""

    def search(self, board: chess.Board, *args: HOMEMADE_ARGS_TYPE) -> PlayResult:  # noqa: ARG002
        """Choose a random move."""
        return PlayResult(random.choice(list(board.legal_moves)), None)


class Alphabetical(ExampleEngine):
    """Get the first move when sorted by san representation."""

    def search(self, board: chess.Board, *args: HOMEMADE_ARGS_TYPE) -> PlayResult:  # noqa: ARG002
        """Choose the first move alphabetically."""
        moves = list(board.legal_moves)
        moves.sort(key=board.san)
        return PlayResult(moves[0], None)


class FirstMove(ExampleEngine):
    """Get the first move when sorted by uci representation."""

    def search(self, board: chess.Board, *args: HOMEMADE_ARGS_TYPE) -> PlayResult:  # noqa: ARG002
        """Choose the first move alphabetically in uci representation."""
        moves = list(board.legal_moves)
        moves.sort(key=str)
        return PlayResult(moves[0], None)


class ComboEngine(ExampleEngine):
    """
    Get a move using multiple different methods.

    This engine demonstrates how one can use `time_limit`, `draw_offered`, and `root_moves`.
    """

    def search(self,
               board: chess.Board,
               time_limit: Limit,
               ponder: bool,  # noqa: ARG002
               draw_offered: bool,
               root_moves: MOVE) -> PlayResult:
        """
        Choose a move using multiple different methods.

        :param board: The current position.
        :param time_limit: Conditions for how long the engine can search (e.g. we have 10 seconds and search up to depth 10).
        :param ponder: Whether the engine can ponder after playing a move.
        :param draw_offered: Whether the bot was offered a draw.
        :param root_moves: If it is a list, the engine should only play a move that is in `root_moves`.
        :return: The move to play.
        """
        if isinstance(time_limit.time, int):
            my_time = time_limit.time
            my_inc = 0
        elif board.turn == chess.WHITE:
            my_time = time_limit.white_clock if isinstance(time_limit.white_clock, int) else 0
            my_inc = time_limit.white_inc if isinstance(time_limit.white_inc, int) else 0
        else:
            my_time = time_limit.black_clock if isinstance(time_limit.black_clock, int) else 0
            my_inc = time_limit.black_inc if isinstance(time_limit.black_inc, int) else 0

        possible_moves = root_moves if isinstance(root_moves, list) else list(board.legal_moves)

        if my_time / 60 + my_inc > 10:
            # Choose a random move.
            move = random.choice(possible_moves)
        else:
            # Choose the first move alphabetically in uci representation.
            possible_moves.sort(key=str)
            move = possible_moves[0]
        return PlayResult(move, None, draw_offered=draw_offered)


def set_low_priority():
    os.nice(1)


class WorstFish(ExampleEngine):

    def __init__(self, commands, options, stderr,  # noqa: ARG002
                 draw_or_resign, game: model.Game | None, debug,  # noqa: ARG002
                 **popen_args: str) -> None:
        # Use fairy-stockfish for from position games due to their potentially invalid positions
        if isinstance(game, model.Game) and game.variant_name == "From Position":
            self.stockfish = chess.engine.SimpleEngine.popen_uci(fairy_stockfish_path, preexec_fn=set_low_priority)
            self.stockfish.configure({"EvalFile": "nn-chess.nnue"})
        else:
            self.stockfish = chess.engine.SimpleEngine.popen_uci(stockfish_path, preexec_fn=set_low_priority)
        super().__init__(commands, options, stderr, draw_or_resign, game, debug, **popen_args)

    def evaluate(self, board: chess.Board, time_limit: float = 0.1) -> chess.engine.Score:
        time_limit -= 0.05
        time_limit = time_limit if time_limit >= 0 else 0

        result = self.stockfish.analyse(board, chess.engine.Limit(time=time_limit))
        return result["score"].relative

    def search(self,
               board: chess.Board,
               time_limit: Limit,
               ponder: bool,
               draw_offered: bool,
               root_moves: MOVE) -> PlayResult:
        # Get amount of legal moves
        legal_moves = tuple(board.legal_moves)

        # Base search time per move in seconds
        search_time = 0.1

        # If the engine will search for more than 10% of the remaining time, then shorten it
        # to be 10% of the remaining time
        if board.turn == chess.WHITE:
            time_left = time_limit.white_clock if isinstance(time_limit.white_clock, numbers.Real) else 15
        else:
            time_left = time_limit.black_clock if isinstance(time_limit.black_clock, numbers.Real) else 15

        if len(legal_moves) * search_time > time_left / 10:
            search_time = (time_left / 10) / len(legal_moves)

        # Initialise variables
        worst_evaluation: Optional[chess.engine.Score] = None
        worst_moves: list[chess.Move] = []

        # Evaluate each move
        for move in legal_moves:
            # Record if the move is a capture
            move.isCapture = board.is_capture(move)

            # Play move
            board.push(move)

            # Record if the move is a check
            move.isCheck = board.is_check()

            # Evaluate position from opponent's perspective
            evaluation: chess.engine.Score = self.evaluate(board, search_time)

            # If the evaluation is better than worst_evaluation, replace the worst_moves list with just this move
            if worst_evaluation is None or worst_evaluation < evaluation:
                worst_evaluation = evaluation
                worst_moves = [move]

            # If the evaluation is the same as worst_evaluation, append the move to worst_moves
            elif worst_evaluation == evaluation:
                worst_moves.append(move)

            # Un-play the move, ready for the next loop
            board.pop()

        # Categorise the moves into captures, checks, and neither
        worst_captures: list[chess.Move] = []
        worst_checks: list[chess.Move] = []
        worst_other: list[chess.Move] = []

        for move in worst_moves:
            if move.isCapture:
                worst_captures.append(move)
            elif move.isCheck:
                worst_checks.append(move)
            else:
                worst_other.append(move)

        # Play a random move, preferring moves first from Other, then from Checks, then from Captures
        if len(worst_other) != 0:
            move = random.choice(worst_other)
        elif len(worst_checks) != 0:
            move = random.choice(worst_checks)
        else:
            move = random.choice(worst_captures)

        return PlayResult(move, None)

    def quit(self):
        self.stockfish.close()

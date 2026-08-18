"""Command-line REPL against the real Azure provider.

    python -m app.ai.chat

Type 'exit' (or Ctrl-C / Ctrl-D) to quit.
"""

from __future__ import annotations

import logging
import sys

from app.ai.context import dev_context
from app.ai.providers.base import ProviderError
from app.ai.schemas import Message
from app.ai.service import AIService
from app.config import ConfigurationError

_EXIT_WORDS = {"exit", "quit", ":q"}

BANNER = """Banking assistant (step 2: read-only, stub data).
Signed in as {user_id} (DEV identity — real auth is not wired up yet).
Type 'exit' to quit.
"""


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    try:
        service = AIService()  # real Azure provider
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # e.g. a malformed endpoint the SDK rejects outright
        print(f"Could not start the AI service: {exc}", file=sys.stderr)
        return 2

    # THE EDGE. Identity is established here, once, and threaded into every
    # turn — the model never supplies it. This is dev-only: when Person A's
    # `get_current_user` exists, this single line becomes
    # `context = build_context(user.id, user.account_ids)` and nothing else in
    # the AI layer changes.
    context = dev_context()

    print(BANNER.format(user_id=context.user_id))
    history: list[Message] = []

    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not user_input:
            continue
        if user_input.lower() in _EXIT_WORDS:
            return 0

        try:
            reply, history = service.handle_message(history, user_input, context)
        except ProviderError as exc:
            # Keep the REPL alive; the history is unchanged so the user can retry.
            print(f"\nmodel error: {exc}\n", file=sys.stderr)
            continue
        except KeyboardInterrupt:
            print()
            return 0

        print(f"\nbot> {reply}\n")


if __name__ == "__main__":
    raise SystemExit(main())

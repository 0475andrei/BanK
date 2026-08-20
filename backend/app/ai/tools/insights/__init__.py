"""Insights (analytical) read tools.

Kept apart from `tools/banking` because the two agents' toolsets diverge from
here on: banking tools answer "what is true right now", insights tools feed
analysis over a window of time.
"""

from app.ai.tools.insights.get_transactions_in_range import GetTransactionsInRangeTool

__all__ = ["GetTransactionsInRangeTool"]

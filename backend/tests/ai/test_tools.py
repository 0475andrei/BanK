"""The stub tool, its validation boundary, and the registry."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.ai.context import Context
from app.ai.schemas import ToolCall, ToolResult
from app.ai.tools.banking import GetBalanceTool
from app.ai.tools.base import Tool
from app.ai.tools.registry import ToolRegistry
from tests.ai.conftest import OWNED_ACCOUNT_IDS


def test_get_balance_returns_fixed_stub_figures(context):
    tool = GetBalanceTool()

    result = tool.execute(
        ToolCall(id="c1", name="get_balance", arguments={"account_id": OWNED_ACCOUNT_IDS[0]}),
        context,
    )

    assert result.ok
    assert result.tool_call_id == "c1"
    assert result.data == {
        "account_id": OWNED_ACCOUNT_IDS[0],
        "balance_minor": 12345,
        "currency": "USD",
        "source": "stub",
    }
    # Minor units stay an int — never a float.
    assert isinstance(result.data["balance_minor"], int)


def test_get_balance_is_read_only():
    assert GetBalanceTool().read_only is True


def test_execute_rejects_invalid_input_without_raising(context):
    tool = GetBalanceTool()

    result = tool.execute(
        ToolCall(id="c1", name="get_balance", arguments={"account_id": 123}), context
    )

    assert result.ok is False
    assert "account_id" in (result.error or "")
    assert result.tool_call_id == "c1"


def test_execute_contains_a_crashing_tool(context):
    class Boom(Tool):
        name = "boom"
        description = "always fails"
        input_schema = GetBalanceTool.input_schema

        def run(self, validated_input: BaseModel, context: Context) -> ToolResult:
            raise RuntimeError("secret detail that must not leak")

    result = Boom().execute(ToolCall(id="c1", name="boom", arguments={}), context)

    assert result.ok is False
    assert "secret detail" not in (result.error or "")


def test_registry_specs_and_lookup():
    registry = ToolRegistry([GetBalanceTool()])

    assert registry.names() == ["get_balance"]
    assert registry.get("get_balance") is not None
    assert registry.get("transfer_money") is None

    spec = registry.list_specs()[0]
    assert spec["type"] == "function"
    assert spec["function"]["name"] == "get_balance"
    assert "account_id" in spec["function"]["parameters"]["properties"]


def test_registry_rejects_duplicates():
    registry = ToolRegistry([GetBalanceTool()])

    with pytest.raises(ValueError):
        registry.register(GetBalanceTool())


def test_registry_subset_narrows_permissions():
    registry = ToolRegistry([GetBalanceTool()])

    assert registry.subset(["get_balance"]).names() == ["get_balance"]
    assert registry.subset([]).names() == []


def test_no_write_tools_are_registered():
    """Guardrail: the model is untrusted; it may only read in this step."""
    from app.ai.service import build_banking_tools

    assert all(tool.read_only for tool in build_banking_tools())

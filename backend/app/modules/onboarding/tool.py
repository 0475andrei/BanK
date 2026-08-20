"""propose_registration - the onboarding agent's only tool.

Pure structured-data extraction: no DB access, no side effects. It hands
back whatever the model currently believes the user's registration fields
are, so the router can surface them to the frontend as a confirmation
screen. Account creation only ever happens through POST /auth/register,
fired by an explicit human confirmation click - this tool never creates
anything, and never bypasses that endpoint's validation.
"""

from pydantic import BaseModel

from app.ai.context import Context
from app.ai.schemas import ToolResult
from app.ai.tools.base import Tool


class ProposeRegistrationInput(BaseModel):
    email: str
    password: str
    first_name: str
    last_name: str
    national_id: str
    phone: str | None = None
    address: str | None = None
    referral_code: str | None = None


class ProposeRegistrationTool(Tool):
    name = "propose_registration"
    description = (
        "Call this once you have collected all required fields (email, "
        "password, first_name, last_name, national_id) and have explicitly "
        "asked the user about each optional one (phone, address, "
        "referral_code) - even if they chose to skip it, pass null for it. "
        "This does NOT create the account; it only reports what you've "
        "gathered so the app can show the user a confirmation screen before "
        "anything is submitted."
    )
    input_schema = ProposeRegistrationInput
    read_only = True

    async def run(self, validated_input: BaseModel, context: Context) -> ToolResult:
        return ToolResult(name=self.name, data=validated_input.model_dump())

"""enforce_face_confirmation's `require_enrolled` gate (Step 16, item 3).

Not exercised through the HTTP layer - no existing route passes
`require_enrolled=True` yet (it is a capability for a future caller, added
without touching transfers/payments). These call the service function
directly against the real test database, the same way
face_auth/service.py::has_face_enrolled needs a real face_credentials row
(or the deliberate absence of one) to answer.
"""

import pytest

from app.core.exceptions import FaceConfirmationRequiredError, FaceEnrollmentRequiredError
from app.modules.face_auth import service as face_auth_service


async def test_require_enrolled_false_no_ops_for_an_unenrolled_user(user_factory, supabase):
    """Existing behaviour, unchanged: `required=False` and the new parameter
    left at its default both mean "nothing to check here"."""
    user = await user_factory()

    await face_auth_service.enforce_face_confirmation(
        supabase, user, required=False, token=None
    )


async def test_require_enrolled_true_rejects_an_unenrolled_user(user_factory, supabase):
    user = await user_factory()

    with pytest.raises(FaceEnrollmentRequiredError):
        await face_auth_service.enforce_face_confirmation(
            supabase, user, required=False, token=None, require_enrolled=True
        )


async def test_require_enrolled_true_still_asks_for_a_token_when_required(
    user_factory, supabase, enroll_face
):
    """`require_enrolled=True` on an enrolled user is not itself a pass - it
    only clears the enrollment precondition. The normal `required`/`token`
    flow underneath still runs: no token supplied still asks for one."""
    user = await user_factory()
    await enroll_face(user.id)  # enrolled; the returned token is unused here

    with pytest.raises(FaceConfirmationRequiredError):
        await face_auth_service.enforce_face_confirmation(
            supabase, user, required=True, token=None, require_enrolled=True
        )


async def test_require_enrolled_true_proceeds_to_normal_flow_for_an_enrolled_user(
    user_factory, supabase, enroll_face
):
    """With a real, freshly-issued token the call goes all the way through
    and consumes it - the same "normal flow" an existing caller gets from
    `required=True` alone; `require_enrolled=True` changes nothing once
    enrollment is confirmed."""
    user = await user_factory()
    token = await enroll_face(user.id)

    await face_auth_service.enforce_face_confirmation(
        supabase, user, required=True, token=token, require_enrolled=True
    )

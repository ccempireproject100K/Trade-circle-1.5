"""Optional company accounts: a business owner can add teammates.

Solo contractors never see any of this. A teammate keeps their own login and
their own profile; the owner invites them by email as an admin or a
contributor, and they must accept before they can do anything.

- Contributors get only the permissions they were given.
- Admins get every permission, and can invite, adjust and remove contributors.
- Only the owner can add or change admins. Billing, plan, alerts, handoffs,
  account settings and ownership stay with the owner: those routes never accept
  a business header, and there is no ownership transfer.
- Nobody can change their own role or permissions.
- Membership is checked on every request, so removing someone stops their
  next action. Each change is recorded in `team_log`.
- A teammate's link to the business shows on the public profile only if the
  teammate turns it on.
"""
from fastapi import Depends, HTTPException, Request, status

from .security import current_user

PERMISSIONS = {
    "profile": "Edit the business profile and landing page",
    "portfolio": "Add, caption, arrange and delete portfolio photos",
    "follow_ups": "See and update follow-ups, including customer contact details",
    "jobs": "See and update jobs",
}
ROLES = ("admin", "contributor")
BUSINESS_HEADER = "x-tc-business"


def member_id(business_id: str, user_id: str) -> str:
    return f"{business_id}:{user_id}"


def effective_permissions(member: dict) -> list[str]:
    return list(PERMISSIONS) if member["role"] == "admin" else [p for p in member.get("permissions", []) if p in PERMISSIONS]


def acting_for(permission: str):
    """The account a request works on: the signed-in member, or a business they're an active teammate of.

    Without the business header nothing changes, so solo contractors need no setup.
    """

    async def dependency(request: Request, user: dict = Depends(current_user)) -> dict:
        business_id = request.headers.get(BUSINESS_HEADER)
        if not business_id or business_id == user["_id"]:
            return user
        db = request.app.state.db
        member = await db.team_members.find_one({"_id": member_id(business_id, user["_id"]), "status": "active"})
        if member is None or permission not in effective_permissions(member):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have access to that for this business.")
        owner = await db.users.find_one({"_id": business_id})
        if owner is None or owner.get("disabled"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "That business account isn't active.")
        request.state.on_behalf_of = business_id  # read by the audit log
        return owner

    return dependency

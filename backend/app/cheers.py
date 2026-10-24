"""The cheers economy: a thank-you with weight, run on paying it forward.

A cheer you receive starts out WAITING. It only COLLECTS — banks — when you
send a cheer to someone else: strict 1-for-1 pairing, oldest waiting first,
and the person you give to need not be the person who gave to you. Collected
can never exceed given, at any scale.

Two kinds of cheers (owner model, 2026-10-23):

- ALLOWANCE cheers are the monthly plan deposit (tiers.CHEERS_MONTHLY), the
  economy's only mint. They stack in the member's allowance wallet up to the
  plan cap (tiers.CHEERS_WALLET_CAP); at the cap, refills pause. They are
  spend-only: never earned, never counted in anyone's bank. Given, one
  lands as 1 waiting cheer.
- BANK cheers are earned. Every collected cheer banks: lifetime banked is
  the member's public standing (only grows, never spent down), and each
  banked cheer also adds 1 spendable bank cheer to the wallet. A bank cheer
  given lands DOUBLE — 1 spent creates 2 waiting cheers for the receiver;
  each landed unit banks as 1 when its receiver collects it.

Spend order is automatic: allowance first, then bank cheers. Free members
have no allowance and cannot initiate from nothing: their gives are funded
by their own banked cheers, or by the LOAN — a pass-through where giving
with an empty wallet but a waiting cheer is funded atomically by the cheer
the give collects (the collected cheer banks, then pays for the give;
balance stays 0, waiting drops by 1).

Anti-gaming, server-side: no self-cheers; a cheer cannot be taken back;
giving is capped at 1 cheer per giver→receiver per day; unlocking is what
spreads — a send collects for its giver at most 2 times per pair per
rolling 7 days (past that, gives still land for the receiver but unlock
nothing). Every send records its unlock pairing (`unlock_pair` on the sent
cheers, `unlocked_by` + `collected_at` on the collected one) so the cap is
auditable, and an admin pair-frequency report watches for farming.

Wallet state lives on the member (`users.cheers`): the spendable allowance
and bank balances, the plan-cycle anchor day, and refill bookkeeping. Every
movement is trailed in `cheers_ledger` (refill / spend_allowance /
spend_bank / collect / pass_through), so the wallet always reconciles with
the ledger. Notifications are in-app only (app.notices) — never texts;
cheer notices flow into the existing email digests like other community
activity.
"""
import uuid
from calendar import monthrange
from datetime import date, datetime, timedelta

from fastapi import HTTPException, status
from pymongo import ReturnDocument

from .deps import now
from .notices import notify
from .tiers import TIER_ORDER, cheers_cap, cheers_monthly

# At most this many of a giver's sends to the same receiver may collect one
# of the giver's waiting cheers per rolling window. Gives past the cap still
# land for the receiver; they just unlock nothing for the giver.
UNLOCK_PAIR_LIMIT = 2
UNLOCK_WINDOW = timedelta(days=7)


# --- the wallet: monthly allowance, plan changes, refills ---


def _next_anchor(after: date, anchor_day: int) -> date:
    """The next monthly anniversary of `anchor_day` strictly after `after` (clamped to the month's length)."""
    year, month = after.year, after.month
    while True:
        candidate = date(year, month, min(anchor_day, monthrange(year, month)[1]))
        if candidate > after:
            return candidate
        month += 1
        if month == 13:
            year, month = year + 1, 1


async def _ledger(db, user_id: str, kind: str, amount: int, *, day: date, note: str = "") -> None:
    await db.cheers_ledger.insert_one(
        {"_id": uuid.uuid4().hex, "user_id": user_id, "kind": kind, "amount": amount, "day": day.isoformat(), "note": note, "created_at": now()}
    )


async def sync_wallet(db, user: dict, day: date) -> dict:
    """Bring a member's cheers wallet up to date for `day` and return it.

    First touch creates the wallet and lands the current plan's allowance.
    A plan upgrade applies the new allowance and cap right away and
    re-anchors the cycle to today; a downgrade claws nothing back — the
    lower cap simply governs future refills. Monthly refills then land for
    every cycle anniversary up to `day`, capped: at the cap, that month's
    refill doesn't land until the member spends down.
    """
    uid = user["_id"]
    tier = user.get("tier", "free")
    wallet = user.get("cheers")
    if wallet is None:
        created = user.get("created_at")
        wallet = {
            "allowance": min(cheers_cap(user), cheers_monthly(user)),
            "bank": 0,
            "anchor_day": created.day if isinstance(created, datetime) else day.day,
            "last_refill_on": day.isoformat(),
            "tier": tier,
        }
        await db.users.update_one({"_id": uid}, {"$set": {"cheers": wallet}})
        if wallet["allowance"]:
            await _ledger(db, uid, "refill", wallet["allowance"], day=day, note="monthly allowance")
        user["cheers"] = wallet
        return wallet

    changed = False
    rank, held_rank = TIER_ORDER.get(tier, 0), TIER_ORDER.get(wallet.get("tier", "free"), 0)
    if rank > held_rank:
        grant = min(cheers_cap(user), wallet["allowance"] + cheers_monthly(user)) - wallet["allowance"]
        if grant > 0:
            wallet["allowance"] += grant
            await _ledger(db, uid, "refill", grant, day=day, note="plan upgrade")
        wallet["anchor_day"] = day.day
        wallet["last_refill_on"] = day.isoformat()
        wallet["tier"] = tier
        changed = True
    elif tier != wallet.get("tier"):
        wallet["tier"] = tier
        changed = True

    monthly, cap = cheers_monthly(user), cheers_cap(user)
    cursor = date.fromisoformat(wallet["last_refill_on"])
    while monthly > 0:
        nxt = _next_anchor(cursor, wallet["anchor_day"])
        if nxt > day:
            break
        if wallet["allowance"] < cap:
            added = min(cap, wallet["allowance"] + monthly) - wallet["allowance"]
            wallet["allowance"] += added
            await _ledger(db, uid, "refill", added, day=nxt, note="monthly allowance")
        cursor = nxt
    if monthly > 0 and wallet["last_refill_on"] != day.isoformat():
        wallet["last_refill_on"] = day.isoformat()
        changed = True
    if changed:
        await db.users.update_one({"_id": uid}, {"$set": {"cheers": wallet}})
    user["cheers"] = wallet
    return wallet


async def apply_refills(db, day: date) -> int:
    """The monthly top-up sweep, run with the scheduled jobs: sync every wallet.

    The lazy sync on every cheers touch already guarantees a member's
    allowance is current the moment they give, collect or look; this sweep
    keeps members who haven't visited current too.
    """
    count = 0
    async for user in db.users.find({"$or": [{"cheers": {"$exists": True}}, {"tier": {"$in": ["starter", "full"]}}]}):
        if user.get("disabled"):
            continue
        await sync_wallet(db, user, day)
        count += 1
    return count


# --- counts and tallies (over the cheers collection) ---


async def waiting_count(db, user_id: str) -> int:
    return await db.cheers.count_documents({"receiver_id": user_id, "status": "waiting"})


async def banked_count(db, user_id: str) -> int:
    """Lifetime banked: every cheer this member has ever collected. Standing only — it never spends down."""
    return await db.cheers.count_documents({"receiver_id": user_id, "status": "collected"})


async def banked_for(db, owner_ids) -> dict:
    """Lifetime banked counts for a set of members, for page/profile badges."""
    ids = list(set(owner_ids))
    found = {i: 0 for i in ids}
    if ids:
        async for c in db.cheers.find({"receiver_id": {"$in": ids}, "status": "collected"}, {"receiver_id": 1}):
            found[c["receiver_id"]] += 1
    return found


async def tallies(db, user: dict, day: date) -> dict:
    wallet = await sync_wallet(db, user, day)
    uid = user["_id"]
    banked = await banked_count(db, uid)
    return {
        "allowance": wallet["allowance"],
        "bank": wallet["bank"],
        "banked": banked,
        "collected": banked,
        "waiting": await waiting_count(db, uid),
        "given": await db.cheers.count_documents({"giver_id": uid}),
        "monthly": cheers_monthly(user),
        "cap": cheers_cap(user),
    }


async def _names(db, ids) -> dict:
    found = {}
    async for p in db.profiles.find({"owner_id": {"$in": list(set(ids))}}, {"owner_id": 1, "slug": 1, "business_name": 1}):
        found[p["owner_id"]] = {"slug": p["slug"], "business_name": p["business_name"]}
    return found


async def activity(db, user_id: str, limit: int = 20) -> dict:
    """Recent given and received cheers for the member's own dashboard.

    A note is the receiver's to read only once the cheer collects, so
    waiting received cheers show no note here.
    """
    given = await db.cheers.find({"giver_id": user_id}).sort("created_at", -1).to_list(limit)
    received = await db.cheers.find({"receiver_id": user_id}).sort("created_at", -1).to_list(limit)
    names = await _names(db, [c["receiver_id"] for c in given] + [c["giver_id"] for c in received])

    def view(cheer: dict, other_id: str, show_note: bool) -> dict:
        return {
            "id": cheer["_id"],
            "member": names.get(other_id),
            "status": cheer["status"],
            "funding": cheer["funding"],
            "post_id": cheer.get("post_id"),
            "handoff_id": cheer.get("handoff_id"),
            "note": cheer.get("note") if show_note else None,
            "created_at": cheer["created_at"],
            "collected_at": cheer.get("collected_at"),
        }

    return {
        "given": [view(c, c["receiver_id"], True) for c in given],
        "received": [view(c, c["giver_id"], c["status"] == "collected") for c in received],
    }


# --- sending: the pairing, the caps, the funding ---


async def send_cheer(db, giver: dict, receiver: dict, *, post: dict | None = None, handoff: dict | None = None, note: str | None = None, day: date) -> dict:
    """Send a cheer from `giver` to `receiver`, collecting the giver's oldest waiting cheer if the pairing allows.

    The spend, the new waiting cheers and the collection land together:
    allowance funds 1 unit, a bank cheer funds 2, and the pass-through loan
    funds 1 out of the very cheer the give collects.
    """
    giver_id, receiver_id = giver["_id"], receiver["_id"]
    if giver_id == receiver_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "You can't cheer yourself — a cheer has to travel to somebody else.")
    if receiver.get("disabled"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    note = (note or "").strip() or None
    wallet = await sync_wallet(db, giver, day)
    stamp = now()
    names = await _names(db, [giver_id, receiver_id])
    giver_name = names.get(giver_id, {}).get("business_name", "A member")
    receiver_name = names.get(receiver_id, {}).get("business_name", "them")

    # Giving cap: one cheer (one send) per pair per day, however it's funded.
    sent_today = await db.cheers.find(
        {"giver_id": giver_id, "receiver_id": receiver_id, "day": day.isoformat()}, {"send_id": 1}
    ).to_list(10)
    if sent_today:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"You've already cheered {receiver_name} today — one cheer per person per day. Spread the rest around.",
        )

    # Unlock-pair cap: at most UNLOCK_PAIR_LIMIT of my sends to this person
    # may have collected one of my waiting cheers in the rolling window.
    pair_units = await db.cheers.find(
        {"giver_id": giver_id, "receiver_id": receiver_id, "unlock_pair": {"$ne": None}, "created_at": {"$gte": stamp - UNLOCK_WINDOW}},
        {"send_id": 1},
    ).to_list(100)
    unlocks_used = len({c["send_id"] for c in pair_units})
    oldest = await db.cheers.find_one({"receiver_id": giver_id, "status": "waiting"}, sort=[("created_at", 1)])
    can_unlock = oldest is not None and unlocks_used < UNLOCK_PAIR_LIMIT

    # Funding, in order: allowance, then bank cheers, then the loan.
    if wallet["allowance"] >= 1:
        funding, units = "allowance", 1
    elif wallet["bank"] >= 1:
        funding, units = "bank", 2
    elif oldest is not None and can_unlock:
        funding, units = "loan", 1
    elif oldest is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Your cheers through {receiver_name} have collected for you twice this week already — the rest still land for them, "
            "they just can't collect for you. Cheer someone new to collect what's waiting, or let the week roll.",
        )
    else:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "You don't have a cheer to give right now. Cheers come from your monthly plan allowance or from other members "
            "cheering your work — and a waiting cheer can always be passed on.",
        )

    if funding in ("allowance", "bank"):
        field = "cheers.allowance" if funding == "allowance" else "cheers.bank"
        debited = await db.users.find_one_and_update(
            {"_id": giver_id, field: {"$gte": 1}}, {"$inc": {field: -1}}, return_document=ReturnDocument.AFTER
        )
        if debited is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Your cheers balance just changed — give it another try.")
        wallet = debited["cheers"]
        await _ledger(db, giver_id, f"spend_{funding}", 1, day=day)

    send_id = uuid.uuid4().hex
    unlock_pair = oldest["_id"] if can_unlock else None
    docs = [
        {
            "_id": uuid.uuid4().hex,
            "send_id": send_id,
            "giver_id": giver_id,
            "receiver_id": receiver_id,
            "post_id": post["_id"] if post else None,
            "handoff_id": handoff["_id"] if handoff else None,
            "note": note if i == 0 else None,
            "funding": funding,
            "day": day.isoformat(),
            "status": "waiting",
            "unlock_pair": unlock_pair,
            "unlocked_by": None,
            "collected_at": None,
            "created_at": stamp,
        }
        for i in range(units)
    ]
    await db.cheers.insert_many(docs)

    collected = None
    if can_unlock:
        await db.cheers.update_one(
            {"_id": oldest["_id"], "status": "waiting"},
            {"$set": {"status": "collected", "collected_at": stamp, "unlocked_by": docs[0]["_id"]}},
        )
        await db.users.update_one({"_id": giver_id}, {"$inc": {"cheers.bank": 1}})
        await _ledger(db, giver_id, "collect", 1, day=day)
        if funding == "loan":
            # The pass-through: the cheer just banked pays for this give.
            await db.users.update_one({"_id": giver_id}, {"$inc": {"cheers.bank": -1}})
            await _ledger(db, giver_id, "pass_through", 1, day=day)
        origin = await _names(db, [oldest["giver_id"]])
        from_name = origin.get(oldest["giver_id"], {}).get("business_name", "A member")
        text = f"Your cheer from {from_name} just landed."
        if oldest.get("note"):
            text += f' "{oldest["note"]}"'
        link = f"/posts/{oldest['post_id']}" if oldest.get("post_id") else "/profile"
        await notify(db, giver_id, "cheer_collected", text, link)
        collected = {"from": from_name, "note": oldest.get("note")}

    if post:
        text = f"{giver_name} cheered your post \"{post['title']}\" — it's waiting."
        if units == 2:
            text = f"{giver_name} cheered your post \"{post['title']}\" — 2 cheers are waiting."
        link = f"/posts/{post['_id']}"
    elif handoff:
        text = f"{giver_name} cheered you for covering their job — it's waiting."
        link = "/handoffs"
    else:
        text = f"{giver_name} cheered you — it's waiting."
        if units == 2:
            text = f"{giver_name} cheered you — 2 cheers are waiting."
        link = "/community"
    await notify(db, receiver_id, "cheer_received", text, link)

    fresh = await db.users.find_one({"_id": giver_id}, {"cheers": 1})
    return {
        "cheer_id": docs[0]["_id"],
        "sent": units,
        "funding": funding,
        "collected": collected,
        "wallet": {
            "allowance": fresh["cheers"]["allowance"],
            "bank": fresh["cheers"]["bank"],
            "waiting": await waiting_count(db, giver_id),
            "banked": await banked_count(db, giver_id),
        },
    }


# --- moderation: pair frequency ---


async def pair_report(db, weeks: int = 12, min_count: int = 4) -> dict:
    """Who cheers whom, how often — the farming watch (follows the handoff patterns report).

    This only surfaces patterns. Nothing here limits or penalizes anyone;
    the caps in send_cheer are the enforcement.
    """
    weeks = max(1, min(weeks, 52))
    since = now() - timedelta(weeks=weeks)
    pairs: dict[tuple[str, str], dict] = {}
    async for c in db.cheers.find({"created_at": {"$gte": since}}):
        row = pairs.setdefault((c["giver_id"], c["receiver_id"]), {"units": 0, "sends": set(), "unlocks": set(), "doubled": set()})
        row["units"] += 1
        row["sends"].add(c["send_id"])
        if c.get("unlock_pair"):
            row["unlocks"].add(c["send_id"])
        if c.get("funding") == "bank":
            row["doubled"].add(c["send_id"])
    names = await _names(db, [i for pair in pairs for i in pair])
    rows = []
    for (giver_id, receiver_id), row in pairs.items():
        back = pairs.get((receiver_id, giver_id), {})
        sends, unlocks = len(row["sends"]), len(row["unlocks"])
        rows.append(
            {
                "from": names.get(giver_id, {"slug": None, "business_name": "Former member"}),
                "to": names.get(receiver_id, {"slug": None, "business_name": "Former member"}),
                "units": row["units"],
                "sends": sends,
                "unlocks": unlocks,
                "doubled_sends": len(row["doubled"]),
                "reverse_sends": len(back.get("sends", ())),
                "review": sends >= min_count or unlocks >= min_count,
            }
        )
    rows.sort(key=lambda r: (not r["review"], -r["sends"]))
    return {"weeks": weeks, "min_count": min_count, "pairs": rows}

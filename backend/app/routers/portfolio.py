import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status

from .. import photos
from ..deps import get_db, now, public_doc
from ..models import PortfolioCaption, PortfolioIn, PortfolioOrder
from ..security import current_user
from ..team import acting_for

router = APIRouter(prefix="/api/me/portfolio", tags=["portfolio"])

MAX_PHOTOS = 200


async def _next_position(db, user: dict) -> int:
    if await db.portfolio.count_documents({"owner_id": user["_id"]}) >= MAX_PHOTOS:
        raise HTTPException(status.HTTP_409_CONFLICT, f"You can keep up to {MAX_PHOTOS} photos. Delete some to add more.")
    last = await db.portfolio.find({"owner_id": user["_id"]}).sort("position", -1).to_list(1)
    return last[0]["position"] + 1 if last else 0


@router.get("")
async def list_items(user: dict = Depends(acting_for("portfolio")), db=Depends(get_db)):
    items = await db.portfolio.find({"owner_id": user["_id"]}, {"media_keys": 0}).sort("position", 1).to_list(500)
    return [public_doc(i) for i in items]


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_item(body: PortfolioIn, request: Request, user: dict = Depends(acting_for("portfolio")), db=Depends(get_db)):
    """Add a photo by link to an image hosted elsewhere."""
    item = {
        "_id": uuid.uuid4().hex,
        "owner_id": user["_id"],
        **body.model_dump(mode="json"),
        "position": await _next_position(db, user),
        "created_at": now(),
    }
    await db.portfolio.insert_one(item)
    request.state.audit_record = item["_id"]
    return public_doc(item)


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_item(
    request: Request,
    file: UploadFile = File(...),
    caption: str = Form("", max_length=280),
    user: dict = Depends(acting_for("portfolio")),
    db=Depends(get_db),
):
    """Upload a photo from the phone or computer."""
    position = await _next_position(db, user)
    photo = await photos.ingest(request, file, user["_id"], "portfolio")
    item_id = photo["id"]
    item = {
        "_id": item_id,
        "owner_id": user["_id"],
        "image_url": photo["image_url"],
        "thumb_url": photo["thumb_url"],
        "media_keys": photo["media_keys"],
        "width": photo["width"],
        "height": photo["height"],
        "caption": caption.strip(),
        "trade_tag": None,
        "taken_on": None,
        "position": position,
        "created_at": now(),
    }
    try:
        await db.portfolio.insert_one(item)
    except Exception:
        photos.discard(request, item)
        raise
    request.state.audit_record = item_id
    return public_doc({k: v for k, v in item.items() if k != "media_keys"})


@router.patch("/{item_id}")
async def update_caption(item_id: str, body: PortfolioCaption, user: dict = Depends(acting_for("portfolio")), db=Depends(get_db)):
    result = await db.portfolio.update_one({"_id": item_id, "owner_id": user["_id"]}, {"$set": {"caption": body.caption}})
    if result.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    return {"id": item_id, "caption": body.caption}


@router.put("/order")
async def reorder(body: PortfolioOrder, user: dict = Depends(acting_for("portfolio")), db=Depends(get_db)):
    """Drag-and-drop result. Must list every item exactly once."""
    owned = {i["_id"] for i in await db.portfolio.find({"owner_id": user["_id"]}, {"_id": 1}).to_list(500)}
    if len(body.ids) != len(set(body.ids)) or set(body.ids) != owned:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Order must list each of your items once")
    for position, item_id in enumerate(body.ids):
        await db.portfolio.update_one({"_id": item_id, "owner_id": user["_id"]}, {"$set": {"position": position}})
    return {"ids": body.ids}


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: str, request: Request, user: dict = Depends(acting_for("portfolio")), db=Depends(get_db)):
    item = await db.portfolio.find_one_and_delete({"_id": item_id, "owner_id": user["_id"]})
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    photos.discard(request, item)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

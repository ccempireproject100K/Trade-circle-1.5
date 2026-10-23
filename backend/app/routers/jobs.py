import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from ..deps import get_db, now, partial_update, public_doc
from ..models import JobIn, JobUpdate
from ..security import current_user
from ..team import acting_for

router = APIRouter(prefix="/api/jobs", tags=["job sheet"])

CLEARABLE = {"customer_phone", "scheduled_on", "estimate_cents"}


async def _own_job(db, user: dict, job_id: str) -> dict:
    job = await db.jobs.find_one({"_id": job_id, "owner_id": user["_id"]})
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return job


@router.get("")
async def list_jobs(user: dict = Depends(acting_for("jobs")), db=Depends(get_db)):
    jobs = await db.jobs.find({"owner_id": user["_id"]}).sort("created_at", -1).to_list(1000)
    return [public_doc(j) for j in jobs]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_job(body: JobIn, request: Request, user: dict = Depends(acting_for("jobs")), db=Depends(get_db)):
    job = {"_id": uuid.uuid4().hex, "owner_id": user["_id"], **body.model_dump(mode="json"), "created_at": now()}
    await db.jobs.insert_one(job)
    request.state.audit_record = job["_id"]
    return public_doc(job)


@router.get("/{job_id}")
async def get_job(job_id: str, user: dict = Depends(acting_for("jobs")), db=Depends(get_db)):
    return public_doc(await _own_job(db, user, job_id))


@router.patch("/{job_id}")
async def update_job(job_id: str, body: JobUpdate, user: dict = Depends(acting_for("jobs")), db=Depends(get_db)):
    await _own_job(db, user, job_id)
    await db.jobs.update_one({"_id": job_id, "owner_id": user["_id"]}, partial_update(body, CLEARABLE))
    return public_doc(await _own_job(db, user, job_id))


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(job_id: str, user: dict = Depends(acting_for("jobs")), db=Depends(get_db)):
    result = await db.jobs.delete_one({"_id": job_id, "owner_id": user["_id"]})
    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

import logging
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.api.deps import SessionDep
from app.worklog.models import Freelancer, Payment, WorkLog
from app.worklog.schemas import (
    FreelancerListResponse,
    FreelancerResponse,
    PaymentCreate,
    PaymentListItem,
    PaymentListResponse,
    PaymentResponse,
    PaymentWorkLogItem,
    TimeEntryResponse,
    WorkLogDetailResponse,
    WorkLogListItem,
    WorkLogListResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["worklogs"])


@router.get("/freelancers/", response_model=FreelancerListResponse)
def get_freelancers(session: SessionDep) -> Any:
    """
    List all freelancers.
    """
    try:
        frs = session.exec(select(Freelancer)).all()
        data = [
            FreelancerResponse(
                id=f.id,
                name=f.name,
                email=f.email,
                hourly_rate=f.hourly_rate,
                created_at=f.created_at,
            )
            for f in frs
        ]
        return FreelancerListResponse(data=data, count=len(data))
    except Exception as e:
        logger.error(f"Failed to fetch freelancers: {e}")
        return FreelancerListResponse(data=[], count=0)


@router.get("/worklogs/", response_model=WorkLogListResponse)
def get_worklogs(
    session: SessionDep,
    date_from: date | None = None,
    date_to: date | None = None,
    freelancer_id: int | None = None,
    status: str | None = None,
) -> Any:
    """
    List all worklogs with earned amounts.
    date_from: filter start date
    date_to: filter end date
    freelancer_id: filter by freelancer
    status: filter by status ('pending' or 'paid')
    """
    try:
        # Get all worklogs (type='worklog')
        wls = session.exec(
            select(WorkLog).where(WorkLog.type == "worklog")
        ).all()

        results = []
        for wl in wls:
            # Apply filters
            if date_from and wl.created_at.date() < date_from:
                continue
            if date_to and wl.created_at.date() > date_to:
                continue
            if freelancer_id and wl.freelancer_id != freelancer_id:
                continue
            if status and wl.status != status:
                continue

            # Get freelancer info
            fr = None
            if wl.freelancer_id:
                fr = session.get(Freelancer, wl.freelancer_id)

            # Get time entries for this worklog
            entries = session.exec(
                select(WorkLog).where(
                    WorkLog.type == "time_entry",
                    WorkLog.parent_id == wl.id,
                )
            ).all()

            # Calculate totals using python (per AGENTS.md)
            t_hrs = 0.0
            for e in entries:
                if e.hours:
                    t_hrs += e.hours

            rt = fr.hourly_rate if fr else 0.0
            amt = t_hrs * rt

            results.append(
                WorkLogListItem(
                    id=wl.id,
                    task_name=wl.task_name,
                    description=wl.description,
                    freelancer_id=wl.freelancer_id,
                    freelancer_name=fr.name if fr else None,
                    freelancer_email=fr.email if fr else None,
                    hourly_rate=rt,
                    total_hours=t_hrs,
                    earned_amount=amt,
                    status=wl.status,
                    payment_id=wl.payment_id,
                    created_at=wl.created_at,
                )
            )

        return WorkLogListResponse(data=results, count=len(results))
    except Exception as e:
        logger.error(f"Failed to fetch worklogs: {e}")
        return WorkLogListResponse(data=[], count=0)


@router.get("/worklogs/{wl_id}", response_model=WorkLogDetailResponse)
def get_worklog_detail(session: SessionDep, wl_id: int) -> Any:
    """
    Get worklog detail with time entries.
    wl_id: worklog ID
    """
    wl = session.get(WorkLog, wl_id)
    if not wl or wl.type != "worklog":
        raise HTTPException(status_code=404, detail="Worklog not found")

    # Get freelancer
    fr = None
    if wl.freelancer_id:
        fr = session.get(Freelancer, wl.freelancer_id)

    # Get time entries
    entries = session.exec(
        select(WorkLog).where(
            WorkLog.type == "time_entry",
            WorkLog.parent_id == wl.id,
        )
    ).all()

    # Calculate totals
    t_hrs = 0.0
    for e in entries:
        if e.hours:
            t_hrs += e.hours

    rt = fr.hourly_rate if fr else 0.0
    amt = t_hrs * rt

    te_list = [
        TimeEntryResponse(
            id=e.id,
            start_time=e.start_time,
            end_time=e.end_time,
            hours=e.hours,
            created_at=e.created_at,
        )
        for e in entries
    ]

    return WorkLogDetailResponse(
        id=wl.id,
        task_name=wl.task_name,
        description=wl.description,
        freelancer_id=wl.freelancer_id,
        freelancer_name=fr.name if fr else None,
        freelancer_email=fr.email if fr else None,
        hourly_rate=rt,
        total_hours=t_hrs,
        earned_amount=amt,
        status=wl.status,
        payment_id=wl.payment_id,
        created_at=wl.created_at,
        time_entries=te_list,
    )


@router.post("/payments/", response_model=PaymentResponse, status_code=201)
def create_payment(session: SessionDep, payload: PaymentCreate) -> Any:
    """
    Create a payment batch.
    payload: date range and exclusions
    """
    if payload.date_range_end < payload.date_range_start:
        raise HTTPException(
            status_code=400, detail="date_range_end must be after date_range_start"
        )

    # Get eligible worklogs (pending, in date range, not excluded)
    wls = session.exec(
        select(WorkLog).where(
            WorkLog.type == "worklog",
            WorkLog.status == "pending",
        )
    ).all()

    eligible = []
    for wl in wls:
        if wl.created_at.date() < payload.date_range_start:
            continue
        if wl.created_at.date() > payload.date_range_end:
            continue
        if wl.id in payload.excluded_wl_ids:
            continue
        if wl.freelancer_id in payload.excluded_freelancer_ids:
            continue
        eligible.append(wl)

    if not eligible:
        raise HTTPException(
            status_code=400,
            detail="No eligible worklogs found for the given date range",
        )

    # Calculate total amount
    ttl = 0.0
    wl_items = []
    for wl in eligible:
        fr = None
        if wl.freelancer_id:
            fr = session.get(Freelancer, wl.freelancer_id)

        entries = session.exec(
            select(WorkLog).where(
                WorkLog.type == "time_entry",
                WorkLog.parent_id == wl.id,
            )
        ).all()

        t_hrs = 0.0
        for e in entries:
            if e.hours:
                t_hrs += e.hours

        rt = fr.hourly_rate if fr else 0.0
        amt = t_hrs * rt
        ttl += amt

        wl_items.append(
            PaymentWorkLogItem(
                id=wl.id,
                task_name=wl.task_name,
                freelancer_name=fr.name if fr else None,
                freelancer_id=wl.freelancer_id,
                total_hours=t_hrs,
                earned_amount=amt,
            )
        )

    # Create payment record
    pmt = Payment(
        status="draft",
        total_amount=round(ttl, 2),
        date_range_start=payload.date_range_start,
        date_range_end=payload.date_range_end,
    )
    session.add(pmt)
    session.commit()
    session.refresh(pmt)

    # Link worklogs to payment
    for wl in eligible:
        wl.payment_id = pmt.id
    session.commit()

    return PaymentResponse(
        id=pmt.id,
        status=pmt.status,
        total_amount=pmt.total_amount,
        date_range_start=pmt.date_range_start,
        date_range_end=pmt.date_range_end,
        created_at=pmt.created_at,
        worklogs=wl_items,
    )


@router.get("/payments/", response_model=PaymentListResponse)
def get_payments(session: SessionDep) -> Any:
    """
    List all payment batches.
    """
    try:
        pmts = session.exec(select(Payment)).all()
        data = []
        for p in pmts:
            # Count worklogs in this payment
            wls = session.exec(
                select(WorkLog).where(
                    WorkLog.type == "worklog",
                    WorkLog.payment_id == p.id,
                )
            ).all()

            data.append(
                PaymentListItem(
                    id=p.id,
                    status=p.status,
                    total_amount=p.total_amount,
                    date_range_start=p.date_range_start,
                    date_range_end=p.date_range_end,
                    created_at=p.created_at,
                    wl_count=len(wls),
                )
            )

        return PaymentListResponse(data=data, count=len(data))
    except Exception as e:
        logger.error(f"Failed to fetch payments: {e}")
        return PaymentListResponse(data=[], count=0)


@router.get("/payments/{pmt_id}", response_model=PaymentResponse)
def get_payment_detail(session: SessionDep, pmt_id: int) -> Any:
    """
    Get payment batch detail with included worklogs.
    pmt_id: payment ID
    """
    pmt = session.get(Payment, pmt_id)
    if not pmt:
        raise HTTPException(status_code=404, detail="Payment not found")

    # Get worklogs in this payment
    wls = session.exec(
        select(WorkLog).where(
            WorkLog.type == "worklog",
            WorkLog.payment_id == pmt.id,
        )
    ).all()

    wl_items = []
    for wl in wls:
        fr = None
        if wl.freelancer_id:
            fr = session.get(Freelancer, wl.freelancer_id)

        entries = session.exec(
            select(WorkLog).where(
                WorkLog.type == "time_entry",
                WorkLog.parent_id == wl.id,
            )
        ).all()

        t_hrs = 0.0
        for e in entries:
            if e.hours:
                t_hrs += e.hours

        rt = fr.hourly_rate if fr else 0.0
        amt = t_hrs * rt

        wl_items.append(
            PaymentWorkLogItem(
                id=wl.id,
                task_name=wl.task_name,
                freelancer_name=fr.name if fr else None,
                freelancer_id=wl.freelancer_id,
                total_hours=t_hrs,
                earned_amount=amt,
            )
        )

    return PaymentResponse(
        id=pmt.id,
        status=pmt.status,
        total_amount=pmt.total_amount,
        date_range_start=pmt.date_range_start,
        date_range_end=pmt.date_range_end,
        created_at=pmt.created_at,
        worklogs=wl_items,
    )


@router.post("/payments/{pmt_id}/confirm", response_model=PaymentResponse)
def confirm_payment(session: SessionDep, pmt_id: int) -> Any:
    """
    Confirm a payment batch, mark worklogs as paid.
    pmt_id: payment ID
    """
    pmt = session.get(Payment, pmt_id)
    if not pmt:
        raise HTTPException(status_code=404, detail="Payment not found")

    if pmt.status == "confirmed":
        raise HTTPException(status_code=400, detail="Payment already confirmed")

    # Mark payment as confirmed
    pmt.status = "confirmed"
    session.commit()

    # Mark all worklogs in this payment as paid
    wls = session.exec(
        select(WorkLog).where(
            WorkLog.type == "worklog",
            WorkLog.payment_id == pmt.id,
        )
    ).all()

    wl_items = []
    for wl in wls:
        wl.status = "paid"
        session.commit()

        fr = None
        if wl.freelancer_id:
            fr = session.get(Freelancer, wl.freelancer_id)

        entries = session.exec(
            select(WorkLog).where(
                WorkLog.type == "time_entry",
                WorkLog.parent_id == wl.id,
            )
        ).all()

        t_hrs = 0.0
        for e in entries:
            if e.hours:
                t_hrs += e.hours

        rt = fr.hourly_rate if fr else 0.0
        amt = t_hrs * rt

        wl_items.append(
            PaymentWorkLogItem(
                id=wl.id,
                task_name=wl.task_name,
                freelancer_name=fr.name if fr else None,
                freelancer_id=wl.freelancer_id,
                total_hours=t_hrs,
                earned_amount=amt,
            )
        )

    return PaymentResponse(
        id=pmt.id,
        status=pmt.status,
        total_amount=pmt.total_amount,
        date_range_start=pmt.date_range_start,
        date_range_end=pmt.date_range_end,
        created_at=pmt.created_at,
        worklogs=wl_items,
    )


@router.delete("/payments/{pmt_id}/worklogs/{wl_id}", status_code=200)
def exclude_worklog_from_payment(
    session: SessionDep, pmt_id: int, wl_id: int
) -> Any:
    """
    Exclude a worklog from a payment batch.
    pmt_id: payment ID
    wl_id: worklog ID to exclude
    """
    pmt = session.get(Payment, pmt_id)
    if not pmt:
        raise HTTPException(status_code=404, detail="Payment not found")

    if pmt.status == "confirmed":
        raise HTTPException(
            status_code=400, detail="Cannot modify a confirmed payment"
        )

    wl = session.get(WorkLog, wl_id)
    if not wl or wl.type != "worklog" or wl.payment_id != pmt_id:
        raise HTTPException(
            status_code=404, detail="Worklog not found in this payment"
        )

    # Remove worklog from payment
    wl.payment_id = None
    session.commit()

    # Recalculate payment total
    remaining = session.exec(
        select(WorkLog).where(
            WorkLog.type == "worklog",
            WorkLog.payment_id == pmt.id,
        )
    ).all()

    ttl = 0.0
    for r in remaining:
        fr = None
        if r.freelancer_id:
            fr = session.get(Freelancer, r.freelancer_id)

        entries = session.exec(
            select(WorkLog).where(
                WorkLog.type == "time_entry",
                WorkLog.parent_id == r.id,
            )
        ).all()

        t_hrs = 0.0
        for e in entries:
            if e.hours:
                t_hrs += e.hours

        rt = fr.hourly_rate if fr else 0.0
        ttl += t_hrs * rt

    pmt.total_amount = round(ttl, 2)
    session.commit()

    return {"message": "Worklog excluded from payment", "new_total": pmt.total_amount}

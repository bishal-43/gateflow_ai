"""services/dashboard_service.py — Dashboard query logic

Each function runs simple, focused SELECT queries.
No complex joins — readable and easy to understand.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.entry import EntrySession, EntryStatus
from models.invite import Invite, InviteType
from models.notification import Notification, NotificationType
from models.walkin import WalkInRequest, WalkInStatus
from schemas.dashboard import (
    AnalyticsGateRow,
    AnalyticsHourRow,
    AnalyticsReasonRow,
    AnalyticsResponse,
    AnalyticsWeekRow,
    EntriesResponse,
    EntryItem,
    OccupancyResponse,
    OverstayItem,
    OverstaysResponse,
    StatsResponse,
    WalkInItem,
    WalkInsResponse,
)


async def get_stats(db: AsyncSession, space_id: UUID) -> StatsResponse:
    """Single space summary — runs 5 small count queries."""

    async def count(where_clause) -> int:
        return (await db.execute(
            select(func.count()).select_from(EntrySession).where(
                EntrySession.space_id == space_id, where_clause
            )
        )).scalar_one()

    inside     = await count(EntrySession.status == EntryStatus.INSIDE)
    exited     = await count(EntrySession.status.in_([EntryStatus.EXITED, EntryStatus.ASSUMED_EXITED]))
    overstayed = await count(EntrySession.status == EntryStatus.OVERSTAYED)
    total      = await count(True)  # all sessions

    pending_walkins = (await db.execute(
        select(func.count()).select_from(WalkInRequest).where(
            WalkInRequest.space_id == space_id,
            WalkInRequest.status == WalkInStatus.PENDING,
        )
    )).scalar_one()

    return StatsResponse(
        space_id=space_id, inside=inside, exited=exited,
        overstayed=overstayed, pending_walkins=pending_walkins, total_entries=total,
    )


async def get_occupancy(db: AsyncSession, space_id: UUID) -> OccupancyResponse:
    """Current inside vs exited count."""
    rows = (await db.execute(
        select(EntrySession.status, func.count().label("n"))
        .where(EntrySession.space_id == space_id)
        .group_by(EntrySession.status)
    )).all()

    counts = {r.status: r.n for r in rows}
    inside = counts.get(EntryStatus.INSIDE, 0) + counts.get(EntryStatus.OVERSTAYED, 0)
    exited = counts.get(EntryStatus.EXITED, 0) + counts.get(EntryStatus.ASSUMED_EXITED, 0)

    return OccupancyResponse(space_id=space_id, inside=inside, exited=exited, total_scanned=inside + exited)


async def get_entries(db: AsyncSession, space_id: UUID, limit: int = 50) -> EntriesResponse:
    """Recent entry sessions for a space, newest first."""
    rows = (await db.execute(
        select(EntrySession)
        .where(EntrySession.space_id == space_id)
        .order_by(EntrySession.entry_time.desc())
        .limit(limit)
    )).scalars().all()

    total = (await db.execute(
        select(func.count()).select_from(EntrySession).where(EntrySession.space_id == space_id)
    )).scalar_one()

    return EntriesResponse(
        space_id=space_id, total=total,
        entries=[EntryItem(
            session_id=s.id, visitor_name=s.visitor_name, gate_id=s.gate_id,
            entry_time=s.entry_time, exit_time=s.exit_time,
            allowed_until=s.allowed_until, status=s.status,
        ) for s in rows],
    )


async def get_walkins(db: AsyncSession, space_id: UUID) -> WalkInsResponse:
    """All walk-in requests for a space, newest first."""
    rows = (await db.execute(
        select(WalkInRequest)
        .where(WalkInRequest.space_id == space_id)
        .order_by(WalkInRequest.created_at.desc())
    )).scalars().all()

    return WalkInsResponse(
        space_id=space_id, total=len(rows),
        requests=[WalkInItem(
            id=r.id, visitor_name=r.visitor_name,
            status=r.status, created_at=r.created_at,
        ) for r in rows],
    )


async def get_overstays(db: AsyncSession, space_id: UUID) -> OverstaysResponse:
    """Sessions currently marked OVERSTAYED for a space."""
    rows = (await db.execute(
        select(EntrySession)
        .where(EntrySession.space_id == space_id, EntrySession.status == EntryStatus.OVERSTAYED)
        .order_by(EntrySession.allowed_until.asc())
    )).scalars().all()

    return OverstaysResponse(
        space_id=space_id, total=len(rows),
        sessions=[OverstayItem(
            session_id=s.id, visitor_name=s.visitor_name,
            entry_time=s.entry_time, allowed_until=s.allowed_until,
        ) for s in rows],
    )


async def get_analytics(db: AsyncSession, space_id: UUID) -> AnalyticsResponse:
    """Aggregate charts for the organizer Analytics page (last 24h / 7d / 30d windows)."""
    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)
    since_7d = now - timedelta(days=7)
    since_30d = now - timedelta(days=30)

    et_rows = (await db.execute(
        select(EntrySession.entry_time).where(
            EntrySession.space_id == space_id,
            EntrySession.entry_time >= since_24h,
        )
    )).scalars().all()
    hour_counts = [0] * 24
    for et in et_rows:
        if et is None:
            continue
        e = et if et.tzinfo else et.replace(tzinfo=timezone.utc)
        hour_counts[e.hour] += 1
    attendance_by_hour = [
        AnalyticsHourRow(hour=f"{h:02d}:00", entries=hour_counts[h]) for h in range(24)
    ]
    peak_h = max(range(24), key=lambda h: hour_counts[h])
    total_h = sum(hour_counts)
    if not total_h:
        peak_hour_label = "—"
    else:
        utc_slot = now.replace(hour=peak_h, minute=0, second=0, microsecond=0)
        if utc_slot > now:
            utc_slot -= timedelta(days=1)
        ist = ZoneInfo("Asia/Kolkata")
        peak_hour_label = utc_slot.astimezone(ist).strftime("%d %b %Y, %I:%M %p").replace(" 0", " ") + " IST"

    # One SQLAlchemy expression object for SELECT + GROUP BY — Postgres rejects duplicate
    # coalesce(trim(...)) trees that don't resolve to the same grouping key.
    reason_bucket = func.coalesce(
        func.nullif(func.trim(WalkInRequest.reason), ""),
        "Other",
    )
    reason_rows = (await db.execute(
        select(reason_bucket.label("reason_label"), func.count().label("c"))
        .where(
            WalkInRequest.space_id == space_id,
            WalkInRequest.created_at >= since_30d,
        )
        .group_by(reason_bucket)
    )).all()
    walkin_by_reason = [
        AnalyticsReasonRow(name=str(label), count=int(c)) for label, c in reason_rows
    ]

    day0 = (now.date() - timedelta(days=6))
    days = [day0 + timedelta(days=i) for i in range(7)]
    agg: dict = {d: {"approved": 0, "rejected": 0} for d in days}
    processed = (await db.execute(
        select(WalkInRequest.status, WalkInRequest.updated_at).where(
            WalkInRequest.space_id == space_id,
            WalkInRequest.status.in_([WalkInStatus.APPROVED, WalkInStatus.REJECTED]),
            WalkInRequest.updated_at >= since_7d,
        )
    )).all()
    for st, ut in processed:
        if ut is None:
            continue
        u = ut if ut.tzinfo else ut.replace(tzinfo=timezone.utc)
        d = u.date()
        if d not in agg:
            continue
        if st == WalkInStatus.APPROVED:
            agg[d]["approved"] += 1
        else:
            agg[d]["rejected"] += 1
    weekly_approvals = [
        AnalyticsWeekRow(
            name=d.strftime("%a"),
            approved=agg[d]["approved"],
            rejected=agg[d]["rejected"],
        )
        for d in days
    ]

    gate_tot: dict[str, int] = defaultdict(int)
    gate_walk: dict[str, int] = defaultdict(int)
    g_rows = (await db.execute(
        select(EntrySession.gate_id, Invite.invite_type, func.count().label("c"))
        .join(Invite, Invite.id == EntrySession.invite_id)
        .where(EntrySession.space_id == space_id, EntrySession.entry_time >= since_7d)
        .group_by(EntrySession.gate_id, Invite.invite_type)
    )).all()
    for gate_id, itype, c in g_rows:
        gid = gate_id or "Unassigned"
        gate_tot[gid] += int(c)
        itype_val = getattr(itype, "value", itype)
        if itype_val == InviteType.WALKIN.value:
            gate_walk[gid] += int(c)
    all_gates = sorted(set(gate_tot) | set(gate_walk))
    gate_activity = [
        AnalyticsGateRow(gate=g, entries=gate_tot[g], walkins=gate_walk[g]) for g in all_gates
    ]

    approved_n = (await db.execute(
        select(func.count()).select_from(WalkInRequest).where(
            WalkInRequest.space_id == space_id,
            WalkInRequest.status == WalkInStatus.APPROVED,
            WalkInRequest.updated_at >= since_30d,
        )
    )).scalar_one()
    rejected_n = (await db.execute(
        select(func.count()).select_from(WalkInRequest).where(
            WalkInRequest.space_id == space_id,
            WalkInRequest.status == WalkInStatus.REJECTED,
            WalkInRequest.updated_at >= since_30d,
        )
    )).scalar_one()
    dec = approved_n + rejected_n
    approval_rate_percent = round(100.0 * approved_n / dec, 1) if dec else None

    security_alerts_7d = (await db.execute(
        select(func.count()).select_from(Notification).where(
            Notification.space_id == space_id,
            Notification.type == NotificationType.QR_REJECTED,
            Notification.created_at >= since_7d,
        )
    )).scalar_one()

    entries_24h = (await db.execute(
        select(func.count()).select_from(EntrySession).where(
            EntrySession.space_id == space_id,
            EntrySession.entry_time >= since_24h,
        )
    )).scalar_one()

    return AnalyticsResponse(
        space_id=space_id,
        attendance_by_hour=attendance_by_hour,
        walkin_by_reason=walkin_by_reason,
        weekly_approvals=weekly_approvals,
        gate_activity=gate_activity,
        total_entries_24h=int(entries_24h),
        peak_hour_label=peak_hour_label,
        approval_rate_percent=approval_rate_percent,
        security_alerts_7d=int(security_alerts_7d),
    )

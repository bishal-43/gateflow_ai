"""models/guard_space.py — Guard ↔ space assignment (MVP scope control)"""
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from database import Base


class GuardSpaceAssignment(Base):
    """
    A guard may only operate (scan / walk-in) on spaces they are assigned to.
    Organizers/residents add assignments; ADMIN may add any.
    """

    __tablename__ = "guard_space_assignments"
    __table_args__ = (UniqueConstraint("space_id", "guard_user_id", name="uq_guard_space_assignment"),)

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    space_id        = Column(UUID(as_uuid=True), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True)
    guard_user_id   = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    assigned_by_id  = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

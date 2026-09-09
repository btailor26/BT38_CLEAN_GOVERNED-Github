"""Persisted carrier/provider tracking history for the canonical FBMShipment.

This is an event ledger only. It does not create another shipment authority,
perform provider reads, poll, schedule work, or write to marketplaces.
"""
from __future__ import annotations

from datetime import datetime

from extensions import db


class FBMShipmentTrackingEvent(db.Model):
    """One provider/carrier tracking event attached to an existing FBM shipment."""

    __tablename__ = "fbm_shipment_tracking_events"

    id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(
        db.Integer,
        db.ForeignKey("fbm_shipments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider = db.Column(db.String(50), nullable=False, default="packlink", index=True)
    event_key = db.Column(db.String(180), nullable=False)
    event_time = db.Column(db.DateTime, nullable=True, index=True)
    status = db.Column(db.String(120), nullable=True)
    description = db.Column(db.Text, nullable=True)
    detail = db.Column(db.Text, nullable=True)
    estimated_delivery_at = db.Column(db.DateTime, nullable=True)
    package_count = db.Column(db.Integer, nullable=True)
    package_data = db.Column(db.JSON, nullable=True)
    raw_event = db.Column(db.JSON, nullable=False, default=dict)
    observed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("shipment_id", "event_key", name="uq_fbm_tracking_event_shipment_key"),
        db.Index("idx_fbm_tracking_event_shipment_time", "shipment_id", "event_time"),
    )

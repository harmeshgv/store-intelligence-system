from fastapi import APIRouter
from app.db import get_conn

router = APIRouter()

@router.get("/stores/{store_id}/funnel")
def get_funnel(store_id: str):
    with get_conn() as conn:
        c = conn.cursor()

        # ENTRY
        c.execute("""
        SELECT COUNT(DISTINCT visitor_id)
        FROM events
        WHERE store_id=? AND event_type='ENTRY' AND is_staff=0
        """, (store_id,))
        entry = c.fetchone()[0] or 0

        # ZONE VISIT
        c.execute("""
        SELECT COUNT(DISTINCT visitor_id)
        FROM events
        WHERE store_id=? AND event_type='ZONE_ENTER' AND is_staff=0
        """, (store_id,))
        zone = c.fetchone()[0] or 0

        # BILLING (zone_id = BILLING)
        c.execute("""
        SELECT COUNT(DISTINCT visitor_id)
        FROM events
        WHERE store_id=? AND zone_id='BILLING' AND is_staff=0
        """, (store_id,))
        billing = c.fetchone()[0] or 0

        # PURCHASE (simplified logic)
        # later you will map using POS data
        purchase = billing  # temporary assumption

    # Drop-offs
    drop_entry_zone = entry - zone
    drop_zone_billing = zone - billing
    drop_billing_purchase = billing - purchase

    return {
        "entry": entry,
        "zone_visit": zone,
        "billing": billing,
        "purchase": purchase,
        "drop_off": {
            "entry_to_zone": drop_entry_zone,
            "zone_to_billing": drop_zone_billing,
            "billing_to_purchase": drop_billing_purchase
        }
    }
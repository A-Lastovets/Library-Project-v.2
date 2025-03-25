from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from app.models.reservation import Reservation


def get_latest_reservation_alias():
    subquery = (
        select(
            Reservation.book_id,
            func.max(Reservation.created_at).label("latest_created"),
        )
        .group_by(Reservation.book_id)
        .subquery()
    )
    r_alias = aliased(Reservation)
    return r_alias, subquery

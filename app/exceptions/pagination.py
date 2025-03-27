def paginate_response(total: int, page: int, per_page: int, items: list):
    return {
        "total_reservations": total,
        "total_pages": (total // per_page) + (1 if total % per_page else 0),
        "current_page": page,
        "per_page": per_page,
        "items": items,
    }

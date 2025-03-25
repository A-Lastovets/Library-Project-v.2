def serialize_book_with_reservation(book, reservation):
    return {
        "id": book.id,
        "title": book.title,
        "author": book.author,
        "year": book.year,
        "category": book.category,
        "language": book.language,
        "description": book.description,
        "status": book.status.value,
        "coverImage": book.cover_image,
        "reservation_status": reservation.status.value,
        "reservation_date": reservation.created_at,
        "expires_at": reservation.expires_at,
    }


def serialize_book_with_user_reservation(book, reservation, user):
    return {
        "id": book.id,
        "title": book.title,
        "author": book.author,
        "year": book.year,
        "category": book.category,
        "language": book.language,
        "description": book.description,
        "status": book.status.value,
        "coverImage": book.cover_image,
        "user": {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
        },
        "reservation_status": reservation.status.value,
        "reservation_date": reservation.created_at,
        "expires_at": reservation.expires_at,
    }

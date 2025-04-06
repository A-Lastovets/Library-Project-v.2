from typing import List, Optional

from sqlalchemy import String, literal
from sqlalchemy.sql import Select, and_, any_, or_

from app.models.book import Book


def apply_book_filters(
    query: Select,
    title: Optional[str] = None,
    author: Optional[str] = None,
    category: Optional[List[str]] = None,
    year: Optional[str] = None,
    language: Optional[str] = None,
    status: Optional[str] = None,
    query_text: Optional[str] = None,
) -> Select:
    if title:
        query = query.where(Book.title.ilike(f"%{title}%"))
    if author:
        query = query.where(Book.author.ilike(f"%{author}%"))
    if category:
        conditions = [literal(cat) == any_(Book.category) for cat in category]
        query = query.where(or_(*conditions))
    if year:
        query = query.where(Book.year.cast(String).ilike(f"%{year}%"))
    if language:
        query = query.where(Book.language.ilike(f"%{language}%"))
    if status:
        query = query.where(Book.status.cast(String).ilike(f"%{status}%"))

    if query_text:
        search_terms = query_text.split()

        search_conditions = and_(
            *(
                (
                    Book.year == int(word)
                    if word.isdigit()
                    else or_(
                        Book.title.ilike(f"%{word}%"),
                        Book.author.ilike(f"%{word}%"),
                        literal(word) == any_(Book.category),
                        Book.language.ilike(f"%{word}%"),
                    )
                )
                for word in search_terms
            ),
        )

        query = query.where(search_conditions)

    return query

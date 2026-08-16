from __future__ import annotations

DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 200


def parse_positive_int(value) -> int | None:
    try:
        n = int(value)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def paginate(query, args, default_per_page: int = DEFAULT_PER_PAGE, max_per_page: int = MAX_PER_PAGE):
    page = parse_positive_int(args.get("page")) or 1
    per_page = min(parse_positive_int(args.get("per_page")) or default_per_page, max_per_page)
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return items, total


def paginated_response(items_json: list, total: int):
    from flask import jsonify

    resp = jsonify(items_json)
    resp.headers["X-Total-Count"] = str(total)
    return resp

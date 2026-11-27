from django.db.models import Q
from rest_framework.response import Response

from apps.core.cursors import decode_cursor, encode_cursor


def page_response(request, query, serializer, scope, size=30, timestamp_field="created_at"):
    if request.query_params.get("paged") != "1":
        return Response(
            serializer(query.order_by(f"-{timestamp_field}", "-pk")[:100], many=True).data
        )
    total = query.count()
    salt = f"safety:{scope}:{request.user.pk}"
    try:
        if request.query_params.get("cursor"):
            stamp, object_id = decode_cursor(request.query_params["cursor"], salt)
            query = query.filter(
                Q(**{f"{timestamp_field}__lt": stamp})
                | Q(**{timestamp_field: stamp, "pk__lt": object_id})
            )
    except ValueError:
        return Response({"error": {"code": "cursor_invalid"}}, status=400)
    batch = list(query.order_by(f"-{timestamp_field}", "-pk")[: size + 1])
    items = batch[:size]
    cursor = (
        encode_cursor(getattr(items[-1], timestamp_field), items[-1].pk, salt)
        if len(batch) > size
        else None
    )
    return Response(
        {"items": serializer(items, many=True).data, "next_cursor": cursor, "total_count": total}
    )

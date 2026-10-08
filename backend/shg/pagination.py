from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """50 per page by default; screens that need a whole group at once ask for ?page_size= (max 500)."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500

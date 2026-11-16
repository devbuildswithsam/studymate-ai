"""Repositories: the only code that queries the database. SMA-30 (guide 7.1a).

Every function that looks data up takes user_id, so forgetting the filter is a visible
mistake. They never commit: the endpoint commits once, so a request is one transaction.
"""

from __future__ import annotations

from services.database_service import DatabaseService


class BaseService:
    """
    Classe de base de tous les services.

    Elle fournit simplement un accès partagé au DatabaseService.
    """

    def __init__(self, database: DatabaseService):

        self.db = database

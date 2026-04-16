"""Доменная модель пользователя."""
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .exceptions import InvalidEmailError


@dataclass
class User:
    """Пользователь системы."""
    email: str
    name: str = ""
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not re.match(r"^[A-Za-z0-9._%-]+@[A-Za-z0-9.-]+[.][A-Za-z]+$", self.email):
            raise InvalidEmailError(self.email)

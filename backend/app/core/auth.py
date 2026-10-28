"""Request identity. Stub: always anonymous. Replaced in Epic 1 (AD-12)."""

from dataclasses import dataclass
from typing import Literal

type SubjectKind = Literal["user", "device", "anonymous"]


@dataclass(frozen=True, slots=True)
class Subject:
    kind: SubjectKind
    id: str | None


ANONYMOUS = Subject(kind="anonymous", id=None)


def get_subject() -> Subject:
    return ANONYMOUS

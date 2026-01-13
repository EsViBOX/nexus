from datetime import datetime, timedelta
from typing import Optional
from sqlmodel import Field, SQLModel, create_engine
from enum import Enum


class NodeStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    blocked = "blocked"


class Machine(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nodo: str = Field(index=True, unique=True)
    machine_id: str = Field(index=True, unique=True)
    fingerprint: Optional[str] = None
    status: NodeStatus = Field(default=NodeStatus.pending)  # Minúsculas
    ip: Optional[str] = None
    mac: Optional[str] = None
    vpn: Optional[str] = None
    via: Optional[str] = None
    report_data: Optional[str] = None
    last_log: Optional[str] = None
    fecha: datetime = Field(default_factory=datetime.now)

    @property
    def is_online(self) -> bool:
        return datetime.now() - self.fecha < timedelta(minutes=40)


# Configuración del motor de SQLite
sqlite_file_name = "data/registrator.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url, echo=False)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

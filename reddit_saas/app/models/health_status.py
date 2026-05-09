import enum


class HealthStatus(str, enum.Enum):
    ACTIVE = "active"
    LIMITED = "limited"
    SHADOWBANNED = "shadowbanned"
    SUSPENDED = "suspended"
    UNKNOWN = "unknown"

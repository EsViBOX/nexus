class NexusError(Exception):
    """Base error"""


class InventoryError(NexusError):
    """Error cargando datos"""


class SecurityError(NexusError):
    """Intento de acceso ilegal"""


class RenderingError(NexusError):
    """Error en Jinja2 o datos faltantes"""

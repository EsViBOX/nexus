import ipaddress
from fastapi import Header, HTTPException, Request, status, Depends
from .config import get_settings, Settings


async def verify_nexus_key(
    x_nexus_key: str = Header(None), settings: Settings = Depends(get_settings)
):
    # --- DEBUG TEMPORAL ---
    print(f"DEBUG: Recibido en Header: {repr(x_nexus_key)}")
    print(f"DEBUG: Esperado en Config: {repr(settings.nexus_api_key)}")
    # ----------------------

    allowed_keys = [settings.nexus_api_key]
    if settings.nexus_api_key_legacy:
        allowed_keys.append(settings.nexus_api_key_legacy)

    if x_nexus_key not in allowed_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing Nexus Key",
        )

    return x_nexus_key


async def verify_dashboard_access(
    request: Request, settings: Settings = Depends(get_settings)
):
    """
    Verifica si la IP del cliente está en la lista blanca del Dashboard.
    """
    # 1. Obtener la IP del cliente (considerando posibles proxies)
    client_ip_str = request.client.host if request.client else "0.0.0.0"
    client_ip = ipaddress.ip_address(client_ip_str)

    # 2. Procesar la lista blanca del .env
    allowed_networks = settings.nexus_dashboard_allowed_ips.split(",")

    is_allowed = False
    for net_str in allowed_networks:
        try:
            # Quitamos espacios por si acaso
            net = ipaddress.ip_network(net_str.strip(), strict=False)
            if client_ip in net:
                is_allowed = True
                break
        except ValueError:
            continue  # Si hay un error de formato en el .env, lo saltamos

    if not is_allowed:
        # Si no está en la lista, lanzamos un 403 Forbidden
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied for IP {client_ip_str}",
        )

    return client_ip_str

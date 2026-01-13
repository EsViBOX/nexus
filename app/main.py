from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import PlainTextResponse, FileResponse
import logging
from datetime import datetime
from pathlib import Path
import json

from sqlmodel import Session, select, desc
from .models import Machine, NodeStatus, engine
from .engine import nexus_engine
from .exceptions import NexusError  # Usado en except para Ruff
from .dependencies import verify_nexus_key, verify_dashboard_access

# Configurar motor de plantillas HTML
templates_web = Jinja2Templates(directory="templates/web")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nexus.api")

app = FastAPI(title="Esvibox Nexus API")


def get_session():
    with Session(engine) as session:
        yield session


# --- RUTAS PÚBLICAS ---


@app.get("/")
async def root():
    return {"status": "Nexus is online", "version": "2.2.2"}


@app.get("/status", dependencies=[Depends(verify_dashboard_access)])
async def get_status_page(request: Request, session: Session = Depends(get_session)):
    """
    Dashboard de estado. Ahora solo accesible desde IPs en la lista blanca.
    No requiere clave en la URL, solo estar en la red correcta.
    """
    statement = select(Machine).order_by(desc(Machine.fecha))
    machines = session.exec(statement).all()
    return templates_web.TemplateResponse(
        "status.html", {"request": request, "machines": machines}
    )


@app.get("/bootstrap", response_class=PlainTextResponse)
async def get_bootstrap(request: Request):
    """
    Entrega el script de bootstrap dinámico.
    Fuente de verdad para la red: YAML (group_vars/all).
    """
    # 1. Pedimos al motor las variables globales del inventario
    global_vars = await nexus_engine.get_all_vars()

    # 2. Extraemos los datos de red del YAML
    srv = global_vars.get("registrator_server", "localhost")
    port = global_vars.get("registrator_port", 80)
    server_url = f"http://{srv}:{port}"

    return templates_web.TemplateResponse(
        "bootstrap.sh.j2",
        {"request": request, "server_url": server_url},
        media_type="text/plain",
    )


# --- RUTAS PROTEGIDAS ---


@app.get(
    "/get-task/{hostname}",
    response_class=PlainTextResponse,
    dependencies=[Depends(verify_nexus_key)],
)
async def get_task(
    hostname: str,
    machine_id: str,
    fingerprint: str,
    session: Session = Depends(get_session),
):
    # 1. Identificar la máquina (YAML + DB)
    real_hostname = await nexus_engine.get_hostname_by_machine_id(machine_id)
    statement = select(Machine).where(Machine.machine_id == machine_id)
    db_machine = session.exec(statement).first()

    if not db_machine:
        raise HTTPException(status_code=403, detail="Machine not registered.")

    # 2. Auto-aprobación si el ID aparece en el YAML
    if not real_hostname or db_machine.status != NodeStatus.approved:
        return "# Nexus: Node pending or not in inventory.\nexit 0"

    # 3. Validación de existencia en Inventario
    if real_hostname is None:
        return "# Nexus: Node not in inventory.\nexit 0"

    # 4. Obtener datos del nodo del Inventario
    node_data = await nexus_engine.get_node_data(real_hostname)

    # --- NUEVA LÓGICA DE PURGA (Añadir aquí) ---
    if node_data.get("nexus_purge") is True:
        logger.warning(f"!!! PURGE ORDERED for {real_hostname} !!!")
        # Marcamos en la DB como bloqueado para que no pueda pedir nada más
        db_machine.status = NodeStatus.blocked
        session.add(db_machine)
        session.commit()
        # Entregamos el script de limpieza total en lugar del normal
        return await nexus_engine.assemble_purge_script(real_hostname)
    # --------------------------------------------

    # 5. Si no hay purga, asegurar que está aprobado para tareas normales
    if db_machine.status != NodeStatus.approved:
        # Si estaba blocked o pending pero el admin ya lo puso en YAML (y sin purge)
        db_machine.status = NodeStatus.approved
        db_machine.nodo = real_hostname
        session.add(db_machine)
        session.commit()

    # 6. Validación de Huella y Force Enroll
    force_enroll = node_data.get("nexus_force_enroll", False)
    if db_machine.fingerprint != fingerprint:
        if force_enroll:
            db_machine.fingerprint = fingerprint
            session.add(db_machine)
            session.commit()
        else:
            raise HTTPException(status_code=403, detail="Invalid hardware fingerprint.")

    # 7. Entrega del script de orquestación normal
    try:
        return await nexus_engine.assemble_script(real_hostname)
    except NexusError as e:
        logger.error(f"Nexus task error for {real_hostname}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/record", dependencies=[Depends(verify_nexus_key)])
async def record_node(request: Request, session: Session = Depends(get_session)):
    try:
        data = await request.json()
        m_id = data.get("machine_id")
        f_print = data.get("fingerprint")

        if not m_id or not f_print:
            raise HTTPException(status_code=422, detail="Missing hardware identity")

        full_log = data.pop("log", "")  # Optimización: evitar duplicidad en report_data
        client_ip = request.client.host if request.client else "0.0.0.0"

        statement = select(Machine).where(Machine.machine_id == m_id)
        db_machine = session.exec(statement).first()

        if not db_machine:
            db_machine = Machine(
                nodo=f"supplicant_{m_id[:8]}",
                machine_id=m_id,
                fingerprint=f_print,
                status=NodeStatus.pending,
            )

        db_machine.ip = data.get("ip")
        db_machine.mac = data.get("mac")
        db_machine.report_data = json.dumps(data)
        db_machine.last_log = full_log
        db_machine.via = client_ip
        db_machine.fecha = datetime.now()

        session.add(db_machine)
        session.commit()
        return {"status": "ok", "node_status": db_machine.status}
    except Exception as e:
        logger.exception(f"Record error: {e}")
        raise HTTPException(status_code=500, detail="Failed to record")


@app.post("/inventory/refresh", dependencies=[Depends(verify_nexus_key)])
async def refresh_inventory():
    try:
        await nexus_engine.refresh_cache(force=True)
        return {"status": "inventory refreshed"}
    except Exception as e:
        logger.error(f"Manual refresh failed: {e}")
        raise HTTPException(status_code=500, detail="Refresh failed")


@app.get("/scripts/{filename}", dependencies=[Depends(verify_nexus_key)])
async def get_static_script(filename: str):
    script_base = Path("files/scripts").resolve()
    target_path = (script_base / filename).resolve()
    if not target_path.is_relative_to(script_base) or not target_path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(target_path)


@app.get("/skels/{filename}", dependencies=[Depends(verify_nexus_key)])
async def get_skel_file(filename: str):
    skel_base = Path("files/skels").resolve()
    target_path = (skel_base / filename).resolve()
    if not target_path.is_relative_to(skel_base) or not target_path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(target_path)


@app.get("/certs/{domain}/{filename}", dependencies=[Depends(verify_nexus_key)])
async def get_certificate_file(domain: str, filename: str):
    cert_base = Path("files/certs").resolve()
    target_path = (cert_base / domain / filename).resolve()
    if not target_path.is_relative_to(cert_base) or not target_path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(target_path)

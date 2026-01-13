import asyncio
import base64
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from jinja2 import Environment, FileSystemLoader, StrictUndefined, exceptions

from .config import get_settings
from .exceptions import InventoryError, RenderingError, SecurityError

logger = logging.getLogger("nexus.engine")


class NexusEngine:
    def __init__(self, template_dir: str = "templates"):
        self.template_base = Path(template_dir).resolve(strict=True)
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(self.template_base)),
            undefined=StrictUndefined,
            auto_reload=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._inventory_cache: Dict[str, Any] = {}
        self._last_update: Optional[datetime] = None
        self._lock = asyncio.Lock()
        self.TTL = timedelta(minutes=5)
        self.inventory_dir = Path("inventory").resolve()
        self._last_mtime = 0.0  # Guardaremos la última fecha de modificación conocida

    def _get_max_mtime(self) -> float:
        """Calcula la fecha de modificación más reciente de todo el inventario."""
        max_mtime = 0.0
        # Recorremos la carpeta inventory y sus subcarpetas (group_vars, etc)
        for root, _, files in os.walk(self.inventory_dir):
            for f in files:
                if f.endswith((".yml", ".yaml")):
                    mtime = os.path.getmtime(os.path.join(root, f))
                    if mtime > max_mtime:
                        max_mtime = mtime
        return max_mtime

    async def _fetch_inventory(self) -> Dict[str, Any]:
        cmd = [
            "ansible-inventory",
            "-i",
            "inventory/hosts.yml",
            "--list",
            "--vault-password-file",
            ".vault_pass",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.error(f"Ansible failed: {stderr.decode()}")
            raise InventoryError("Failed to fetch inventory from Ansible")

        return json.loads(stdout.decode())

    def _get_file_hash(self, filename: str) -> str:
        """Calcula el MD5 de un script físico en el servidor."""
        path = Path("files/scripts") / filename
        if not path.exists():
            return ""
        return hashlib.md5(path.read_bytes()).hexdigest()

    def _get_skel_hash(self, filename: str) -> str:
        path = Path("files/skels") / filename
        if not path.exists():
            return ""
        return hashlib.md5(path.read_bytes()).hexdigest()

    def _get_cert_hash(self, domain: str, filename: str) -> str:
        path = Path("files/certs") / domain / filename
        return hashlib.md5(path.read_bytes()).hexdigest() if path.exists() else ""

    async def refresh_cache(self, force: bool = False):
        async with self._lock:
            now = datetime.now()
            current_max_mtime = self._get_max_mtime()

            # Decidimos si refrescar basándonos en:
            # 1. Flag forzado
            # 2. Caché vacía
            # 3. Han pasado 5 minutos (TTL)
            # 4. NUEVO: Los archivos físicos son más nuevos que nuestra última carga
            should_reload = (
                force
                or not self._inventory_cache
                or self._last_update is None
                or (now - self._last_update > self.TTL)
                or (current_max_mtime > self._last_mtime)
            )

            if should_reload:
                logger.info("Inventory change or TTL detected. Refreshing cache...")
                data = await self._fetch_inventory()
                self._inventory_cache = data.get("_meta", {}).get("hostvars", {})
                # NUEVO: Guardamos las variables globales (grupo 'all') para el bootstrap
                self._all_vars = data.get("all", {}).get("vars", {})
                self._last_update = now
                self._last_mtime = (
                    current_max_mtime  # Guardamos la nueva marca de tiempo
                )
                logger.info(f"Inventory cache updated. New marker: {self._last_mtime}")

    # NUEVO: Método para que main.py obtenga la red del YAML
    async def get_all_vars(self) -> Dict[str, Any]:
        """Retorna las variables globales del inventario (grupo all)."""
        if not self._inventory_cache:
            await self.refresh_cache()
        return getattr(self, "_all_vars", {})

    async def get_node_data(self, hostname: str) -> Dict[str, Any]:
        """Acceso público a los datos de un nodo en el inventario."""
        if not self._inventory_cache:
            await self.refresh_cache()

        node = self._inventory_cache.get(hostname)
        if not node:
            raise InventoryError(f"Node {hostname} not found in inventory")

        return node

    async def get_hostname_by_machine_id(self, machine_id: str) -> Optional[str]:
        """Busca en el inventario qué hostname tiene asignado un machine_id (nexus_id)."""
        if not self._inventory_cache:
            await self.refresh_cache()

        # Iteramos por todos los hosts del inventario buscando la variable 'nexus_id'
        for hostname, host_vars in self._inventory_cache.items():
            if host_vars.get("nexus_id") == machine_id:
                return hostname
        return None

    def _minify_script(self, content: str) -> str:
        """Limpia el script de comentarios y líneas vacías para aligerarlo."""
        lines = content.splitlines()
        clean_lines = []

        for i, line in enumerate(lines):
            # 1. Preservar la primera línea (Shebang) siempre
            if i == 0 and line.startswith("#!"):
                clean_lines.append(line)
                continue

            # 2. Eliminar espacios en blanco a los lados
            stripped = line.strip()

            # 3. Saltar si la línea está vacía o es un comentario puro
            # Explicación regex: Empieza por # y no es #!
            if not stripped or (
                stripped.startswith("#") and not stripped.startswith("#!")
            ):
                continue

            clean_lines.append(stripped)

        return "\n".join(clean_lines)

    def _safe_get_template(self, task_path: str):
        """Validación de seguridad contra Path Traversal y carga de plantilla."""
        try:
            target = self.template_base / f"{task_path}.sh.j2"
            resolved_path = target.resolve(strict=True)

            if not resolved_path.is_relative_to(self.template_base):
                raise SecurityError(f"Path Injection Attempt: {task_path}")

            rel_path = resolved_path.relative_to(self.template_base)
            return self.jinja_env.get_template(str(rel_path))
        except (FileNotFoundError, RuntimeError):
            raise RenderingError(f"Task template missing or insecure: {task_path}")

    async def assemble_script(self, hostname: str) -> str:
        """Ensambla el script de configuración completo de forma atómica y segura."""
        if not self._inventory_cache:
            await self.refresh_cache()

        # 1. Obtener datos del nodo desde la caché de inventario
        node_data = self._inventory_cache.get(hostname)
        if not node_data:
            raise InventoryError(f"Node {hostname} not found in inventory")
        node_data["hostname"] = hostname

        # 2. Gestión de Seguridad (Excepción por convenio: API KEY desde .env)
        settings = get_settings()
        raw_key = settings.nexus_api_key
        if not raw_key:
            raise RenderingError("NEXUS_API_KEY not found in server .env configuration")

        # 2. La codificamos en Base64 y le damos la vuelta (reverse)
        # [::-1] es el truco de Python para invertir un string
        # Inyectamos la clave ofuscada en lugar de la real
        node_data["nexus_api_key_scrambled"] = base64.b64encode(
            raw_key.encode()
        ).decode()[::-1]

        # 3. Procesar Manifiesto de SCRIPTS (Tarea 06)
        raw_scripts = node_data.get("nexus_scripts", [])
        processed_manifest = []
        for s in raw_scripts:
            # Si es un string 'script.sh', lo convertimos a objeto interno
            s_obj = {"name": s} if isinstance(s, str) else s
            name = s_obj.get("name")
            if not name:
                continue  # Saltar si el formato es inválido
            item = {
                "name": name,
                "remove": s_obj.get("remove", False),
                "override": s_obj.get("override", False),
                "hash": "",
            }
            # Solo calculamos hash si existe el archivo y no vamos a borrarlo
            if not item["remove"]:
                file_hash = self._get_file_hash(name)
                if file_hash:
                    item["hash"] = file_hash
                elif not item["override"]:
                    # Si no hay hash y no es override, algo va mal con el archivo físico
                    logger.warning(
                        f"Script {name} defined but not found in files/scripts/"
                    )
                    continue
            processed_manifest.append(item)
        node_data["script_manifest"] = processed_manifest

        # 4. Procesar Manifiesto de SKELS (Tarea 07 - Dot-Prefix Mapping)
        raw_skels = node_data.get("nexus_skels", [])
        processed_skels = []
        for s in raw_skels:
            s_obj = {"name": s} if isinstance(s, str) else s
            name = s_obj.get("name")
            if not name:
                continue
            # Lógica de mapeo del nombre de destino (Dot-Prefix)
            dest_name = name
            if name.startswith("dot."):
                dest_name = "." + name[4:]  # Quita 'dot.' y añade '.'
            item = {
                "src_name": name,  # Nombre en el servidor (dot.bashrc)
                "dest_name": dest_name,  # Nombre en el cliente (.bashrc)
                "remove": s_obj.get("remove", False),
                "override": s_obj.get("override", False),
                "hash": "",
            }
            if not item["remove"]:
                item["hash"] = self._get_skel_hash(name)
            processed_skels.append(item)
        node_data["skel_manifest"] = processed_skels

        # 5. Procesar Manifiesto de SSL (Tarea 08 - Multi-Cert)
        raw_certs = node_data.get("nexus_ssl", [])
        cert_manifest = []
        for c in raw_certs:
            c_obj = {"domain": c} if isinstance(c, str) else c
            domain = c_obj.get("domain")
            if not domain:
                continue
            entry = {
                "domain": domain,
                "dest_path": c_obj.get("dest_path"),
                "remove": c_obj.get("remove", False),
                "override": c_obj.get("override", False),
                "generate_p12": c_obj.get("generate_p12", False),
                "generate_combined": c_obj.get("generate_combined", False),
                "restart_services": c_obj.get("restart_services", []),
                "files": [],
            }
            if not entry["remove"]:
                # Solo buscamos los archivos si no vamos a borrar
                for f in ["cert.pem", "privkey.pem", "chain.pem", "fullchain.pem"]:
                    f_hash = self._get_cert_hash(domain, f)
                    if f_hash:
                        entry["files"].append({"name": f, "hash": f_hash})
            cert_manifest.append(entry)
        node_data["cert_manifest"] = cert_manifest

        # 6. Fase de Carga Atómica del Workflow
        workflow = node_data.get("nexus_workflow", [])
        if not workflow:
            raise RenderingError(f"No workflow defined for {hostname}")
        try:
            # Validamos y cargamos todos los templates antes de renderizar nada
            templates_to_render = [self._safe_get_template(t) for t in workflow]
        except (SecurityError, RenderingError) as e:
            logger.error(f"Pipeline assembly abort for {hostname}: {e}")
            raise

        # 7. Fase de Renderizado y Minificación Final
        try:
            # Renderizamos la unión de todos los fragmentos
            full_script = "\n".join(
                [t.render(node=node_data) for t in templates_to_render]
            )
            # Limpiamos comentarios y espacios para el cliente
            return self._minify_script(full_script)
        except exceptions.UndefinedError as e:
            logger.error(f"JINJA2 VARIABLE ERROR for {hostname}: {e}")
            raise RenderingError(f"Missing variable in Vault or Inventory: {e}")

    # --- Método de Purga actualizado ---
    async def assemble_purge_script(self, hostname: str) -> str:
        """Genera un script de limpieza total usando el ayudante seguro."""
        node_data = await self.get_node_data(hostname)
        node_data["hostname"] = hostname

        # Inyectamos la clave para el reporte final de purga
        settings = get_settings()
        node_data["nexus_api_key_scrambled"] = base64.b64encode(
            settings.nexus_api_key.encode()
        ).decode()[::-1]

        templates = [
            self._safe_get_template("base/header"),
            self._safe_get_template("base/purge"),
        ]

        full_script = "\n".join([t.render(node=node_data) for t in templates])
        return self._minify_script(full_script)


nexus_engine = NexusEngine()

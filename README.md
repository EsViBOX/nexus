# ***Nexus***
### Unified Linux Provisioning, Security & Orchestration Engine

**NEXUS** es un ecosistema de infraestructura híbrida que trasciende el plataformado tradicional. Ha sido diseñado para gestionar el ciclo de vida completo (nacimiento, configuración, mantenimiento y desmantelamiento) de flotas Linux heterogéneas, garantizando la Idempotencia, la Seguridad de Confianza Cero y la Observabilidad Total.

## 1. Filosofía de Diseño y Evolución
El proyecto nace de una refactorización profunda de un sistema heredado basado en scripts de Shell monolíticos y bases de datos MySQL gestionadas por PHP. La transición a Nexus se basó en cuatro pilares de ingeniería:

* **Desacoplamiento Lógico**: Separar la Lógica de Ejecución (Bash/Ash) de la Fuente de Verdad (YAML/Ansible) y del Estado de Persistencia (SQLite).

* **Arquitectura Híbrida (Pull-Push Ready)**: Un agente ligero en el cliente (Pull) que descarga "instrucciones masticadas" por el Manager, preparando el camino para el control directo (Push) vía Ansible.

* **Inmutabilidad de Identidad**: La máquina no es su Hostname (volátil), sino su Hardware (inmutable).

* **Minimización de Superficie de Ataque**: Eliminación de secretos en texto plano y protección de la API mediante tokens de flota y ofuscación en tránsito.

## 2. Stack Tecnológico: Decisiones de Ingeniería

### A. Backend: Python 3.11+ & FastAPI
* Migrar de PHP a Python/FastAPI.

  La naturaleza asíncrona de FastAPI permite manejar cientos de peticiones de telemetría concurrentes sin bloquear el hilo principal. Python permite una integración nativa con las librerías internas de Ansible para procesar inventarios y Vaults sin invocar procesos externos pesados.

### B. Gestión de Entorno: Astral uv
* Sustituir pip y venv por uv.

  uv garantiza instalaciones muy rápidas y una resolución de dependencias determinista (vía uv.lock), vital para que el Manager sea replicable en cualquier servidor Debian 13 sin "drift" de versiones.

### C. Motor de Datos: Ansible Core (Inventory & Vault)
* Usar Ansible solo en el servidor (Manager-side).

  Permite gestionar la flota con la potencia de Ansible (grupos, herencia de variables, secretos cifrados) sin obligar al cliente a tener Python instalado (crítico para Synology, Alpine o routers).

### D. Persistencia: SQLModel + SQLite
* Usar SQLite para el historial de nodos.

  Elimina la sobrecarga de mantener un servidor MariaDB/PostgreSQL. Al usar SQLModel, Nexus se beneficia de la validación de tipos de Pydantic y la potencia de SQLAlchemy en una base de datos de un solo archivo portable.

## 3. Modelo de Seguridad: Defensa en Profundidad
Nexus implementa capas de seguridad solapadas para proteger la infraestructura:

### Firma de Identidad (Hardware Fingerprinting)
Nexus no confía en el nombre que una máquina dice tener. En el primer contacto, el cliente genera una Huella Digital combinando:
* Machine-ID: El identificador único del sistema operativo.
* MAC Address Inventory: Un volcado ordenado de todas las interfaces físicas.
Esta huella se hashea (SHA-256) y se convierte en el Token Técnico de la máquina. Si una VM es clonada, su MAC cambiará, la huella será inválida y Nexus bloqueará el acceso.

### Ofuscación en Tránsito (Scrambling)
Para entornos donde no hay HTTPS disponible, Nexus utiliza un algoritmo de Reversed-Base64 Scrambling. La clave de la API nunca viaja como API_KEY=secret. El servidor la codifica y la invierte; el cliente la recompone solo en la memoria RAM del proceso Bash.

### Admisión Controlada (Admission Control)
El flujo de alta sigue el patrón Supplicant -> Approved:
* Un nodo nuevo se registra como supplicant (Estado: PENDING).
La API solo le entrega una tarea de telemetría, bloqueando el acceso a llaves RSA o Passwords.
* Solo cuando el administrador vincula el ID en el hosts.yml, la API otorga el estado APPROVED y libera la configuración real.


## 4. El Motor de Configuración (Nexus Engine)
El corazón del sistema es el ensamblador de scripts asíncrono localizado en app/engine.py.

### Atomicidad de Entrega
El motor utiliza un patrón de Ensamblado en Dos Fases:
* Fase de Validación: Comprueba la existencia física de cada fragmento del workflow y valida que las rutas sean seguras mediante Path.resolve(strict=True), previniendo ataques de *Path Traversal*.

* Fase de Renderizado: Inyecta las variables del Vault. Gracias a StrictUndefined, si falta una sola coma o una variable de password no está en el Vault, el proceso aborta y no entrega un script incompleto que podría dejar la máquina a medias.

### Sincronización Inteligente (Hash-Based Sync)
Nexus implementa la lógica de Idempotencia Real para archivos (Scripts, Skels, SSL):
* El servidor envía el MD5 del archivo deseado.
* El cliente compara el hash local.
* Solo si hay discrepancia, se inicia la descarga.

Esto permite gestionar miles de archivos en toda la flota con un impacto de red mínimo.

## 5. Anatomía del Sistema de Tareas
El despliegue se divide en fragmentos modulares (.sh.j2) ensamblados dinámicamente según el workflow.yml de cada grupo:
* **00-persistence**: Instala el Self-Healing Agent. Genera un Timer de Systemd y asegura la llave de identidad en /etc/nexus/key con permisos 400.
* **02-sshd**: Endurecimiento del servicio SSH. Gestiona puertos y métodos de autenticación de forma atómica.
* **03-password**: Sincroniza las sombras de contraseñas (/etc/shadow) usando hashes SHA-512 inyectados desde el Vault.
* **04/05-ssh-identity**: Despliegue de llaves privadas RSA y gestión del archivo authorized_keys.
* **06/07-sync**: Sincronización de herramientas de utilidad y dotfiles de usuario (dot.bashrc -> .bashrc). Soporta los flags override: true (forzar) y remove: true (limpiar).
* **08-ssl**: Distribución de certificados multi-dominio. Genera contenedores PKCS12 y PEM combinados. Incluye una lógica de reinicio de servicios única: si 5 certificados cambian y todos usan Nginx, Nginx se reinicia solo una vez al final.
* **99-clean**: Fase de borrado de rastros temporales.

## 6. Dashboard y Telemetría
La interfaz /status no es solo una tabla; es una herramienta de diagnóstico:
* Detección de Origen: Muestra la IP reportada por la máquina frente a la IP de conexión (útil para detectar problemas de NAT o VPN).
* Control de Latencia: El estado Online/Offline se calcula dinámicamente basándose en la última ventana de 40 minutos del agente.
* Terminal Modal: Permite inspeccionar el log de salida de Bash de cualquier nodo con formato de terminal, facilitando el soporte remoto sin necesidad de acceso SSH directo.

## 7. Guía de Operaciones Rápidas

### Para añadir una máquina
* Ejecutar el bootstrap dinámico:

      curl -s https://example.com:8000/bootstrap | sudo bash -s -- supplicant "TU_LLAVE_API"

### Para rotar la clave de la flota
* Generar nueva clave en .env bajo *NEXUS_API_KEY*.
* Mover la antigua a *NEXUS_API_KEY_LEGACY*.

  Nexus permitirá que las máquinas entren con la vieja, pero les entregará la nueva en el script. La Tarea 00 actualizará /etc/nexus/key automáticamente.

### Para purgar un nodo (Decommissioning)
* En el inventario del host, añadir:

      nexus_purge: true.

* Refrescar API.

  En la próxima llamada, el nodo ejecutará un script de "auto-borrado" de sus servicios y secretos.

## 📈 8. Futuro: Fase PUSH (Nexus v3)
Nexus Engine deja los cimientos listos para la Parte 2:
* El inventario ya tiene las IPs vivas de cada nodo.
* Las llaves SSH ya están desplegadas.
* El servidor ya conoce el machine_id.

El siguiente paso será un módulo en la API que invoque ansible-playbook directamente contra los nodos registrados, permitiendo cambios instantáneos sin esperar al ciclo de X minutos.

***NEXUS*** - *Donde la simplicidad del Shell se encuentra con la potencia de la orquestación moderna.*

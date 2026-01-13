import os
from dotenv import load_dotenv

load_dotenv()
key = os.getenv("NEXUS_API_KEY")

if key:
    print(f"ÉXITO: Se ha leído la clave. Empieza por: {key[:3]}...")
else:
    print("ERROR: No se ha podido leer NEXUS_API_KEY del archivo .env")

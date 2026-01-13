# init_db.py
from app.models import create_db_and_tables

if __name__ == "__main__":
    print("Inicializando base de datos SQLite...")
    create_db_and_tables()
    print("¡Base de datos Nexus lista en data/registrator.db!")
Profile
"""Descarga los datos crudos desde Google Drive a la carpeta Datos/.

Autentica con OAuth2 via navegador la primera vez y guarda el token
para reutilizarlo. Si la carpeta Datos/ ya existe y tiene los archivos
necesarios, no descarga nada.

Uso:
    python descargar_datos.py                    # descarga si falta datos
    python descargar_datos.py --forzar           # descarga siempre
    python descargar_datos.py --verificar        # solo verifica sin descargar
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

ROOT = Path(__file__).resolve().parent
DATOS = ROOT / "Datos"
CREDENTIALS_JSON = ROOT / "credentials.json"
TOKEN_JSON = ROOT / "token.json"

# ID de la carpeta en Google Drive
FOLDER_ID = "1UtAYDRRlAANC_62faBzLNoh_3GEyeQlM"

# Archivos requeridos con sus nombres en Google Drive
ARCHIVOS_REQUERIDOS = {
    "ventas_anonimizado-001.csv": "ventas_anonimizado-001.csv",
    "clientes_anonimizado.csv": "clientes_anonimizado.csv",
    "catalogo_filtrado.csv": "catalogo_filtrado.csv",
    "sucursales_anonimizado.csv": "sucursales_anonimizado.csv",
}

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def autenticar() -> Credentials:
    """Autentica con OAuth2. Abre navegador la primera vez."""
    creds = None

    if TOKEN_JSON.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_JSON), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refrescando token de autenticacion...")
            creds.refresh(Request())
        else:
            if not CREDENTIALS_JSON.exists():
                print(
                    f"ERROR: No se encontro {CREDENTIALS_JSON}\n"
                    "Descarga las credenciales OAuth 2.0 desde Google Cloud Console:\n"
                    "  1. Ve a https://console.cloud.google.com\n"
                    "  2. Crea un proyecto (o usa uno existente)\n"
                    "  3. Habilita la Google Drive API\n"
                    "  4. Ve a APIs & Services > Credentials\n"
                    "  5. Crea OAuth 2.0 Client ID (Desktop App)\n"
                    "  6. Descarga el JSON y guardalo como credentials.json aqui"
                )
                sys.exit(1)

            print("Abrindo navegador para autenticacion con Google...")
            print("(Si no se abre automaticamente, copia la URL de la consola)")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_JSON), SCOPES
            )
            creds = flow.run_local_server(
                port=0,
                prompt="consent",
                access_type="offline",
            )
            print("Autenticacion exitosa.")

        TOKEN_JSON.write_text(creds.to_json(), encoding="utf-8")
        print(f"Token guardado en {TOKEN_JSON}")

    return creds


def listar_archivos(service, folder_id: str) -> list[dict]:
    """Lista todos los archivos en una carpeta de Drive."""
    archivos = []
    page_token = None

    while True:
        resultado = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="nextPageToken, files(id, name, size)",
                pageToken=page_token,
                pageSize=100,
            )
            .execute()
        )
        archivos.extend(resultado.get("files", []))
        page_token = resultado.get("nextPageToken")
        if not page_token:
            break

    return archivos


def descargar_archivo(service, file_id: str, destino: Path, nombre: str) -> None:
    """Descarga un archivo de Google Drive."""
    print(f"  Descargando {nombre}...", end="", flush=True)

    request = service.files().get_media(fileId=file_id)
    from googleapiclient.http import MediaIoBaseDownload
    import io

    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)

    done = False
    while not done:
        status, done = downloader.next_chunk()
        if status:
            print(f" {int(status.progress() * 100)}%", end="", flush=True)

    fh.seek(0)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "wb") as f:
        f.write(fh.read())

    tam_mb = destino.stat().st_size / (1024 * 1024)
    print(f" ({tam_mb:.1f} MB)")


def verificar_datos() -> bool:
    """Verifica que la carpeta Datos/ tenga todos los archivos requeridos."""
    if not DATOS.exists():
        return False

    for nombre in ARCHIVOS_REQUERIDOS:
        if not (DATOS / nombre).exists():
            return False

    return True


def mostrar_estado():
    """Muestra el estado actual de la carpeta Datos/."""
    if not DATOS.exists():
        print("Carpeta Datos/ no existe.")
        return

    print(f"Carpeta: {DATOS}")
    for nombre in ARCHIVOS_REQUERIDOS:
        archivo = DATOS / nombre
        if archivo.exists():
            tam = archivo.stat().st_size
            if tam > 1e9:
                print(f"  [OK] {nombre:40s} {tam / 1e9:.2f} GB")
            elif tam > 1e6:
                print(f"  [OK] {nombre:40s} {tam / 1e6:.1f} MB")
            else:
                print(f"  [OK] {nombre:40s} {tam / 1e3:.0f} KB")
        else:
            print(f"  [FALTA] {nombre}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--forzar",
        action="store_true",
        help="Descarga aunque los archivos ya existan.",
    )
    parser.add_argument(
        "--verificar",
        action="store_true",
        help="Solo muestra el estado de los archivos sin descargar.",
    )
    args = parser.parse_args()

    if args.verificar:
        mostrar_estado()
        if verificar_datos():
            print("\nTodos los archivos estan presentes.")
        else:
            print("\nFaltan archivos. Ejecuta sin --verificar para descargar.")
        return

    if verificar_datos() and not args.forzar:
        print("Los datos ya estan descargados. Usa --forzar para volver a descargar.")
        mostrar_estado()
        return

    print("=== Descarga de datos desde Google Drive ===\n")
    print(f"Destino: {DATOS}\n")

    creds = autenticar()
    service = build("drive", "v3", credentials=creds)

    print(f"\nListando archivos en la carpeta de Drive...")
    archivos = listar_archivos(service, FOLDER_ID)
    print(f"Encontrados {len(archivos)} archivos.\n")

    if not archivos:
        print("ERROR: La carpeta de Drive esta vacia o no se pudo acceder.")
        print("Verifica que la carpeta este compartida con la cuenta que usaste.")
        sys.exit(1)

    for archivo in archivos:
        nombre = archivo["name"]
        file_id = archivo["id"]
        tam = int(archivo.get("size", 0))

        if tam > 1e9:
            print(f"  {nombre:40s} {tam / 1e9:.2f} GB")
        elif tam > 1e6:
            print(f"  {nombre:40s} {tam / 1e6:.1f} MB")
        else:
            print(f"  {nombre:40s} {tam / 1e3:.0f} KB")

    print()

    for archivo in archivos:
        nombre = archivo["name"]
        file_id = archivo["id"]
        destino = DATOS / nombre
        descargar_archivo(service, file_id, destino, nombre)

    print("\n=== Descarga completada ===\n")
    mostrar_estado()


if __name__ == "__main__":
    main()

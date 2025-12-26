import streamlit as st
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import json
import re
from datetime import datetime
import pandas as pd
import urllib.parse

# --- CONFIGURACIÓN ---
SHEET_ID = "17Cn82TTSyXbipbW3zZ7cvYe6L6aDkX3EPK6xO7MTxzU"
MI_EMAIL_CALENDARIO = "gabrielromero900@gmail.com"
ID_CARPETA_PADRE_DRIVE = "1XS4-h6-VpY_P-C3t_L-X4r8F6O-9-C-y"

st.set_page_config(page_title="CRM-IA: MyCar Centro", page_icon="🚗", layout="wide")

if "messages" not in st.session_state:
    st.session_state.messages = []

# --- CONEXIÓN ---
def conectar():
    SCOPE = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/calendar"]
    try:
        if "gcp_service_account" in st.secrets:
            creds_info = dict(st.secrets["gcp_service_account"])
            if "private_key" in creds_info:
                creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
            creds = Credentials.from_service_account_info(creds_info, scopes=SCOPE)
        else:
            creds = Credentials.from_service_account_file("credenciales.json", scopes=SCOPE)
        
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID)
        cal_service = build('calendar', 'v3', credentials=creds)
        drive_service = build('drive', 'v3', credentials=creds)
        return sheet.worksheet("Stock"), sheet.worksheet("Leeds"), cal_service, drive_service
    except Exception as e:
        st.error(f"Error de conexión: {e}")
        return None, None, None, None

ws_stock, ws_leeds, calendar_service, drive_service = conectar()
if ws_stock is None: st.stop()

# --- IA: GEMINI 3 FLASH PREVIEW ---
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel('models/gemini-3-flash-preview')

# --- FUNCIONES DE GESTIÓN ---
def crear_carpeta_drive(nombre_cliente):
    try:
        meta = {'name': nombre_cliente, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [ID_CARPETA_PADRE_DRIVE]}
        folder = drive_service.files().create(body=meta, fields='id, webViewLink').execute()
        return folder.get('webViewLink')
    except: return "-"

def eliminar_registro(hoja, criterio):
    try:
        celda = hoja.find(str(criterio), in_column=2)
        hoja.delete_rows(celda.row)
        return True
    except: return False

def gestionar_calendario(accion, resumen, fecha=None):
    try:
        if accion == "CREAR":
            event = {'summary': resumen, 'start': {'date': fecha, 'timeZone': 'America/Argentina/Buenos_Aires'}, 'end': {'date': fecha, 'timeZone': 'America/Argentina/Buenos_Aires'}}
            calendar_service.events().insert(calendarId=MI_EMAIL_CALENDARIO, body=event).execute()
        elif accion == "BORRAR":
            events = calendar_service.events().list(calendarId=MI_EMAIL_CALENDARIO, q=resumen).execute()
            for e in events.get('items', []):
                calendar_service.events().delete(calendarId=MI_EMAIL_CALENDARIO, eventId=e['id']).execute()
        return True
    except: return False

def guardar_stock(data):
    hoy = datetime.now().strftime("%d/%m/%Y")
    # Crear carpeta en Drive para el nuevo auto
    link = crear_carpeta_drive(f"{data['Cliente']} - {data['Vehiculo']}")
    ws_stock.append_row([hoy, data['Cliente'], data['Vehiculo'], data.get('Año','-'), data.get('KM','-'), data.get('Color','-'), "-", "-", data.get('Patente','-'), link])

def guardar_leed(data):
    hoy = datetime.now().strftime("%d/%m/%Y")
    ws_leeds.append_row([hoy, data['Cliente'], data.get('Busca','-'), data.get('Telefono','-'), data.get('Nota','-'), data.get('Fecha_Remind','-')])

# --- INTERFAZ ---
st.title("🤖 CRM-IA: MyCar Centro")

col1, col2 = st.columns(2)
with col1: 
    if st.button("📊 Ver Stock"): st.dataframe(pd.DataFrame(ws_stock.get_all_records()))
with col2: 
    if st.button("👥 Ver Leeds"): st.dataframe(pd.DataFrame(ws_leeds.get_all_records()))

archivo = st.file_uploader("📷 Subir PDF/Foto", type=["pdf", "jpg", "png", "jpeg"])

for message in st.session_state.messages:
    with st.chat_message(message["role"]): st.markdown(message["content"])

if prompt := st.chat_input("¿Qué novedades hay?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    with st.chat_message("assistant"):
        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        # Leer datos reales para que la IA responda con precisión
        contexto_stock = ws_stock.get_all_records()
        
        instruccion = f"""
        Hoy es {fecha_hoy}. Eres el gestor de MyCar Centro. Responde CORTO y DIRECTO.
        STOCK REAL: {contexto_stock}
        ACCIONES: GUARDAR_AUTO, ELIMINAR_AUTO, GUARDAR_LEED, ELIMINAR_LEED, BORRAR_EVENTO, WHATSAPP.
        JSON OBLIGATORIO: DATA_START {{"ACCION": "...", "Cliente": "...", "Vehiculo": "...", "Telefono": "...", "Fecha_Remind": "YYYY-MM-DD", "Mensaje": "..."}} DATA_END
        """
        
        try:
            contenidos = [instruccion, prompt]
            if archivo: contenidos.append({"mime_type": archivo.type, "data": archivo.getvalue()})
            
            response = model.generate_content(contenidos)
            res_text = response.text
            respuesta_visible = re.sub(r"DATA_START.*?DATA_END", "", res_text, flags=re.DOTALL).strip()
            st.markdown(respuesta_visible)
            st.session_state.messages.append({"role": "assistant", "content": respuesta_visible})

            matches = re.findall(r"DATA_START\s*(.*?)\s*DATA_END", res_text, re.DOTALL)
            for m in matches:
                data = json.loads(m)
                if data["ACCION"] == "GUARDAR_AUTO": guardar_stock(data)
                elif data["ACCION"] == "ELIMINAR_AUTO": eliminar_registro(ws_stock, data['Cliente'])
                elif data["ACCION"] == "GUARDAR_LEED": 
                    guardar_leed(data)
                    if data.get("Fecha_Remind") and data["Fecha_Remind"] != "-":
                        gestionar_calendario("CREAR", f"Llamar a {data['Cliente']}", data["Fecha_Remind"])
                elif data["ACCION"] == "ELIMINAR_LEED": eliminar_registro(ws_leeds, data['Cliente'])
                elif data["ACCION"] == "BORRAR_EVENTO": gestionar_calendario("BORRAR", f"Llamar a {data['Cliente']}")
                elif data["ACCION"] == "WHATSAPP":
                    link_wa = f"https://wa.me/{data['Telefono']}?text={urllib.parse.quote(data['Mensaje'])}"
                    st.link_button("📲 Enviar WhatsApp", link_wa)
                st.success(f"Operación {data['ACCION']} realizada.")
        
        except Exception as e:
            if "quota" in str(e).lower():
                st.warning("⚠️ Límite de mensajes alcanzado. Espera 60 segundos antes de volver a preguntar.")
            else: st.error(f"Error: {e}")

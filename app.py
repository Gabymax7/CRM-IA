import streamlit as st
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import json
import re
from datetime import datetime, timedelta
import pandas as pd
import urllib.parse

# --- CONFIGURACIÓN ESTÁTICA ---
SHEET_ID = "17Cn82TTSyXbipbW3zZ7cvYe6L6aDkX3EPK6xO7MTxzU"
MI_EMAIL_CALENDARIO = "gabrielromero900@gmail.com"
ID_CARPETA_PADRE_DRIVE = "1XS4-h6-VpY_P-C3t_L-X4r8F6O-9-C-y"

st.set_page_config(page_title="CRM-IA: MyCar Centro", page_icon="🚗", layout="wide")

# --- GESTIÓN DE CUOTA ---
if "uso_ia" not in st.session_state: st.session_state.uso_ia = []
if "messages" not in st.session_state: st.session_state.messages = []

def limpiar_cuota():
    ahora = datetime.now()
    st.session_state.uso_ia = [t for t in st.session_state.uso_ia if ahora - t < timedelta(seconds=60)]
    return len(st.session_state.uso_ia)

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

# --- BARRA LATERAL ---
with st.sidebar:
    st.header("⚙️ CRM MyCar")
    mensajes_usados = limpiar_cuota()
    st.metric("Mensajes (último min)", f"{mensajes_usados} / 20")
    if mensajes_usados >= 18: st.warning("⚠️ Límite de cuota cerca.")
    st.divider()
    if st.button("🗑️ Limpiar Historial"):
        st.session_state.messages = []
        st.rerun()

# --- FUNCIONES DE LÓGICA ---
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

# --- INTERFAZ ---
st.title("🤖 CRM-IA: MyCar Centro")

c1, c2 = st.columns(2)
with c1: 
    if st.button("📊 Ver Stock"): st.dataframe(pd.DataFrame(ws_stock.get_all_records()))
with c2: 
    if st.button("👥 Ver Leeds"): st.dataframe(pd.DataFrame(ws_leeds.get_all_records()))

archivo = st.file_uploader("📷 Cargar PDF o Foto", type=["pdf", "jpg", "png", "jpeg"])

for message in st.session_state.messages:
    with st.chat_message(message["role"]): st.markdown(message["content"])

if prompt := st.chat_input("¿Qué novedades hay?"):
    st.session_state.uso_ia.append(datetime.now())
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    with st.chat_message("assistant"):
        contexto = f"Hoy: {datetime.now().strftime('%Y-%m-%d')}. Eres gestor de MyCar. Sé conciso. Stock: {ws_stock.get_all_records()[:10]}"
        try:
            inputs = [contexto, prompt]
            if archivo: inputs.append({"mime_type": archivo.type, "data": archivo.getvalue()})
            
            response = model.generate_content(inputs)
            res_text = response.text
            respuesta_visible = re.sub(r"DATA_START.*?DATA_END", "", res_text, flags=re.DOTALL).strip()
            st.markdown(respuesta_visible)
            st.session_state.messages.append({"role": "assistant", "content": respuesta_visible})

            for m in re.findall(r"DATA_START\s*(.*?)\s*DATA_END", res_text, re.DOTALL):
                data = json.loads(m)
                if data["ACCION"] == "GUARDAR_AUTO":
                    link = crear_carpeta_drive(f"{data['Cliente']} - {data['Vehiculo']}")
                    ws_stock.append_row([datetime.now().strftime("%d/%m/%Y"), data['Cliente'], data['Vehiculo'], data.get('Año','-'), data.get('KM','-'), data.get('Color','-'), "-", "-", data.get('Patente','-'), link])
                elif data["ACCION"] == "GUARDAR_LEED":
                    ws_leeds.append_row([datetime.now().strftime("%d/%m/%Y"), data['Cliente'], data.get('Busca','-'), data.get('Telefono','-'), data.get('Nota','-'), data.get('Fecha_Remind','-')])
                    if data.get("Fecha_Remind"): gestionar_calendario("CREAR", f"Llamar a {data['Cliente']}", data["Fecha_Remind"])
                elif data["ACCION"] == "ELIMINAR_AUTO": eliminar_registro(ws_stock, data['Cliente'])
                elif data["ACCION"] == "ELIMINAR_LEED": eliminar_registro(ws_leeds, data['Cliente'])
                elif data["ACCION"] == "BORRAR_EVENTO": gestionar_calendario("BORRAR", f"Llamar a {data['Cliente']}")
                elif data["ACCION"] == "WHATSAPP":
                    st.link_button("📲 Enviar WhatsApp", f"https://wa.me/{data['Telefono']}?text={urllib.parse.quote(data['Mensaje'])}")
                st.success(f"Hecho: {data['ACCION']}")
        except Exception as e:
            if "quota" in str(e).lower(): st.warning("⚠️ Límite de cuota excedido. Espera 60s.")
            else: st.error(f"Error: {e}")

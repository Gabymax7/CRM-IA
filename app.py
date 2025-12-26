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

# --- CONFIGURACIÓN ---
SHEET_ID = "17Cn82TTSyXbipbW3zZ7cvYe6L6aDkX3EPK6xO7MTxzU"
ID_CARPETA_PADRE_DRIVE = "1XS4-h6-VpY_P-C3t_L-X4r8F6O-9-C-y"
MI_EMAIL_CALENDARIO = "gabrielromero900@gmail.com"

st.set_page_config(page_title="CRM MyCar Centro", page_icon="🚗", layout="wide")

# --- CONEXIÓN ---
@st.cache_resource
def conectar():
    SCOPE = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/calendar"]
    try:
        creds_info = dict(st.secrets["gcp_service_account"])
        creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPE)
        
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID)
        drive = build('drive', 'v3', credentials=creds)
        cal = build('calendar', 'v3', credentials=creds)
        return sheet.worksheet("Stock"), sheet.worksheet("Leeds"), drive, cal
    except Exception as e:
        st.error(f"Error de conexión: {e}")
        return None, None, None, None

ws_stock, ws_leeds, drive_service, cal_service = conectar()
if ws_stock is None: st.stop()

# --- IA SETUP ---
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel('models/gemini-3-flash-preview')

# --- FUNCIONES DE GESTIÓN ---
def crear_carpeta_drive(nombre):
    try:
        meta = {'name': nombre, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [ID_CARPETA_PADRE_DRIVE]}
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
            cal_service.events().insert(calendarId=MI_EMAIL_CALENDARIO, body=event).execute()
        elif accion == "BORRAR":
            events = cal_service.events().list(calendarId=MI_EMAIL_CALENDARIO, q=resumen).execute()
            for e in events.get('items', []):
                cal_service.events().delete(calendarId=MI_EMAIL_CALENDARIO, eventId=e['id']).execute()
        return True
    except: return False

# --- UI: BARRA LATERAL ---
if "uso_ia" not in st.session_state: st.session_state.uso_ia = []
with st.sidebar:
    st.header("⚙️ CRM MyCar")
    ahora = datetime.now()
    st.session_state.uso_ia = [t for t in st.session_state.uso_ia if ahora - t < timedelta(seconds=60)]
    st.metric("Mensajes (último min)", f"{len(st.session_state.uso_ia)} / 20")
    st.divider()
    if st.button("🗑️ Limpiar Historial"):
        st.session_state.messages = []
        st.rerun()

# --- INTERFAZ PRINCIPAL ---
st.title("🤖 CRM-IA: MyCar Centro")
tab1, tab2, tab3 = st.tabs(["💬 Chat & Comandos", "📦 Stock", "👥 Leeds"])

with tab1:
    archivo = st.file_uploader("📷 Subir PDF, Foto o Audio", type=["pdf", "jpg", "png", "jpeg", "m4a", "wav", "mp3"])
    if "messages" not in st.session_state: st.session_state.messages = []
    
    for m in st.session_state.messages:
        with st.chat_message(m["role"]): st.markdown(m["content"])

    if prompt := st.chat_input("¿Qué novedades hay?"):
        st.session_state.uso_ia.append(datetime.now())
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)

        with st.chat_message("assistant"):
            try:
                stock_data = ws_stock.get_all_records()
                leeds_data = ws_leeds.get_all_records()
                instruccion = f"Hoy: {datetime.now().strftime('%Y-%m-%d')}. Eres gestor de MyCar. Sé corto. Stock: {stock_data[:15]}. Leeds: {leeds_data[:15]}."
                
                inputs = [instruccion, prompt]
                if archivo: inputs.append({"mime_type": archivo.type, "data": archivo.getvalue()})
                
                res = model.generate_content(inputs)
                txt = res.text
                visible = re.sub(r"DATA_START.*?DATA_END", "", txt, flags=re.DOTALL).strip()
                st.markdown(visible)
                st.session_state.messages.append({"role": "assistant", "content": visible})

                for m in re.findall(r"DATA_START\s*(.*?)\s*DATA_END", txt, re.DOTALL):
                    data = json.loads(m)
                    if data["ACCION"] == "GUARDAR_AUTO":
                        link = crear_carpeta_drive(f"{data['Cliente']} - {data['Vehiculo']}")
                        ws_stock.append_row([datetime.now().strftime("%d/%m/%Y"), data['Cliente'], data['Vehiculo'], data.get('Año','-'), data.get('KM','-'), data.get('Color','-'), "-", "-", data.get('Patente','-'), link])
                    elif data["ACCION"] == "GUARDAR_LEED":
                        ws_leeds.append_row([datetime.now().strftime("%d/%m/%Y"), data['Cliente'], data.get('Busca','-'), data.get('Telefono','-'), data.get('Nota','-'), data.get('Fecha_Remind','-')])
                        if data.get("Fecha_Remind") and data["Fecha_Remind"] != "-":
                            gestionar_calendario("CREAR", f"Llamar a {data['Cliente']}", data["Fecha_Remind"])
                    elif data["ACCION"] == "ELIMINAR_AUTO": eliminar_registro(ws_stock, data['Cliente'])
                    elif data["ACCION"] == "ELIMINAR_LEED": eliminar_registro(ws_leeds, data['Cliente'])
                    elif data["ACCION"] == "WHATSAPP":
                        st.link_button("📲 Enviar WhatsApp", f"https://wa.me/{data['Telefono']}?text={urllib.parse.quote(data['Mensaje'])}")
                    st.success(f"Hecho: {data['ACCION']}")
            except Exception as e:
                st.error(f"Error: {e}")

with tab2:
    if st.button("🔄 Refrescar Stock"): st.rerun()
    st.dataframe(pd.DataFrame(ws_stock.get_all_records()), use_container_width=True)

with tab3:
    if st.button("🔄 Refrescar Leeds"): st.rerun()
    st.dataframe(pd.DataFrame(ws_leeds.get_all_records()), use_container_width=True)

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
MI_EMAIL_CALENDARIO = "gabrielromero900@gmail.com"
ID_CARPETA_PADRE_DRIVE = "1XS4-h6-VpY_P-C3t_L-X4r8F6O-9-C-y"

st.set_page_config(page_title="CRM-IA: MyCar Centro", page_icon="🚗", layout="wide")

if "uso_ia" not in st.session_state: st.session_state.uso_ia = []
if "messages" not in st.session_state: st.session_state.messages = []

# --- BARRA LATERAL (SELECTOR DE IA) ---
with st.sidebar:
    st.header("⚙️ Configuración")
    # Selector de modelos para saltar límites de cuota
    modelo_elegido = st.selectbox(
        "Cambiar versión de IA", 
        ["models/gemini-1.5-flash", "models/gemini-2.0-flash", "models/gemini-3-flash-preview"],
        index=2,
        help="Si una versión da error de cuota, cambia a otra para seguir testeando."
    )
    
    # Contador de mensajes
    ahora = datetime.now()
    st.session_state.uso_ia = [t for t in st.session_state.uso_ia if ahora - t < timedelta(seconds=60)]
    st.metric("Mensajes (último min)", f"{len(st.session_state.uso_ia)} / 20")
    
    st.divider()
    if st.button("🗑️ Limpiar Chat"):
        st.session_state.messages = []
        st.rerun()

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

# --- INICIALIZAR IA SELECCIONADA ---
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel(modelo_elegido)

# --- FUNCIONES DE DRIVE Y BORRADO ---
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

# --- INTERFAZ PRINCIPAL ---
st.title("🤖 CRM-IA: MyCar Centro")

c1, c2 = st.columns(2)
with c1: 
    if st.button("📊 Ver Stock"): st.dataframe(pd.DataFrame(ws_stock.get_all_records()))
with c2: 
    if st.button("👥 Ver Leeds"): st.dataframe(pd.DataFrame(ws_leeds.get_all_records()))

archivo = st.file_uploader("📷 Cargar PDF o Foto", type=["pdf", "jpg", "png", "jpeg"])

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]): st.markdown(msg["content"])

if prompt := st.chat_input("¿Qué novedades hay?"):
    st.session_state.uso_ia.append(datetime.now())
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    with st.chat_message("assistant"):
        contexto = f"Hoy: {datetime.now().strftime('%Y-%m-%d')}. Eres gestor de MyCar. Sé directo. Stock: {ws_stock.get_all_records()[:5]}"
        try:
            input_ia = [contexto, prompt]
            if archivo: input_ia.append({"mime_type": archivo.type, "data": archivo.getvalue()})
            
            res = model.generate_content(input_ia)
            visible = re.sub(r"DATA_START.*?DATA_END", "", res.text, flags=re.DOTALL).strip()
            st.markdown(visible)
            st.session_state.messages.append({"role": "assistant", "content": visible})

            for m in re.findall(r"DATA_START\s*(.*?)\s*DATA_END", res.text, re.DOTALL):
                data = json.loads(m)
                if data["ACCION"] == "GUARDAR_AUTO":
                    link = crear_carpeta_drive(f"{data['Cliente']} - {data['Vehiculo']}")
                    ws_stock.append_row([datetime.now().strftime("%d/%m/%Y"), data['Cliente'], data['Vehiculo'], data.get('Año','-'), data.get('KM','-'), data.get('Color','-'), "-", "-", data.get('Patente','-'), link])
                elif data["ACCION"] == "ELIMINAR_AUTO": eliminar_registro(ws_stock, data['Cliente'])
                elif data["ACCION"] == "ELIMINAR_LEED": eliminar_registro(ws_leeds, data['Cliente'])
                elif data["ACCION"] == "WHATSAPP":
                    st.link_button("📲 Enviar WhatsApp", f"https://wa.me/{data['Telefono']}?text={urllib.parse.quote(data['Mensaje'])}")
                st.success(f"Hecho: {data['ACCION']}")
        except Exception as e:
            if "quota" in str(e).lower():
                st.warning("⚠️ Límite agotado en este modelo. Selecciona otro en el panel de la izquierda.")
            else: st.error(f"Error: {e}")

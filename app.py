import streamlit as st
import google.generativeai as genai
from groq import Groq # Nueva integración
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

st.set_page_config(page_title="CRM MyCar Multi-IA", page_icon="🚗", layout="wide")

# --- BARRA LATERAL (CONTROL DE IA) ---
if "uso_ia" not in st.session_state: st.session_state.uso_ia = []
if "messages" not in st.session_state: st.session_state.messages = []

with st.sidebar:
    st.header("⚙️ Selector de Motor")
    # Te permite saltar el límite de Gemini usando Groq
    motor_ia = st.selectbox("IA Activa", ["Gemini 3 Flash", "Groq (Llama 3.3)"])
    
    mensajes = len([t for t in st.session_state.uso_ia if datetime.now() - t < timedelta(seconds=60)])
    st.metric("Mensajes/min (Gemini)", f"{mensajes} / 20")
    
    st.divider()
    if st.button("🗑️ Limpiar Chat"):
        st.session_state.messages = []
        st.rerun()

# --- CONEXIÓN A GOOGLE ---
@st.cache_resource
def conectar():
    creds_info = dict(st.secrets["gcp_service_account"])
    creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
    creds = Credentials.from_service_account_info(creds_info, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/calendar"])
    gc = gspread.authorize(creds)
    return gc.open_by_key(SHEET_ID).worksheet("Stock"), gc.open_by_key(SHEET_ID).worksheet("Leeds"), build('drive', 'v3', credentials=creds)

ws_stock, ws_leeds, drive_service = conectar()

# --- FUNCIONES DE IA ---
def llamar_ia(prompt, archivo=None):
    # Lógica para Gemini
    if motor_ia == "Gemini 3 Flash":
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        model = genai.GenerativeModel('models/gemini-3-flash-preview')
        inputs = [prompt]
        if archivo: inputs.append({"mime_type": archivo.type, "data": archivo.getvalue()})
        res = model.generate_content(inputs)
        return res.text
    
    # Lógica para Groq (Solo texto por ahora para máxima velocidad)
    else:
        client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
        )
        return completion.choices[0].message.content

# --- INTERFAZ ---
st.title("🤖 CRM-IA: MyCar Centro")
tab1, tab2, tab3 = st.tabs(["💬 Chat", "📦 Stock", "👥 Leeds"])

with tab1:
    archivo = st.file_uploader("📷 Subir archivo (Solo para Gemini)", type=["pdf", "jpg", "png", "jpeg", "mp4", "m4a"])
    for m in st.session_state.messages:
        with st.chat_message(m["role"]): st.markdown(m["content"])

    if prompt_user := st.chat_input("¿Qué novedades hay?"):
        st.session_state.uso_ia.append(datetime.now())
        st.session_state.messages.append({"role": "user", "content": prompt_user})
        with st.chat_message("user"): st.markdown(prompt_user)

        with st.chat_message("assistant"):
            try:
                stock_ref = str(ws_stock.get_all_records()[:10])
                instruccion = f"""Hoy: {datetime.now().strftime('%Y-%m-%d')}. Eres gestor de MyCar Centro.
                STOCK: {stock_ref}. Responde CORTO.
                ACCIONES: GUARDAR_AUTO, ELIMINAR_AUTO, GUARDAR_LEED, WHATSAPP.
                JSON: DATA_START {{"ACCION": "...", "Cliente": "...", "Vehiculo": "...", "Telefono": "...", "Mensaje": "..."}} DATA_END"""
                
                respuesta = llamar_ia(instruccion + "\n\nUsuario: " + prompt_user, archivo)
                visible = re.sub(r"DATA_START.*?DATA_END", "", respuesta, flags=re.DOTALL).strip()
                st.markdown(visible)
                st.session_state.messages.append({"role": "assistant", "content": visible})

                for match in re.findall(r"DATA_START\s*(.*?)\s*DATA_END", respuesta, re.DOTALL):
                    data = json.loads(match)
                    if data["ACCION"] == "GUARDAR_AUTO":
                        # Crear carpeta en Drive
                        meta = {'name': f"{data['Cliente']} - {data['Vehiculo']}", 'mimeType': 'application/vnd.google-apps.folder', 'parents': [ID_CARPETA_PADRE_DRIVE]}
                        f = drive_service.files().create(body=meta, fields='webViewLink').execute()
                        ws_stock.append_row([datetime.now().strftime("%d/%m/%Y"), data['Cliente'], data['Vehiculo'], data.get('Año','-'), data.get('KM','-'), data.get('Color','-'), "-", "-", data.get('Patente','-'), f.get('webViewLink')])
                    elif data["ACCION"] == "WHATSAPP":
                        st.link_button("📲 Enviar WhatsApp", f"https://wa.me/{data['Telefono']}?text={urllib.parse.quote(data['Mensaje'])}")
                    st.toast(f"✅ {data['ACCION']} completada.")
            except Exception as e:
                st.error(f"Error: {e}")

with tab2: st.dataframe(pd.DataFrame(ws_stock.get_all_records()))
with tab3: st.dataframe(pd.DataFrame(ws_leeds.get_all_records()))

import streamlit as st
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import json
import re
from datetime import datetime
import pandas as pd

# --- CONFIGURACIÓN ---
SHEET_ID = "17Cn82TTSyXbipbW3zZ7cvYe6L6aDkX3EPK6xO7MTxzU"
MI_EMAIL_CALENDARIO = "gabrielromero900@gmail.com"

st.set_page_config(page_title="CRM-IA: MyCar Centro", page_icon="🚗", layout="wide")

if "messages" not in st.session_state:
    st.session_state.messages = []

# --- CONEXIÓN A GOOGLE ---
def conectar():
    SCOPE = [
        "https://www.googleapis.com/auth/spreadsheets", 
        "https://www.googleapis.com/auth/drive", 
        "https://www.googleapis.com/auth/calendar"
    ]
    try:
        if "gcp_service_account" in st.secrets:
            # Convierte secretos de Streamlit en un diccionario limpio
            creds_info = dict(st.secrets["gcp_service_account"])
            # Asegura que la clave privada tenga los saltos de línea correctos
            if "private_key" in creds_info:
                creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
            creds = Credentials.from_service_account_info(creds_info, scopes=SCOPE)
        else:
            # Opción para uso local
            creds = Credentials.from_service_account_file("credenciales.json", scopes=SCOPE)
        
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID)
        cal_service = build('calendar', 'v3', credentials=creds)
        return sheet.worksheet("Stock"), sheet.worksheet("Leeds"), cal_service
    except Exception as e:
        st.error(f"Error de conexión: {e}")
        return None, None, None

ws_stock, ws_leeds, calendar_service = conectar()

if ws_stock is None:
    st.stop()

# --- CONFIGURACIÓN IA (Gemini 3 Flash Preview) ---
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel('models/gemini-3-flash-preview')

# --- FUNCIONES ---
def procesar_archivo(uploaded_file):
    if uploaded_file is not None:
        return {"mime_type": uploaded_file.type, "data": uploaded_file.getvalue()}
    return None

# --- INTERFAZ ---
st.title("🤖 CRM-IA: MyCar Centro")

col1, col2 = st.columns(2)
with col1: 
    if st.button("📊 Ver Stock"):
        st.dataframe(pd.DataFrame(ws_stock.get_all_records()))
with col2: 
    if st.button("👥 Ver Leeds"):
        st.dataframe(pd.DataFrame(ws_leeds.get_all_records()))

archivo = st.file_uploader("📷 Subir foto de Patente o Lista", type=["pdf", "jpg", "png", "jpeg"])

for message in st.session_state.messages:
    with st.chat_message(message["role"]): st.markdown(message["content"])

if prompt := st.chat_input("¿Qué novedades hay?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    with st.chat_message("assistant"):
        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        instruccion = f"Hoy es {fecha_hoy}. Eres el gestor de MyCar Centro. Responde con brevedad y amabilidad."
        
        contenidos = [instruccion, prompt]
        if archivo:
            img_data = procesar_archivo(archivo)
            if img_data: contenidos.append(img_data)
            
        try:
            # Respuesta usando el nuevo modelo Gemini 3
            response = model.generate_content(contenidos)
            st.markdown(response.text)
            st.session_state.messages.append({"role": "assistant", "content": response.text})
        except Exception as e:
            st.error(f"Error en la IA: {e}")

import streamlit as st
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import json
import re
from datetime import datetime, timedelta
import pandas as pd

# --- CONFIGURACIÓN ---
SHEET_ID = "17Cn82TTSyXbipbW3zZ7cvYe6L6aDkX3EPK6xO7MTxzU"
MI_EMAIL_CALENDARIO = "gabrielromero900@gmail.com" 

st.set_page_config(page_title="CRM-IA: MyCar", page_icon="🚗", layout="wide")

# 1. INICIALIZAR ESTADO (Evita el error de 'no attribute messages')
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- CONEXIÓN ---
def conectar():
    SCOPE = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/calendar"]
    
    if "gcp_service_account" in st.secrets:
        # Streamlit Cloud: st.secrets ya es un diccionario
        creds_info = dict(st.secrets["gcp_service_account"])
        if "private_key" in creds_info:
            creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPE)
    else:
        # Uso local
        creds = Credentials.from_service_account_file("credenciales.json", scopes=SCOPE)
    
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID)
    cal_service = build('calendar', 'v3', credentials=creds)
    return sheet.worksheet("Stock"), sheet.worksheet("Leeds"), cal_service

try:
    ws_stock, ws_leeds, calendar_service = conectar()
except Exception as e:
    st.error(f"Error de conexión: {e}")
    st.stop()

# 2. MODELO CORREGIDO (Probamos con gemini-1.5-flash que es el estándar)
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-1.5-flash') 

# --- FUNCIONES DE APOYO ---

def procesar_archivo(uploaded_file):
    """Convierte el archivo de Streamlit a formato que la IA entienda"""
    if uploaded_file is not None:
        return {"mime_type": uploaded_file.type, "data": uploaded_file.getvalue()}
    return None

def crear_evento_calendario(resumen, fecha_iso):
    try:
        event = {
            'summary': resumen,
            'start': {'date': fecha_iso, 'timeZone': 'America/Argentina/Buenos_Aires'},
            'end': {'date': fecha_iso, 'timeZone': 'America/Argentina/Buenos_Aires'},
        }
        calendar_service.events().insert(calendarId=MI_EMAIL_CALENDARIO, body=event).execute()
        return True
    except: return False

# ... (Funciones de guardado de Stock y Leeds se mantienen igual) ...

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
        
        # Obtenemos los últimos registros para que la IA sepa qué hay en stock
        stock_actual = ws_stock.get_all_records()[:20]
        
        instruccion = f"""
        Hoy es {fecha_hoy}. Eres el gestor de MyCar. 
        Este es el Stock actual: {stock_actual}
        
        REGLAS:
        1. Si preguntan por stock, responde basándote en los datos arriba.
        2. PARTICULAR vende/ofrece: GUARDAR_AUTO.
        3. Alguien busca COMPRAR: GUARDAR_LEED.
        
        JSON OBLIGATORIO AL FINAL:
        DATA_START {{"ACCION": "...", "Cliente": "...", "Vehiculo": "...", "Patente": "...", "Año": "...", "KM": "...", "Color": "...", "Busca": "...", "Fecha_Remind": "YYYY-MM-DD", "Nota": "..."}} DATA_END
        """
        
        # Enviamos los contenidos procesados (Texto + Imagen corregida)
        contenidos = [instruccion, prompt]
        if archivo:
            # Aquí corregimos el TypeError convirtiendo la foto
            contenidos.append(procesar_archivo(archivo))
            
        try:
            response = model.generate_content(contenidos)
            res_text = response.text
            respuesta_visible = re.sub(r"DATA_START.*?DATA_END", "", res_text, flags=re.DOTALL).strip()
            st.markdown(respuesta_visible)
            st.session_state.messages.append({"role": "assistant", "content": respuesta_visible})
            # ... (Procesamiento del JSON igual al anterior) ...
        except Exception as e:
            st.error(f"Error en la IA: {e}")

import streamlit as st
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import json
import re
from datetime import datetime
import pandas as pd

# --- CONFIGURACIÓN ESTÁTICA ---
SHEET_ID = "17Cn82TTSyXbipbW3zZ7cvYe6L6aDkX3EPK6xO7MTxzU"
MI_EMAIL_CALENDARIO = "gabrielromero900@gmail.com"

st.set_page_config(page_title="CRM-IA: MyCar Centro", page_icon="🚗", layout="wide")

if "messages" not in st.session_state:
    st.session_state.messages = []

# --- CONEXIÓN A GOOGLE ---
def conectar():
    SCOPE = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/calendar"]
    try:
        if "gcp_service_account" in st.secrets:
            # Convierte el AttrDict de Streamlit en un diccionario real de Python
            creds_info = dict(st.secrets["gcp_service_account"])
            # Arregla los saltos de línea de la clave privada
            if "private_key" in creds_info:
                creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
            creds = Credentials.from_service_account_info(creds_info, scopes=SCOPE)
        else:
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

# --- CONFIGURACIÓN GEMINI 3 FLASH (Lanzado 17/12/2025) ---
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-3-flash')

# --- FUNCIONES DE LÓGICA ---
def procesar_archivo(uploaded_file):
    if uploaded_file is not None:
        return {"mime_type": uploaded_file.type, "data": uploaded_file.getvalue()}
    return None

def guardar_o_actualizar_stock(data):
    hoy = datetime.now().strftime("%d/%m/%Y")
    try:
        celda = ws_stock.find(data['Cliente'], in_column=2)
        fila = celda.row
        ws_stock.update(range_name=f"D{fila}:F{fila}", values=[[data.get('Año','-'), data.get('KM','-'), data.get('Color','-')]])
        if data.get('Patente'): ws_stock.update_cell(fila, 9, data['Patente'])
        return "actualizado"
    except:
        ws_stock.append_row([hoy, data['Cliente'], data['Vehiculo'], data.get('Año','-'), data.get('KM','-'), data.get('Color','-'), "-", "-", data.get('Patente','-'), "-"])
        return "nuevo"

def guardar_o_actualizar_leed(data):
    hoy = datetime.now().strftime("%d/%m/%Y")
    try:
        celda = ws_leeds.find(data['Cliente'], in_column=2)
        fila = celda.row
        ws_leeds.update(range_name=f"A{fila}:F{fila}", values=[[hoy, data['Cliente'], data['Busca'], data.get('Telefono','-'), data.get('Nota','-'), data.get('Fecha_Remind','-')]])
    except:
        ws_leeds.append_row([hoy, data['Cliente'], data['Busca'], data.get('Telefono','-'), data.get('Nota','-'), data.get('Fecha_Remind','-')])

# --- INTERFAZ ---
st.title("🤖 CRM-IA: MyCar Centro")

c1, c2 = st.columns(2)
with c1: 
    if st.button("📊 Ver Stock"):
        st.dataframe(pd.DataFrame(ws_stock.get_all_records()))
with c2: 
    if st.button("👥 Ver Leeds"):
        st.dataframe(pd.DataFrame(ws_leeds.get_all_records()))

archivo = st.file_uploader("📷 Subir foto de Patente o Lista", type=["pdf", "jpg", "png", "jpeg"])

for m in st.session_state.messages:
    with st.chat_message(m["role"]): st.markdown(m["content"])

if prompt := st.chat_input("¿Qué novedades hay?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    with st.chat_message("assistant"):
        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        instruccion = f"""Hoy es {fecha_hoy}. Eres el gestor de MyCar.
        Si hay datos para guardar usa: DATA_START {{"ACCION": "GUARDAR_AUTO", "Cliente": "...", "Vehiculo": "...", "Patente": "...", "Año": "...", "KM": "...", "Color": "...", "Busca": "...", "Fecha_Remind": "YYYY-MM-DD"}} DATA_END"""
        
        contenidos = [instruccion, prompt]
        if archivo:
            img_data = procesar_archivo(archivo)
            if img_data: contenidos.append(img_data)
            
        try:
            response = model.generate_content(contenidos)
            res_text = response.text
            respuesta_visible = re.sub(r"DATA_START.*?DATA_END", "", res_text, flags=re.DOTALL).strip()
            st.markdown(respuesta_visible)
            st.session_state.messages.append({"role": "assistant", "content": respuesta_visible})

            if "DATA_START" in res_text:
                json_data = json.loads(re.search(r"DATA_START\s*(.*?)\s*DATA_END", res_text, re.DOTALL).group(1))
                if "GUARDAR_AUTO" in json_data["ACCION"]: guardar_o_actualizar_stock(json_data)
                else: guardar_o_actualizar_leed(json_data)
                st.success("✅ Datos sincronizados con Google Sheets.")
        except Exception as e:
            st.error(f"Error en la IA: {e}")

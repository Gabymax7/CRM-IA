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

# Inicialización crítica para evitar errores de st.session_state 
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- CONEXIÓN ---
def conectar():
    SCOPE = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/calendar"]
    
    if "gcp_service_account" in st.secrets:
        # En la nube, convertimos el secreto directamente a diccionario
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

genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-1.5-flash-latest')

# --- FUNCIONES ---
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

def guardar_o_actualizar_stock(data):
    hoy = datetime.now().strftime("%d/%m/%Y")
    try:
        # Buscar duplicados por nombre de Cliente
        celda = ws_stock.find(data['Cliente'], in_column=2)
        fila = celda.row
        ws_stock.update(range_name=f"D{fila}:F{fila}", values=[[data.get('Año','-'), data.get('KM','-'), data.get('Color','-')]])
        if data.get('Patente'): ws_stock.update_cell(fila, 9, data['Patente'])
        return "actualizado"
    except:
        ws_stock.append_row([hoy, data['Cliente'], data['Vehiculo'], data.get('Año','-'), data.get('KM','-'), data.get('Color','-'), "-", "-", data.get('Patente','-'), "-"])
        return "nuevo"

def guardar_o_actualizar_leed(data):
    try:
        hoy = datetime.now().strftime("%d/%m/%Y")
        try:
            celda = ws_leeds.find(data['Cliente'], in_column=2)
            fila = celda.row
            ws_leeds.update(range_name=f"A{fila}:F{fila}", values=[[hoy, data['Cliente'], data['Busca'], data.get('Telefono','-'), data.get('Nota','-'), data.get('Fecha_Remind','-')]])
            return "actualizado"
        except:
            ws_leeds.append_row([hoy, data['Cliente'], data['Busca'], data.get('Telefono','-'), data.get('Nota','-'), data.get('Fecha_Remind','-')])
            return "nuevo"
    except: return "error"

# --- INTERFAZ ---
st.title("🤖 CRM-IA: MyCar Centro")

col1, col2 = st.columns(2)
with col1: 
    if st.button("📊 Ver Stock"):
        st.dataframe(pd.DataFrame(ws_stock.get_all_records()))
with col2: 
    # Esta es la línea que estaba incompleta en tu error de sintaxis
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
        instruccion = f"""
        Hoy es {fecha_hoy}. Eres el gestor de MyCar.
        REGLAS:
        1. PARTICULAR vende/ofrece: GUARDAR_AUTO. Saca Año, KM, Color.
        2. Alguien busca COMPRAR: GUARDAR_LEED.
        3. Foto de PATENTE: ACTUALIZAR_PATENTE.
        JSON OBLIGATORIO:
        DATA_START {{"ACCION": "...", "Cliente": "...", "Vehiculo": "...", "Patente": "...", "Año": "...", "KM": "...", "Color": "...", "Busca": "...", "Fecha_Remind": "YYYY-MM-DD", "Nota": "..."}} DATA_END
        """
        inputs = [instruccion, prompt]
        if archivo: inputs.append(archivo)
        
        response = model.generate_content(inputs)
        res_text = response.text
        # Limpieza robusta del JSON para evitar caracteres de control [cite: 2]
        respuesta_visible = re.sub(r"DATA_START.*?DATA_END", "", res_text, flags=re.DOTALL).strip()
        st.markdown(respuesta_visible)
        st.session_state.messages.append({"role": "assistant", "content": respuesta_visible})

        if "DATA_START" in res_text:
            try:
                data_match = re.search(r"DATA_START\s*(.*?)\s*DATA_END", res_text, re.DOTALL)
                if data_match:
                    data = json.loads(data_match.group(1))
                    if data["ACCION"] == "GUARDAR_AUTO":
                        guardar_o_actualizar_stock(data)
                        st.success("✅ Stock procesado.")
                    elif data["ACCION"] == "GUARDAR_LEED":
                        guardar_o_actualizar_leed(data)
                        st.success("✅ Leeds procesado.")
                        if data.get("Fecha_Remind") and data["Fecha_Remind"] != "-":
                            crear_evento_calendario(f"Llamar a {data['Cliente']}", data["Fecha_Remind"])
            except: pass

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

if "messages" not in st.session_state:
    st.session_state.messages = []

# --- CONEXIÓN ---
def conectar():
    SCOPE = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/calendar"]
    # En Streamlit Cloud, usaremos st.secrets para las credenciales
    if "gcp_service_account" in st.secrets:
        info = json.loads(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(info, scopes=SCOPE)
    else:
        creds = Credentials.from_service_account_file("credenciales.json", scopes=SCOPE)
    
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID)
    cal_service = build('calendar', 'v3', credentials=creds)
    return sheet.worksheet("Stock"), sheet.worksheet("Leeds"), cal_service

try:
    ws_stock, ws_leeds, calendar_service = conectar()
except Exception as e:
    st.error(f"Error de conexión: {e}")

genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-1.5-flash-latest')

# --- FUNCIONES DE LÓGICA ---

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
    """Evita duplicados en stock buscando por Cliente y Vehículo"""
    hoy = datetime.now().strftime("%d/%m/%Y")
    try:
        # Intenta buscar si el cliente ya tiene ese auto cargado
        celda = ws_stock.find(data['Cliente'], in_column=2)
        fila = celda.row
        if ws_stock.cell(fila, 3).value == data['Vehiculo']:
            # Si coinciden Cliente (Col 2) y Vehículo (Col 3), actualizamos datos técnicos
            ws_stock.update(range_name=f"D{fila}:F{fila}", values=[[data.get('Año','-'), data.get('KM','-'), data.get('Color','-')]])
            if data.get('Patente'): ws_stock.update_cell(fila, 9, data['Patente'])
            return "actualizado"
    except: pass
    
    # Si no existe, nueva fila: Fecha, Cliente, Vehiculo, Año, KM, Color, VTV, Origen, Patente, Drive
    ws_stock.append_row([hoy, data['Cliente'], data['Vehiculo'], data.get('Año','-'), data.get('KM','-'), data.get('Color','-'), "-", "-", data.get('Patente','-'), "-"])
    return "nuevo"

def actualizar_patente_por_nombre(nombre_cliente, patente):
    """Busca al cliente en Stock y le asigna la patente detectada"""
    try:
        celda = ws_stock.find(nombre_cliente, in_column=2)
        ws_stock.update_cell(celda.row, 9, patente)
        return True
    except: return False

# --- INTERFAZ ---
st.title("🤖 CRM-IA: MyCar Centro")

# Botones de visualización rápida
c1, c2 = st.columns(2)
with c1: 
    if st.button("📊 Ver Stock"): st.dataframe(pd.DataFrame(ws_stock.get_all_records()))
with c2: 
    if st.button("👥 Ver Leeds"): st.dataframe(pd.DataFrame(ws_leeds.get_all_records()))

# Subida de archivos (Fotos de patentes, listas, etc)
archivo = st.file_uploader("📷 Subir foto o lista (Patentes, Stock, etc.)", type=["pdf", "jpg", "png", "jpeg"])

for m in st.session_state.messages:
    with st.chat_message(m["role"]): st.markdown(m["content"])

if prompt := st.chat_input("¿Qué novedades hay?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    with st.chat_message("assistant"):
        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        
        instruccion = f"""
        Hoy es {fecha_hoy}. Eres el gestor de MyCar.
        STOCK: {ws_stock.get_all_records()[:15]}
        LEEDS: {ws_leeds.get_all_records()[:15]}

        REGLAS:
        1. Si el usuario sube una foto de una PATENTE y dice de quién es, usa ACCION: ACTUALIZAR_PATENTE.
        2. Si un PARTICULAR ofrece su auto, es GUARDAR_AUTO. Extrae Año, KM y Color.
        3. Si alguien busca COMPRAR, es GUARDAR_LEED.

        JSON OBLIGATORIO:
        DATA_START {{"ACCION": "...", "Cliente": "...", "Vehiculo": "...", "Patente": "...", "Año": "...", "KM": "...", "Color": "...", "Busca": "...", "Fecha_Remind": "YYYY-MM-DD", "Nota": "..."}} DATA_END
        """

        # Enviar texto y/o archivo a Gemini
        if archivo:
            response = model.generate_content([instruccion, prompt, archivo])
        else:
            response = model.generate_content([instruccion, prompt])
        
        res_text = response.text
        respuesta_visible = re.sub(r"DATA_START.*?DATA_END", "", res_text, flags=re.DOTALL).strip()
        st.markdown(respuesta_visible)
        st.session_state.messages.append({"role": "assistant", "content": respuesta_visible})

        if "DATA_START" in res_text:
            try:
                data = json.loads(re.search(r"DATA_START\s*(.*?)\s*DATA_END", res_text, re.DOTALL).group(1))
                
                if data["ACCION"] == "GUARDAR_AUTO":
                    res = guardar_o_actualizar_stock(data)
                    st.success(f"✅ Stock {'actualizado' if res == 'actualizado' else 'registrado'}.")

                elif data["ACCION"] == "ACTUALIZAR_PATENTE":
                    if actualizar_patente_por_nombre(data['Cliente'], data['Patente']):
                        st.success(f"🚗 Patente {data['Patente']} asignada a {data['Cliente']}.")
                    else:
                        st.error("No encontré al cliente en Stock para asignarle esa patente.")

                elif data["ACCION"] == "GUARDAR_LEED":
                    # Lógica de Leeds ya existente...
                    ws_leeds.append_row([datetime.now().strftime("%d/%m/%Y"), data['Cliente'], data['Busca'], data.get('Telefono','-'), data.get('Nota','-'), data.get('Fecha_Remind','-')])
                    st.success(f"✅ Interesado {data['Cliente']} registrado.")
                    if data.get("Fecha_Remind") and data["Fecha_Remind"] != "-":
                        crear_evento_calendario(f"Llamar a {data['Cliente']}", data["Fecha_Remind"])
            except Exception as e:
                st.error(f"Error procesando: {e}")
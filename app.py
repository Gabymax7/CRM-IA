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
    return sheet.worksheet("Stock"), sheet.worksheet("Leeds"), cal_service

try:
    ws_stock, ws_leeds, calendar_service = conectar()
except Exception as e:
    st.error(f"Error de conexión: {e}")
    st.stop()

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
        return "actualizado"
    except:
        ws_leeds.append_row([hoy, data['Cliente'], data['Busca'], data.get('Telefono','-'), data.get('Nota','-'), data.get('Fecha_Remind','-')])
        return "nuevo"

def buscar_coincidencias(auto_nuevo):
    leeds = ws_leeds.get_all_records()
    for l in leeds:
        if str(l.get('Busca', '')).lower() in auto_nuevo.lower():
            st.warning(f"💡 ¡AVISO! {l['Cliente']} busca un {auto_nuevo}. Tel: {l.get('Telefono','')}")

# --- INTERFAZ ---
st.title("🤖 CRM-IA: MyCar Centro")

c1, c2 = st.columns(2)
with c1: 
    if st.button("📊 Ver Stock"): st.dataframe(pd.DataFrame(ws_stock.get_all_records()))
with c2: 
    if st.button("👥 Ver Leeds"): st.dataframe(pd.DataFrame(ws_leeds.get_all_records()))

archivo = st.file_uploader("📷 Foto de Patente o Lista", type=["pdf", "jpg", "png", "jpeg"])

for m in st.session_state.messages:
    with st.chat_message(m["role"]): st.markdown(m["content"])

if prompt := st.chat_input("¿Qué novedades hay?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    with st.chat_message("assistant"):
        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        instruccion = f"""
        Hoy es {fecha_hoy}. Eres el gestor de MyCar.
        REGLAS:
        1. PARTICULAR vende: GUARDAR_AUTO. Extrae Año, KM, Color.
        2. Alguien busca COMPRAR: GUARDAR_LEED.
        3. Foto de PATENTE: Si el usuario dice de quién es el auto de la foto, usa ACTUALIZAR_PATENTE.
        JSON OBLIGATORIO AL FINAL:
        DATA_START {{"ACCION": "...", "Cliente": "...", "Vehiculo": "...", "Patente": "...", "Año": "...", "KM": "...", "Color": "...", "Busca": "...", "Fecha_Remind": "YYYY-MM-DD", "Nota": "..."}} DATA_END
        """
        response = model.generate_content([instruccion, prompt, archivo] if archivo else [instruccion, prompt])
        res_text = response.text
        respuesta_visible = re.sub(r"DATA_START.*?DATA_END", "", res_text, flags=re.DOTALL).strip()
        st.markdown(respuesta_visible)
        st.session_state.messages.append({"role": "assistant", "content": respuesta_visible})

        if "DATA_START" in res_text:
            try:
                data = json.loads(re.search(r"DATA_START\s*(.*?)\s*DATA_END", res_text, re.DOTALL).group(1))
                if data["ACCION"] in ["GUARDAR_AUTO", "ACTUALIZAR_PATENTE"]:
                    guardar_o_actualizar_stock(data)
                    st.success("✅ Stock actualizado.")
                    buscar_coincidencias(data.get('Vehiculo',''))
                elif data["ACCION"] == "GUARDAR_LEED":
                    guardar_o_actualizar_leed(data)
                    st.success("✅ Leeds actualizado.")
                    if data.get("Fecha_Remind") and data["Fecha_Remind"] != "-":
                        crear_evento_calendario(f"Llamar a {data['Cliente']}", data["Fecha_Remind"])
            except: st.error("Error al procesar los datos.")

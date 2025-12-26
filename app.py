import streamlit as st
import google.generativeai as genai
from groq import Groq
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import json
import re
from datetime import datetime
import pandas as pd
import urllib.parse

# --- 📍 CONFIGURACIÓN (IDs ACTUALIZADOS) ---
SHEET_ID = "17Cn82TTSyXbipbW3zZ7cvYe6L6aDkX3EPK6xO7MTxzU"
ID_CARPETA_PADRE_DRIVE = "1ZMZQm3gRER4lzof8wCToY6IqLgivhGms" 

st.set_page_config(page_title="CRM IA", page_icon="🚗", layout="wide")

# --- CONEXIÓN ---
@st.cache_resource
def conectar():
    creds_info = dict(st.secrets["gcp_service_account"])
    creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
    creds = Credentials.from_service_account_info(creds_info, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
    gc = gspread.authorize(creds)
    drive = build('drive', 'v3', credentials=creds)
    return gc.open_by_key(SHEET_ID).worksheet("Stock"), gc.open_by_key(SHEET_ID).worksheet("Leeds"), drive

ws_stock, ws_leeds, drive_service = conectar()

# --- INTERFAZ ---
st.title("CRM IA")
tab1, tab2, tab3 = st.tabs(["💬 Chat", "📦 Stock", "👥 Leeds"])

if "messages" not in st.session_state: st.session_state.messages = []

with tab1:
    # 1. PRIMERO MOSTRAMOS LOS MENSAJES (Para que el input quede abajo)
    for m in st.session_state.messages:
        with st.chat_message(m["role"]): st.markdown(m["content"])

    # 2. DESPUÉS EL INPUT
    if prompt := st.chat_input("¿Qué novedades hay?"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)

        with st.chat_message("assistant"):
            # Lógica de IA (Groq por defecto)
            client = Groq(api_key=st.secrets["GROQ_API_KEY"])
            stock_ref = str(ws_stock.get_all_records()[:15])
            instruccion = f"Hoy: {datetime.now().strftime('%Y-%m-%d')}. Stock: {stock_ref}. Responde corto. Acciones: GUARDAR_AUTO, ELIMINAR_AUTO, WHATSAPP. JSON: DATA_START {{...}} DATA_END"
            
            res = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": instruccion}, {"role": "user", "content": prompt}]
            )
            respuesta = res.choices[0].message.content
            visible = re.sub(r"DATA_START.*?DATA_END", "", respuesta, flags=re.DOTALL).strip()
            st.markdown(visible)
            st.session_state.messages.append({"role": "assistant", "content": visible})

            # Procesar acciones
            for match in re.findall(r"DATA_START\s*(.*?)\s*DATA_END", respuesta, re.DOTALL):
                data = json.loads(match)
                if data["ACCION"] == "GUARDAR_AUTO":
                    meta = {'name': f"{data['Cliente']} - {data['Vehiculo']}", 'mimeType': 'application/vnd.google-apps.folder', 'parents': [ID_CARPETA_PADRE_DRIVE]}
                    f = drive_service.files().create(body=meta, fields='webViewLink').execute()
                    ws_stock.append_row([datetime.now().strftime("%d/%m/%Y"), data['Cliente'], data['Vehiculo'], data.get('Año','-'), data.get('Km','-'), data.get('Color','-'), "-", "-", data.get('Patente','-'), f.get('webViewLink')])
                elif data["ACCION"] == "ELIMINAR_AUTO":
                    try:
                        celda = ws_stock.find(str(data['Cliente']), in_column=2)
                        if celda: ws_stock.delete_rows(celda.row)
                    except: st.error("No encontré ese registro para borrar.")
                st.toast(f"✅ {data['ACCION']} completada.")

with tab2: st.dataframe(pd.DataFrame(ws_stock.get_all_records()))
with tab3: st.dataframe(pd.DataFrame(ws_leeds.get_all_records()))

import streamlit as st
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import json
import re
from datetime import datetime
import pandas as pd
import urllib.parse

# --- CONFIGURACIÓN ---
SHEET_ID = "17Cn82TTSyXbipbW3zZ7cvYe6L6aDkX3EPK6xO7MTxzU"
MI_EMAIL_CALENDARIO = "gabrielromero900@gmail.com"

st.set_page_config(page_title="CRM-IA: MyCar Centro", page_icon="🚗", layout="wide")

if "messages" not in st.session_state:
    st.session_state.messages = []

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
        return sheet.worksheet("Stock"), sheet.worksheet("Leeds"), cal_service
    except Exception as e:
        st.error(f"Error de conexión: {e}")
        return None, None, None

ws_stock, ws_leeds, calendar_service = conectar()

if ws_stock is None:
    st.stop()

# --- IA: GEMINI 3 FLASH PREVIEW ---
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel('models/gemini-3-flash-preview')

# --- FUNCIONES DE BASE DE DATOS ---
def guardar_o_actualizar_stock(data):
    hoy = datetime.now().strftime("%d/%m/%Y")
    try:
        # Busca por Cliente o Patente para actualizar
        celda = ws_stock.find(data.get('Cliente', '---'), in_column=2)
        fila = celda.row
        ws_stock.update(range_name=f"C{fila}:F{fila}", values=[[data.get('Vehiculo','-'), data.get('Año','-'), data.get('KM','-'), data.get('Color','-')]])
        if data.get('Patente'): ws_stock.update_cell(fila, 9, data['Patente'])
        return "Actualizado"
    except:
        ws_stock.append_row([hoy, data.get('Cliente','-'), data.get('Vehiculo','-'), data.get('Año','-'), data.get('KM','-'), data.get('Color','-'), "-", "-", data.get('Patente','-'), "-"])
        return "Nuevo"

def guardar_o_actualizar_leed(data):
    hoy = datetime.now().strftime("%d/%m/%Y")
    try:
        celda = ws_leeds.find(data.get('Cliente', '---'), in_column=2)
        fila = celda.row
        ws_leeds.update(range_name=f"A{fila}:F{fila}", values=[[hoy, data['Cliente'], data.get('Busca','-'), data.get('Telefono','-'), data.get('Nota','-'), data.get('Fecha_Remind','-')]])
    except:
        ws_leeds.append_row([hoy, data.get('Cliente','-'), data.get('Busca','-'), data.get('Telefono','-'), data.get('Nota','-'), data.get('Fecha_Remind','-')])

def crear_evento_calendario(resumen, fecha_iso):
    try:
        event = {'summary': resumen, 'start': {'date': fecha_iso, 'timeZone': 'America/Argentina/Buenos_Aires'}, 'end': {'date': fecha_iso, 'timeZone': 'America/Argentina/Buenos_Aires'}}
        calendar_service.events().insert(calendarId=MI_EMAIL_CALENDARIO, body=event).execute()
        return True
    except: return False

# --- INTERFAZ ---
st.title("🤖 CRM-IA: MyCar Centro")

c1, c2 = st.columns(2)
with c1: 
    if st.button("📊 Ver Stock"): st.dataframe(pd.DataFrame(ws_stock.get_all_records()))
with c2: 
    if st.button("👥 Ver Leeds"): st.dataframe(pd.DataFrame(ws_leeds.get_all_records()))

archivo = st.file_uploader("📷 PDF de Stock o Foto de Patente", type=["pdf", "jpg", "png", "jpeg"])

for message in st.session_state.messages:
    with st.chat_message(message["role"]): st.markdown(message["content"])

if prompt := st.chat_input("¿Qué novedades hay?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    with st.chat_message("assistant"):
        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        contexto_stock = ws_stock.get_all_records()[:15]
        contexto_leeds = ws_leeds.get_all_records()[:15]
        
        instruccion = f"""
        Hoy es {fecha_hoy}. Eres el gestor de MyCar. Responde DIRECTO y CONCISO.
        STOCK ACTUAL: {contexto_stock}
        LEEDS ACTUALES: {contexto_leeds}

        ACCIONES POSIBLES:
        1. PDF/FOTO con lista de autos: Extraer todos y usar GUARDAR_AUTO para cada uno.
        2. Alguien consulta stock: Responder basado en la lista.
        3. Alguien busca comprar: GUARDAR_LEED.
        4. Pedir mensaje de WhatsApp: Generar texto y usar ACCION: "WHATSAPP".

        FORMATO JSON OBLIGATORIO:
        DATA_START {{"ACCION": "GUARDAR_AUTO/GUARDAR_LEED/WHATSAPP/CONSULTA", "Cliente": "...", "Vehiculo": "...", "Patente": "...", "Año": "...", "KM": "...", "Color": "...", "Busca": "...", "Telefono": "...", "Fecha_Remind": "YYYY-MM-DD", "Mensaje": "..."}} DATA_END
        """
        
        contenidos = [instruccion, prompt]
        if archivo:
            contenidos.append({"mime_type": archivo.type, "data": archivo.getvalue()})
            
        try:
            response = model.generate_content(contenidos)
            res_text = response.text
            respuesta_visible = re.sub(r"DATA_START.*?DATA_END", "", res_text, flags=re.DOTALL).strip()
            st.markdown(respuesta_visible)
            st.session_state.messages.append({"role": "assistant", "content": respuesta_visible})

            # Procesar JSON de respuesta
            matches = re.findall(r"DATA_START\s*(.*?)\s*DATA_END", res_text, re.DOTALL)
            for m in matches:
                data = json.loads(m)
                if data["ACCION"] == "GUARDAR_AUTO":
                    guardar_o_actualizar_stock(data)
                    st.success(f"✅ {data.get('Vehiculo')} registrado.")
                elif data["ACCION"] == "GUARDAR_LEED":
                    guardar_o_actualizar_leed(data)
                    if data.get("Fecha_Remind") and data["Fecha_Remind"] != "-":
                        crear_evento_calendario(f"Llamar a {data['Cliente']}", data["Fecha_Remind"])
                    st.success(f"✅ Lead {data['Cliente']} guardado.")
                elif data["ACCION"] == "WHATSAPP":
                    if data.get("Telefono") and data["Telefono"] != "-":
                        txt = urllib.parse.quote(data["Mensaje"])
                        link = f"https://wa.me/{data['Telefono']}?text={txt}"
                        st.link_button("📲 Enviar WhatsApp", link)
            
        except Exception as e:
            st.error(f"Error: {e}")

import streamlit as st
import google.generativeai as genai
from groq import Groq
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import json
import re
from datetime import datetime, timedelta
import pandas as pd
import urllib.parse
import time

# --- 📍 CONFIGURACIÓN ACTUALIZADA (26/12/2025) ---
SHEET_ID = "17Cn82TTSyXbipbW3zZ7cvYe6L6aDkX3EPK6xO7MTxzU"
ID_CARPETA_PADRE_DRIVE = "1ZMZQm3gRER4lzof8wCToY6IqLgivhGms" 
MI_EMAIL_CALENDARIO = "gabrielromero900@gmail.com"

# Título de la página actualizado a pedido del usuario
st.set_page_config(page_title="CRM IA", page_icon="🚗", layout="wide")

# --- CONTROL DE CUOTA ---
if "uso_ia" not in st.session_state: st.session_state.uso_ia = []
if "messages" not in st.session_state: st.session_state.messages = []

def contar_mensajes():
    ahora = datetime.now()
    st.session_state.uso_ia = [t for t in st.session_state.uso_ia if ahora - t < timedelta(seconds=60)]
    return len(st.session_state.uso_ia)

# --- CONEXIÓN A GOOGLE ---
@st.cache_resource
def conectar():
    SCOPE = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/calendar"]
    try:
        creds_info = dict(st.secrets["gcp_service_account"])
        creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPE)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
        drive = build('drive', 'v3', credentials=creds)
        cal = build('calendar', 'v3', credentials=creds)
        return sh.worksheet("Stock"), sh.worksheet("Leeds"), drive, cal
    except Exception as e:
        st.error(f"Error de conexión: {e}")
        return None, None, None, None

ws_stock, ws_leeds, drive_service, cal_service = conectar()
if ws_stock is None: st.stop()

# --- BARRA LATERAL ---
with st.sidebar:
    st.header("⚙️ Ajustes")
    motor_ia = st.selectbox("Motor de IA", ["Gemini 3 Flash", "Groq (Llama 3.3)"], index=0)
    mensajes = contar_mensajes()
    st.metric("Mensajes/min (IA)", f"{mensajes} / 20")
    if mensajes >= 18: st.warning("⚠️ Límite cerca. Considera cambiar a Groq.")
    st.divider()
    if st.button("🗑️ Limpiar Historial"):
        st.session_state.messages = []
        st.rerun()

# --- FUNCIONES DE IA ---
def llamar_ia(instruccion, prompt_user, archivo=None):
    if motor_ia == "Gemini 3 Flash":
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        model = genai.GenerativeModel('models/gemini-3-flash-preview')
        inputs = [instruccion, prompt_user]
        if archivo: inputs.append({"mime_type": archivo.type, "data": archivo.getvalue()})
        res = model.generate_content(inputs)
        return res.text
    else:
        client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        res = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": instruccion}, {"role": "user", "content": prompt_user}]
        )
        return res.choices[0].message.content

# --- INTERFAZ PRINCIPAL ---
st.title("CRM IA") # Título simplificado
tab1, tab2, tab3 = st.tabs(["💬 Chat Multimodal", "📦 Stock", "👥 Leeds"])

with tab1:
    archivo = st.file_uploader("🎤 Audio, 📄 PDF, 📷 Foto o 🎬 Video", type=["pdf", "jpg", "png", "jpeg", "m4a", "wav", "mp3", "mp4", "mov"])
    
    for m in st.session_state.messages:
        with st.chat_message(m["role"]): st.markdown(m["content"])

    if prompt := st.chat_input("¿Qué novedades hay?"):
        st.session_state.uso_ia.append(datetime.now())
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)

        with st.chat_message("assistant"):
            try:
                stock_ref = str(ws_stock.get_all_records()[:15])
                instruccion = f"""Hoy: {datetime.now().strftime('%Y-%m-%d')}. Eres el gestor experto de MyCar Centro. 
                SOPORTE: Analiza fotos, audios y VIDEOS (estado del motor, chapa).
                STOCK ACTUAL: {stock_ref}. Responde CORTO.
                ACCIONES: GUARDAR_AUTO, ELIMINAR_AUTO, GUARDAR_LEED, WHATSAPP, PRESUPUESTO.
                JSON: DATA_START {{"ACCION": "...", "Cliente": "...", "Vehiculo": "...", "Telefono": "...", "Mensaje": "...", "Presupuesto": "..."}} DATA_END"""
                
                respuesta = llamar_ia(instruccion, prompt, archivo)
                visible = re.sub(r"DATA_START.*?DATA_END", "", respuesta, flags=re.DOTALL).strip()
                st.markdown(visible)
                st.session_state.messages.append({"role": "assistant", "content": visible})

                for match in re.findall(r"DATA_START\s*(.*?)\s*DATA_END", respuesta, re.DOTALL):
                    data = json.loads(match)
                    if data["ACCION"] == "GUARDAR_AUTO":
                        meta = {'name': f"{data['Cliente']} - {data['Vehiculo']}", 'mimeType': 'application/vnd.google-apps.folder', 'parents': [ID_CARPETA_PADRE_DRIVE]}
                        f = drive_service.files().create(body=meta, fields='webViewLink').execute()
                        ws_stock.append_row([datetime.now().strftime("%d/%m/%Y"), data['Cliente'], data['Vehiculo'], data.get('Año','-'), data.get('Km','-'), data.get('Color','-'), "-", "-", data.get('Patente','-'), f.get('webViewLink')])
                    elif data["ACCION"] == "GUARDAR_LEED":
                        ws_leeds.append_row([datetime.now().strftime("%d/%m/%Y"), data['Cliente'], data.get('Busca','-'), data.get('Telefono','-'), data.get('Nota','-'), data.get('Fecha_Remind','-')])
                    elif data["ACCION"] == "WHATSAPP":
                        st.link_button("📲 Enviar WhatsApp", f"https://wa.me/{data['Telefono']}?text={urllib.parse.quote(data['Mensaje'])}")
                    st.toast(f"✅ {data['ACCION']} completada.")
            
            except Exception as e:
                if "quota" in str(e).lower():
                    st.warning("⚠️ Límite de mensajes en Gemini. Cambia a Groq en la barra lateral.")
                else: st.error(f"Error: {e}")

with tab2:
    if st.button("🔄 Refrescar Stock"): st.rerun()
    st.dataframe(pd.DataFrame(ws_stock.get_all_records()), use_container_width=True)

with tab3:
    if st.button("🔄 Refrescar Leeds"): st.rerun()
    st.dataframe(pd.DataFrame(ws_leeds.get_all_records()), use_container_width=True)

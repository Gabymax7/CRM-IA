import streamlit as st
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import json
import re
from datetime import datetime, timedelta
import pandas as pd
import plotly.express as px
import urllib.parse
import time

# --- CONFIGURACIÓN ---
SHEET_ID = "17Cn82TTSyXbipbW3zZ7cvYe6L6aDkX3EPK6xO7MTxzU"
ID_CARPETA_PADRE_DRIVE = "1XS4-h6-VpY_P-C3t_L-X4r8F6O-9-C-y"
MI_EMAIL_CALENDARIO = "gabrielromero900@gmail.com"

st.set_page_config(page_title="CRM MyCar PRO", page_icon="🚗", layout="wide")

# --- CONEXIÓN ---
@st.cache_resource
def conectar_servicios():
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

ws_stock, ws_leeds, drive_service, cal_service = conectar_servicios()

# --- IA CON REINTENTO AUTOMÁTICO ---
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel('models/gemini-3-flash-preview')

def consultar_ia(contenidos):
    for intento in range(3): # Reintenta 3 veces si hay error de cuota
        try:
            return model.generate_content(contenidos)
        except Exception as e:
            if "quota" in str(e).lower() and intento < 2:
                time.sleep(2) # Espera corta antes de reintentar
                continue
            raise e

# --- FUNCIONES PRO ---
def crear_carpeta(nombre):
    try:
        meta = {'name': nombre, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [ID_CARPETA_PADRE_DRIVE]}
        f = drive_service.files().create(body=meta, fields='id, webViewLink').execute()
        return f.get('webViewLink')
    except: return "-"

def eliminar_fila(hoja, nombre):
    try:
        celda = hoja.find(str(nombre), in_column=2)
        hoja.delete_rows(celda.row)
        return True
    except: return False

# --- UI: BARRA LATERAL (ESTADÍSTICAS) ---
with st.sidebar:
    st.title("📊 MyCar Analytics")
    try:
        df_s = pd.DataFrame(ws_stock.get_all_records())
        if not df_s.empty:
            st.metric("Total Stock", len(df_s))
            fig = px.pie(df_s, names='Vehiculo', title="Distribución de Modelos", hole=0.4)
            fig.update_layout(showlegend=False, margin=dict(t=30, b=0, l=0, r=0))
            st.plotly_chart(fig, use_container_width=True)
    except: st.write("Carga datos para ver estadísticas.")
    
    st.divider()
    if st.button("🗑️ Limpiar Chat"):
        st.session_state.messages = []
        st.rerun()

# --- INTERFAZ PRINCIPAL ---
st.title("🤖 CRM-IA: MyCar Centro")

tab1, tab2, tab3 = st.tabs(["💬 Chat & Comandos", "📦 Inventario", "👥 Leeds"])

with tab1:
    # Soporta Foto, PDF y Audio (Dictado por voz)
    archivo = st.file_uploader("🎤 Dictado, 📄 PDF o 📷 Foto", type=["pdf", "jpg", "png", "m4a", "wav", "mp3"])
    
    if "messages" not in st.session_state: st.session_state.messages = []
    for m in st.session_state.messages:
        with st.chat_message(m["role"]): st.markdown(m["content"])

    if prompt := st.chat_input("¿Qué hacemos hoy?"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)

        with st.chat_message("assistant"):
            try:
                # Contexto dinámico para búsqueda inteligente
                stock_txt = str(ws_stock.get_all_records()[:20])
                instruccion = f"""Hoy: {datetime.now().strftime('%Y-%m-%d')}. Eres gestor de MyCar Centro. 
                REGLA: Responde CORTO. Usa el STOCK REAL para buscar: {stock_txt}.
                Si te piden borrar, usar ELIMINAR_AUTO o ELIMINAR_LEED.
                JSON: DATA_START {{"ACCION": "...", "Cliente": "...", "Vehiculo": "...", "Telefono": "...", "Fecha_Remind": "YYYY-MM-DD", "Mensaje": "..."}} DATA_END"""
                
                inputs = [instruccion, prompt]
                if archivo: inputs.append({"mime_type": archivo.type, "data": archivo.getvalue()})
                
                res = consultar_ia(inputs)
                txt = res.text
                visible = re.sub(r"DATA_START.*?DATA_END", "", txt, flags=re.DOTALL).strip()
                st.markdown(visible)
                st.session_state.messages.append({"role": "assistant", "content": visible})

                for m in re.findall(r"DATA_START\s*(.*?)\s*DATA_END", txt, re.DOTALL):
                    data = json.loads(m)
                    if data["ACCION"] == "GUARDAR_AUTO":
                        link = crear_carpeta(f"{data['Cliente']} - {data['Vehiculo']}")
                        ws_stock.append_row([datetime.now().strftime("%d/%m/%Y"), data['Cliente'], data['Vehiculo'], data.get('Año','-'), data.get('KM','-'), data.get('Color','-'), "-", "-", data.get('Patente','-'), link])
                    elif data["ACCION"] == "ELIMINAR_AUTO": eliminar_fila(ws_stock, data['Cliente'])
                    elif data["ACCION"] == "WHATSAPP":
                        st.link_button("📲 Enviar WhatsApp", f"https://wa.me/{data['Telefono']}?text={urllib.parse.quote(data['Mensaje'])}")
                    st.toast(f"✅ Acción {data['ACCION']} completada.")
            except Exception as e:
                st.error(f"Error: {e}")

with tab2:
    if st.button("🔄 Refrescar Stock"): st.rerun()
    st.dataframe(pd.DataFrame(ws_stock.get_all_records()), use_container_width=True)

with tab3:
    st.dataframe(pd.DataFrame(ws_leeds.get_all_records()), use_container_width=True)

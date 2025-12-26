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
import time

# --- 📍 CONFIGURACIÓN ---
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

# --- HELPER: BUSCADOR FLEXIBLE ---
def encontrar_fila_flexible(hoja, texto_busqueda):
    try:
        registros = hoja.get_all_records()
        texto_busqueda = str(texto_busqueda).lower().strip()
        for i, row in enumerate(registros, start=2):
            cliente_en_excel = str(row.get('Cliente', '')).lower().strip()
            if texto_busqueda in cliente_en_excel:
                return i
        return None
    except: return None

# --- CEREBRO IA (MODO OBEDIENTE) ---
def consultar_ia(prompt_usuario, archivo=None):
    # Datos frescos
    stock_txt = str(ws_stock.get_all_records())
    leeds_txt = str(ws_leeds.get_all_records())
    
    instruccion_sistema = f"""
    ERES UN ROBOT EJECUTOR DE MYCAR. NO PIENSES, SOLO ACTÚA.
    
    DATOS REALES:
    STOCK: {stock_txt}
    LEEDS: {leeds_txt}
    
    REGLAS ESTRICTAS:
    1. Si el usuario confirma una acción (ej: "sí", "hazlo", "a ambos"), NO EXPLIQUES NADA. SOLO GENERA EL JSON.
    2. Si te piden borrar y el nombre existe, GENERA EL JSON DE INMEDIATO.
    3. NO RESUMAS la situación.
    
    FORMATO JSON OBLIGATORIO (Único output permitido para acciones):
    DATA_START {{"ACCION": "...", "Cliente": "...", "Vehiculo": "...", "Telefono": "..."}} DATA_END
    
    ACCIONES: GUARDAR_AUTO, ELIMINAR_AUTO, ELIMINAR_LEED, WHATSAPP.
    """

    if archivo:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        model = genai.GenerativeModel('models/gemini-3-flash-preview')
        inputs = [instruccion_sistema, prompt_usuario, {"mime_type": archivo.type, "data": archivo.getvalue()}]
        res = model.generate_content(inputs)
        return res.text
    else:
        client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        # Enviamos historial para que recuerde el contexto "anterior"
        mensajes_api = [{"role": "system", "content": instruccion_sistema}]
        for m in st.session_state.messages[-5:]: # Últimos 5 mensajes
            mensajes_api.append({"role": m["role"], "content": m["content"]})
        mensajes_api.append({"role": "user", "content": prompt_usuario})

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=mensajes_api,
            temperature=0 # CERO creatividad para que sea obediente
        )
        return completion.choices[0].message.content

# --- INTERFAZ ---
st.title("CRM IA")
tab1, tab2, tab3 = st.tabs(["💬 Chat", "📦 Stock", "👥 Leeds"])

if "messages" not in st.session_state: st.session_state.messages = []

with tab1:
    # 1. CARGADOR ARRIBA
    archivo = st.file_uploader("📷 Adjuntar", type=["pdf", "jpg", "png", "mp4"])

    # 2. HISTORIAL DE MENSAJES (ESTO TIENE QUE IR ANTES DEL INPUT PARA QUE EL INPUT QUEDE ABAJO)
    container_chat = st.container()
    with container_chat:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])

    # 3. INPUT DE TEXTO (AL FINAL DEL CODIGO VISUAL)
    if prompt := st.chat_input("Escribe una orden..."):
        # Mostrar mensaje usuario
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Procesando..."):
                try:
                    respuesta = consultar_ia(prompt, archivo)
                    
                    # Ocultar el JSON sucio y mostrar solo texto limpio
                    texto_visible = re.sub(r"DATA_START.*?DATA_END", "", respuesta, flags=re.DOTALL).strip()
                    if texto_visible:
                        st.markdown(texto_visible)
                        st.session_state.messages.append({"role": "assistant", "content": texto_visible})

                    # Ejecutar acciones silenciosamente
                    accion_realizada = False
                    for match in re.findall(r"DATA_START\s*(.*?)\s*DATA_END", respuesta, re.DOTALL):
                        data = json.loads(match)
                        
                        if data["ACCION"] == "GUARDAR_AUTO":
                            meta = {'name': f"{data['Cliente']} - {data['Vehiculo']}", 'mimeType': 'application/vnd.google-apps.folder', 'parents': [ID_CARPETA_PADRE_DRIVE]}
                            f = drive_service.files().create(body=meta, fields='webViewLink').execute()
                            ws_stock.append_row([datetime.now().strftime("%d/%m/%Y"), data['Cliente'], data['Vehiculo'], data.get('Año','-'), data.get('Km','-'), data.get('Color','-'), "-", "-", data.get('Patente','-'), f.get('webViewLink')])
                            st.toast(f"✅ Guardado: {data['Vehiculo']}")
                            accion_realizada = True

                        elif data["ACCION"] == "ELIMINAR_AUTO":
                            fila = encontrar_fila_flexible(ws_stock, data['Cliente'])
                            if fila:
                                ws_stock.delete_rows(fila)
                                st.success(f"🗑️ Eliminado del Stock: {data['Cliente']}")
                                accion_realizada = True
                            else: st.error("No encontré ese cliente.")

                        elif data["ACCION"] == "ELIMINAR_LEED":
                            fila = encontrar_fila_flexible(ws_leeds, data['Cliente'])
                            if fila:
                                ws_leeds.delete_rows(fila)
                                st.success(f"🗑️ Leed eliminado: {data['Cliente']}")
                                accion_realizada = True
                        
                        elif data["ACCION"] == "WHATSAPP":
                             link = f"https://wa.me/{data.get('Telefono','')}?text={urllib.parse.quote(data.get('Mensaje',''))}"
                             st.link_button(f"📲 WhatsApp a {data['Cliente']}", link)
                             accion_realizada = True

                    if accion_realizada:
                        time.sleep(1)
                        st.rerun()

                except Exception as e:
                    st.error(f"Error: {e}")

with tab2:
    if st.button("🔄 Refrescar Stock"): st.rerun()
    st.dataframe(pd.DataFrame(ws_stock.get_all_records()))

with tab3:
    st.dataframe(pd.DataFrame(ws_leeds.get_all_records()))

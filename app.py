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

# --- LÓGICA DE IA HÍBRIDA ---
def consultar_ia(prompt, archivo=None):
    # Contexto global: Lee Stock y Leeds
    stock_txt = str(ws_stock.get_all_records()[:20]) 
    leeds_txt = str(ws_leeds.get_all_records()[:20])
    
    instruccion = f"""
    Hoy: {datetime.now().strftime('%Y-%m-%d')}. Eres el gestor de MyCar.
    DATOS REALES:
    - STOCK: {stock_txt}
    - LEEDS: {leeds_txt}
    
    TUS CAPACIDADES:
    1. Si piden guardar auto -> JSON ACCION: "GUARDAR_AUTO"
    2. Si piden guardar leed -> JSON ACCION: "GUARDAR_LEED"
    3. Si piden borrar -> JSON ACCION: "ELIMINAR_AUTO" o "ELIMINAR_LEED"
    4. Si hay que contactar -> JSON ACCION: "WHATSAPP" (Genera el mensaje)
    
    FORMATO JSON OBLIGATORIO:
    DATA_START {{"ACCION": "...", "Cliente": "...", "Vehiculo": "...", "Telefono": "...", "Mensaje": "..."}} DATA_END
    """

    # 1. Si hay archivo, OBLIGATORIAMENTE usamos Gemini (Groq no ve archivos)
    if archivo:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        model = genai.GenerativeModel('models/gemini-3-flash-preview')
        inputs = [instruccion, prompt, {"mime_type": archivo.type, "data": archivo.getvalue()}]
        res = model.generate_content(inputs)
        return res.text

    # 2. Si es solo texto, usamos Groq (Más rápido y sin limite de 60s)
    else:
        client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": instruccion}, {"role": "user", "content": prompt}]
        )
        return completion.choices[0].message.content

# --- INTERFAZ ---
st.title("CRM IA")
tab1, tab2, tab3 = st.tabs(["💬 Chat", "📦 Stock", "👥 Leeds"])

if "messages" not in st.session_state: st.session_state.messages = []

with tab1:
    # A. Cargador de Archivos (Vuelve la vista!)
    archivo = st.file_uploader("📷 Foto, PDF o Audio (Activa Gemini automáticamente)", type=["pdf", "jpg", "png", "jpeg", "mp4", "m4a", "mp3"])

    # B. Historial de Chat
    for m in st.session_state.messages:
        with st.chat_message(m["role"]): st.markdown(m["content"])

    # C. Input de Usuario
    if prompt := st.chat_input("Escribe tu orden..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)

        with st.chat_message("assistant"):
            try:
                # Llamada inteligente (Elige motor según si hay archivo o no)
                respuesta_completa = consultar_ia(prompt, archivo)
                
                # Limpiar JSON para mostrar solo texto al usuario
                texto_visible = re.sub(r"DATA_START.*?DATA_END", "", respuesta_completa, flags=re.DOTALL).strip()
                st.markdown(texto_visible)
                st.session_state.messages.append({"role": "assistant", "content": texto_visible})

                # Ejecutar Acciones (El cerebro del CRM)
                for match in re.findall(r"DATA_START\s*(.*?)\s*DATA_END", respuesta_completa, re.DOTALL):
                    data = json.loads(match)
                    
                    if data["ACCION"] == "GUARDAR_AUTO":
                        # Crear carpeta + Link
                        meta = {'name': f"{data['Cliente']} - {data['Vehiculo']}", 'mimeType': 'application/vnd.google-apps.folder', 'parents': [ID_CARPETA_PADRE_DRIVE]}
                        f = drive_service.files().create(body=meta, fields='webViewLink').execute()
                        # Guardar en Sheet
                        ws_stock.append_row([datetime.now().strftime("%d/%m/%Y"), data['Cliente'], data['Vehiculo'], data.get('Año','-'), data.get('Km','-'), data.get('Color','-'), "-", "-", data.get('Patente','-'), f.get('webViewLink')])
                        st.toast(f"✅ Auto guardado: {data['Vehiculo']}")
                    
                    elif data["ACCION"] == "GUARDAR_LEED":
                        ws_leeds.append_row([datetime.now().strftime("%d/%m/%Y"), data['Cliente'], data.get('Busca','-'), data.get('Telefono','-'), data.get('Nota','-')])
                        st.toast(f"✅ Leed guardado: {data['Cliente']}")

                    elif data["ACCION"] == "ELIMINAR_AUTO":
                        celda = ws_stock.find(str(data['Cliente']), in_column=2)
                        if celda: 
                            ws_stock.delete_rows(celda.row)
                            st.toast("🗑️ Auto eliminado")
                        else: st.warning("No encontré ese cliente en Stock.")

                    elif data["ACCION"] == "ELIMINAR_LEED":
                        celda = ws_leeds.find(str(data['Cliente']), in_column=2) # Busca en columna 2 (Nombre)
                        if celda:
                            ws_leeds.delete_rows(celda.row)
                            st.toast("🗑️ Leed eliminado")

                    elif data["ACCION"] == "WHATSAPP":
                        # Botón Mágico recuperado
                        link_wa = f"https://wa.me/{data['Telefono']}?text={urllib.parse.quote(data['Mensaje'])}"
                        st.link_button(f"📲 Enviar a {data['Cliente']}", link_wa)

            except Exception as e:
                st.error(f"Ocurrió un error técnico: {e}")

with tab2:
    if st.button("🔄 Actualizar Stock"): st.rerun()
    st.dataframe(pd.DataFrame(ws_stock.get_all_records()))

with tab3:
    if st.button("🔄 Actualizar Leeds"): st.rerun()
    st.dataframe(pd.DataFrame(ws_leeds.get_all_records()))

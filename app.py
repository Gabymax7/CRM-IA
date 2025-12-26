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

# --- LÓGICA DE IA CON MEMORIA ---
def consultar_ia_con_memoria(prompt_usuario, archivo=None):
    # 1. Preparar datos frescos
    stock_txt = str(ws_stock.get_all_records())
    leeds_txt = str(ws_leeds.get_all_records())
    
    instruccion_sistema = f"""
    Hoy: {datetime.now().strftime('%Y-%m-%d')}. Eres el gestor EJECUTIVO de MyCar.
    DATOS ACTUALES (NO INVENTES NADA QUE NO ESTÉ AQUÍ):
    - STOCK: {stock_txt}
    - LEEDS: {leeds_txt}
    
    TU OBJETIVO: Ejecutar órdenes. No dudes tanto.
    - Si te dicen "borra a Roberto", y hay un Roberto, GENERA EL JSON DE ELIMINAR.
    - Si hay ambigüedad, pregunta corto.
    - Si el usuario confirma ("sí, hazlo"), EJECUTA.
    
    FORMATO JSON OBLIGATORIO PARA ACCIONES:
    DATA_START {{"ACCION": "...", "Cliente": "...", "Vehiculo": "..."}} DATA_END
    
    ACCIONES VÁLIDAS: GUARDAR_AUTO, GUARDAR_LEED, ELIMINAR_AUTO, ELIMINAR_LEED, WHATSAPP.
    """

    # 2. Si hay archivo -> Usar GEMINI (Sin memoria larga, solo análisis visual)
    if archivo:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        model = genai.GenerativeModel('models/gemini-3-flash-preview')
        inputs = [instruccion_sistema, prompt_usuario, {"mime_type": archivo.type, "data": archivo.getvalue()}]
        res = model.generate_content(inputs)
        return res.text

    # 3. Si es texto -> Usar GROQ CON MEMORIA
    else:
        client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        
        # Construir historial para enviarle a la IA (Sistema + Últimos 6 mensajes + Actual)
        mensajes_api = [{"role": "system", "content": instruccion_sistema}]
        
        # Agregamos los últimos mensajes del chat real para que tenga contexto
        historial_reciente = st.session_state.messages[-6:] # Toma los últimos 6
        for m in historial_reciente:
            mensajes_api.append({"role": m["role"], "content": m["content"]})
            
        # Agregamos el prompt actual
        mensajes_api.append({"role": "user", "content": prompt_usuario})

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=mensajes_api,
            temperature=0.3 # Más bajo = Más preciso y menos alucinación
        )
        return completion.choices[0].message.content

# --- INTERFAZ ---
st.title("CRM IA")
tab1, tab2, tab3 = st.tabs(["💬 Chat", "📦 Stock", "👥 Leeds"])

if "messages" not in st.session_state: st.session_state.messages = []

with tab1:
    archivo = st.file_uploader("📷 Adjuntar (Activa Gemini)", type=["pdf", "jpg", "png", "mp4", "m4a"])

    # 1. MOSTRAR HISTORIAL
    for m in st.session_state.messages:
        with st.chat_message(m["role"]): st.markdown(m["content"])

    # 2. CAPTURAR INPUT
    if prompt := st.chat_input("Escribe una orden..."):
        # Guardar mensaje usuario
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Procesando..."):
                try:
                    respuesta_full = consultar_ia_con_memoria(prompt, archivo)
                    
                    # Limpiar y mostrar texto
                    texto_visible = re.sub(r"DATA_START.*?DATA_END", "", respuesta_full, flags=re.DOTALL).strip()
                    if texto_visible:
                        st.markdown(texto_visible)
                        st.session_state.messages.append({"role": "assistant", "content": texto_visible})

                    # Ejecutar Acciones
                    accion_realizada = False
                    for match in re.findall(r"DATA_START\s*(.*?)\s*DATA_END", respuesta_full, re.DOTALL):
                        data = json.loads(match)
                        
                        if data["ACCION"] == "GUARDAR_AUTO":
                            meta = {'name': f"{data['Cliente']} - {data['Vehiculo']}", 'mimeType': 'application/vnd.google-apps.folder', 'parents': [ID_CARPETA_PADRE_DRIVE]}
                            f = drive_service.files().create(body=meta, fields='webViewLink').execute()
                            ws_stock.append_row([datetime.now().strftime("%d/%m/%Y"), data['Cliente'], data['Vehiculo'], data.get('Año','-'), data.get('Km','-'), data.get('Color','-'), "-", "-", data.get('Patente','-'), f.get('webViewLink')])
                            st.toast(f"✅ Auto guardado: {data['Vehiculo']}")
                            accion_realizada = True

                        elif data["ACCION"] == "ELIMINAR_AUTO":
                            # Busca coincidencias parciales si es necesario
                            celda = None
                            try:
                                celda = ws_stock.find(str(data['Cliente']), in_column=2)
                            except: pass
                            
                            if celda:
                                ws_stock.delete_rows(celda.row)
                                st.success(f"🗑️ Eliminado: {data['Cliente']}")
                                accion_realizada = True
                            else:
                                st.error(f"No encontré a {data['Cliente']} en la lista exacta.")

                        elif data["ACCION"] == "WHATSAPP":
                            link = f"https://wa.me/{data.get('Telefono','')}?text={urllib.parse.quote(data.get('Mensaje',''))}"
                            st.link_button(f"📲 WhatsApp a {data['Cliente']}", link)
                            accion_realizada = True

                    # 3. REFRESCAR LA PAGINA SI HUBO ACCION (Vital para borrar el input y actualizar historial)
                    if accion_realizada:
                        time.sleep(1) # Pequeña pausa para ver el toast
                        st.rerun()
                        
                except Exception as e:
                    st.error(f"Error: {e}")
        
        # Si no hubo acción de datos pero sí respuesta de texto, también refrescamos para ordenar el chat
        st.rerun()

with tab2:
    if st.button("🔄 Refrescar Stock"): st.rerun()
    st.dataframe(pd.DataFrame(ws_stock.get_all_records()))

with tab3:
    st.dataframe(pd.DataFrame(ws_leeds.get_all_records()))

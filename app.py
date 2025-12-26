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

# --- 📍 CONFIGURACIÓN (IDs REVISADOS) ---
SHEET_ID = "17Cn82TTSyXbipbW3zZ7cvYe6L6aDkX3EPK6xO7MTxzU"
# Este es el ID NUEVO que me pasaste. Asegúrate que en tu archivo quede ESTE y no el viejo.
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
        # Mapeo especial para números (ej: "borra el 1")
        if texto_busqueda.isdigit():
            idx = int(texto_busqueda) - 1
            if 0 <= idx < len(registros):
                return idx + 2 # +2 porque sheets empieza en 1 y tiene header
        
        # Búsqueda por texto
        for i, row in enumerate(registros, start=2):
            # Buscamos en todas las columnas por si acaso
            fila_texto = " ".join([str(v).lower() for v in row.values()])
            if texto_busqueda in fila_texto:
                return i
        return None
    except: return None

# --- CEREBRO IA (GROQ + GEMINI) ---
def consultar_ia(prompt_usuario, archivo=None):
    # Leemos datos para dárselos a la IA
    try:
        stock_raw = ws_stock.get_all_records()
        leeds_raw = ws_leeds.get_all_records()
        # Convertimos a texto simple para que la IA lo entienda mejor
        stock_txt = "\n".join([f"{i+1}. {r['Cliente']} - {r['Vehiculo']} ({r.get('Año','')})" for i, r in enumerate(stock_raw)])
        leeds_txt = "\n".join([f"{i+1}. {r['Cliente']} busca {r['Busca']}" for i, r in enumerate(leeds_raw)])
    except:
        stock_txt = "Sin datos"
        leeds_txt = "Sin datos"
    
    instruccion_sistema = f"""
    ERES EL GESTOR DE LA AGENCIA MYCAR.
    
    DATOS ACTUALES:
    --- STOCK ---
    {stock_txt}
    --- LEEDS ---
    {leeds_txt}
    
    REGLAS DE RESPUESTA:
    1. Si te preguntan "¿qué hay?", RESPONDE CON UNA LISTA LIMPIA (No uses JSON ni corchetes). Usa viñetas.
    2. Si te dicen "borra el 1" o "borra a Juan", genera el JSON correspondiente.
    3. Si te dicen "borra todo", responde que por seguridad debe ser uno por uno.
    4. NO ALUCINES DATOS. Solo usa lo que ves arriba.
    
    FORMATO JSON PARA ACCIONES (Solo úsalo si hay una orden clara):
    DATA_START {{"ACCION": "...", "Cliente": "...", "Vehiculo": "...", "Telefono": "..."}} DATA_END
    
    ACCIONES VÁLIDAS: GUARDAR_AUTO, ELIMINAR_AUTO, GUARDAR_LEED, ELIMINAR_LEED, WHATSAPP.
    """

    if archivo:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        model = genai.GenerativeModel('models/gemini-3-flash-preview')
        inputs = [instruccion_sistema, prompt_usuario, {"mime_type": archivo.type, "data": archivo.getvalue()}]
        res = model.generate_content(inputs)
        return res.text
    else:
        client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        mensajes_api = [{"role": "system", "content": instruccion_sistema}]
        # Memoria corta (últimos 4 mensajes)
        for m in st.session_state.messages[-4:]:
            mensajes_api.append({"role": m["role"], "content": m["content"]})
        mensajes_api.append({"role": "user", "content": prompt_usuario})

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=mensajes_api,
            temperature=0 # Cero creatividad para evitar errores
        )
        return completion.choices[0].message.content

# --- INTERFAZ ---
st.title("CRM IA")
tab1, tab2, tab3 = st.tabs(["💬 Chat", "📦 Stock", "👥 Leeds"])

if "messages" not in st.session_state: st.session_state.messages = []

with tab1:
    # 1. Cargador (Arriba)
    archivo = st.file_uploader("📷 Adjuntar archivo", type=["pdf", "jpg", "png", "mp4"])

    # 2. Contenedor de Chat (Para mantener mensajes visualmente ordenados)
    chat_container = st.container()
    with chat_container:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])

    # 3. Input (Siempre abajo)
    if prompt := st.chat_input("Escribe una orden..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_container:
            with st.chat_message("user"): st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Procesando..."):
                try:
                    respuesta = consultar_ia(prompt, archivo)
                    
                    # Limpieza visual: Quitar el JSON de la vista del usuario
                    texto_visible = re.sub(r"DATA_START.*?DATA_END", "", respuesta, flags=re.DOTALL).strip()
                    if texto_visible:
                        st.markdown(texto_visible)
                        st.session_state.messages.append({"role": "assistant", "content": texto_visible})

                    # Procesador de Acciones
                    accion_realizada = False
                    for match in re.findall(r"DATA_START\s*(.*?)\s*DATA_END", respuesta, re.DOTALL):
                        data = json.loads(match)
                        
                        if data["ACCION"] == "GUARDAR_AUTO":
                            meta = {'name': f"{data['Cliente']} - {data['Vehiculo']}", 'mimeType': 'application/vnd.google-apps.folder', 'parents': [ID_CARPETA_PADRE_DRIVE]}
                            try:
                                f = drive_service.files().create(body=meta, fields='webViewLink').execute()
                                link_drive = f.get('webViewLink')
                            except: link_drive = "Error ID Drive"
                            
                            ws_stock.append_row([datetime.now().strftime("%d/%m/%Y"), data['Cliente'], data['Vehiculo'], data.get('Año','-'), data.get('Km','-'), data.get('Color','-'), "-", "-", data.get('Patente','-'), link_drive])
                            st.toast(f"✅ Guardado: {data['Vehiculo']}")
                            accion_realizada = True

                        elif data["ACCION"] == "ELIMINAR_AUTO":
                            fila = encontrar_fila_flexible(ws_stock, data['Cliente'])
                            if fila:
                                ws_stock.delete_rows(fila)
                                st.success(f"🗑️ Auto eliminado: {data['Cliente']}")
                                accion_realizada = True
                            else: st.warning(f"No encontré a '{data['Cliente']}' para borrar.")

                        elif data["ACCION"] == "ELIMINAR_LEED":
                            fila = encontrar_fila_flexible(ws_leeds, data['Cliente'])
                            if fila:
                                ws_leeds.delete_rows(fila)
                                st.success(f"🗑️ Leed eliminado: {data['Cliente']}")
                                accion_realizada = True
                            else: st.warning("No encontré ese Leed.")

                        elif data["ACCION"] == "WHATSAPP":
                            link = f"https://wa.me/{data.get('Telefono','')}?text={urllib.parse.quote(data.get('Mensaje',''))}"
                            st.link_button(f"📲 WhatsApp a {data['Cliente']}", link)
                            accion_realizada = True

                    if accion_realizada:
                        time.sleep(1)
                        st.rerun()

                except Exception as e:
                    st.error(f"Error técnico: {e}")

with tab2:
    if st.button("🔄 Refrescar Stock"): st.rerun()
    st.dataframe(pd.DataFrame(ws_stock.get_all_records()))

with tab3:
    if st.button("🔄 Refrescar Leeds"): st.rerun()
    st.dataframe(pd.DataFrame(ws_leeds.get_all_records()))

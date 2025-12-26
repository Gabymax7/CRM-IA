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
import time  # <--- Faltaba esto para que funcione el refresco

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

# --- HELPER: BUSCADOR INSENSIBLE A MAYÚSCULAS ---
def encontrar_fila_flexible(hoja, texto_busqueda):
    """Busca un texto en la columna 2 (Cliente) ignorando mayúsculas/minúsculas"""
    try:
        registros = hoja.get_all_records()
        texto_busqueda = str(texto_busqueda).lower().strip()
        
        # Iterar filas (empezando desde la fila 2 porque la 1 es header)
        for i, row in enumerate(registros, start=2):
            cliente_en_excel = str(row.get('Cliente', '')).lower().strip()
            # Coincidencia exacta o parcial fuerte
            if texto_busqueda == cliente_en_excel or texto_busqueda in cliente_en_excel:
                return i # Retorna el número de fila real en la hoja
        return None
    except:
        return None

# --- LÓGICA DE IA CON MEMORIA REFORZADA ---
def consultar_ia_con_memoria(prompt_usuario, archivo=None):
    # Obtener datos frescos
    try:
        stock_data = ws_stock.get_all_records()
        leeds_data = ws_leeds.get_all_records()
    except:
        stock_data = "Error leyendo stock"
        leeds_data = "Error leyendo leeds"
    
    instruccion_sistema = f"""
    ERES EL GESTOR DE MYCAR. TU PALABRA ES LEY, PERO SOLO SI ESTÁ EN LOS DATOS.
    
    DATOS EN TIEMPO REAL (NO INVENTES NADA QUE NO ESTÉ AQUÍ):
    --- INICIO STOCK ---
    {str(stock_data)}
    --- FIN STOCK ---
    
    --- INICIO LEEDS ---
    {str(leeds_data)}
    --- FIN LEEDS ---

    REGLAS DE ORO:
    1. Si te preguntan "¿Hay un Fiesta?", MIRA EL STOCK ARRIBA. Si no está en la lista de texto, DI QUE NO HAY. No alucines.
    2. Si el usuario dice "borra ese auto" y acabas de hablar de él, ASUME QUE EXISTE EN EL CONTEXTO y genera el JSON de eliminar.
    3. Si el usuario confirma con un "sí", EJECUTA LA ACCIÓN PENDIENTE DEL MENSAJE ANTERIOR.
    
    FORMATO JSON OBLIGATORIO PARA ACCIONES (ÚSALO SIEMPRE QUE EL USUARIO ORDENE ALGO):
    DATA_START {{"ACCION": "...", "Cliente": "...", "Vehiculo": "...", "Telefono": "..."}} DATA_END
    
    ACCIONES: GUARDAR_AUTO, GUARDAR_LEED, ELIMINAR_AUTO, ELIMINAR_LEED, WHATSAPP.
    """

    if archivo:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        model = genai.GenerativeModel('models/gemini-3-flash-preview')
        inputs = [instruccion_sistema, prompt_usuario, {"mime_type": archivo.type, "data": archivo.getvalue()}]
        res = model.generate_content(inputs)
        return res.text
    else:
        client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        # Construir historial con contexto fuerte
        mensajes_api = [{"role": "system", "content": instruccion_sistema}]
        # Incluir últimos 4 mensajes para contexto corto y preciso
        historial = st.session_state.messages[-4:] 
        for m in historial:
            mensajes_api.append({"role": m["role"], "content": m["content"]})
        mensajes_api.append({"role": "user", "content": prompt_usuario})

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=mensajes_api,
            temperature=0.1 # Bajamos temperatura a 0.1 para máxima fidelidad a los datos
        )
        return completion.choices[0].message.content

# --- INTERFAZ ---
st.title("CRM IA")
tab1, tab2, tab3 = st.tabs(["💬 Chat", "📦 Stock", "👥 Leeds"])

if "messages" not in st.session_state: st.session_state.messages = []

with tab1:
    archivo = st.file_uploader("📷 Adjuntar (Gemini)", type=["pdf", "jpg", "png", "mp4"])

    # Historial
    for m in st.session_state.messages:
        with st.chat_message(m["role"]): st.markdown(m["content"])

    # Input
    if prompt := st.chat_input("Escribe una orden..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Pensando..."):
                try:
                    respuesta = consultar_ia_con_memoria(prompt, archivo)
                    
                    texto_visible = re.sub(r"DATA_START.*?DATA_END", "", respuesta, flags=re.DOTALL).strip()
                    if texto_visible:
                        st.markdown(texto_visible)
                        st.session_state.messages.append({"role": "assistant", "content": texto_visible})

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
                            # Usamos el buscador flexible nuevo
                            fila = encontrar_fila_flexible(ws_stock, data['Cliente'])
                            if fila:
                                ws_stock.delete_rows(fila)
                                st.success(f"🗑️ Eliminado cliente: {data['Cliente']}")
                                accion_realizada = True
                            else:
                                st.error(f"⚠️ No encontré a '{data['Cliente']}' en el Stock real.")

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
                        time.sleep(1.5)
                        st.rerun()

                except Exception as e:
                    st.error(f"Error: {e}")

with tab2:
    if st.button("🔄 Refrescar Stock"): st.rerun()
    st.dataframe(pd.DataFrame(ws_stock.get_all_records()))

with tab3:
    if st.button("🔄 Refrescar Leeds"): st.rerun()
    st.dataframe(pd.DataFrame(ws_leeds.get_all_records()))

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

# --- BARRA LATERAL: SELECTOR DE IA ---
with st.sidebar:
    st.header("⚙️ Configuración")
    modo_ia = st.radio(
        "Cerebro IA:", 
        ["Automático (Recomendado)", "Forzar Gemini (Google)", "Forzar Groq (Llama)"],
        index=0,
        help="Automático usa Groq para velocidad y Gemini para archivos/respaldo."
    )
    if st.button("🗑️ Limpiar Chat"):
        st.session_state.messages = []
        st.rerun()

# --- HELPER: BUSCADOR FLEXIBLE ---
def encontrar_fila_flexible(hoja, texto_busqueda):
    try:
        registros = hoja.get_all_records()
        texto_busqueda = str(texto_busqueda).lower().strip()
        if texto_busqueda.isdigit():
            idx = int(texto_busqueda) - 1
            if 0 <= idx < len(registros): return idx + 2 
        for i, row in enumerate(registros, start=2):
            fila_texto = " ".join([str(v).lower() for v in row.values()])
            if texto_busqueda in fila_texto: return i
        return None
    except: return None

# --- HELPER: FILTRO DE VACÍOS ---
def filtrar_vacios(lista_registros):
    datos = []
    vacios = 0
    for r in lista_registros:
        contenido = "".join([str(v) for v in r.values()]).strip()
        if not contenido:
            vacios += 1
            if vacios >= 3: break
        else:
            vacios = 0
            datos.append(r)
    return datos

# --- CEREBRO IA (CON SELECTOR MANUAL) ---
def consultar_ia(prompt_usuario, archivo=None):
    # 1. Preparar Datos
    try:
        raw_stock = ws_stock.get_all_records()
        raw_leeds = ws_leeds.get_all_records()
        stock_safe = filtrar_vacios(raw_stock)
        leeds_safe = filtrar_vacios(raw_leeds)
        stock_txt = "\n".join([f"Auto {i+1}: {str(r)}" for i, r in enumerate(stock_safe)])
        leeds_txt = "\n".join([f"Leed {i+1}: {str(r)}" for i, r in enumerate(leeds_safe)])
    except: stock_txt, leeds_txt = "Error", "Error"
    
    instruccion = f"""
    ERES EL GESTOR DE MYCAR.
    DATOS:
    --- STOCK ---
    {stock_txt}
    --- LEEDS ---
    {leeds_txt}
    REGLAS:
    1. Si no hay cliente, asume "Agencia".
    2. Usa toda la info (Año, Km, etc).
    3. Responde limpio.
    JSON ACCIONES: DATA_START {{"ACCION": "...", "Cliente": "...", "Vehiculo": "...", "Año": "...", "Km": "...", "Color": "...", "Patente": "...", "Telefono": "...", "Mensaje": "..."}} DATA_END
    """

    def usar_gemini():
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        model = genai.GenerativeModel('models/gemini-2.0-flash-exp')
        inputs = [instruccion, prompt_usuario]
        if archivo: inputs.append({"mime_type": archivo.type, "data": archivo.getvalue()})
        res = model.generate_content(inputs)
        return res.text

    def usar_groq():
        client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        mensajes = [{"role": "system", "content": instruccion}]
        for m in st.session_state.messages[-4:]: 
            mensajes.append({"role": m["role"], "content": m["content"]})
        mensajes.append({"role": "user", "content": prompt_usuario})
        completion = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=mensajes, temperature=0)
        return completion.choices[0].message.content

    # 2. LÓGICA DE SELECCIÓN
    if archivo:
        return usar_gemini() # Si hay archivo, Gemini es obligatorio
    
    if modo_ia == "Forzar Gemini (Google)":
        return usar_gemini()
    
    elif modo_ia == "Forzar Groq (Llama)":
        try:
            return usar_groq()
        except Exception as e:
            st.warning(f"Groq falló ({e}). Usando Gemini de respaldo.")
            return usar_gemini()
            
    else: # Automático
        try:
            return usar_groq()
        except:
            print("Cambio automático a Gemini")
            return usar_gemini()

# --- INTERFAZ ---
if "messages" not in st.session_state: st.session_state.messages = []

tab1, tab2, tab3 = st.tabs(["💬 Chat", "📦 Stock", "👥 Leeds"])

with tab1:
    archivo = st.file_uploader("📷 Adjuntar (Usa Gemini)", type=["pdf", "jpg", "png", "mp4"])
    
    chat_container = st.container()
    with chat_container:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])
        st.write("---")
        st.write("")
        st.write("")

    if prompt := st.chat_input("Escribe una orden..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_container:
            with st.chat_message("user"): st.markdown(prompt)
            with st.chat_message("assistant"):
                with st.spinner(f"Procesando con {modo_ia.split()[0]}..."):
                    try:
                        respuesta = consultar_ia(prompt, archivo)
                        texto_visible = re.sub(r"DATA_START.*?DATA_END", "", respuesta, flags=re.DOTALL).strip()
                        if texto_visible:
                            st.markdown(texto_visible)
                            st.session_state.messages.append({"role": "assistant", "content": texto_visible})

                        for match in re.findall(r"DATA_START\s*(.*?)\s*DATA_END", respuesta, re.DOTALL):
                            data = json.loads(match)
                            if data["ACCION"] == "GUARDAR_AUTO":
                                cliente = data.get('Cliente') or "Agencia"
                                meta = {'name': f"{cliente} - {data['Vehiculo']}", 'mimeType': 'application/vnd.google-apps.folder', 'parents': [ID_CARPETA_PADRE_DRIVE]}
                                try:
                                    f = drive_service.files().create(body=meta, fields='webViewLink').execute()
                                    link = f.get('webViewLink')
                                except: link = "Error Drive"
                                ws_stock.append_row([datetime.now().strftime("%d/%m/%Y"), cliente, data['Vehiculo'], data.get('Año','-'), data.get('Km','-'), data.get('Color','-'), "-", "-", data.get('Patente','-'), link])
                                st.toast(f"✅ Guardado: {data['Vehiculo']}")
                            elif data["ACCION"] == "ELIMINAR_AUTO":
                                fila = encontrar_fila_flexible(ws_stock, data['Cliente'])
                                if fila:
                                    try:
                                        link = ws_stock.cell(fila, 10).value 
                                        if "folders/" in str(link):
                                            fid = re.search(r'folders/([a-zA-Z0-9-_]+)', str(link))
                                            if fid: drive_service.files().delete(fileId=fid.group(1)).execute()
                                    except: pass
                                    ws_stock.delete_rows(fila)
                                    st.success(f"🗑️ Eliminado: {data['Cliente']}")
                            elif data["ACCION"] == "ELIMINAR_LEED":
                                fila = encontrar_fila_flexible(ws_leeds, data['Cliente'])
                                if fila:
                                    ws_leeds.delete_rows(fila)
                                    st.success("🗑️ Leed eliminado")
                            elif data["ACCION"] == "WHATSAPP":
                                link = f"https://wa.me/{data.get('Telefono','')}?text={urllib.parse.quote(data.get('Mensaje',''))}"
                                st.link_button(f"📲 WhatsApp", link)

                    except Exception as e:
                        st.error(f"Error: {e}")
        time.sleep(0.5)
        st.rerun()

with tab2:
    if st.button("🔄 Refrescar Stock"): st.rerun()
    # PROTECCIÓN CRÍTICA: Convertimos todo a texto para evitar el error 'ArrowInvalid'
    try:
        df = pd.DataFrame(ws_stock.get_all_records()).astype(str)
        st.dataframe(df, use_container_width=True)
    except: st.info("Stock vacío o error de formato en Excel.")

with tab3:
    if st.button("🔄 Refrescar Leeds"): st.rerun()
    try:
        df = pd.DataFrame(ws_leeds.get_all_records()).astype(str)
        st.dataframe(df, use_container_width=True)
    except: st.info("Leeds vacío.")

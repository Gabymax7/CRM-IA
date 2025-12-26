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
        if texto_busqueda.isdigit():
            idx = int(texto_busqueda) - 1
            if 0 <= idx < len(registros): return idx + 2 
        for i, row in enumerate(registros, start=2):
            fila_texto = " ".join([str(v).lower() for v in row.values()])
            if texto_busqueda in fila_texto: return i
        return None
    except: return None

# --- HELPER: LIMPIEZA DE DATOS (LA IDEA DE GABRIEL) ---
def filtrar_vacios(lista_registros):
    """Corta la lectura si encuentra 3 filas vacías seguidas para ahorrar tokens."""
    datos_utiles = []
    vacios_seguidos = 0
    
    for r in lista_registros:
        # Unimos todos los valores de la fila en un solo texto para ver si hay algo escrito
        contenido = "".join([str(v) for v in r.values()]).strip()
        
        if not contenido: # Si la fila está vacía
            vacios_seguidos += 1
            if vacios_seguidos >= 3: 
                break # ¡STOP! Dejamos de leer aquí
        else:
            vacios_seguidos = 0 # Reiniciamos contador si encontramos datos
            datos_utiles.append(r)
            
    return datos_utiles

# --- CEREBRO IA (CON OPTIMIZACIÓN Y PLAN B) ---
def consultar_ia(prompt_usuario, archivo=None):
    # 1. Preparar y Filtrar datos (Ahorro masivo de memoria)
    try:
        raw_stock = ws_stock.get_all_records()
        raw_leeds = ws_leeds.get_all_records()
        
        # Aplicamos tu filtro inteligente
        stock_filtrado = filtrar_vacios(raw_stock)
        leeds_filtrado = filtrar_vacios(raw_leeds)

        stock_txt = "\n".join([f"Auto {i+1}: {str(r)}" for i, r in enumerate(stock_filtrado)])
        leeds_txt = "\n".join([f"Leed {i+1}: {str(r)}" for i, r in enumerate(leeds_filtrado)])
    except: stock_txt, leeds_txt = "Error lectura", "Error lectura"
    
    instruccion = f"""
    ERES EL GESTOR DE MYCAR.
    DATOS ACTUALES:
    --- STOCK ---
    {stock_txt}
    --- LEEDS ---
    {leeds_txt}
    
    REGLAS:
    1. Si no hay cliente, asume "Agencia".
    2. Usa toda la info disponible (Año, Km, Color).
    3. Responde limpio (sin JSON, salvo para ejecutar acciones).
    
    JSON ACCIONES: DATA_START {{"ACCION": "...", "Cliente": "...", "Vehiculo": "...", "Año": "...", "Km": "...", "Color": "...", "Patente": "...", "Telefono": "...", "Mensaje": "..."}} DATA_END
    ACCIONES: GUARDAR_AUTO, ELIMINAR_AUTO, GUARDAR_LEED, ELIMINAR_LEED, WHATSAPP.
    """

    # Función interna para llamar a Gemini (Plan B)
    def usar_gemini():
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        model = genai.GenerativeModel('models/gemini-2.0-flash-exp')
        inputs = [instruccion, prompt_usuario]
        if archivo: inputs.append({"mime_type": archivo.type, "data": archivo.getvalue()})
        res = model.generate_content(inputs)
        return res.text

    # 2. Lógica de Selección de Motor
    if archivo:
        return usar_gemini()
    else:
        try:
            client = Groq(api_key=st.secrets["GROQ_API_KEY"])
            mensajes = [{"role": "system", "content": instruccion}]
            # Limitamos el historial enviado a los últimos 4 mensajes
            for m in st.session_state.messages[-4:]: 
                mensajes.append({"role": m["role"], "content": m["content"]})
            mensajes.append({"role": "user", "content": prompt_usuario})

            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=mensajes,
                temperature=0
            )
            return completion.choices[0].message.content
        
        except Exception as e:
            # Si Groq falla por límite, usamos Gemini silenciosamente
            print(f"Groq saturado, cambiando a Gemini... Error: {e}")
            return usar_gemini()

# --- INTERFAZ USUARIO ---
st.title("CRM IA")
tab1, tab2, tab3 = st.tabs(["💬 Chat", "📦 Stock", "👥 Leeds"])

if "messages" not in st.session_state: st.session_state.messages = []

with tab1:
    archivo = st.file_uploader("📷 Adjuntar (Activa Gemini)", type=["pdf", "jpg", "png", "mp4"])

    # Contenedor Historial
    chat_container = st.container()
    with chat_container:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])
        st.write("---") 
        st.write("") 
        st.write("") 

    # Input
    if prompt := st.chat_input("Escribe una orden..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        with chat_container:
            with st.chat_message("user"): st.markdown(prompt)
            with st.chat_message("assistant"):
                with st.spinner("Procesando..."):
                    try:
                        respuesta = consultar_ia(prompt, archivo)
                        
                        texto_visible = re.sub(r"DATA_START.*?DATA_END", "", respuesta, flags=re.DOTALL).strip()
                        if texto_visible:
                            st.session_state.messages.append({"role": "assistant", "content": texto_visible})
                            st.markdown(texto_visible)

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
    st.dataframe(pd.DataFrame(ws_stock.get_all_records()))

with tab3:
    if st.button("🔄 Refrescar Leeds"): st.rerun()
    st.dataframe(pd.DataFrame(ws_leeds.get_all_records()))

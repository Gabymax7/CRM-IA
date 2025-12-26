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

# --- HELPER 1: BUSCADOR FLEXIBLE ---
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

# --- HELPER 2: FILTRO PARA AHORRAR TOKENS ---
def filtrar_vacios(lista_registros):
    """Detiene la lectura si encuentra 3 filas vacías seguidas."""
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

# --- CEREBRO IA (DOBLE MOTOR + MEMORIA INTELIGENTE) ---
def consultar_ia(prompt_usuario, archivo=None):
    # 1. Lectura de Datos Segura
    try:
        raw_stock = ws_stock.get_all_records()
        raw_leeds = ws_leeds.get_all_records()
        
        # Filtramos para no saturar a Groq
        stock_safe = filtrar_vacios(raw_stock)
        leeds_safe = filtrar_vacios(raw_leeds)

        # Convertimos a texto forzando lectura de todas las columnas
        stock_txt = "\n".join([f"Auto {i+1}: {str(r)}" for i, r in enumerate(stock_safe)])
        leeds_txt = "\n".join([f"Leed {i+1}: {str(r)}" for i, r in enumerate(leeds_safe)])
    except: 
        stock_txt, leeds_txt = "Error de lectura", "Error de lectura"
    
    instruccion = f"""
    ERES EL GESTOR DE MYCAR.
    
    DATOS ACTUALES:
    --- STOCK ---
    {stock_txt}
    --- LEEDS ---
    {leeds_txt}
    
    REGLAS OPERATIVAS:
    1. Si ingresan un auto sin dueño, asume Cliente="Agencia".
    2. Lee todos los campos del diccionario (Año, Km, Color) aunque tengan nombres raros.
    3. Responde normal. Solo usa JSON para ejecutar acciones.
    
    FORMATO JSON PARA ACCIONES:
    DATA_START {{"ACCION": "...", "Cliente": "...", "Vehiculo": "...", "Año": "...", "Km": "...", "Color": "...", "Patente": "...", "Telefono": "...", "Mensaje": "..."}} DATA_END
    
    ACCIONES: GUARDAR_AUTO, ELIMINAR_AUTO, GUARDAR_LEED, ELIMINAR_LEED, WHATSAPP.
    """

    # Función interna: Gemini (Respaldo o Multimedia)
    def usar_gemini():
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        model = genai.GenerativeModel('models/gemini-2.0-flash-exp')
        inputs = [instruccion, prompt_usuario]
        if archivo: inputs.append({"mime_type": archivo.type, "data": archivo.getvalue()})
        res = model.generate_content(inputs)
        return res.text

    # 2. Selección de Motor
    if archivo:
        return usar_gemini()
    else:
        try:
            # Intento principal: Groq
            client = Groq(api_key=st.secrets["GROQ_API_KEY"])
            mensajes = [{"role": "system", "content": instruccion}]
            # Historial corto (últimos 4) para no gastar tokens
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
            # Fallback automático
            print(f"⚠️ Groq falló ({e}). Cambiando a Gemini.")
            return usar_gemini()

# --- INTERFAZ USUARIO ---
st.title("CRM IA")
tab1, tab2, tab3 = st.tabs(["💬 Chat", "📦 Stock", "👥 Leeds"])

if "messages" not in st.session_state: st.session_state.messages = []

with tab1:
    archivo = st.file_uploader("📷 Adjuntar (Activa Gemini)", type=["pdf", "jpg", "png", "mp4"])

    # Contenedor del Historial (Arriba)
    chat_container = st.container()
    with chat_container:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])
        # Espacio para que el último mensaje no quede tapado
        st.write("---") 
        st.write("")
        st.write("")

    # Input (Abajo y Fijo)
    if prompt := st.chat_input("Escribe una orden..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        # Mostrar mensaje usuario visualmente
        with chat_container:
            with st.chat_message("user"): st.markdown(prompt)
            
            with st.chat_message("assistant"):
                with st.spinner("Procesando..."):
                    try:
                        respuesta = consultar_ia(prompt, archivo)
                        
                        # Limpiar JSON de la vista
                        texto_visible = re.sub(r"DATA_START.*?DATA_END", "", respuesta, flags=re.DOTALL).strip()
                        if texto_visible:
                            st.markdown(texto_visible)
                            st.session_state.messages.append({"role": "assistant", "content": texto_visible})

                        # Ejecutar Acciones
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
        
        # Refresco forzado para limpiar input
        time.sleep(0.5)
        st.rerun()

# --- TABS DE DATOS (CON PROTECCIÓN ANTI-CRASH) ---
with tab2:
    if st.button("🔄 Refrescar Stock"): st.rerun()
    # .astype(str) convierte TODO a texto para evitar el error de pyarrow/Año
    try:
        df_stock = pd.DataFrame(ws_stock.get_all_records()).astype(str)
        st.dataframe(df_stock, use_container_width=True)
    except: st.info("Stock vacío o error de lectura.")

with tab3:
    if st.button("🔄 Refrescar Leeds"): st.rerun()
    try:
        df_leeds = pd.DataFrame(ws_leeds.get_all_records()).astype(str)
        st.dataframe(df_leeds, use_container_width=True)
    except: st.info("Lista de Leeds vacía.")

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
        
        # 1. Búsqueda por Número (ej: "borra el 1")
        if texto_busqueda.isdigit():
            idx = int(texto_busqueda) - 1
            if 0 <= idx < len(registros):
                return idx + 2 # +2 por header y base 1
        
        # 2. Búsqueda por Texto
        for i, row in enumerate(registros, start=2):
            fila_texto = " ".join([str(v).lower() for v in row.values()])
            if texto_busqueda in fila_texto:
                return i
        return None
    except: return None

# --- CEREBRO IA (AHORA LEE TODO) ---
def consultar_ia(prompt_usuario, archivo=None):
    # Leer datos frescos
    try:
        stock_raw = ws_stock.get_all_records()
        leeds_raw = ws_leeds.get_all_records()
        
        # --- CORRECCIÓN AQUÍ: Le pasamos TODAS las columnas a la IA ---
        stock_txt = []
        for i, r in enumerate(stock_raw):
            info_auto = f"Índice {i+1}: Cliente: {r.get('Cliente','?')} | Auto: {r.get('Vehiculo','?')} | Año: {r.get('Año','?')} | Km: {r.get('Km','?')} | Color: {r.get('Color','?')}"
            stock_txt.append(info_auto)
        stock_txt = "\n".join(stock_txt)
        
        leeds_txt = "\n".join([f"{i+1}. {r['Cliente']} busca {r['Busca']} (Tel: {r.get('Telefono','')})" for i, r in enumerate(leeds_raw)])
    except:
        stock_txt = "Vacío"
        leeds_txt = "Vacío"
    
    instruccion = f"""
    ERES EL GESTOR DE MYCAR.
    
    TUS DATOS COMPLETOS:
    --- STOCK ---
    {stock_txt}
    --- LEEDS ---
    {leeds_txt}
    
    REGLAS:
    1. SI NO HAY CLIENTE EN LA ORDEN DE INGRESO: Asume Cliente="Agencia".
    2. SI PIDEN INFO: Tienes el Año, Km y Color arriba. Úsalos.
    3. FORMATO LIMPIO: No uses JSON para responder preguntas normales.
    
    JSON SOLO PARA EJECUTAR ACCIONES (Guardar/Borrar):
    DATA_START {{"ACCION": "...", "Cliente": "...", "Vehiculo": "...", "Año": "...", "Km": "...", "Color": "...", "Patente": "...", "Telefono": "...", "Mensaje": "..."}} DATA_END
    
    ACCIONES: GUARDAR_AUTO, ELIMINAR_AUTO, GUARDAR_LEED, ELIMINAR_LEED, WHATSAPP.
    """

    if archivo:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        model = genai.GenerativeModel('models/gemini-3-flash-preview')
        inputs = [instruccion, prompt_usuario, {"mime_type": archivo.type, "data": archivo.getvalue()}]
        res = model.generate_content(inputs)
        return res.text
    else:
        client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        mensajes = [{"role": "system", "content": instruccion}]
        for m in st.session_state.messages[-4:]: 
            mensajes.append({"role": m["role"], "content": m["content"]})
        mensajes.append({"role": "user", "content": prompt_usuario})

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=mensajes,
            temperature=0
        )
        return completion.choices[0].message.content

# --- INTERFAZ USUARIO ---
st.title("CRM IA")
tab1, tab2, tab3 = st.tabs(["💬 Chat", "📦 Stock", "👥 Leeds"])

if "messages" not in st.session_state: st.session_state.messages = []

with tab1:
    archivo = st.file_uploader("📷 Adjuntar (Activa Gemini)", type=["pdf", "jpg", "png", "mp4"])

    # 1. BUCLE DE MENSAJES SIMPLE (Mejora visual)
    for m in st.session_state.messages:
        with st.chat_message(m["role"]): st.markdown(m["content"])
    
    # Espacio invisible para empujar el contenido arriba si es necesario
    st.write("") 

    # 2. INPUT ANCLADO ABAJO
    if prompt := st.chat_input("Escribe una orden..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Procesando..."):
                try:
                    respuesta = consultar_ia(prompt, archivo)
                    
                    # Mostrar texto limpio
                    texto_visible = re.sub(r"DATA_START.*?DATA_END", "", respuesta, flags=re.DOTALL).strip()
                    if texto_visible:
                        st.markdown(texto_visible)
                        st.session_state.messages.append({"role": "assistant", "content": texto_visible})

                    # EJECUTAR ACCIONES
                    accion = False
                    for match in re.findall(r"DATA_START\s*(.*?)\s*DATA_END", respuesta, re.DOTALL):
                        data = json.loads(match)
                        
                        if data["ACCION"] == "GUARDAR_AUTO":
                            cliente_final = data.get('Cliente', 'Agencia')
                            if not cliente_final: cliente_final = "Agencia"

                            meta = {'name': f"{cliente_final} - {data['Vehiculo']}", 'mimeType': 'application/vnd.google-apps.folder', 'parents': [ID_CARPETA_PADRE_DRIVE]}
                            try:
                                f = drive_service.files().create(body=meta, fields='webViewLink').execute()
                                link = f.get('webViewLink')
                            except: link = "Error Drive"
                            
                            ws_stock.append_row([datetime.now().strftime("%d/%m/%Y"), cliente_final, data['Vehiculo'], data.get('Año','-'), data.get('Km','-'), data.get('Color','-'), "-", "-", data.get('Patente','-'), link])
                            st.toast(f"✅ Guardado: {data['Vehiculo']}")
                            accion = True

                        elif data["ACCION"] == "ELIMINAR_AUTO":
                            fila = encontrar_fila_flexible(ws_stock, data['Cliente'])
                            if fila:
                                try:
                                    link_drive = ws_stock.cell(fila, 10).value 
                                    if "folders/" in str(link_drive):
                                        id_match = re.search(r'folders/([a-zA-Z0-9-_]+)', str(link_drive))
                                        if id_match:
                                            drive_service.files().delete(fileId=id_match.group(1)).execute()
                                            st.toast("🗑️ Carpeta eliminada")
                                except: pass
                                
                                ws_stock.delete_rows(fila)
                                st.success(f"🗑️ Eliminado: {data['Cliente']}")
                                accion = True
                            else: st.warning(f"No encontré el auto.")

                        elif data["ACCION"] == "ELIMINAR_LEED":
                            fila = encontrar_fila_flexible(ws_leeds, data['Cliente'])
                            if fila:
                                ws_leeds.delete_rows(fila)
                                st.success(f"🗑️ Leed eliminado: {data['Cliente']}")
                                accion = True
                            
                        elif data["ACCION"] == "WHATSAPP":
                             link = f"https://wa.me/{data.get('Telefono','')}?text={urllib.parse.quote(data.get('Mensaje',''))}"
                             st.link_button(f"📲 WhatsApp a {data['Cliente']}", link)
                             accion = True

                    if accion:
                        time.sleep(1)
                        st.rerun()

                except Exception as e:
                    st.error(f"Error: {e}")

with tab2:
    if st.button("🔄 Refrescar Stock"): st.rerun()
    st.dataframe(pd.DataFrame(ws_stock.get_all_records()))

with tab3:
    if st.button("🔄 Refrescar Leeds"): st.rerun()
    st.dataframe(pd.DataFrame(ws_leeds.get_all_records()))

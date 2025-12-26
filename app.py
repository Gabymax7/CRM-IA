import streamlit as st
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import json
import re
from datetime import datetime
import pandas as pd
import plotly.express as px
import urllib.parse

# --- CONFIGURACIÓN ---
SHEET_ID = "17Cn82TTSyXbipbW3zZ7cvYe6L6aDkX3EPK6xO7MTxzU"
ID_CARPETA_PADRE_DRIVE = "1XS4-h6-VpY_P-C3t_L-X4r8F6O-9-C-y"

st.set_page_config(page_title="CRM MyCar Inteligente", page_icon="🚗", layout="wide")

# --- CONEXIÓN ---
@st.cache_resource
def conectar():
    creds_info = dict(st.secrets["gcp_service_account"])
    creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
    creds = Credentials.from_service_account_info(creds_info, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/calendar"])
    gc = gspread.authorize(creds)
    return gc.open_by_key(SHEET_ID).worksheet("Stock"), gc.open_by_key(SHEET_ID).worksheet("Leeds"), build('drive', 'v3', credentials=creds)

ws_stock, ws_leeds, drive_service = conectar()

# --- IA ---
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel('models/gemini-3-flash-preview')

# --- MEJORA: NORMALIZACIÓN DE DATOS ---
def obtener_stock_limpio():
    try:
        df = pd.DataFrame(ws_stock.get_all_records())
        if df.empty: return df
        
        # Diccionario básico de marcas para agrupar rápido
        marcas = ['Toyota', 'Volkswagen', 'VW', 'Fiat', 'Renault', 'Ford', 'Chevrolet', 'Peugeot', 'Honda', 'Citroen']
        
        def limpiar(txt):
            txt = str(txt).upper()
            found_brand = "OTRO"
            for m in marcas:
                if m.upper() in txt:
                    found_brand = m.replace("VW", "VOLKSWAGEN").upper()
                    break
            # Retorna la marca y el nombre original limpio
            return found_brand

        df['Marca'] = df['Vehiculo'].apply(limpiar)
        return df
    except: return pd.DataFrame()

# --- UI: BARRA LATERAL ---
with st.sidebar:
    st.title("📊 Estadísticas Reales")
    df_clean = obtener_stock_limpio()
    if not df_clean.empty:
        # Gráfico por MARCA (Agrupa Gol, Polo, Vento bajo VW)
        fig_marca = px.bar(df_clean['Marca'].value_counts().reset_index(), 
                           x='Marca', y='count', title="Stock por Marca",
                           labels={'count': 'Unidades'}, color='Marca')
        st.plotly_chart(fig_marca, use_container_width=True)
        
        st.metric("Total Unidades", len(df_clean))
    st.divider()
    if st.button("🗑️ Limpiar Chat"):
        st.session_state.messages = []
        st.rerun()

# --- INTERFAZ PRINCIPAL ---
st.title("🤖 CRM-IA: MyCar Centro")
tab1, tab2 = st.tabs(["💬 Chat", "📦 Stock Completo"])

with tab1:
    archivo = st.file_uploader("📷 Foto o 📄 PDF", type=["pdf", "jpg", "png", "jpeg"])
    if "messages" not in st.session_state: st.session_state.messages = []
    
    for m in st.session_state.messages:
        with st.chat_message(m["role"]): st.markdown(m["content"])

    if prompt := st.chat_input("¿Qué novedad hay?"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)

        with st.chat_message("assistant"):
            instruccion = f"Hoy es {datetime.now().strftime('%Y-%m-%d')}. Eres gestor de MyCar. Responde CORTO. Stock: {ws_stock.get_all_records()[:10]}"
            inputs = [instruccion, prompt]
            if archivo: inputs.append({"mime_type": archivo.type, "data": archivo.getvalue()})
            
            res = model.generate_content(inputs)
            visible = re.sub(r"DATA_START.*?DATA_END", "", res.text, flags=re.DOTALL).strip()
            st.markdown(visible)
            st.session_state.messages.append({"role": "assistant", "content": visible})

            for m in re.findall(r"DATA_START\s*(.*?)\s*DATA_END", res.text, re.DOTALL):
                data = json.loads(m)
                if data["ACCION"] == "GUARDAR_AUTO":
                    # Crear carpeta y link
                    meta = {'name': f"{data['Cliente']} - {data['Vehiculo']}", 'mimeType': 'application/vnd.google-apps.folder', 'parents': [ID_CARPETA_PADRE_DRIVE]}
                    f = drive_service.files().create(body=meta, fields='webViewLink').execute()
                    ws_stock.append_row([datetime.now().strftime("%d/%m/%Y"), data['Cliente'], data['Vehiculo'], data.get('Año','-'), data.get('KM','-'), data.get('Color','-'), "-", "-", data.get('Patente','-'), f.get('webViewLink')])
                    st.toast(f"✅ Guardado: {data['Vehiculo']}")

with tab2:
    st.dataframe(df_clean, use_container_width=True)

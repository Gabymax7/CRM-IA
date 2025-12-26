import streamlit as st
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import json
import re
from datetime import datetime
import pandas as pd

# --- CONFIGURACIÓN ---
SHEET_ID = "17Cn82TTSyXbipbW3zZ7cvYe6L6aDkX3EPK6xO7MTxzU"

st.set_page_config(page_title="CRM-IA: MyCar", page_icon="🚗")

if "messages" not in st.session_state:
    st.session_state.messages = []

# --- CONEXIÓN SEGURA ---
def conectar():
    SCOPE = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    # Si estamos en la nube (Streamlit Cloud)
    if "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        # Limpiamos la clave privada para evitar el error de "Incorrect padding"
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPE)
    # Si estamos en la PC
    else:
        creds = Credentials.from_service_account_file("credenciales.json", scopes=SCOPE)
    
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID)
    return sheet.worksheet("Stock"), sheet.worksheet("Leeds")

try:
    ws_stock, ws_leeds = conectar()
except Exception as e:
    st.error(f"Error de conexión: {e}")
    st.stop()

# Usamos la versión estable para evitar el error 404
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-1.5-flash') 

# --- INTERFAZ ---
st.title("🤖 CRM-IA: MyCar Centro")

col1, col2 = st.columns(2)
with col1:
    if st.button("📊 Ver Stock"):
        st.dataframe(pd.DataFrame(ws_stock.get_all_records()))
with col2:
    if st.button("👥 Ver Leeds"):
        st.dataframe(pd.DataFrame(ws_leeds.get_all_records()))

# Chat e IA
for m in st.session_state.messages:
    with st.chat_message(m["role"]): st.markdown(m["content"])

if prompt := st.chat_input("¿Qué novedades hay?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)
    
    with st.chat_message("assistant"):
        response = model.generate_content(prompt)
        st.markdown(response.text)
        st.session_state.messages.append({"role": "assistant", "content": response.text})

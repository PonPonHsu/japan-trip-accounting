import streamlit as st
import pandas as pd
from datetime import datetime
import json
import google.generativeai as genai
from PIL import Image
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import io
import time

# --- 基礎設定 ---
st.set_page_config(page_title="日本旅行記帳系統", page_icon="🧾", layout="centered")

# 【請務必修改此處】你的 Google Sheets 網址
GSHEET_URL = "https://docs.google.com/spreadsheets/d/1kECMoz7jzf-5-PLf9gVZJ4M38_NFFcCID4AILXAtTKk/edit?gid=0#gid=0"
# 【請務必修改此處】Google Drive 總收據資料夾 ID
DRIVE_ROOT_ID = "1PeLDeGLAvcKTYRLIiK-m_AAIKNDGzLll"

# --- 初始化 Google 服務 ---
def get_creds():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    return Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)

def get_gsheet_client():
    return gspread.authorize(get_creds())

def get_drive_service():
    return build('drive', 'v3', credentials=get_creds())

def sync_data():
    client = get_gsheet_client()
    sheet = client.open_by_url(GSHEET_URL).get_worksheet(0)
    data = sheet.get_all_records()
    return pd.DataFrame(data), sheet

# --- 輔助函式：列出資料夾與檔案 ---
def list_subfolders(parent_id):
    service = get_drive_service()
    query = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    return {f['name']: f['id'] for f in results.get('files', [])}

def list_files_in_folder(folder_id):
    service = get_drive_service()
    query = f"'{folder_id}' in parents and mimeType contains 'image/' and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    return results.get('files', [])

def download_file(file_id):
    service = get_drive_service()
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    from googleapiclient.http import MediaIoBaseDownload
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        _, done = downloader.next_chunk()
    return fh.getvalue()

# --- 刪除確認對話框 ---
@st.dialog("⚠️ 確認刪除")
def confirm_delete_dialog(row_index, item_name, sheet):
    st.warning(f"確定要從雲端刪除「{item_name}」？")
    if st.button("🔥 確定刪除", use_container_width=True, type="primary"):
        sheet.delete_rows(row_index + 2)
        st.success("已刪除！")
        time.sleep(1)
        st.rerun()

# --- 初始化 Gemini ---
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-2.5-flash') 
except:
    st.error("API Key 設定錯誤")

# --- 狀態初始化 ---
if 'batch_results' not in st.session_state:
    st.session_state.batch_results = []
if 'processing' not in st.session_state:
    st.session_state.processing = False

CONSUMERS = ["三人分", "金城舞", "阿鵬", "小君", "阿杏"]
PAYMENT_METHODS = ["現金", "小君卡", "阿鵬卡"]

st.title("🧾 旅費拆帳完全體 (雲端批次版)")

tab1, tab2, tab3 = st.tabs(["📸 批次收據辨識", "✍️ 手動輸入", "📊 雲端帳單結算"])

# === 分頁 1：批次辨識模式 ===
with tab1:
    st.subheader("📂 選擇雲端資料夾")
    
    # 1. 選擇子資料夾
    try:
        subfolders = list_subfolders(DRIVE_ROOT_ID)
        if not subfolders:
            st.info("根資料夾內沒有子資料夾。")
            current_folder_id = DRIVE_ROOT_ID
        else:
            folder_name = st.selectbox("請選擇日期或分類資料夾", ["直接讀取根目錄"] + list(subfolders.keys()))
            current_folder_id = subfolders[folder_name] if folder_name != "直接讀取根目錄" else DRIVE_ROOT_ID
        
        # 2. 顯示檔案勾選清單
        st.divider()
        st.markdown("### 📋 選擇收據檔案")
        files = list_files_in_folder(current_folder_id)
        
        if not files:
            st.warning("此資料夾內沒有圖片檔案。")
        else:
            selected_file_ids = []
            for f in files:
                if st.checkbox(f['name'], key=f"check_{f['id']}"):
                    selected_file_ids.append((f['id'], f['name']))
            
            # 3. 執行批次辨識
            if selected_file_ids:
                if st.button(f"🤖 開始辨識 ({len(selected_file_ids)} 個檔案)", use_container_width=True, type="primary"):
                    st.session_state.batch_results = [] # 清空舊結果
                    progress_bar = st.progress(0)
                    
                    for i, (f_id, f_name) in

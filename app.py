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

# 【請務必修改此處】
GSHEET_URL = "https://docs.google.com/spreadsheets/d/1kECMoz7jzf-5-PLf9gVZJ4M38_NFFcCID4AILXAtTKk/edit?gid=0#gid=0"
# 【請務必修改此處】Google Drive 存放收據的資料夾 ID
DRIVE_FOLDER_ID = "1PeLDeGLAvcKTYRLIiK-m_AAIKNDGzLll"

# --- 初始化 Google 服務 ---
def get_creds():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/drive.readonly"
    ]
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
    # 使用你測試成功過的 2.5-flash
    model = genai.GenerativeModel('gemini-2.5-flash') 
except:
    st.error("API Key 設定錯誤")

if 'ai_processed' not in st.session_state:
    st.session_state.ai_processed = False
if 'current_data' not in st.session_state:
    st.session_state.current_data = None

CONSUMERS = ["三人分", "金城舞", "阿鵬", "小君", "阿杏"]
PAYMENT_METHODS = ["現金", "小君卡", "阿鵬卡"]

st.title("🧾 旅費拆帳完全體 (雲端連動版)")

tab1, tab2, tab3 = st.tabs(["📸 收據辨識", "✍️ 手動輸入", "📊 雲端帳單結算"])

# === 分頁 1：收據辨識 (含批次讀取) ===
with tab1:
    mode = st.radio("選擇模式", ["手機上傳/拍照", "從雲端資料夾抓取"], horizontal=True)
    
    selected_image = None
    
    if mode == "手機上傳/拍照":
        uploaded_file = st.file_uploader("上傳收據", type=["png", "jpg", "jpeg"])
        if uploaded_file:
            selected_image = Image.open(uploaded_file)
            st.image(selected_image, use_container_width=True)
            
    else:
        # 從 Google Drive 資料夾抓取檔案清單
        try:
            drive_service = get_drive_service()
            query = f"'{DRIVE_FOLDER_ID}' in parents and (mimeType contains 'image/' or mimeType = 'application/pdf') and trashed = false"
            results = drive_service.files().list(q=query, pageSize=10, fields="files(id, name)").execute()
            files = results.get('files', [])
            
            if not files:
                st.info("資料夾內目前沒有任何收據檔案。")
            else:
                file_options = {f['name']: f['id'] for f in files}
                selected_file_name = st.selectbox("請選擇要辨識的雲端收據", list(file_options.keys()))
                
                if st.button("🔽 下載並預覽"):
                    file_id = file_options[selected_file_name]
                    request = drive_service.files().get_media(fileId=file_id)
                    fh = io.BytesIO()
                    from googleapiclient.http import MediaIoBaseDownload
                    downloader = MediaIoBaseDownload(fh, request)
                    done = False
                    while done is False:
                        status, done = downloader.next_chunk()
                    
                    st.session_state.drive_img_bytes = fh.getvalue()
                
                if 'drive_img_bytes' in st.session_state:
                    selected_image = Image.open(io.BytesIO(st.session_state.drive_img_bytes))
                    st.image(selected_image, use_container_width=True)
        except Exception as e:
            st.error(f"讀取雲端資料夾失敗：{e}")

    # --- AI 辨識邏輯 ---
    if selected_image:
        if st.button("🤖 執行 AI 辨識", use_container_width=True):
            with st.spinner('AI 正在分析...'):
                prompt = """
                你是一個專業的日翻中記帳助理。請辨識收據，並回傳純 JSON 格式：
                1. "payment_method": 判斷「現金」或「信用卡」。
                2. "items": 陣列，包含 original_name (日文), translated_name (繁體中文或品牌英文讀音), price (數字)。
                """
                try:
                    response = model.generate_content([prompt, selected_image])
                    txt = response.text.strip().removeprefix('```json').removesuffix('```').strip()
                    st.session_state.current_data = json.loads(txt)
                    st.session_state.ai_processed = True
                except:
                    st.error("辨識失敗")

    if st.session_state.ai_processed and st.session_state.current_data:
        st.subheader("🛒 辨識結果與品項分配")
        data = st.session_state.current_data
        method = st.selectbox("確認付款方式", PAYMENT_METHODS)
        
        with st.form("gs_form"):
            rows_to_add = []
            for i, item in enumerate(data.get('items', [])):
                st.write(f"**{item['translated_name']}** (¥{item['price']})")
                cons = st.selectbox("誰的？", CONSUMERS, key=f"r_{i}")
                payer = "阿鵬" if method == "阿鵬卡" else "小君"
                rows_to_add.append([datetime.now().strftime("%Y-%m-%d"), item['translated_name'], item['price'], method, payer, cons])
            
            if st.form_submit_button("✅ 存入雲端試算表", use_container_width=True):
                _, sheet = sync_data()
                sheet.append_rows(rows_to_add)
                st.success("已存入 Google Sheets！")
                st.session_state.ai_processed = False
                if 'drive_img_bytes' in st.session_state: del st.session_state.drive_img_bytes

# === 分頁 2：手動輸入 (維持原樣) ===
with tab2:
    with st.form("manual"):
        m_item = st.text_input("項目")
        m_price = st.number_input("日幣金額", min_value=0)
        m_method = st.selectbox("付款", PAYMENT_METHODS)
        m_cons = st.selectbox("對象", CONSUMERS)
        if st.form_submit_button("💾 存入雲端"):
            if m_item:
                _, sheet = sync_data()
                sheet.append_row([datetime.now().strftime("%Y-%m-%d"), m_item, m_price, m_method, "阿鵬" if m_method=="阿鵬卡" else "小君", m_cons])
                st.success("已存入！")

# === 分頁 3：雲端結算 (含刪除功能) ===
with tab3:
    if st.button("🔄 刷新雲端資料庫"): st.rerun()
    try:
        df, sheet = sync_data()
        if not df.empty:
            totals = {"阿鵬": 0, "小君": 0, "阿杏": 0}
            for _, r in df.iterrows():
                p, c = r["日幣金額"], r["消費者"]
                if c == "三人分":
                    for k in totals: totals[k] += p/3
                elif c == "金城舞":
                    totals["阿鵬"] += p/2; totals["小君"] += p/2
                elif c in totals:
                    totals[c] += p
            c1, c2, c3 = st.columns(3)
            c1.metric("阿鵬", f"¥{int(totals['阿鵬'])}")
            c2.metric("小君", f"¥{int(totals['小君'])}")
            c3.metric("阿杏", f"¥{int(totals['阿杏'])}")
            st.divider()
            for index, row in df.iterrows():
                with st.container(border=True):
                    c_i, c_d = st.columns([4, 1])
                    with c_i: st.markdown(f"**{row['品項']}** (¥{row['日幣金額']})")
                    with c_d:
                        if st.button("🗑️", key=f"del_{index}"): confirm_delete_dialog(index, row['品項'], sheet)
    except Exception as e:
        st.error(f"連線失敗：{e}")

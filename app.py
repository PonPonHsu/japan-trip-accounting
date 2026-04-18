import streamlit as st
import pandas as pd
from datetime import datetime
import json
import google.generativeai as genai
from PIL import Image
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
import time

# --- 基礎設定 ---
st.set_page_config(page_title="日本旅行記帳系統", page_icon="🧾", layout="centered")

# 【請務必修改此處】你的 Google Sheets 網址
GSHEET_URL = "https://docs.google.com/spreadsheets/d/你的試算表ID/edit"

# 【請務必修改此處】Google Drive 總收據資料夾 ID
DRIVE_ROOT_ID = "你的資料夾ID"

# --- 側邊欄設計 (進階導航) ---
with st.sidebar:
    st.title("🧳 旅程快捷鍵")
    st.link_button("📊 查看完整雲端帳單 ↗️", GSHEET_URL, use_container_width=True)
    st.metric("設定匯率", "0.203")
    st.divider()
    st.caption("提示：每天晚上掃描完收據後，建議進去試算表確認總額。")

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

# --- 雲端資料夾輔助函式 ---
def list_subfolders(parent_id):
    service = get_drive_service()
    query = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    return {f['name']: f['id'] for f in results.get('files', [])}

def list_files_in_folder(folder_id):
    service = get_drive_service()
    query = f"'{folder_id}' in parents and (mimeType contains 'image/' or mimeType = 'application/pdf') and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    return results.get('files', [])

def download_file(file_id):
    service = get_drive_service()
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        _, done = downloader.next_chunk()
    return fh.getvalue()

# --- 刪除確認對話框 ---
@st.dialog("⚠️ 確認刪除")
def confirm_delete_dialog(row_index, item_name, sheet):
    st.warning(f"您確定要從雲端刪除「{item_name}」這筆資料嗎？")
    st.write("刪除後將無法復原。")
    if st.button("🔥 確定刪除", use_container_width=True, type="primary"):
        sheet.delete_rows(row_index + 2)
        st.success("資料已成功刪除！")
        time.sleep(1)
        st.rerun()

# --- 初始化 Gemini ---
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    # 使用額度最穩定的官方別名
    model = genai.GenerativeModel('gemini-flash-latest') 
except:
    st.error("API Key 設定錯誤，請檢查 Secrets")

# --- 狀態初始化 ---
if 'batch_results' not in st.session_state:
    st.session_state.batch_results = []
if 'processing' not in st.session_state:
    st.session_state.processing = False

CONSUMERS = ["三人分", "金城舞", "阿鵬", "小君", "阿杏"]
PAYMENT_METHODS = ["現金", "小君卡", "阿鵬卡"]

# --- 主介面 ---
st.title("🧾 旅費拆帳完全體")

tab1, tab2, tab3 = st.tabs(["📸 批次收據辨識", "✍️ 手動輸入", "📊 雲端帳單結算"])

# === 分頁 1：批次辨識模式 ===
with tab1:
    st.subheader("📂 選擇收據來源")
    try:
        subfolders = list_subfolders(DRIVE_ROOT_ID)
        folder_options = ["直接讀取根目錄"] + list(subfolders.keys())
        folder_name = st.selectbox("請選擇日期或分類資料夾", folder_options)
        current_folder_id = subfolders[folder_name] if folder_name != "直接讀取根目錄" else DRIVE_ROOT_ID
        
        st.divider()
        st.markdown("### 📋 勾選要辨識的檔案")
        files = list_files_in_folder(current_folder_id)
        
        if not files:
            st.info("此資料夾內沒有可辨識的圖片。")
        else:
            selected_files = []
            for f in files:
                if st.checkbox(f['name'], key=f"check_{f['id']}"):
                    selected_files.append((f['id'], f['name']))
            
            if selected_files:
                if st.button(f"🤖 開始辨識 ({len(selected_files)} 個檔案)", use_container_width=True, type="primary"):
                    st.session_state.batch_results = [] 
                    progress_bar = st.progress(0)
                    
                    for i, (f_id, f_name) in enumerate(selected_files):
                        with st.spinner(f"正在處理 ({i+1}/{len(selected_files)}): {f_name}..."):
                            img_data = download_file(f_id)
                            img = Image.open(io.BytesIO(img_data))
                            
                            prompt = """
                            你是一個專業的日翻中記帳助理。請辨識收據，並回傳純 JSON 格式：
                            1. "payment_method": 判斷「現金」或「信用卡」。
                            2. "items": 陣列，包含 original_name (日文), translated_name (翻譯), price (數字)。
                            
                            【重要翻譯規則】：
                            - translated_name 必須翻譯成「繁體中文」，且符合台灣用語。
                            - 如果遇到無法辨識的品牌名或專有名詞，請直接使用「英文讀音 (Romaji)」作為 translated_name，不可保留日文假名。
                            """
                            response = model.generate_content([prompt, img])
                            txt = response.text.strip().removeprefix('```json').removesuffix('```').strip()
                            result = json.loads(txt)
                            result['file_name'] = f_name
                            st.session_state.batch_results.append(result)
                            
                        progress_bar.progress((i + 1) / len(selected_files))
                        
                        # 每張之間休息 15 秒以符合免費版 API 限制
                        if i < len(selected_files) - 1:
                            time.sleep(15) 
                    
                    st.success("✅ 辨識完成！請在下方確認並分配。")

    except Exception as e:
        st.error(f"連線失敗：{e}")

    # 顯示暫存結果供使用者分配
    if st.session_state.batch_results:
        st.divider()
        st.subheader("🛒 辨識明細分配")
        with st.form("batch_save_form"):
            all_rows = []
            for idx, res in enumerate(st.session_state.batch_results):
                st.markdown(f"**📄 檔案：{res['file_name']}**")
                def_method = "小君卡" if "卡" in res.get("payment_method", "") else "現金"
                method = st.selectbox(f"付款方式 ({idx})", PAYMENT_METHODS, index=PAYMENT_METHODS.index(def_method), key=f"m_{idx}")
                
                for j, item in enumerate(res.get('items', [])):
                    c1, c2 = st.columns([2, 1])
                    with c1: st.write(f"· {item['translated_name']} (¥{item['price']})")
                    with c2: cons = st.selectbox("誰的？", CONSUMERS, key=f"c_{idx}_{j}", label_visibility="collapsed")
                    
                    payer = "阿鵬" if method == "阿鵬卡" else "小君"
                    all_rows.append([datetime.now().strftime("%Y-%m-%d"), item['translated_name'], item['price'], method, payer, cons])
                st.write("---")
            
            if st.form_submit_button("✅ 全部同步至雲端試算表", use_container_width=True):
                _, sheet = sync_data()
                sheet.append_rows(all_rows)
                st.success(f"成功存入 {len(all_rows)} 筆明細！")
                st.session_state.batch_results = []

# === 分頁 2：手動輸入 ===
with tab2:
    with st.form("manual"):
        m_item = st.text_input("品項名稱")
        m_price = st.number_input("日幣金額", min_value=0, step=100)
        m_method = st.selectbox("付款方式", PAYMENT_METHODS)
        m_cons = st.selectbox("這筆是誰的消費？", CONSUMERS)
        if st.form_submit_button("💾 儲存至雲端"):
            if m_item:
                _, sheet = sync_data()
                payer = "阿鵬" if m_method == "阿鵬卡" else "小君"
                sheet.append_row([datetime.now().strftime("%Y-%m-%d"), m_item, m_price, m_method, payer, m_cons])
                st.success("已成功存入！")

# === 分頁 3：雲端結算 ===
with tab3:
    if st.button("🔄 刷新雲端資料"): st.rerun()
    try:
        df, sheet = sync_data()
        if not df.empty:
            totals = {"阿鵬": 0.0, "小君": 0.0, "阿杏": 0.0}
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
                    ci, cd = st.columns([4, 1])
                    with ci:
                        st.markdown(f"**{row['品項']}** (¥{row['日幣金額']})")
                        st.caption(f"{row['日期']} | {row['消費者']} | 代墊：{row['代墊者']}")
                    with cd:
                        if st.button("🗑️", key=f"del_{index}"):
                            confirm_delete_dialog(index, row['品項'], sheet)
        else:
            st.info("雲端目前沒有紀錄。")
    except Exception as e:
        st.error(f"讀取失敗：{e}")

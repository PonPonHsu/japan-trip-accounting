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
    # 將 2.5 改成額度超大的 2.0 版本
    model = genai.GenerativeModel('gemini-flash-latest')
except:
    st.error("API Key 設定錯誤")

# --- 狀態初始化 ---
if 'batch_results' not in st.session_state:
    st.session_state.batch_results = []
if 'processing' not in st.session_state:
    st.session_state.processing = False

CONSUMERS = ["三人分", "金城舞", "阿鵬", "小君", "阿杏"]
PAYMENT_METHODS = ["現金", "小君卡", "阿鵬卡"]

st.title("🧾 旅費拆帳")

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
                    
                    for i, (f_id, f_name) in enumerate(selected_file_ids):
                        with st.spinner(f"正在處理 ({i+1}/{len(selected_file_ids)}): {f_name}... (為避免 API 限制，每張約需 15 秒)"):
                            img_data = download_file(f_id)
                            img = Image.open(io.BytesIO(img_data))
                            
                            prompt = """
                            你是一個專業的日翻中記帳助理。請辨識收據，並回傳純 JSON 格式：
                            1. "payment_method": 判斷「現金」或「信用卡」。
                            2. "items": 陣列，包含 original_name (日文), translated_name (中文), price (數字)。
                            """
                            response = model.generate_content([prompt, img])
                            txt = response.text.strip().removeprefix('```json').removesuffix('```').strip()
                            result = json.loads(txt)
                            result['file_name'] = f_name # 紀錄檔名
                            st.session_state.batch_results.append(result)
                            
                        progress_bar.progress((i + 1) / len(selected_file_ids))
                        
                        # 【新增防呆煞車機制】如果不是最後一張收據，就強制程式休息 15 秒
                        if i < len(selected_file_ids) - 1:
                            time.sleep(15) 
                    
                    st.success("✅ 所有檔案辨識完成！請在下方分配明細。")

    except Exception as e:
        st.error(f"雲端存取失敗：{e}")

    # 4. 顯示批次結果並分配
    if st.session_state.batch_results:
        st.divider()
        st.subheader("🛒 辨識結果與存檔")
        
        with st.form("batch_save_form"):
            all_rows = []
            for idx, res in enumerate(st.session_state.batch_results):
                st.markdown(f"**📄 檔案：{res['file_name']}**")
                
                # 付款方式預設判定
                def_method = "小君卡" if "卡" in res.get("payment_method", "") else "現金"
                method = st.selectbox(f"付款方式 ({idx})", PAYMENT_METHODS, index=PAYMENT_METHODS.index(def_method), key=f"method_{idx}")
                payer = "阿鵬" if method == "阿鵬卡" else "小君"
                
                for j, item in enumerate(res.get('items', [])):
                    c1, c2 = st.columns([2, 1])
                    with c1:
                        st.write(f"· {item['translated_name']} (¥{item['price']})")
                    with c2:
                        cons = st.selectbox("誰的？", CONSUMERS, key=f"cons_{idx}_{j}", label_visibility="collapsed")
                    
                    all_rows.append([datetime.now().strftime("%Y-%m-%d"), item['translated_name'], item['price'], method, payer, cons])
                st.write("---")
            
            if st.form_submit_button("✅ 全部存入雲端試算表", use_container_width=True):
                _, sheet = sync_data()
                sheet.append_rows(all_rows)
                st.success(f"已成功同步 {len(all_rows)} 筆明細至 Google Sheets！")
                st.session_state.batch_results = [] # 清空結果

# === 分頁 2 & 3 維持先前功能 (手動輸入、雲端結算) ===
with tab2:
    with st.form("manual"):
        m_item = st.text_input("項目")
        m_price = st.number_input("金額", min_value=0)
        m_method = st.selectbox("付款", PAYMENT_METHODS)
        m_cons = st.selectbox("對象", CONSUMERS)
        if st.form_submit_button("💾 存入雲端"):
            if m_item:
                _, sheet = sync_data()
                sheet.append_row([datetime.now().strftime("%Y-%m-%d"), m_item, m_price, m_method, "阿鵬" if m_method=="阿鵬卡" else "小君", m_cons])
                st.success("已存入！")

with tab3:
    if st.button("🔄 刷新資料"): st.rerun()
    try:
        df, sheet = sync_data()
        if not df.empty:
            # 統計個人應付
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
                    with c_i: st.markdown(f"**{row['品項']}** (¥{row['日幣金額']})\n\n{row['日期']} | {row['消費者']}")
                    with c_d:
                        if st.button("🗑️", key=f"del_{index}"): confirm_delete_dialog(index, row['品項'], sheet)
    except Exception as e:
        st.error(f"連線失敗：{e}")

import streamlit as st
import pandas as pd
from datetime import datetime
import time

# --- 初始化設定與暫存區 ---
st.set_page_config(page_title="日本旅行記帳系統", page_icon="🧾", layout="centered")

# 使用 session_state 來暫存目前所有的記帳紀錄與狀態
if 'expense_db' not in st.session_state:
    st.session_state.expense_db = []
if 'ai_processed' not in st.session_state:
    st.session_state.ai_processed = False

# 消費者與付款選項
CONSUMERS = ["三人分", "金城舞", "阿鵬", "小君", "阿杏"]
PAYMENT_METHODS = ["現金", "小君卡", "阿鵬卡"]

def get_payer(method):
    if method in ["現金", "小君卡"]:
        return "小君"
    elif method == "阿鵬卡":
        return "阿鵬"
    return "未知"

# --- 模擬 AI 辨識回傳的假資料 (供測試用) ---
MOCK_RECEIPT = {
    "payment_method": "現金", 
    "items": [
        {"original_name": "おにぎり", "translated_name": "飯糰", "price": 350},
        {"original_name": "生ビール", "translated_name": "生啤酒", "price": 1200},
        {"original_name": "お茶", "translated_name": "綠茶", "price": 150},
        {"original_name": "和牛焼肉", "translated_name": "和牛燒肉", "price": 4500}
    ]
}

# --- 介面設計 ---
st.title("🧾 旅費拆帳小幫手")

# 建立三個分頁：收據模式、手動模式、結算報表
tab1, tab2, tab3 = st.tabs(["📸 收據辨識", "✍️ 手動輸入", "📊 結算與匯出"])

# === 分頁 1：收據辨識模式 ===
with tab1:
    st.markdown("### 📤 上傳收據檔案")
    # 建立上傳元件，限制只能上傳圖片或 PDF
    uploaded_file = st.file_uploader("請選擇收據 (支援圖片檔與 PDF)", type=["png", "jpg", "jpeg", "pdf"])
    
    if uploaded_file is not None:
        # 顯示上傳成功訊息
        st.success(f"✅ 成功上傳檔案：{uploaded_file.name}")
        
        # 如果是圖片，就直接在畫面上預覽
        if uploaded_file.type in ["image/png", "image/jpeg", "image/jpg"]:
            st.image(uploaded_file, caption="收據預覽", use_container_width=True)
        elif uploaded_file.type == "application/pdf":
            st.info("📄 這是一個 PDF 檔案（未來會交由後端直接解析）")
            
        st.divider()
        
        # 建立一個按鈕來觸發「AI 辨識」
        if st.button("🤖 交給 AI 辨識收據", use_container_width=True):
            # 顯示進度條，模擬 AI 處理時間
            with st.spinner('AI 正在努力辨識品項與翻譯中，請稍候...'):
                time.sleep(2) 
                st.session_state.ai_processed = True
                
        # 當 AI 辨識完成後，顯示分配表單
        if st.session_state.ai_processed:
            st.subheader("🛒 辨識結果與品項分配")
            
            # 讀取模擬的 AI 資料
            payment_method = MOCK_RECEIPT["payment_method"]
            payer = get_payer(payment_method)
            
            col1, col2 = st.columns(2)
            col1.metric("付款方式", payment_method)
            col2.metric("系統判定代墊者", payer)
            
            with st.form("receipt_form"):
                selections = []
                for i, item in enumerate(MOCK_RECEIPT["items"]):
                    st.markdown(f"**{item['translated_name']}** ({item['original_name']})")
                    
                    c1, c2 = st.columns([1, 2])
                    with c1:
                        st.write(f"¥ {item['price']}")
                    with c2:
                        consumer = st.selectbox(
                            "誰的消費？", options=CONSUMERS, key=f"r_item_{i}", label_visibility="collapsed"
                        )
                    
                    selections.append({
                        "日期": datetime.now().strftime("%Y-%m-%d"),
                        "品項": item['translated_name'],
                        "日幣金額": item['price'],
                        "付款方式": payment_method,
                        "代墊者": payer,
                        "消費者": consumer
                    })
                    st.write("---")
                    
                submitted = st.form_submit_button("💾 儲存這筆收據", use_container_width=True)
                if submitted:
                    st.session_state.expense_db.extend(selections)
                    st.success("✅ 收據明細已加入資料庫！請至「結算報表」查看。")
                    # 存檔後重置狀態，準備迎接下一張收據
                    st.session_state.ai_processed = False


# === 分頁 2：手動輸入模式 ===
with tab2:
    st.subheader("✍️ 新增單筆無收據消費")
    with st.form("manual_form"):
        m_date = st.date_input("日期", datetime.now())
        m_item = st.text_input("消費品項名稱 (如：路邊攤糰子)")
        m_price = st.number_input("日幣金額", min_value=0, step=100)
        m_method = st.selectbox("付款方式", PAYMENT_METHODS)
        m_consumer = st.selectbox("這筆是誰的消費？", CONSUMERS)
        
        m_submitted = st.form_submit_button("💾 儲存單筆消費", use_container_width=True)
        
        if m_submitted and m_item:
            m_payer = get_payer(m_method)
            st.session_state.expense_db.append({
                "日期": m_date.strftime("%Y-%m-%d"),
                "品項": m_item,
                "日幣金額": m_price,
                "付款方式": m_method,
                "代墊者": m_payer,
                "消費者": m_consumer
            })
            st.success(f"✅ 已新增：{m_item} (¥{m_price})")


# === 分頁 3：結算與匯出 ===
with tab3:
    st.subheader("📊 目前累積帳單")
    
    if len(st.session_state.expense_db) == 0:
        st.write("目前還沒有任何記帳紀錄喔！")
    else:
        # 將暫存資料轉為 DataFrame
        df = pd.DataFrame(st.session_state.expense_db)
        
        # 顯示原始明細
        st.dataframe(df, use_container_width=True)
        
        # --- 自動拆帳邏輯 ---
        st.divider()
        st.subheader("💰 個人應付總額 (自動拆算)")
        
        # 初始化每個人的總花費
        personal_totals = {"阿鵬": 0.0, "小君": 0.0, "阿杏": 0.0}
        
        for _, row in df.iterrows():
            price = row["日幣金額"]
            consumer = row["消費者"]
            
            # 處理平分邏輯
            if consumer == "三人分":
                split_price = price / 3
                personal_totals["阿鵬"] += split_price
                personal_totals["小君"] += split_price
                personal_totals["阿杏"] += split_price
            elif consumer == "金城舞":
                split_price = price / 2
                personal_totals["阿鵬"] += split_price
                personal_totals["小君"] += split_price
            elif consumer in personal_totals:
                personal_totals[consumer] += price
                
        # 顯示拆算結果
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("阿鵬 總消費", f"¥ {int(personal_totals['阿鵬'])}")
        col_b.metric("小君 總消費", f"¥ {int(personal_totals['小君'])}")
        col_c.metric("阿杏 總消費", f"¥ {int(personal_totals['阿杏'])}")
        
        st.info("💡 提示：『金城舞』已自動除以 2 攤給阿鵬與小君；『三人分』已自動除以 3。")
        
        # 提供 CSV 下載
        st.divider()
        csv = df.to_csv(index=False).encode('utf-8-sig') # 使用 utf-8-sig 讓 Excel 開啟不亂碼
        st.download_button(
            label="📥 下載明細為 CSV 檔 (可匯入 Google Sheets)",
            data=csv,
            file_name=f"japan_trip_expenses_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            use_container_width=True
        )
        
        # 清空按鈕
        st.write("") # 增加一點間距
        if st.button("🗑️ 清空所有紀錄 (請確認已下載檔案)", use_container_width=True, type="primary"):
            st.session_state.expense_db = []
            st.rerun()

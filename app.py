import streamlit as st
import pandas as pd
from datetime import datetime

# --- 初始化設定與暫存區 ---
st.set_page_config(page_title="日本旅行記帳系統", page_icon="🧾", layout="centered")

# 使用 session_state 來暫存目前所有的記帳紀錄
if 'expense_db' not in st.session_state:
    st.session_state.expense_db = []

# 消費者選項
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
    "receipt_name": "2026-04-24_晚餐.pdf",
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
tab1, tab2, tab3 = st.tabs(["📸 收據辨識 (測試)", "✍️ 手動輸入", "📊 結算與匯出"])

# === 分頁 1：收據辨識模式 ===
with tab1:
    st.info(f"📄 目前處理檔案：{MOCK_RECEIPT['receipt_name']}")
    
    payment_method = MOCK_RECEIPT["payment_method"]
    payer = get_payer(payment_method)
    
    col1, col2 = st.columns(2)
    col1.metric("付款方式", payment_method)
    col2.metric("系統判定代墊者", payer)
    st.divider()

    st.subheader("🛒 品項分配")
    
    # 建立表單
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
        
        st.info("💡 提示：『金城舞』已自動除以2攤給阿鵬與小君；『三人分』已自動除以3。")
        
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
        if st.button("🗑️ 清空所有紀錄", use_container_width=True):
            st.session_state.expense_db = []
            st.rerun()
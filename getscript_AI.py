import streamlit as st
import requests
import xml.etree.ElementTree as ET
import re
from collections import Counter
from urllib.parse import urlparse, parse_qs
from deep_translator import GoogleTranslator
from concurrent.futures import ThreadPoolExecutor
import time

# 1. Cấu hình giao diện
st.set_page_config(page_title="Missevan Sub Tool Pro", page_icon="🎙️", layout="wide")

st.title("🎙️ Missevan Sub Tool Pro")
st.caption("Giải thuật: Caching + Parallel Batch Processing (4 Threads)")

# --- TRỤ CỘT 1: CACHING (Giữ dữ liệu gốc trong RAM) ---
@st.cache_data(show_spinner=False)
def get_missevan_script(url, cookie_str):
    """Truy xuất dữ liệu XML từ Missevan và chuẩn hóa kịch bản gốc"""
    try:
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        sound_id = query_params.get('id', [None])[0] or next((p for p in reversed(parsed_url.path.split('/')) if p.isdigit()), None)
        
        headers = {"User-Agent": "Mozilla/5.0", "Referer": url, "Cookie": cookie_str}
        info = requests.get(f"https://www.missevan.com/sound/getsound?soundid={sound_id}", headers=headers).json()
        
        if not info.get('success'):
            return None, "Không tìm thấy dữ liệu âm thanh."

        title = info['info']['sound']['soundstr']
        dm_resp = requests.get(f"https://www.missevan.com/sound/getdm?soundid={sound_id}", headers=headers)
        root = ET.fromstring(dm_resp.content)
        
        items, uids_45 = [], []
        for d in root.findall('.//d'):
            p = d.get('p').split(',')
            if d.text:
                items.append({'t': float(p[0]), 'm': p[1], 'uid': p[6], 'txt': d.text.strip()})
                if p[1] in ['4', '5']: uids_45.append(p[6])
        
        sub_uids = [uid for uid, c in Counter(uids_45).items() if c > 5]
        final = [i for i in items if i['uid'] in sub_uids and i['m'] in ['4', '5']] if sub_uids else items
        final.sort(key=lambda x: x['t'])
        
        # Format kịch bản gốc theo yêu cầu của Khai
        cn_text = f"TITLE: {title}\nNGUỒN: {url}\nSỐ DÒNG: {len(final)}\n" + "-"*30 + "\n"
        for item in final:
            m, s = divmod(int(item['t']), 60)
            cn_text += f"[{m:02d}:{s:02d}] {item['txt']}\n"
            
        return {"title": title, "cn_text": cn_text}, None
    except Exception as e:
        return None, str(e)

# --- TRỤ CỘT 2: PARALLEL BATCH PROCESSING (Dịch đa luồng tốc độ cao) ---
def translate_script_fast(cn_text, batch_size=45, max_workers=4):
    """Chia nhỏ lô và dịch song song để tối ưu tốc độ"""
    translator = GoogleTranslator(source='zh-CN', target='vi')
    lines = cn_text.split('\n')
    translated_dict = {}
    
    # Lọc danh sách thoại cần dịch
    work_list = []
    for line in lines:
        match = re.match(r'(\[.*?\])\s*(.*)', line)
        if match and match.group(2).strip():
            work_list.append((line, match.group(1), match.group(2)))

    total = len(work_list)
    if total == 0: return cn_text

    # Chia nhỏ thành các lô
    batches = [work_list[i : i + batch_size] for i in range(0, total, batch_size)]
    
    progress_bar = st.progress(0, text="Khởi động trình dịch đa luồng...")
    processed_count = 0

    def process_single_batch(batch):
        # Kết nối các thoại bằng dấu xuống dòng kép để Google hiểu là các đoạn rời rạc
        combined_text = "\n\n".join([item[2] for item in batch])
        try:
            translated_combined = translator.translate(combined_text)
            translated_parts = translated_combined.split("\n\n")
            
            local_results = {}
            for idx, item in enumerate(batch):
                orig_line = item[0]
                timestamp = item[1]
                val = translated_parts[idx].strip() if idx < len(translated_parts) else "[Lỗi dịch dòng]"
                local_results[orig_line] = f"{timestamp} {val}"
            return local_results
        except:
            # Nếu dịch lô lỗi, dịch lẻ từng dòng trong lô đó (Safety Fallback)
            return {item[0]: f"{item[1]} {translator.translate(item[2])}" for item in batch}

    # Thực thi đa luồng
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process_single_batch, b) for b in batches]
        for future in futures:
            result = future.result()
            translated_dict.update(result)
            processed_count += len(result)
            progress_bar.progress(processed_count / total, text=f"⚡ Đang dịch tốc độ cao: {processed_count}/{total} dòng")
            time.sleep(0.1) # Giảm áp lực cho UI thread

    progress_bar.empty()
    
    # Ghép lại kịch bản hoàn chỉnh dựa trên map kết quả
    final_output = []
    for line in lines:
        final_output.append(translated_dict.get(line, line))
    
    return "\n".join(final_output)

# 2. Sidebar - Thanh quản lý
with st.sidebar:
    st.header("⚙️ Hệ thống")
    cookie = st.text_input("Cookie Missevan (nếu có):", type="password")
    st.divider()
    if st.button("🧹 Xóa bộ nhớ đệm (Clear Cache)"):
        st.cache_data.clear()
        st.session_state.cn_data = None
        st.session_state.vi_data = None
        st.rerun()

# 3. Giao diện chính
url_input = st.text_input("Dán link Missevan:", placeholder="https://www.missevan.com/sound/...")

# Quản lý trạng thái bằng Session State
if 'cn_data' not in st.session_state: st.session_state.cn_data = None
if 'vi_data' not in st.session_state: st.session_state.vi_data = None

# Nút xử lý chính
if st.button("🚀 Bóc tách kịch bản", use_container_width=True):
    if url_input:
        data, err = get_missevan_script(url_input, cookie)
        if data:
            st.session_state.cn_data = data
            st.session_state.vi_data = None # Xóa bản dịch cũ của link trước đó
            st.rerun()
        else:
            st.error(f"Lỗi: {err}")

# --- TRỤ CỘT 3: OPTIMIZED UI (Phân luồng hiển thị) ---
if st.session_state.cn_data:
    data = st.session_state.cn_data
    safe_title = re.sub(r'[\\/*?:"<>|]', '', data['title'])
    
    # Khu vực nút tải phía trên
    dl_col1, dl_col2 = st.columns(2)
    with dl_col1:
        st.download_button(
            "📥 Tải Bản Gốc (CN)", 
            data['cn_text'], 
            f"CN_{safe_title}.txt", 
            use_container_width=True
        )
    with dl_col2:
        if st.session_state.vi_data:
            st.download_button(
                "📥 Tải Bản Dịch (VI)", 
                st.session_state.vi_data, 
                f"VI_{safe_title}.txt", 
                use_container_width=True
            )
        else:
            st.button("📥 Đang dịch ngầm... (Vui lòng đợi)", disabled=True, use_container_width=True)

    st.divider()

    # Khu vực hiển thị nội dung
    txt_col1, txt_col2 = st.columns(2)
    with txt_col1:
        st.subheader("🇨🇳 Nội dung gốc")
        st.code(data['cn_text'], language="text")
        
    with txt_col2:
        st.subheader("🇻🇳 Bản dịch tiếng Việt")
        if st.session_state.vi_data is None:
            # Tự động kích hoạt trình dịch khi thấy text gốc đã hiện diện
            with st.container():
                vi_result = translate_script_fast(data['cn_text'])
                st.session_state.vi_data = vi_result
                st.rerun()
        else:
            st.code(st.session_state.vi_data, language="text")

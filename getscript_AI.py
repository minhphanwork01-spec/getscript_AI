import streamlit as st
import requests
import xml.etree.ElementTree as ET
import re
from collections import Counter
from urllib.parse import urlparse, parse_qs
from deep_translator import GoogleTranslator, MyMemoryTranslator
from concurrent.futures import ThreadPoolExecutor, as_completed
import time


# =========================================================
# 1. CONFIG
# =========================================================

st.set_page_config(
    page_title="Missevan Sub Tool Pro",
    page_icon="🎙️",
    layout="wide"
)

st.title("🎙️ Missevan Sub Tool Pro")
st.caption("Caching + Safe Request + Controlled Batch Translation")


DEFAULT_TIMEOUT = 15

# Thêm tên riêng ở đây nếu cần.
# Ví dụ:
# GLOSSARY = {
#     "沈清秋": "Thẩm Thanh Thu",
#     "洛冰河": "Lạc Băng Hà",
# }
GLOSSARY = {}


# =========================================================
# 2. HELPER FUNCTIONS
# =========================================================

def extract_sound_id(url: str):
    """Lấy sound_id từ query ?id= hoặc từ path cuối URL."""
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)

    sound_id = query_params.get("id", [None])[0]

    if not sound_id:
        sound_id = next(
            (p for p in reversed(parsed_url.path.split("/")) if p.isdigit()),
            None
        )

    return sound_id


def safe_filename(name: str, max_len: int = 120):
    """Làm sạch title để dùng làm tên file."""
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:max_len] if name else "missevan_script"


def clean_cn_line(text: str):
    """Làm sạch nhẹ dòng thoại trước khi dịch."""
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[~～]{2,}", "～", text)
    return text


def protect_glossary_terms(text: str, glossary: dict):
    """
    Thay tên riêng bằng token để giảm khả năng máy dịch phá tên.
    """
    mapping = {}

    for idx, (term, vi_name) in enumerate(glossary.items()):
        token = f"__NAME_{idx}__"
        if term in text:
            text = text.replace(term, token)
            mapping[token] = vi_name

    return text, mapping


def restore_glossary_terms(text: str, mapping: dict):
    """Khôi phục token glossary thành tên Việt."""
    for token, vi_name in mapping.items():
        text = text.replace(token, vi_name)
    return text


def get_translator(engine: str):
    """
    Tạo translator mới cho từng batch/thread.
    Không dùng chung object translator giữa nhiều thread.
    """
    if engine == "GoogleTranslator":
        return GoogleTranslator(source="zh-CN", target="vi")

    if engine == "MyMemoryTranslator":
        return MyMemoryTranslator(source="zh-CN", target="vi")

    raise ValueError(f"Engine không hỗ trợ: {engine}")


# =========================================================
# 3. MISSEVAN FETCHER
# =========================================================

@st.cache_data(show_spinner=False)
def get_missevan_script(
    url: str,
    cookie_str: str,
    min_sub_lines_per_uid: int = 5,
    timeout: int = DEFAULT_TIMEOUT
):
    """
    Truy xuất dữ liệu XML từ Missevan và chuẩn hóa kịch bản gốc.
    Cache theo url, cookie, min_sub_lines_per_uid.
    """
    try:
        sound_id = extract_sound_id(url)

        if not sound_id:
            return None, "Không lấy được sound_id từ URL. Hãy kiểm tra lại link Missevan."

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": url,
        }

        if cookie_str:
            headers["Cookie"] = cookie_str

        info_url = f"https://www.missevan.com/sound/getsound?soundid={sound_id}"
        dm_url = f"https://www.missevan.com/sound/getdm?soundid={sound_id}"

        info_resp = requests.get(info_url, headers=headers, timeout=timeout)
        info_resp.raise_for_status()

        try:
            info = info_resp.json()
        except Exception:
            return None, "Response getsound không phải JSON hợp lệ."

        if not info.get("success"):
            return None, "Không tìm thấy dữ liệu âm thanh hoặc cần cookie đăng nhập."

        try:
            title = info["info"]["sound"]["soundstr"]
        except KeyError:
            title = f"sound_{sound_id}"

        dm_resp = requests.get(dm_url, headers=headers, timeout=timeout)
        dm_resp.raise_for_status()

        try:
            root = ET.fromstring(dm_resp.content)
        except ET.ParseError:
            return None, "Không parse được XML danmaku/subtitle."

        items = []
        uids_45 = []

        for d in root.findall(".//d"):
            p_attr = d.get("p")

            if not p_attr or not d.text:
                continue

            p = p_attr.split(",")

            # Format p thường có nhiều field, cần p[0], p[1], p[6]
            if len(p) < 7:
                continue

            try:
                timestamp = float(p[0])
            except ValueError:
                continue

            mode = p[1]
            uid = p[6]
            text = d.text.strip()

            if not text:
                continue

            item = {
                "t": timestamp,
                "m": mode,
                "uid": uid,
                "txt": text
            }

            items.append(item)

            if mode in ["4", "5"]:
                uids_45.append(uid)

        if not items:
            return None, "Không tìm thấy dòng subtitle/danmaku nào trong XML."

        uid_counter = Counter(uids_45)

        sub_uids = [
            uid for uid, count in uid_counter.items()
            if count >= min_sub_lines_per_uid
        ]

        # Nếu nhận diện được UID subtitle thì chỉ lấy mode 4/5 của UID đó.
        # Nếu không nhận diện được thì fallback lấy toàn bộ items.
        if sub_uids:
            final_items = [
                item for item in items
                if item["uid"] in sub_uids and item["m"] in ["4", "5"]
            ]
            filter_note = (
                f"Đã lọc theo UID subtitle: {len(sub_uids)} UID, "
                f"ngưỡng >= {min_sub_lines_per_uid} dòng."
            )
        else:
            final_items = items
            filter_note = (
                "Không nhận diện được UID subtitle rõ ràng, "
                "đang fallback lấy toàn bộ danmaku/subtitle."
            )

        final_items.sort(key=lambda x: x["t"])

        cn_lines = [
            f"TITLE: {title}",
            f"NGUỒN: {url}",
            f"SOUND_ID: {sound_id}",
            f"SỐ DÒNG: {len(final_items)}",
            f"FILTER: {filter_note}",
            "-" * 30
        ]

        for item in final_items:
            m, s = divmod(int(item["t"]), 60)
            cn_lines.append(f"[{m:02d}:{s:02d}] {item['txt']}")

        cn_text = "\n".join(cn_lines)

        return {
            "title": title,
            "sound_id": sound_id,
            "cn_text": cn_text,
            "line_count": len(final_items),
            "filter_note": filter_note
        }, None

    except requests.exceptions.Timeout:
        return None, "Request timeout. Missevan phản hồi quá chậm hoặc host đang bị nghẽn."

    except requests.exceptions.HTTPError as e:
        return None, f"Lỗi HTTP khi gọi Missevan: {e}"

    except requests.exceptions.RequestException as e:
        return None, f"Lỗi kết nối khi gọi Missevan: {e}"

    except Exception as e:
        return None, f"Lỗi không xác định: {e}"


# =========================================================
# 4. TRANSLATION
# =========================================================

def translate_script_fast(
    cn_text: str,
    engine: str = "GoogleTranslator",
    batch_size: int = 35,
    max_workers: int = 3,
    sleep_between_updates: float = 0.05
):
    """
    Dịch script theo batch, có fallback từng dòng.
    Chỉ dịch các dòng có timestamp dạng [mm:ss].
    """
    lines = cn_text.split("\n")
    translated_dict = {}

    work_list = []

    for idx, line in enumerate(lines):
        match = re.match(r"(\[.*?\])\s*(.*)", line)

        if not match:
            continue

        timestamp = match.group(1)
        text = match.group(2).strip()

        if not text:
            continue

        cleaned_text = clean_cn_line(text)

        work_list.append({
            "idx": idx,
            "orig_line": line,
            "timestamp": timestamp,
            "text": cleaned_text
        })

    total = len(work_list)

    if total == 0:
        return cn_text

    batches = [
        work_list[i:i + batch_size]
        for i in range(0, total, batch_size)
    ]

    progress_bar = st.progress(0, text="Khởi động trình dịch...")
    status_box = st.empty()

    processed_count = 0
    error_count = 0

    def translate_single_line(translator, item):
        """Dịch từng dòng, có glossary protection."""
        original_text = item["text"]

        protected_text, mapping = protect_glossary_terms(original_text, GLOSSARY)

        try:
            translated = translator.translate(protected_text)
            translated = restore_glossary_terms(translated, mapping)
            return f"{item['timestamp']} {translated}", None
        except Exception as e:
            return f"{item['timestamp']} [Lỗi dịch] {original_text}", str(e)

    def process_single_batch(batch):
        """
        Dịch một batch.
        Nếu batch lỗi hoặc số đoạn dịch không khớp, fallback dịch từng dòng.
        """
        local_results = {}
        local_errors = 0

        translator = get_translator(engine)

        sep_token = "<|SEP_9527|>"
        sep = f"\n{sep_token}\n"

        protected_texts = []
        mappings = []

        for item in batch:
            protected_text, mapping = protect_glossary_terms(item["text"], GLOSSARY)
            protected_texts.append(protected_text)
            mappings.append(mapping)

        combined_text = sep.join(protected_texts)

        try:
            translated_combined = translator.translate(combined_text)
            translated_parts = translated_combined.split(sep_token)

            if len(translated_parts) == len(batch):
                for idx, item in enumerate(batch):
                    translated = translated_parts[idx].strip()
                    translated = restore_glossary_terms(translated, mappings[idx])
                    local_results[item["orig_line"]] = f"{item['timestamp']} {translated}"

                return local_results, local_errors

        except Exception:
            pass

        # Fallback: dịch từng dòng nếu batch lỗi hoặc split không khớp.
        for item in batch:
            translated_line, err = translate_single_line(translator, item)

            if err:
                local_errors += 1

            local_results[item["orig_line"]] = translated_line

        return local_results, local_errors

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_batch = {
            executor.submit(process_single_batch, batch): batch
            for batch in batches
        }

        for future in as_completed(future_to_batch):
            batch = future_to_batch[future]

            try:
                result, local_errors = future.result()
            except Exception as e:
                result = {}
                local_errors = len(batch)

                for item in batch:
                    result[item["orig_line"]] = (
                        f"{item['timestamp']} [Lỗi dịch batch] {item['text']}"
                    )

            translated_dict.update(result)
            processed_count += len(batch)
            error_count += local_errors

            progress = min(processed_count / total, 1.0)

            progress_bar.progress(
                progress,
                text=f"⚡ Đang dịch: {processed_count}/{total} dòng"
            )

            if error_count:
                status_box.warning(f"Số dòng fallback/lỗi dịch: {error_count}")
            else:
                status_box.info("Đang dịch batch, chưa ghi nhận lỗi.")

            time.sleep(sleep_between_updates)

    progress_bar.empty()

    if error_count:
        status_box.warning(f"Hoàn tất dịch. Có {error_count} dòng bị fallback/lỗi.")
    else:
        status_box.success("Hoàn tất dịch.")

    final_output = []

    for line in lines:
        final_output.append(translated_dict.get(line, line))

    return "\n".join(final_output)


# =========================================================
# 5. SIDEBAR
# =========================================================

with st.sidebar:
    st.header("⚙️ Cấu hình")

    cookie = st.text_input(
        "Cookie Missevan nếu cần:",
        type="password",
        help="Chỉ cần nhập nếu audio cần đăng nhập hoặc bị giới hạn."
    )

    st.divider()

    min_sub_lines = st.number_input(
        "Ngưỡng nhận diện UID subtitle:",
        min_value=1,
        max_value=50,
        value=5,
        step=1,
        help="UID có số dòng mode 4/5 >= ngưỡng này sẽ được xem là người đăng subtitle."
    )

    request_timeout = st.number_input(
        "Request timeout giây:",
        min_value=5,
        max_value=60,
        value=15,
        step=5
    )

    st.divider()

    translator_engine = st.selectbox(
        "Engine dịch:",
        ["GoogleTranslator", "MyMemoryTranslator"],
        index=0,
        help="GoogleTranslator thường ổn hơn cho Trung → Việt. MyMemory dùng như fallback/thử nghiệm."
    )

    batch_size = st.number_input(
        "Batch size:",
        min_value=5,
        max_value=80,
        value=35,
        step=5,
        help="Batch càng lớn càng nhanh nhưng dễ lỗi/rate-limit hơn."
    )

    max_workers = st.number_input(
        "Số luồng dịch:",
        min_value=1,
        max_value=6,
        value=3,
        step=1,
        help="Web host yếu nên dùng 2-3. Dùng quá cao dễ bị dịch lỗi."
    )

    st.divider()

    if st.button("🧹 Xóa bộ nhớ đệm / Reset", use_container_width=True):
        st.cache_data.clear()
        st.session_state.cn_data = None
        st.session_state.vi_data = None
        st.session_state.last_url = ""
        st.rerun()


# =========================================================
# 6. SESSION STATE INIT
# =========================================================

if "cn_data" not in st.session_state:
    st.session_state.cn_data = None

if "vi_data" not in st.session_state:
    st.session_state.vi_data = None

if "last_url" not in st.session_state:
    st.session_state.last_url = ""


# =========================================================
# 7. MAIN UI
# =========================================================

url_input = st.text_input(
    "Dán link Missevan:",
    placeholder="https://www.missevan.com/sound/..."
)

col_a, col_b = st.columns([1, 1])

with col_a:
    extract_clicked = st.button(
        "🚀 Bóc tách kịch bản",
        use_container_width=True
    )

with col_b:
    clear_current_clicked = st.button(
        "🗑️ Xóa kết quả hiện tại",
        use_container_width=True
    )

if clear_current_clicked:
    st.session_state.cn_data = None
    st.session_state.vi_data = None
    st.session_state.last_url = ""
    st.rerun()


# =========================================================
# 8. EXTRACT SCRIPT
# =========================================================

if extract_clicked:
    if not url_input.strip():
        st.error("Bạn chưa nhập link Missevan.")
    else:
        with st.spinner("Đang bóc tách dữ liệu từ Missevan..."):
            data, err = get_missevan_script(
                url=url_input.strip(),
                cookie_str=cookie.strip(),
                min_sub_lines_per_uid=int(min_sub_lines),
                timeout=int(request_timeout)
            )

        if data:
            st.session_state.cn_data = data
            st.session_state.vi_data = None
            st.session_state.last_url = url_input.strip()
            st.success("Bóc tách kịch bản thành công.")
            st.rerun()
        else:
            st.error(f"Lỗi: {err}")


# =========================================================
# 9. DISPLAY + DOWNLOAD + TRANSLATE
# =========================================================

if st.session_state.cn_data:
    data = st.session_state.cn_data
    safe_title = safe_filename(data["title"])

    st.info(
        f"Đã lấy được {data.get('line_count', 0)} dòng. "
        f"{data.get('filter_note', '')}"
    )

    st.divider()

    btn_col1, btn_col2, btn_col3 = st.columns(3)

    with btn_col1:
        st.download_button(
            "📥 Tải bản gốc CN",
            data["cn_text"],
            f"CN_{safe_title}.txt",
            mime="text/plain",
            use_container_width=True
        )

    with btn_col2:
        translate_clicked = st.button(
            "🌐 Dịch sang tiếng Việt",
            use_container_width=True
        )

    with btn_col3:
        if st.session_state.vi_data:
            st.download_button(
                "📥 Tải bản dịch VI",
                st.session_state.vi_data,
                f"VI_{safe_title}.txt",
                mime="text/plain",
                use_container_width=True
            )
        else:
            st.button(
                "📥 Chưa có bản dịch",
                disabled=True,
                use_container_width=True
            )

    if translate_clicked:
        with st.spinner("Đang dịch. Không đóng tab trong lúc xử lý..."):
            vi_result = translate_script_fast(
                cn_text=data["cn_text"],
                engine=translator_engine,
                batch_size=int(batch_size),
                max_workers=int(max_workers)
            )

        st.session_state.vi_data = vi_result
        st.success("Dịch xong.")
        st.rerun()

    st.divider()

    txt_col1, txt_col2 = st.columns(2)

    with txt_col1:
        st.subheader("🇨🇳 Nội dung gốc")
        st.code(data["cn_text"], language="text")

    with txt_col2:
        st.subheader("🇻🇳 Bản dịch tiếng Việt")

        if st.session_state.vi_data:
            st.code(st.session_state.vi_data, language="text")
        else:
            st.warning("Chưa có bản dịch. Bấm nút “Dịch sang tiếng Việt” để bắt đầu.")

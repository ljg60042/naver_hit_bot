import os
import tkinter as tk
from tkinter import ttk, messagebox
import threading
from config import CafeConfig, CafeTarget
from crawler import NaverCafeViewAutomation
from post_info import fetch_post_info

URL_FILE = "urls.txt"
TITLE_MAX_LEN = 18
CHECK_ON = "☑"
CHECK_OFF = "☐"


def truncate_title(title: str, max_len: int = TITLE_MAX_LEN) -> str:
    if title and len(title) > max_len:
        return title[:max_len - 1].rstrip() + "…"
    return title or ""

class AppGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("네이버 카페 조회수 자동화")
        self.root.geometry("930x640")
        self.root.resizable(False, False)

        self.bot_thread = None
        self.bot = None
        self.selected_item = None
        self.title_map = {}  # item_id -> 잘리지 않은 전체 제목
        self.checked_items = set()  # 체크박스로 선택된 item_id 목록
        self._run_items = []  # 마지막으로 시작한 자동화 작업의 대상 item_id 목록(진행 상황 인덱스 매핑용)
        self._tooltip = None
        self._tooltip_item = None

        self.setup_styles()
        self.create_widgets()
        
        # 프로그램 시작 시 저장된 URL 로드 및 최신 조회수 동기화 실행
        self.load_saved_urls()
        
        # 창 X 버튼 클릭 이벤트 연결
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def setup_styles(self):
        self.BG_MAIN = "#f3f3f3"
        self.BG_HEADER = "#e6e6ea"

        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.map(
            "Treeview",
            background=[("selected", "#0078d7")],
            foreground=[("selected", "#ffffff")]
        )

        # 전체 화면을 하나의 밝은 톤으로 통일
        self.root.configure(bg=self.BG_MAIN)
        self.style.configure("TFrame", background=self.BG_MAIN)
        self.style.configure("TLabelframe", background=self.BG_MAIN)
        self.style.configure("TLabelframe.Label", background=self.BG_MAIN, font=("맑은 고딕", 9, "bold"))
        self.style.configure("TLabel", background=self.BG_MAIN)

        # 목록 헤더 셀 전용 스타일 (살짝 더 짙은 톤으로 구분)
        self.style.configure("Header.TLabel", background=self.BG_HEADER, font=("맑은 고딕", 9, "bold"))

    def create_widgets(self):
        log_frame = ttk.LabelFrame(self.root, text=" 실행 로그 ", padding=10)
        log_frame.pack(fill="both", expand=True, padx=15, pady=(10, 8))

        self.txt_log = tk.Text(
            log_frame, state="disabled", bg="#ffffff", fg="#1a1a1a", insertbackground="#1a1a1a",
            font=("Consolas", 9), height=10, relief="flat",
            highlightthickness=1, highlightbackground="#cccccc", highlightcolor="#cccccc"
        )
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=log_scroll.set)

        self.txt_log.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

        url_frame = ttk.LabelFrame(self.root, text=" 타겟 카페 게시글 정보 관리 ", padding=10)
        url_frame.pack(fill="x", padx=15, pady=8)

        input_frame = ttk.Frame(url_frame)
        input_frame.pack(fill="x", pady=(0, 8))

        ttk.Label(input_frame, text="URL:").pack(side="left", padx=(0, 5))
        self.ent_url_input = ttk.Entry(input_frame, width=45)
        self.ent_url_input.pack(side="left", fill="x", expand=True, padx=(0, 10))

        ttk.Label(input_frame, text="목표 횟수:").pack(side="left", padx=(0, 5))
        self.ent_count_input = ttk.Entry(input_frame, width=6)
        self.ent_count_input.insert(0, "10")
        self.ent_count_input.pack(side="left", padx=(0, 10))

        self.btn_submit = ttk.Button(input_frame, text="추가", width=8, command=self.add_url)
        self.btn_submit.pack(side="left", padx=(0, 4))

        self.btn_delete = ttk.Button(input_frame, text="삭제", width=8, command=self.delete_checked_urls)
        self.btn_delete.pack(side="left", padx=(0, 4))

        self.btn_reset = ttk.Button(input_frame, text="초기화", width=8, command=self.reset_input_form)
        self.btn_reset.pack(side="left")

        # =========================================================================
        # [수정] 컬럼 순서 변경: URL -> 제목 -> 진행 상황 -> 조회수(작업전/작업후)
        # =========================================================================
        grid_container = ttk.Frame(url_frame)
        grid_container.pack(fill="x", pady=(0, 8))

        # 상단 헤더 프레임
        header_frame = ttk.Frame(grid_container)
        header_frame.pack(fill="x")

        # 0열: 전체 선택 체크박스 (행 체크박스와 동일한 글리프를 쓰는 커스텀 라벨)
        self.lbl_select_all = ttk.Label(
            header_frame, text=CHECK_OFF, anchor="center", style="Header.TLabel", cursor="hand2"
        )
        self.lbl_select_all.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.lbl_select_all.bind("<Button-1>", lambda event: self.toggle_all_checks())

        # 1열: 카페 게시글 URL
        lbl_h_url = ttk.Label(header_frame, text="카페 게시글 URL", anchor="center", relief="solid", borderwidth=1, style="Header.TLabel")
        lbl_h_url.grid(row=0, column=1, rowspan=2, sticky="nsew", ipady=4)

        # 2열: 게시글 제목
        lbl_h_title = ttk.Label(header_frame, text="게시글 제목", anchor="center", relief="solid", borderwidth=1, style="Header.TLabel")
        lbl_h_title.grid(row=0, column=2, rowspan=2, sticky="nsew", ipady=4)

        # 3열: 진행 상황 (현재/목표)
        lbl_h_count = ttk.Label(header_frame, text="진행 상황 (현재/목표)", anchor="center", relief="solid", borderwidth=1, style="Header.TLabel")
        lbl_h_count.grid(row=0, column=3, rowspan=2, sticky="nsew", ipady=4)

        # 4~5열: 조회수 (작업전 / 작업후)
        lbl_h_views_group = ttk.Label(header_frame, text="조회수", anchor="center", relief="solid", borderwidth=1, style="Header.TLabel")
        lbl_h_views_group.grid(row=0, column=4, columnspan=2, sticky="nsew", ipady=2)

        lbl_h_views_before = ttk.Label(header_frame, text="작업전", anchor="center", relief="solid", borderwidth=1, style="Header.TLabel")
        lbl_h_views_before.grid(row=1, column=4, sticky="nsew", ipady=2)

        lbl_h_views_after = ttk.Label(header_frame, text="작업후", anchor="center", relief="solid", borderwidth=1, style="Header.TLabel")
        lbl_h_views_after.grid(row=1, column=5, sticky="nsew", ipady=2)

        # 상단 헤더 열 너비를 Treeview 컬럼과 동일하게 맞춤.
        # "제목" 컬럼 하나에만 남는 공간을 몰아줘서(weight=1) 창을 넓혀도
        # 헤더-본문 경계가 어긋나지 않으면서 트레일링 빈 공간도 생기지 않게 함.
        header_frame.columnconfigure(0, weight=0, minsize=32)  # 체크박스
        header_frame.columnconfigure(1, weight=0, minsize=310) # URL
        header_frame.columnconfigure(2, weight=1, minsize=240) # 제목 (남는 폭 흡수)
        header_frame.columnconfigure(3, weight=0, minsize=130) # 진행 상황
        header_frame.columnconfigure(4, weight=0, minsize=65)  # 작업전
        header_frame.columnconfigure(5, weight=0, minsize=65)  # 작업후

        # 본문 목록 Treeview
        list_frame = ttk.Frame(grid_container)
        list_frame.pack(fill="x")

        # 컬럼 순서 설정
        columns = ("url", "title", "count", "views_before", "views_after")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="tree", height=8, selectmode="browse")
        self.style.configure("Treeview", indent=0)  # 체크박스용 #0 컬럼의 확장 화살표 여백 제거

        # 체크박스 전용 컬럼(#0)과 각 데이터 컬럼 너비 설정
        # (헤더와 동일하게 "제목" 컬럼만 stretch=True로 남는 폭을 흡수)
        self.tree.column("#0", width=32, minwidth=32, anchor="center", stretch=False)
        self.tree.column("url", width=310, anchor="w", stretch=False)
        self.tree.column("title", width=240, anchor="w", stretch=True)
        self.tree.column("count", width=130, anchor="center", stretch=False)
        self.tree.column("views_before", width=65, anchor="center", stretch=False)
        self.tree.column("views_after", width=65, anchor="center", stretch=False)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side="left", fill="x", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewSelect>>", self.on_select_row)
        self.tree.bind("<Motion>", self.on_tree_motion)
        self.tree.bind("<Leave>", self.hide_tooltip)
        self.tree.bind("<Button-1>", self.on_tree_click)

        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill="x", padx=15, pady=8)

        self.btn_start = ttk.Button(btn_frame, text="작업 시작", command=self.start_automation)
        self.btn_start.pack(side="left", expand=True, fill="x", padx=(0, 5))

        self.btn_stop = ttk.Button(btn_frame, text="작업 정지", command=self.stop_automation, state="disabled")
        self.btn_stop.pack(side="right", expand=True, fill="x", padx=(5, 0))

    def set_entry_text(self, entry: ttk.Entry, text: str, readonly: bool = False):
        entry.config(state="normal")
        entry.delete(0, tk.END)
        entry.insert(0, text)
        if readonly:
            entry.config(state="readonly")

    def reset_input_form(self):
        self.selected_item = None
        if self.tree.selection():
            self.tree.selection_remove(self.tree.selection())

        self.set_entry_text(self.ent_url_input, "", readonly=False)
        self.set_entry_text(self.ent_count_input, "10", readonly=False)
        self.btn_submit.config(text="추가", command=self.add_url)

    def on_select_row(self, event):
        selected_items = self.tree.selection()
        if not selected_items:
            return

        self.selected_item = selected_items[0]
        values = self.tree.item(self.selected_item, "values")
        url = values[0]                             # URL 인덱스 = 0
        target_count = values[2].split("/")[-1].strip() # 진행 상황 인덱스 = 2

        self.set_entry_text(self.ent_url_input, url, readonly=True)
        self.set_entry_text(self.ent_count_input, target_count, readonly=False)
        self.btn_submit.config(text="수정", command=self.update_selected_url)

    def on_tree_motion(self, event):
        row_id = self.tree.identify_row(event.y)
        col_id = self.tree.identify_column(event.x)

        # "title" 컬럼(#2)이 아니거나 행이 없으면 툴팁 숨김
        if not row_id or col_id != "#2":
            self.hide_tooltip()
            return

        full_title = self.title_map.get(row_id, "")
        displayed = self.tree.set(row_id, "title")
        if not full_title or full_title == displayed:
            self.hide_tooltip()
            return

        x = event.x_root + 15
        y = event.y_root + 10

        if self._tooltip_item == row_id and self._tooltip is not None:
            self._tooltip.wm_geometry(f"+{x}+{y}")
            return

        self.hide_tooltip()
        tw = tk.Toplevel(self.root)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tw, text=full_title, justify="left", background="#ffffe0",
            relief="solid", borderwidth=1, font=("맑은 고딕", 9), padx=6, pady=3
        ).pack()
        self._tooltip = tw
        self._tooltip_item = row_id

    def hide_tooltip(self, event=None):
        if self._tooltip is not None:
            self._tooltip.destroy()
        self._tooltip = None
        self._tooltip_item = None

    def on_tree_click(self, event):
        row_id = self.tree.identify_row(event.y)
        col_id = self.tree.identify_column(event.x)

        if not row_id or col_id != "#0":
            return

        self.toggle_check(row_id)
        return "break"  # 체크박스 클릭이 행 선택(수정 폼 채우기)으로 이어지지 않도록 함

    def toggle_check(self, item_id):
        if item_id in self.checked_items:
            self.checked_items.discard(item_id)
            self.tree.item(item_id, text=CHECK_OFF)
        else:
            self.checked_items.add(item_id)
            self.tree.item(item_id, text=CHECK_ON)
        self.sync_select_all_checkbox()

    def toggle_all_checks(self):
        items = self.tree.get_children()
        all_checked = bool(items) and all(item in self.checked_items for item in items)
        new_state = not all_checked  # 이미 전체 체크된 상태면 전체 해제, 아니면 전체 체크
        for item in items:
            if new_state:
                self.checked_items.add(item)
                self.tree.item(item, text=CHECK_ON)
            else:
                self.checked_items.discard(item)
                self.tree.item(item, text=CHECK_OFF)
        self.lbl_select_all.config(text=CHECK_ON if new_state else CHECK_OFF)

    def sync_select_all_checkbox(self):
        items = self.tree.get_children()
        all_checked = bool(items) and all(item in self.checked_items for item in items)
        self.lbl_select_all.config(text=CHECK_ON if all_checked else CHECK_OFF)

    def set_all_buttons_state(self, enable: bool):
        state = "normal" if enable else "disabled"
        self.btn_submit.config(state=state)
        self.btn_reset.config(state=state)
        self.btn_delete.config(state=state)
        self.btn_start.config(state=state)
        self.btn_stop.config(state="disabled")

    def set_buttons_state(self, is_running: bool):
        state_during_run = "disabled" if is_running else "normal"
        stop_state = "normal" if is_running else "disabled"

        self.btn_submit.config(state=state_during_run)
        self.btn_reset.config(state=state_during_run)
        self.btn_delete.config(state=state_during_run)
        self.btn_start.config(state=state_during_run)
        self.btn_stop.config(state=stop_state)

    def add_url(self):
        self.ent_url_input.config(state="normal")
        url = self.ent_url_input.get().strip()
        count_str = self.ent_count_input.get().strip()

        if not url:
            messagebox.showwarning("경고", "URL을 입력해 주세요.")
            return

        try:
            count = int(count_str)
            if count <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("경고", "목표 횟수는 1 이상의 올바른 숫자로 입력해 주세요.")
            return

        temp_item = self.tree.insert("", tk.END, text=CHECK_OFF, values=(url, "⏳ 게시글 정보 수집 중...", f"0 / {count}", "불러오는 중", "불러오는 중"))
        
        self.btn_submit.config(state="disabled")
        self.btn_reset.config(state="disabled")
        self.append_log(f"게시글 정보를 수집 중입니다: {url}")

        def fetch_task():
            info = fetch_post_info(url)
            if info.ok:
                title = info.title or "제목 없음"
                views = str(info.views)
            else:
                title = f"[{info.error}]"
                views = "0"

            self.root.after(0, lambda: self._finish_add_url(temp_item, title, views, url, count))

        threading.Thread(target=fetch_task, daemon=True).start()

    def _finish_add_url(self, item_id, title, views, url, count):
        if self.tree.exists(item_id):
            self.title_map[item_id] = title
            # (URL, 제목, 진행상황, 조회수(작업전), 조회수(작업후)) - 작업후는 작업 전이므로 공백
            self.tree.item(item_id, values=(url, truncate_title(title), f"0 / {count}", views, ""))
        
        self.save_urls()
        self.reset_input_form()
        
        self.btn_submit.config(state="normal")
        self.btn_reset.config(state="normal")
        self.append_log(f"정보 수집 완료: 제목='{title}', 조회수={views}")

    def update_selected_url(self):
        if not self.selected_item or not self.tree.exists(self.selected_item):
            messagebox.showinfo("안내", "수정할 목록 항목을 먼저 선택해 주세요.")
            return

        count_str = self.ent_count_input.get().strip()

        try:
            count = int(count_str)
            if count <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("경고", "목표 횟수는 1 이상의 올바른 숫자로 입력해 주세요.")
            return

        values = self.tree.item(self.selected_item, "values")
        url, title, views_before, views_after = values[0], values[1], values[3], values[4]
        current_count = values[2].split("/")[0].strip()

        self.tree.item(self.selected_item, values=(url, title, f"{current_count} / {count}", views_before, views_after))
        self.save_urls()
        messagebox.showinfo("완료", "목표 횟수가 수정되었습니다.")
        self.reset_input_form()

    def delete_checked_urls(self):
        to_delete = [item for item in self.checked_items if self.tree.exists(item)]
        if not to_delete:
            messagebox.showinfo("안내", "삭제할 항목의 체크박스를 먼저 선택해 주세요.")
            return

        for item in to_delete:
            self.tree.delete(item)
            self.title_map.pop(item, None)
            self.checked_items.discard(item)

        self.sync_select_all_checkbox()
        self.save_urls()
        self.reset_input_form()

    def update_count_in_tree(self, index: int, current_count: int):
        # 여러 워커 스레드에서 동시에 호출될 수 있으므로 Tk 메인 스레드로 넘겨서 처리
        self.root.after(0, lambda: self._apply_count_update(index, current_count))

    def _apply_count_update(self, index: int, current_count: int):
        # 체크된 항목만 골라 실행한 경우 index는 그 대상 목록 기준이므로 self._run_items를 사용
        items = getattr(self, "_run_items", None) or self.tree.get_children()
        if index < len(items) and self.tree.exists(items[index]):
            item = items[index]
            values = self.tree.item(item, "values")
            url, title, views_before, views_after = values[0], values[1], values[3], values[4]
            target_count = values[2].split("/")[-1].strip()
            self.tree.item(item, values=(url, title, f"{current_count} / {target_count}", views_before, views_after))

    def on_target_complete(self, index: int, new_views: str):
        # 여러 워커 스레드에서 동시에 호출될 수 있으므로 Tk 메인 스레드로 넘겨서 처리
        self.root.after(0, lambda: self._apply_target_complete(index, new_views))

    def _apply_target_complete(self, index: int, new_views: str):
        items = getattr(self, "_run_items", None) or self.tree.get_children()
        if index >= len(items) or not self.tree.exists(items[index]):
            return
        item = items[index]
        values = self.tree.item(item, "values")
        url, title, count_info, views_before = values[0], values[1], values[2], values[3]
        self.tree.item(item, values=(url, title, count_info, views_before, new_views))
        self.save_urls()

    def reset_counts_in_tree(self, items=None):
        for item in (items if items is not None else self.tree.get_children()):
            values = self.tree.item(item, "values")
            url, title, views_before, views_after = values[0], values[1], values[3], values[4]
            target_count = values[2].split("/")[-1].strip()
            # 이전 회차의 "작업후" 값을 이번 회차의 "작업전"으로 이어받고, "작업후"는 다시 공백으로
            new_before = views_after if views_after else views_before
            self.tree.item(item, values=(url, title, f"0 / {target_count}", new_before, ""))

    def update_all_views_in_tree(self, on_complete=None, mark_as_result=False, items=None):
        items = items if items is not None else self.tree.get_children()
        if not items:
            if on_complete:
                on_complete()
            return

        self.append_log("등록된 URL 목록의 최신 조회수를 동기화하는 중입니다...")

        def sync_task():
            for item in items:
                if not self.tree.exists(item):
                    continue
                values = self.tree.item(item, "values")
                url, title, count_info, init_v = values[0], values[1], values[2], values[3]
                full_title = self.title_map.get(item, title)

                info = fetch_post_info(url)
                if info.ok:
                    new_views = str(info.views)
                    new_title = info.title or full_title
                else:
                    new_views = init_v
                    new_title = full_title
                    self.root.after(0, lambda u=url, n=info.error: self.append_log(f"{u} 조회수 갱신 실패: {n}", "WARN"))

                self.root.after(0, lambda it=item, t=new_title, nv=new_views, u=url, c=count_info:
                    self._apply_synced_row(it, t, nv, u, c, mark_as_result)
                )

            self.root.after(0, lambda: self._finish_sync_views(on_complete))

        threading.Thread(target=sync_task, daemon=True).start()

    def _apply_synced_row(self, item, full_title, views, url, count_info, mark_as_result):
        if not self.tree.exists(item):
            return
        self.title_map[item] = full_title
        if mark_as_result:
            # 자동화 작업이 끝난 직후: "작업전"은 그대로 두고 "작업후"만 최신 값으로 채움
            views_before = self.tree.item(item, "values")[3]
            self.tree.item(item, values=(url, truncate_title(full_title), count_info, views_before, views))
        else:
            # 시작 시점 동기화: "작업전"만 최신 값으로 채우고 "작업후"는 작업 전이므로 공백
            self.tree.item(item, values=(url, truncate_title(full_title), count_info, views, ""))

    def _finish_sync_views(self, on_complete=None):
        self.save_urls()
        self.append_log("최신 조회수 동기화 및 저장 완료.", "SUCCESS")
        
        self.set_all_buttons_state(True)
        
        if on_complete:
            on_complete()

    def load_saved_urls(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.title_map.clear()

        if os.path.exists(URL_FILE):
            try:
                with open(URL_FILE, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            parts = line.split("||")
                            if len(parts) >= 5:
                                title, init_v, cur_v, url, count = parts[0], parts[1], parts[2], parts[3], parts[4]
                            elif len(parts) == 4:
                                title, cur_v, url, count = parts[0], parts[1], parts[2], parts[3]
                                init_v = cur_v
                            else:
                                continue
                            # 작업후는 이번 세션에서 실제로 작업이 끝나기 전까지 공백으로 표시
                            new_item = self.tree.insert("", tk.END, text=CHECK_OFF, values=(url, truncate_title(title), f"0 / {count}", init_v, ""))
                            self.title_map[new_item] = title
                
                if self.tree.get_children():
                    self.set_all_buttons_state(False)
                    self.update_all_views_in_tree()

            except Exception as e:
                print(f"URL 파일 불러오기 실패: {e}")

    def save_urls(self):
        try:
            with open(URL_FILE, "w", encoding="utf-8") as f:
                for item in self.tree.get_children():
                    values = self.tree.item(item, "values")
                    url, title, count_info, init_v, cur_v = values[0], values[1], values[2], values[3], values[4]
                    full_title = self.title_map.get(item, title)
                    target_count = count_info.split("/")[-1].strip()
                    f.write(f"{full_title}||{init_v}||{cur_v}||{url}||{target_count}\n")
        except Exception as e:
            print(f"URL 파일 저장 실패: {e}")

    def append_log(self, message: str, level: str = "INFO"):
        # 여러 워커 스레드에서 동시에 호출될 수 있으므로 Tk 메인 스레드로 넘겨서 처리
        self.root.after(0, lambda: self._apply_log(message, level))

    def _apply_log(self, message: str, level: str):
        self.txt_log.config(state="normal")
        self.txt_log.insert(tk.END, f"[{level}] {message}\n")
        self.txt_log.see(tk.END)
        self.txt_log.config(state="disabled")

    def clear_log(self):
        self.txt_log.config(state="normal")
        self.txt_log.delete("1.0", tk.END)
        self.txt_log.config(state="disabled")

    def start_automation(self):
        all_items = self.tree.get_children()
        if not all_items:
            messagebox.showwarning("경고", "최소 하나 이상의 카페 URL을 등록해 주세요.")
            return

        run_items = [item for item in all_items if item in self.checked_items]
        if not run_items:
            messagebox.showwarning("경고", "선택한 게시물이 없습니다.")
            return

        self.clear_log()
        self.append_log(f"체크된 {len(run_items)}개 게시글을 대상으로 작업을 시작합니다.")
        self.reset_counts_in_tree(run_items)
        self._run_items = run_items  # update_count_in_tree에서 진행 상황 인덱스를 매핑하는 데 사용

        targets = []
        for item in run_items:
            values = self.tree.item(item, "values")
            url, title, count_info, init_v, cur_v = values[0], values[1], values[2], values[3], values[4]
            full_title = self.title_map.get(item, title)
            target_count = int(count_info.split("/")[1].strip())
            targets.append(CafeTarget(url=url, title=full_title, initial_views=init_v, views=cur_v, target_count=target_count, current_count=0))

        self.save_urls()

        # 같은 IP에서 요청이 잦으면(워커 2개 동시 실행 포함) 네이버가 조회수 반영을 걸러내는 것으로
        # 확인되어, 워커 1개(순차 실행)로 되돌리고 방문 간격도 다시 넉넉히 둠
        config = CafeConfig(targets=targets, min_sec=15.0, max_sec=30.0, worker_count=1)

        self.bot = NaverCafeViewAutomation(
            config=config,
            log_callback=self.append_log,
            count_callback=self.update_count_in_tree,
            target_complete_callback=self.on_target_complete
        )

        self.bot_thread = threading.Thread(target=self.bot.start_loop, daemon=True)
        self.bot_thread.start()

        self.set_buttons_state(is_running=True)
        self.root.after(500, self.check_thread_completion)

    def check_thread_completion(self):
        if self.bot_thread and self.bot_thread.is_alive():
            self.root.after(500, self.check_thread_completion)
        else:
            self.set_buttons_state(is_running=False)
            # 이번 회차에서 실제로 작업한 항목만 "작업후" 값을 갱신 (체크 안 한 항목은 건드리지 않음)
            run_items = [item for item in self._run_items if self.tree.exists(item)]
            self.update_all_views_in_tree(mark_as_result=True, items=run_items)

    def stop_automation(self):
        if self.bot:
            self.bot.stop()

    def on_closing(self):
        if self.bot:
            self.bot.stop()

        self.save_urls()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = AppGUI(root)
    root.mainloop()
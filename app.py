import streamlit as st
from database.database import SessionLocal, init_db
from models.models import Project, Thread, Message
from api.gemini_client import GeminiClient
import datetime
from google.genai import types
import logging # logging をインポート
from utils.markdown_export import export_message_to_markdown # <-- インポートを追加
from database.crud import ( # インポートを整形
    search_messages, 
    delete_thread, 
    update_thread_name, 
    delete_project, 
    update_project,
    delete_all_threads_in_project, # <-- 新しい関数をインポート
    delete_empty_threads_in_project # <-- 空チャット削除関数をインポート
)
from sqlalchemy import func
from utils.csv_export import get_all_data_as_dataframe, generate_csv_data # <-- CSVエクスポート関数をインポート
import json # json モジュールをインポート
import os # os モジュールをインポート
import re # re モジュールをインポート

# logging の基本設定
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# --- 状態保存/読み込み設定 ---
STATE_FILE = ".last_state.json"

# --- 状態保存ヘルパー関数 ---
def save_last_project_id(project_id: int | None):
    try:
        data = {"last_project_id": project_id}
        with open(STATE_FILE, 'w') as f:
            json.dump(data, f)
        logging.debug(f"Saved last project ID: {project_id} to {STATE_FILE}")
    except Exception as e:
        logging.error(f"Failed to save last state to {STATE_FILE}: {e}")

# --- 状態読み込みヘルパー関数 ---
def load_last_project_id() -> int | None:
    if not os.path.exists(STATE_FILE):
        return None
    try:
        with open(STATE_FILE, 'r') as f:
            data = json.load(f)
        last_id = data.get("last_project_id")
        logging.debug(f"Loaded last project ID: {last_id} from {STATE_FILE}")
        return last_id
    except Exception as e:
        logging.error(f"Failed to load last state from {STATE_FILE}: {e}")
        return None

# --- データベース初期化 ---
init_db()

# --- ★★★ 初期状態設定 ★★★ ---
def set_initial_state():
    """アプリ初回起動時に最後の状態を復元し、新規チャットを開始"""
    # 既に初期化済みであれば何もしない
    if 'initial_state_complete' in st.session_state:
        logging.debug("Initial state already set. Skipping.")
        return
    
    logging.info("Performing initial state setup...")
    last_project_id = load_last_project_id()
    initial_project_id = None
    initial_thread_id = None

    if last_project_id is not None:
        db = SessionLocal()
        try:
            # 最後に使ったプロジェクトが存在するか確認
            last_project = db.query(Project).filter(Project.id == last_project_id).first()
            if last_project:
                initial_project_id = last_project_id
                # 新しいチャットを作成
                threads_count = db.query(func.count(Thread.id)).filter(Thread.project_id == initial_project_id).scalar() or 0
                new_thread = Thread(project_id=initial_project_id, name=f"新しいチャット {threads_count + 1}")
                db.add(new_thread)
                db.commit()
                db.refresh(new_thread)
                initial_thread_id = new_thread.id
                logging.info(f"Restored project {initial_project_id}, created and selected new thread {initial_thread_id}")
            else:
                logging.warning(f"Last project ID {last_project_id} not found in DB. Clearing state.")
                save_last_project_id(None) # 無効なIDはクリア
        except Exception as e:
            logging.error(f"Error setting initial state: {e}")
            if db.is_active:
                 db.rollback()
        finally:
            db.close()

    # --- セッション状態の初期化 --- (読み込んだ値で初期化)
    # この部分は初回のみ実行される
    st.session_state.current_project_id = initial_project_id
    st.session_state.current_thread_id = initial_thread_id
    st.session_state.search_results = None
    st.session_state.show_search_results = False
    st.session_state.editing_project = False
    st.session_state.project_to_edit_id = None
    st.session_state.visible_thread_count = 5 # チャット表示件数もここで初期化
    st.session_state.creating_project = False
    
    # ★★★ 初期化完了フラグを立てる ★★★
    st.session_state.initial_state_complete = True
    logging.info("Initial state setup complete.")

# アプリのメインロジック開始前に初期状態を設定
set_initial_state()
# ★★★ 初期状態設定ここまで ★★★

# --- 定数 --- # モデルリストを定義
AVAILABLE_MODELS = [
    "gemini-2.0-flash", 
    "gemini-2.0-flash-thinking-exp-01-21",
    "gemini-2.0-pro-exp-02-05", 
    "gemini-2.5-pro-exp-03-25"
]

# --- サイドバー --- 
st.sidebar.title("Gemini Search Chat")

# JavaScript for auto-focusing on chat input
# 注: これはStreamlitの制限により完全には機能しない場合がありますが、試してみる価値があります
js_focus_script = """
<script>
    // ページロード後に実行
    document.addEventListener('DOMContentLoaded', function() {
        // chat-inputクラスを持つ要素を探す (Streamlitのチャット入力欄の特徴的なクラス)
        setTimeout(function() {
            const chatInputs = document.querySelectorAll('textarea[data-testid="stChatInput"]');
            if (chatInputs.length > 0) {
                chatInputs[0].focus();
            }
        }, 500); // ページ読み込み完了後に少し待ってからフォーカス
    });
</script>
"""

# --- プロジェクト管理 --- 
st.sidebar.header("プロジェクト")

db = SessionLocal()
try:
    projects = db.query(Project).order_by(Project.name).all()
    project_names = [p.name for p in projects]
    project_map = {p.name: p.id for p in projects}

    # プロジェクト選択
    selected_project_name = st.sidebar.selectbox(
        "プロジェクトを選択", 
        project_names,
        index=project_names.index(next((p.name for p in projects if p.id == st.session_state.current_project_id), None)) if st.session_state.current_project_id and any(p.id == st.session_state.current_project_id for p in projects) else 0,
    )

    if selected_project_name:
        new_project_id = project_map[selected_project_name]
        # プロジェクトが切り替わったらチャット選択もリセット & 状態保存
        if st.session_state.current_project_id != new_project_id:
             st.session_state.current_thread_id = None 
             st.session_state.current_project_id = new_project_id
             save_last_project_id(new_project_id) # ★状態保存
             st.rerun() # 明示的にリランして初期化を促す？
        # 既に選択されているものが再度選ばれた場合は何もしない

    else:
        # プロジェクトが選択されなかった場合 (例: プロジェクトが0件)
        if st.session_state.current_project_id is not None:
             st.session_state.current_project_id = None
             st.session_state.current_thread_id = None
             save_last_project_id(None) # ★状態保存 (クリア)

    # --- 新規プロジェクト作成ボタン --- 
    if st.sidebar.button("新しいプロジェクトを作成", key="create_project_button_sidebar"):
        st.session_state.creating_project = True
        st.session_state.editing_project = False 
        st.session_state.show_search_results = False
        # current_project_id などは main エリアの作成完了時に設定＆保存
        st.rerun()

    # --- プロジェクト操作ボタン (編集/削除) ---
    if st.session_state.current_project_id:
        current_project_id_for_ops = st.session_state.current_project_id # 削除処理用にIDを保持
        current_project_name = next((p.name for p in projects if p.id == current_project_id_for_ops), "不明なプロジェクト")
        
        col_edit, col_delete = st.sidebar.columns(2) 
        
        # 編集ボタン
        with col_edit:
            if st.button("⚙️ 編集", key="edit_project_button", use_container_width=True):
                st.session_state.editing_project = True
                st.session_state.project_to_edit_id = current_project_id_for_ops
                st.session_state.creating_project = False # 他のモード解除
                st.session_state.show_search_results = False 
                st.rerun() 
        
        # 削除ボタン
        with col_delete:
            if st.button(f"🗑️ 削除", key="delete_project_button", use_container_width=True):
                st.session_state.confirm_delete_project = True 
                st.rerun() 

        # 削除確認メッセージの表示と最終削除処理
        if st.session_state.get("confirm_delete_project", False):
            st.sidebar.warning(f"プロジェクト '{current_project_name}' を削除すると、関連する全てのチャットとメッセージも削除されます。本当に削除しますか？")
            col1_confirm, col2_confirm = st.sidebar.columns(2)
            if col1_confirm.button("はい、削除します", key="confirm_delete_yes"):
                delete_success = delete_project(db, current_project_id_for_ops)
                if delete_success:
                    st.sidebar.success(f"プロジェクト '{current_project_name}' を削除しました。")
                    st.session_state.current_project_id = None
                    st.session_state.current_thread_id = None
                    st.session_state.confirm_delete_project = False 
                    save_last_project_id(None) # ★状態保存 (クリア)
                    st.rerun() 
                else:
                    st.sidebar.error("プロジェクトの削除に失敗しました。")
                    st.session_state.confirm_delete_project = False 
                    st.rerun()
            if col2_confirm.button("キャンセル", key="confirm_delete_no"):
                st.session_state.confirm_delete_project = False 
                st.rerun()

    # --- チャット管理 --- (プロジェクトが選択されている場合のみ表示)
    if st.session_state.current_project_id:
        current_project_id = st.session_state.current_project_id
        threads = db.query(Thread).filter(Thread.project_id == current_project_id).order_by(Thread.updated_at.desc()).all()
        # logging.info(f"[Sidebar Render] Fetched {len(threads)} threads for project {current_project_id}. Displaying up to {st.session_state.visible_thread_count}") # <-- ログ削除

        # 新規チャット作成ボタン
        if st.sidebar.button("新規チャット"):
            new_thread = Thread(project_id=current_project_id, name=f"新規チャット") # 仮の名前
            db.add(new_thread)
            db.commit()
            db.refresh(new_thread)
            
            # --- ★★★ 空チャットの自動削除 (今作成したチャットは除く) ★★★ ---
            deleted_count = delete_empty_threads_in_project(
                db, 
                current_project_id, 
                exclude_thread_id=new_thread.id # ★ 除外IDを指定
            )
            if deleted_count > 0:
                logging.info(f"{deleted_count} 件の空チャットを自動削除しました。")
            # --- ★★★ 自動削除ここまで ★★★ ---

            st.session_state.current_thread_id = new_thread.id
            st.session_state.show_search_results = False # 検索結果表示中なら解除
            st.session_state.creating_project = False # 他のモードも解除
            st.session_state.editing_project = False
            # st.sidebar.success("新規チャットを開始しました！") # サクセスメッセージは不要（画面遷移するため）
            st.rerun() # 画面を更新して新しいチャットに移動

        # --- ★★★ 検索ボックスとボタンをここに移動 ★★★ ---
        col_search1, col_search2 = st.sidebar.columns([0.7, 0.3]) # 幅を調整
        with col_search1:
            search_query = st.text_input("メッセージを検索", key="search_input", label_visibility="collapsed") # ラベルを非表示に
        with col_search2:
            search_button_pressed = st.button("検索", key="search_button", use_container_width=True)

        if search_button_pressed:
            if search_query:
                db_session = SessionLocal()
                try:
                    results = search_messages(db_session, search_query)
                    # 結果を保存（プロジェクト名とチャット名も取得して付加する）
                    detailed_results = []
                    for msg in results:
                        # 関連するチャットとプロジェクトを取得
                        # N+1 問題を避けるため、本来は JOIN で取得する方が効率的
                        thread = db_session.query(Thread).filter(Thread.id == msg.thread_id).first()
                        project = db_session.query(Project).filter(Project.id == thread.project_id).first() if thread else None
                        detailed_results.append({
                            "message": msg,
                            "thread_name": thread.name if thread else "不明なチャット",
                            "project_name": project.name if project else "不明なプロジェクト",
                            "project_id": thread.project_id if thread else None,
                            "thread_id": msg.thread_id
                        })
                    st.session_state.search_results = detailed_results
                    st.session_state.show_search_results = True 
                    st.session_state.current_thread_id = None 
                    st.session_state.editing_project = False # 他モード解除
                    st.session_state.creating_project = False
                    logging.debug(f"検索を実行しました: Query='{search_query}', Results={len(results)}")
                    st.rerun() 
                finally:
                    db_session.close()
            else:
                st.sidebar.warning("検索キーワードを入力してください。")
                st.session_state.show_search_results = False 
                st.session_state.search_results = None

        # 検索結果表示中はチャット表示に戻るボタンを出す (場所はここでもOK)
        if st.session_state.show_search_results:
            if st.sidebar.button("チャットに戻る", key="back_to_chat_button"):
                st.session_state.show_search_results = False
                st.session_state.search_results = None
                st.rerun()
        # --- ★★★ 検索機能 移動ここまで ★★★ ---

        st.sidebar.divider() # チャットリストの前に区切り線

        # チャット一覧表示 (全件表示)
        selected_thread_id = st.session_state.current_thread_id
        # threads_to_display = threads[:st.session_state.visible_thread_count] # <-- 削除

        if not threads: # チャットが全くない場合
             st.sidebar.caption("まだチャットがありません。")
        else:
            # チャット名と削除ボタンを1行に表示
            for thread in threads: # 全ての threads をループ
                col1, col2 = st.sidebar.columns([0.8, 0.2])
                with col1:
                    # メッセージ数を取得する処理を削除
                    # message_count_query = db.query(func.count(Message.id)).filter(Message.thread_id == thread.id)
                    # message_count = message_count_query.scalar() or 0
                    # thread_label = f"{thread.name} ({message_count} msgs)"
                    
                    # スレッド名のみをラベルとして使用
                    thread_label = thread.name
                    
                    # チャット選択ボタン
                    if st.button(thread_label, key=f"select_thread_{thread.id}", use_container_width=True,
                                  type="primary" if thread.id == selected_thread_id else "secondary"):
                        st.session_state.current_thread_id = thread.id
                        st.session_state.show_search_results = False 
                        st.session_state.editing_project = False 
                        st.rerun()
                with col2:
                    # チャット削除ボタン
                    if st.button("🗑️", key=f"delete_thread_{thread.id}", help="このチャットを削除します"):
                        thread_id_to_delete = thread.id 
                        thread_name_to_delete = thread.name 
                        logging.info(f"[Delete Button Clicked] Attempting to delete thread ID: {thread_id_to_delete}, Name: {thread_name_to_delete}") 
                        delete_success = delete_thread(db, thread_id_to_delete)
                        logging.info(f"[Delete Action] Deletion result for thread {thread_id_to_delete}: {delete_success}") 
                        if delete_success:
                            st.sidebar.success(f"チャット '{thread_name_to_delete}' を削除しました。") 
                            current_selection = st.session_state.current_thread_id
                            if current_selection == thread_id_to_delete:
                                st.session_state.current_thread_id = None
                                logging.info(f"[Delete Action] Current thread selection {current_selection} was deleted, setting to None.") 
                            else:
                                logging.info(f"[Delete Action] Deleted thread {thread_id_to_delete}, current selection {current_selection} remains.") 
                            st.rerun()
                        else:
                            st.sidebar.error(f"チャット '{thread_name_to_delete}' の削除に失敗しました。") 
                
        st.sidebar.divider() # チャットリストの後にも区切り線

        # --- ★ 全チャット一括削除ボタン ★ --- 
        if threads: # チャットが存在する場合のみ表示
            st.sidebar.divider() # 個別チャットとの区切り
            if st.sidebar.button("⚠️ このプロジェクトの全チャット履歴を削除", key="delete_all_threads_button"):
                st.session_state.confirm_delete_all_threads = True # 確認状態をセット
                st.rerun()

            # 確認メッセージと最終削除処理
            if st.session_state.get("confirm_delete_all_threads", False):
                current_project = db.query(Project).filter(Project.id == current_project_id).first() # プロジェクト名表示用
                st.sidebar.warning(f"プロジェクト '{current_project.name if current_project else ''}' の全てのチャット履歴 ({len(threads)}件) を削除します。本当によろしいですか？")
                col1_confirm_all, col2_confirm_all = st.sidebar.columns(2)
                if col1_confirm_all.button("はい、全て削除します", key="confirm_delete_all_yes"):
                    delete_success = delete_all_threads_in_project(db, current_project_id)
                    if delete_success:
                        st.sidebar.success("全ての関連チャット履歴を削除しました。")
                        st.session_state.current_thread_id = None # チャット選択解除
                        st.session_state.confirm_delete_all_threads = False # 確認状態リセット
                        st.rerun()
                    else:
                        st.sidebar.error("全チャット履歴の削除に失敗しました。")
                        st.session_state.confirm_delete_all_threads = False # 確認状態リセット
                        st.rerun()
                if col2_confirm_all.button("キャンセル", key="confirm_delete_all_no"):
                    st.session_state.confirm_delete_all_threads = False # 確認状態リセット
                    st.rerun()
        # --- ★ 一括削除ここまで ★ ---
        else: # チャットがない場合は区切り線だけ表示（任意）
             st.sidebar.divider()

    # --- CSVエクスポート機能 --- 
    st.sidebar.divider()
    st.sidebar.header("エクスポート")

    # ダウンロードボタン表示前にデータを準備
    df_export = get_all_data_as_dataframe(db) 
    csv_data = generate_csv_data(df_export)

    if csv_data:
        st.sidebar.download_button(
            label="全データをCSVでダウンロード",
            data=csv_data,
            file_name="gemini_search_chat_export.csv",
            mime="text/csv",
            key="download_csv_button"
        )
    else:
        st.sidebar.warning("エクスポートするデータがありません。")

finally:
    db.close()

# --- メインコンテンツエリア --- 

# プロジェクト作成モードかどうか (最優先)
if st.session_state.creating_project:
    st.title("新しいプロジェクトを作成")
    db = SessionLocal()
    try:
        with st.form(key="create_project_form"):
            new_project_name = st.text_input("プロジェクト名")
            new_system_prompt = st.text_area("システムプロンプト", value="あなたは役立つアシスタントです。", height=200)
            
            submitted = st.form_submit_button("作成")
            if submitted:
                if new_project_name and new_project_name.strip():
                    existing_project = db.query(Project).filter(Project.name == new_project_name.strip()).first()
                    if not existing_project:
                        new_project = Project(
                            name=new_project_name.strip(), 
                            system_prompt=new_system_prompt
                        )
                        db.add(new_project)
                        db.commit()
                        db.refresh(new_project) # IDを取得
                        st.success(f"プロジェクト '{new_project.name}' を作成しました！")
                        st.session_state.creating_project = False 
                        st.session_state.current_project_id = new_project.id # 作成したプロジェクトを選択
                        st.session_state.current_thread_id = None # チャットは未選択のまま or 新規作成?
                        save_last_project_id(new_project.id) # ★状態保存
                        # ここで新規チャットも作成して選択状態にするか？ 要件に合わせて調整
                        # 現状はプロジェクト選択のみ。次にリロードされると新規チャットが作られる想定。
                        st.rerun()
                    else:
                        st.error("同じ名前のプロジェクトが既に存在します。")
                else:
                    st.warning("プロジェクト名を入力してください。")
        
        if st.button("キャンセル"):
            st.session_state.creating_project = False
            st.rerun()
    finally:
        db.close()

# プロジェクト編集中かどうか (次に優先)
elif st.session_state.editing_project and st.session_state.project_to_edit_id:
    st.title("プロジェクト編集")
    db = SessionLocal()
    try:
        project_to_edit = db.query(Project).filter(Project.id == st.session_state.project_to_edit_id).first()
        if project_to_edit:
            with st.form(key="edit_project_form"):
                st.write(f"プロジェクト ID: {project_to_edit.id}")
                edited_name = st.text_input("プロジェクト名", value=project_to_edit.name)
                edited_system_prompt = st.text_area("システムプロンプト", value=project_to_edit.system_prompt, height=200)
                
                submitted = st.form_submit_button("保存")
                if submitted:
                    update_success = update_project(db, project_to_edit.id, edited_name, edited_system_prompt)
                    if update_success:
                        st.success("プロジェクトを更新しました！")
                        st.session_state.editing_project = False
                        st.session_state.project_to_edit_id = None
                        # 最後に選択していたIDを保存 (名前変更されてもIDは同じ)
                        save_last_project_id(project_to_edit.id) # ★状態保存
                        st.rerun()
                    else:
                        st.error("プロジェクトの更新に失敗しました。名前が重複している可能性があります。")
            
            if st.button("キャンセル"):
                st.session_state.editing_project = False
                st.session_state.project_to_edit_id = None
                st.rerun()
        else:
            st.error("編集対象のプロジェクトが見つかりません。")
            st.session_state.editing_project = False
            st.session_state.project_to_edit_id = None
    finally:
        db.close()

# 次に検索結果表示モードかどうかをチェック
elif st.session_state.show_search_results:
    st.title("検索結果")
    results = st.session_state.search_results
    if results:
        st.write(f"{len(results)} 件のメッセージが見つかりました。")
        
        # 検索キーワードを取得（サイドバーの検索ボックスから）
        search_terms = st.session_state.get("search_input", "").strip().split()
        
        for result in results:
            msg = result["message"]
            # 検索結果カードのヘッダー
            st.markdown(f"### **{result['project_name']}** / **{result['thread_name']}** ({msg.created_at.strftime('%Y-%m-%d %H:%M')}) - {msg.role}")
            
            # メッセージ内容を表示（検索キーワードをハイライト）
            content = msg.content
            if search_terms:
                # 検索キーワードごとにハイライト
                for term in search_terms:
                    if term.strip():  # 空の検索語を除外
                        # 大文字小文字を区別せずにキーワードを強調表示
                        pattern = re.compile(re.escape(term), re.IGNORECASE)
                        # matched_text はキーワードが一致した元のテキスト（大文字/小文字を保持）
                        content = pattern.sub(lambda m: f"<span style='background-color: #0000FF; font-weight: bold;'>{m.group(0)}</span>", content)
            
            # HTMLタグが解釈されるようにunsafe_allow_htmlをTrueに設定
            st.markdown(content, unsafe_allow_html=True)
            
            # 検索結果から該当チャットにジャンプするボタン
            if st.button(f"このチャットを開く ({result['thread_name']})", key=f"goto_thread_{msg.id}"):
                st.session_state.current_project_id = result['project_id']
                st.session_state.current_thread_id = result['thread_id']
                st.session_state.show_search_results = False 
                st.session_state.editing_project = False # 他のモード解除
                st.session_state.creating_project = False
                save_last_project_id(result['project_id']) # ★状態保存
                st.rerun()
            # セパレータで検索結果を区切る
            st.divider()
    else:
        st.info("検索条件に一致するメッセージは見つかりませんでした。")

else:
    # --- 通常のチャット表示 --- 
    st.title("Chat")

    if st.session_state.current_project_id:
        db = SessionLocal()
        try:
            current_project = db.query(Project).filter(Project.id == st.session_state.current_project_id).first()
            if current_project:
                st.subheader(f"プロジェクト: {current_project.name}")
                
                if st.session_state.current_thread_id:
                    current_thread = db.query(Thread).filter(Thread.id == st.session_state.current_thread_id).first()
                    if current_thread:
                        st.write(f"チャット: {current_thread.name}")

                        # --- モデル選択 (チャットエリア上部) ---
                        # グローバルなアプリ設定として選択モデルを保存（チャット間で共有）
                        if 'global_selected_model' not in st.session_state:
                            st.session_state.global_selected_model = AVAILABLE_MODELS[0] # デフォルト
                        
                        # 現在の選択値を一時的な変数に保存
                        current_selection = st.selectbox(
                            "使用するモデル:", 
                            AVAILABLE_MODELS,
                            index=AVAILABLE_MODELS.index(st.session_state.global_selected_model) if st.session_state.global_selected_model in AVAILABLE_MODELS else 0,
                            key="model_selector_main",
                            label_visibility="collapsed"  # ラベルを非表示に設定
                        )
                        
                        # 選択が変更された場合のみ、グローバル設定を更新
                        if current_selection != st.session_state.global_selected_model:
                            st.session_state.global_selected_model = current_selection
                            st.success(f"モデルを {current_selection} に変更しました。", icon="✅")
                        
                        # APIリクエスト用のモデル名変数
                        selected_model_for_api = st.session_state.global_selected_model

                        # --- チャット履歴の表示 ---
                        messages = db.query(Message).filter(Message.thread_id == current_thread.id).order_by(Message.created_at).all()
                        for msg in messages:
                            with st.chat_message(msg.role):
                                st.markdown(msg.content) # マークダウンとして表示

                        # チャット入力欄に自動フォーカスするJavaScriptを適用
                        st.markdown(js_focus_script, unsafe_allow_html=True)
                        
                        # --- ★★★ チャット入力と後続処理を復元 ★★★ ---
                        if prompt := st.chat_input("メッセージを入力してください"):
                            # 1. ユーザーメッセージを表示し、DBに保存
                            with st.chat_message("user"):
                                st.markdown(prompt)
                            
                            user_message = Message(thread_id=current_thread.id, role="user", content=prompt)
                            db.add(user_message)
                            
                            # チャットの最終更新日時を更新
                            current_thread.updated_at = datetime.datetime.utcnow()
                            db.add(current_thread)
                            
                            db.commit()

                            # --- ★マークダウンエクスポート (ユーザー) ---
                            export_message_to_markdown(
                                project_name=current_project.name,
                                thread_id=current_thread.id,
                                thread_name=current_thread.name,
                                role="user",
                                content=prompt
                            )
                            # --- ★マークダウンエクスポートここまで ---

                            # 2. Gemini API 呼び出し準備
                            #    - 履歴を API 用の形式に変換 (システムプロンプトは別途渡す)
                            history_for_api = []
                            for m in messages:
                                try:
                                    # 役割(role)に応じて Content オブジェクトを作成
                                    # DBの 'assistant' を API の 'model' に変換
                                    api_role = 'model' if m.role == 'assistant' else m.role
                                    # parts はリストである必要があるため、Part オブジェクトを生成
                                    # Part.from_text でエラーが出たため Part(text=...) を使用
                                    history_for_api.append(types.Content(role=api_role, parts=[types.Part(text=m.content)]))
                                except ValueError as e:
                                    st.error(f"履歴メッセージのフォーマットエラー (ID: {m.id}, Role: {m.role}): {e}")
                                    continue 
                            
                            # 最新のユーザーメッセージを Content オブジェクトとして追加 (role は 'user' で確定)
                            try:
                                # Part.from_text でエラーが出たため Part(text=...) を使用
                                history_for_api.append(types.Content(role="user", parts=[types.Part(text=prompt)]))
                            except ValueError as e:
                                st.error(f"ユーザー入力のフォーマットエラー: {e}")
                                db.rollback() 
                                st.stop()

                            # 3. Gemini API 呼び出しと応答表示 (ストリーミング)
                            try:
                                # Client の初期化を変更 (引数なし)
                                client = GeminiClient()

                                # --- デバッグログ追加 ---
                                logging.debug(f"Project ID: {current_project.id}, Thread ID: {current_thread.id}")
                                logging.debug(f"Selected Model: {selected_model_for_api}")
                                logging.debug(f"System Prompt: {current_project.system_prompt}")
                                logging.debug(f"History for API (first 5 items): {history_for_api[:5]}") # 全部は多いので先頭5件
                                logging.debug(f"Total history items for API: {len(history_for_api)}")
                                # --- デバッグログここまで ---

                                with st.chat_message("assistant"):
                                    # ストリーミング応答を表示するプレースホルダー
                                    response_placeholder = st.empty()
                                    full_response = ""
                                    # メソッド呼び出しに session_state からモデル名を取得して渡す
                                    stream = client.generate_content_stream(
                                        model_name=selected_model_for_api, # 選択されたモデルを使用
                                        history=history_for_api, 
                                        system_prompt=current_project.system_prompt
                                    )
                                    for chunk in stream:
                                        full_response += chunk
                                        response_placeholder.markdown(full_response + "▌") 
                                    response_placeholder.markdown(full_response) 

                                # 4. アシスタントの応答をDBに保存
                                assistant_message = Message(thread_id=current_thread.id, role="assistant", content=full_response)
                                db.add(assistant_message)
                                
                                # チャットの最終更新日時を再度更新
                                current_thread.updated_at = datetime.datetime.utcnow()
                                db.add(current_thread)

                                db.commit()

                                # --- ★マークダウンエクスポート (アシスタント) ---
                                export_message_to_markdown(
                                    project_name=current_project.name,
                                    thread_id=current_thread.id,
                                    thread_name=current_thread.name,
                                    role="assistant",
                                    content=full_response
                                )
                                # --- ★マークダウンエクスポートここまで ---

                                # --- ★★★ チャット名の自動設定 (最初のやり取り後) ★★★ ---
                                if not messages: # API呼び出し前のメッセージリストが空だったら
                                    new_thread_name = prompt[:20] # ユーザー入力の先頭20文字
                                    if new_thread_name:
                                        logging.info(f"最初のやり取りを検出。チャット ID {current_thread.id} の名前を自動設定: '{new_thread_name}'")
                                        # update_thread_name を直接呼び出すのではなく、セッションを再利用
                                        update_success = update_thread_name(db, current_thread.id, new_thread_name)
                                        if update_success:
                                            # 即時反映のため rerun
                                            st.rerun()
                                        else:
                                            logging.warning("チャット名の自動設定に失敗しました。")
                                # --- ★★★ 自動設定ここまで ★★★ ---

                            except Exception as e:
                                st.error(f"Gemini API の呼び出し中にエラーが発生しました: {e}")
                        # --- ★★★ チャット入力復元ここまで ★★★ ---

                    else:
                        st.warning("選択されたチャットが見つかりません。")
                        st.session_state.current_thread_id = None # リセット
                else:
                    st.info("サイドバーからチャットを選択または作成してください。")
            else:
                st.warning("選択されたプロジェクトが見つかりません。サイドバーからプロジェクトを選択または作成してください。")
                st.session_state.current_project_id = None
                st.session_state.current_thread_id = None
        finally:
            db.close()
    else:
        st.info("サイドバーからプロジェクトを選択または作成してください。")

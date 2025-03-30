import streamlit as st
from database.database import SessionLocal, init_db
from models.models import Project, Thread, Message
from api.gemini_client import GeminiClient
import datetime
from google.genai import types
import logging # logging をインポート
from utils.markdown_export import export_message_to_markdown # <-- インポートを追加
from database.crud import search_messages, delete_thread, update_thread_name, delete_project, update_project # <-- delete_project をインポート
from sqlalchemy import func
from utils.csv_export import get_all_data_as_dataframe, generate_csv_data # <-- CSVエクスポート関数をインポート
import json # json モジュールをインポート
import os # os モジュールをインポート

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
    """アプリ初回起動時に最後の状態を復元し、新規スレッドを開始"""
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
                # 新しいスレッドを作成
                threads_count = db.query(func.count(Thread.id)).filter(Thread.project_id == initial_project_id).scalar() or 0
                new_thread = Thread(project_id=initial_project_id, name=f"新しいスレッド {threads_count + 1}")
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
    st.session_state.visible_thread_count = 5 # スレッド表示件数もここで初期化
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
        # プロジェクトが切り替わったらスレッド選択もリセット & 状態保存
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
            st.sidebar.warning(f"プロジェクト '{current_project_name}' を削除すると、関連する全てのスレッドとメッセージも削除されます。本当に削除しますか？")
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

    # --- スレッド管理 --- (プロジェクトが選択されている場合のみ表示)
    if st.session_state.current_project_id:
        st.sidebar.header("スレッド")
        current_project_id = st.session_state.current_project_id
        threads = db.query(Thread).filter(Thread.project_id == current_project_id).order_by(Thread.updated_at.desc()).all()
        # logging.info(f"[Sidebar Render] Fetched {len(threads)} threads for project {current_project_id}. Displaying up to {st.session_state.visible_thread_count}") # <-- ログ削除

        # 新規スレッド作成ボタン
        if st.sidebar.button("新しいスレッドを開始"):
            new_thread = Thread(project_id=current_project_id, name=f"新しいスレッド {len(threads) + 1}") # 仮の名前
            db.add(new_thread)
            db.commit()
            db.refresh(new_thread)
            st.session_state.current_thread_id = new_thread.id
            # st.session_state.visible_thread_count = 5 # <-- 削除
            st.sidebar.success("新しいスレッドを開始しました！")
            st.rerun()
        
        st.sidebar.divider() # スレッドリストの前に区切り線

        # スレッド一覧表示 (全件表示)
        selected_thread_id = st.session_state.current_thread_id
        # threads_to_display = threads[:st.session_state.visible_thread_count] # <-- 削除

        if not threads: # スレッドが全くない場合
             st.sidebar.caption("まだスレッドがありません。")
        else:
            # スレッド名と削除ボタンを1行に表示
            for thread in threads: # 全ての threads をループ
                col1, col2 = st.sidebar.columns([0.8, 0.2])
                with col1:
                    # メッセージ数を取得 (効率は改善の余地あり)
                    message_count_query = db.query(func.count(Message.id)).filter(Message.thread_id == thread.id)
                    message_count = message_count_query.scalar() or 0
                    thread_label = f"{thread.name} ({message_count} msgs)"
                    
                    # スレッド選択ボタン
                    if st.button(thread_label, key=f"select_thread_{thread.id}", use_container_width=True,
                                  type="primary" if thread.id == selected_thread_id else "secondary"):
                        st.session_state.current_thread_id = thread.id
                        st.session_state.show_search_results = False 
                        st.session_state.editing_project = False 
                        st.rerun()
                with col2:
                    # スレッド削除ボタン
                    if st.button("🗑️", key=f"delete_thread_{thread.id}", help="このスレッドを削除します"):
                        thread_id_to_delete = thread.id 
                        thread_name_to_delete = thread.name 
                        logging.info(f"[Delete Button Clicked] Attempting to delete thread ID: {thread_id_to_delete}, Name: {thread_name_to_delete}") 
                        delete_success = delete_thread(db, thread_id_to_delete)
                        logging.info(f"[Delete Action] Deletion result for thread {thread_id_to_delete}: {delete_success}") 
                        if delete_success:
                            st.sidebar.success(f"スレッド '{thread_name_to_delete}' を削除しました。") 
                            current_selection = st.session_state.current_thread_id
                            if current_selection == thread_id_to_delete:
                                st.session_state.current_thread_id = None
                                logging.info(f"[Delete Action] Current thread selection {current_selection} was deleted, setting to None.") 
                            else:
                                logging.info(f"[Delete Action] Deleted thread {thread_id_to_delete}, current selection {current_selection} remains.") 
                            st.rerun()
                        else:
                            st.sidebar.error(f"スレッド '{thread_name_to_delete}' の削除に失敗しました。") 
                
        st.sidebar.divider() # スレッドリストの後にも区切り線

    # --- ★検索機能 --- 
    st.sidebar.header("検索")
    search_query = st.sidebar.text_input("メッセージを検索", key="search_input")
    if st.sidebar.button("検索実行", key="search_button"):
        if search_query:
            db_session = SessionLocal()
            try:
                results = search_messages(db_session, search_query)
                # 結果を保存（プロジェクト名とスレッド名も取得して付加する）
                detailed_results = []
                for msg in results:
                    # 関連するスレッドとプロジェクトを取得
                    # N+1 問題を避けるため、本来は JOIN で取得する方が効率的
                    thread = db_session.query(Thread).filter(Thread.id == msg.thread_id).first()
                    project = db_session.query(Project).filter(Project.id == thread.project_id).first() if thread else None
                    detailed_results.append({
                        "message": msg,
                        "thread_name": thread.name if thread else "不明なスレッド",
                        "project_name": project.name if project else "不明なプロジェクト",
                        "project_id": thread.project_id if thread else None,
                        "thread_id": msg.thread_id
                    })
                st.session_state.search_results = detailed_results
                st.session_state.show_search_results = True # 検索結果表示モードに
                st.session_state.current_thread_id = None # 検索時は特定のスレッドを選択解除
                logging.debug(f"検索を実行しました: Query='{search_query}', Results={len(results)}")
                st.rerun() # メインエリアの表示を更新するため
            finally:
                db_session.close()
        else:
            st.sidebar.warning("検索キーワードを入力してください。")
            st.session_state.show_search_results = False # 検索モード解除
            st.session_state.search_results = None

    # 検索結果表示中はチャット表示に戻るボタンを出す
    if st.session_state.show_search_results:
        if st.sidebar.button("チャットに戻る", key="back_to_chat_button"):
            st.session_state.show_search_results = False
            st.session_state.search_results = None
            # 前回選択していたプロジェクト/スレッドに戻すか、あるいは単にクリアするか
            # ここではクリアして、ユーザーに再度選択させる
            # st.session_state.current_project_id = ... (保持していた場合)
            # st.session_state.current_thread_id = ... (保持していた場合)
            st.rerun()
    # --- 検索機能ここまで ---

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
                        st.session_state.current_thread_id = None # スレッドは未選択のまま or 新規作成?
                        save_last_project_id(new_project.id) # ★状態保存
                        # ここで新規スレッドも作成して選択状態にするか？ 要件に合わせて調整
                        # 現状はプロジェクト選択のみ。次にリロードされると新規スレッドが作られる想定。
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
        for result in results:
            msg = result["message"]
            with st.expander(f"**{result['project_name']}** / **{result['thread_name']}** ({msg.created_at.strftime('%Y-%m-%d %H:%M')}) - {msg.role}"):
                st.markdown(f"> {msg.content[:100]}..." if len(msg.content) > 100 else f"> {msg.content}") # プレビュー
                # st.markdown(msg.content) # 全文表示
                # 検索結果から該当スレッドにジャンプするボタン
                if st.button(f"このスレッドを開く ({result['thread_name']})", key=f"goto_thread_{msg.id}"):
                    st.session_state.current_project_id = result['project_id']
                    st.session_state.current_thread_id = result['thread_id']
                    st.session_state.show_search_results = False 
                    st.session_state.editing_project = False # 他のモード解除
                    st.session_state.creating_project = False
                    save_last_project_id(result['project_id']) # ★状態保存
                    st.rerun()
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
                        st.write(f"スレッド: {current_thread.name}")

                        # --- モデル選択 (チャットエリア上部) ---
                        # セッションステートに選択モデルを保存
                        if 'selected_model' not in st.session_state:
                            st.session_state.selected_model = AVAILABLE_MODELS[0] # デフォルト
                        
                        st.session_state.selected_model = st.selectbox(
                            "使用するモデル:", 
                            AVAILABLE_MODELS,
                            index=AVAILABLE_MODELS.index(st.session_state.selected_model) if st.session_state.selected_model in AVAILABLE_MODELS else 0,
                            key="model_selector_main"  # <-- 一意なキーを追加
                        )

                        # --- チャット履歴の表示 ---
                        messages = db.query(Message).filter(Message.thread_id == current_thread.id).order_by(Message.created_at).all()
                        for msg in messages:
                            with st.chat_message(msg.role):
                                st.markdown(msg.content) # マークダウンとして表示

                        # --- ★★★ チャット入力と後続処理を復元 ★★★ ---
                        if prompt := st.chat_input("メッセージを入力してください"):
                            # 1. ユーザーメッセージを表示し、DBに保存
                            with st.chat_message("user"):
                                st.markdown(prompt)
                            
                            user_message = Message(thread_id=current_thread.id, role="user", content=prompt)
                            db.add(user_message)
                            
                            # スレッドの最終更新日時を更新
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
                                logging.debug(f"Selected Model: {st.session_state.selected_model}")
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
                                        model_name=st.session_state.selected_model, # 選択されたモデルを使用
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
                                
                                # スレッドの最終更新日時を再度更新
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

                                # --- ★★★ スレッド名の自動設定 (最初のやり取り後) ★★★ ---
                                if not messages: # API呼び出し前のメッセージリストが空だったら
                                    new_thread_name = prompt[:20] # ユーザー入力の先頭20文字
                                    if new_thread_name:
                                        logging.info(f"最初のやり取りを検出。スレッド ID {current_thread.id} の名前を自動設定: '{new_thread_name}'")
                                        # update_thread_name を直接呼び出すのではなく、セッションを再利用
                                        update_success = update_thread_name(db, current_thread.id, new_thread_name)
                                        if update_success:
                                            # 即時反映のため rerun
                                            st.rerun()
                                        else:
                                            logging.warning("スレッド名の自動設定に失敗しました。")
                                # --- ★★★ 自動設定ここまで ★★★ ---

                            except Exception as e:
                                st.error(f"Gemini API の呼び出し中にエラーが発生しました: {e}")
                        # --- ★★★ チャット入力復元ここまで ★★★ ---

                    else:
                        st.warning("選択されたスレッドが見つかりません。")
                        st.session_state.current_thread_id = None # リセット
                else:
                    st.info("サイドバーからスレッドを選択または作成してください。")
            else:
                st.warning("選択されたプロジェクトが見つかりません。サイドバーからプロジェクトを選択または作成してください。")
                st.session_state.current_project_id = None
                st.session_state.current_thread_id = None
        finally:
            db.close()
    else:
        st.info("サイドバーからプロジェクトを選択または作成してください。")

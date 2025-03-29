import streamlit as st
from database.database import SessionLocal, init_db
from models.models import Project, Thread, Message
from api.gemini_client import GeminiClient
import datetime
from google.genai import types
import logging # logging をインポート
from utils.markdown_export import export_message_to_markdown # <-- インポートを追加
from database.crud import search_messages # <-- search_messages をインポート

# logging の基本設定
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# --- データベース初期化 ---
init_db()

# --- セッション状態の初期化 ---
if "current_project_id" not in st.session_state:
    st.session_state.current_project_id = None
if "current_thread_id" not in st.session_state:
    st.session_state.current_thread_id = None
if "search_results" not in st.session_state:
    st.session_state.search_results = None # 検索結果を格納
if "show_search_results" not in st.session_state:
    st.session_state.show_search_results = False # 検索結果表示モードのフラグ

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
        # プロジェクトが切り替わったらスレッド選択もリセット
        if st.session_state.current_project_id != project_map[selected_project_name]:
             st.session_state.current_thread_id = None 
        st.session_state.current_project_id = project_map[selected_project_name]

    else:
        st.session_state.current_project_id = None
        st.session_state.current_thread_id = None

    # 新規プロジェクト作成
    with st.sidebar.expander("新しいプロジェクトを作成"): 
        new_project_name = st.text_input("プロジェクト名")
        new_system_prompt = st.text_area("システムプロンプト", value="あなたは役立つアシスタントです。")
        # モデル選択を削除 (要件変更)
        # selected_model = st.selectbox("使用するモデルを選択", AVAILABLE_MODELS, index=0)
        
        if st.button("作成"):
            # モデル選択のチェックを削除
            if new_project_name:
                # 同じ名前のプロジェクトがないか確認
                existing_project = db.query(Project).filter(Project.name == new_project_name).first()
                if not existing_project:
                    new_project = Project(
                        name=new_project_name, 
                        system_prompt=new_system_prompt,
                        # model_name=selected_model # モデル選択を削除
                    )
                    db.add(new_project)
                    db.commit()
                    db.refresh(new_project) # IDを取得するためにリフレッシュ
                    st.session_state.current_project_id = new_project.id # 作成したプロジェクトを選択状態にする
                    st.session_state.current_thread_id = None # 新規プロジェクト作成時はスレッド未選択
                    st.sidebar.success(f"プロジェクト '{new_project_name}' を作成しました！")
                    st.rerun() # サイドバーの表示を更新
                else:
                    st.sidebar.error("同じ名前のプロジェクトが既に存在します。")
            else:
                # メッセージを修正
                st.sidebar.warning("プロジェクト名を入力してください。")

    # --- スレッド管理 --- (プロジェクトが選択されている場合のみ表示)
    if st.session_state.current_project_id:
        st.sidebar.header("スレッド")
        current_project_id = st.session_state.current_project_id
        threads = db.query(Thread).filter(Thread.project_id == current_project_id).order_by(Thread.updated_at.desc()).all()
        thread_names = [t.name for t in threads]
        thread_map = {t.name: t.id for t in threads}

        # 新規スレッド作成ボタン
        if st.sidebar.button("新しいスレッドを開始"): 
            new_thread = Thread(project_id=current_project_id, name=f"新しいスレッド {len(threads) + 1}") # 仮の名前
            db.add(new_thread)
            db.commit()
            db.refresh(new_thread)
            st.session_state.current_thread_id = new_thread.id
            st.sidebar.success("新しいスレッドを開始しました！")
            st.rerun()

        # スレッド選択
        selected_thread_name = st.sidebar.selectbox(
            "スレッドを選択",
            thread_names,
            index=thread_names.index(next((t.name for t in threads if t.id == st.session_state.current_thread_id), None)) if st.session_state.current_thread_id and any(t.id == st.session_state.current_thread_id for t in threads) else 0,
            # disabled=not threads # スレッドがなくても新規作成があるので disabled にしない
        )

        if selected_thread_name:
            st.session_state.current_thread_id = thread_map[selected_thread_name]
        elif threads: # スレッドが存在するのに選択されていない場合（初期状態など）
             st.session_state.current_thread_id = threads[0].id # 最新のスレッドをデフォルトで選択
        else:
            st.session_state.current_thread_id = None

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

finally:
    db.close()

# --- メインコンテンツエリア --- 

# 検索結果表示モードかどうかで表示を切り替える
if st.session_state.show_search_results:
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
                    st.session_state.show_search_results = False # チャット表示モードに戻す
                    st.session_state.search_results = None
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

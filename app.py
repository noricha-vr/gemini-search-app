import streamlit as st
from database.database import SessionLocal, init_db
from models.models import Project, Thread, Message
from api.gemini_client import GeminiClient
import datetime

# --- データベース初期化 ---
init_db()

# --- セッション状態の初期化 ---
if "current_project_id" not in st.session_state:
    st.session_state.current_project_id = None
if "current_thread_id" not in st.session_state:
    st.session_state.current_thread_id = None

# --- 定数 --- # モデルリストを定義
AVAILABLE_MODELS = [
    "gemini-2.0-flash", # 消さない
    "gemini-2.0-pro-exp-02-05", # 消さない
    "gemini-2.5-pro-exp-03-25" # 消さない
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
        # モデル選択を追加 (要件 2.1)
        selected_model = st.selectbox("使用するモデルを選択", AVAILABLE_MODELS, index=0)
        
        if st.button("作成"):
            if new_project_name and selected_model:
                # 同じ名前のプロジェクトがないか確認
                existing_project = db.query(Project).filter(Project.name == new_project_name).first()
                if not existing_project:
                    new_project = Project(
                        name=new_project_name, 
                        system_prompt=new_system_prompt,
                        model_name=selected_model # モデル選択の値を入れる
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
                st.sidebar.warning("プロジェクト名とモデルを選択してください。")

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

finally:
    db.close()

# --- メインコンテンツエリア --- 
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
                    
                    # --- チャット履歴の表示 ---
                    messages = db.query(Message).filter(Message.thread_id == current_thread.id).order_by(Message.created_at).all()
                    for msg in messages:
                        with st.chat_message(msg.role):
                            st.markdown(msg.content) # マークダウンとして表示

                    # --- チャット入力 ---
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
                        # db.refresh(user_message) # 必要なら

                        # 2. Gemini API 呼び出し準備
                        #    - 履歴を API 用の形式に変換 (システムプロンプトは別途渡す)
                        history_for_api = []
                        for m in messages: # DBから取得したメッセージ + 今追加したユーザーメッセージ
                             history_for_api.append({'role': m.role, 'parts': [m.content]})
                        history_for_api.append({'role': 'user', 'parts': [prompt]}) # 最新のユーザー入力を追加

                        # 3. Gemini API 呼び出しと応答表示 (ストリーミング)
                        try:
                            client = GeminiClient(model_name=current_project.model_name)
                            with st.chat_message("assistant"):
                                # ストリーミング応答を表示するプレースホルダー
                                response_placeholder = st.empty() 
                                full_response = ""
                                # st.write_stream を使用してストリーミング表示
                                stream = client.generate_content_stream(
                                    history=history_for_api, 
                                    system_prompt=current_project.system_prompt
                                )
                                for chunk in stream:
                                    full_response += chunk
                                    response_placeholder.markdown(full_response + "▌") # カーソル風の表示
                                response_placeholder.markdown(full_response) # 最終的な応答を表示

                            # 4. アシスタントの応答をDBに保存
                            assistant_message = Message(thread_id=current_thread.id, role="assistant", content=full_response)
                            db.add(assistant_message)
                            
                            # スレッドの最終更新日時を再度更新
                            current_thread.updated_at = datetime.datetime.utcnow()
                            db.add(current_thread)

                            db.commit()
                            # st.rerun() # 応答後に再実行すると入力が消えるので不要かも

                        except Exception as e:
                            st.error(f"Gemini API の呼び出し中にエラーが発生しました: {e}")
                            # エラー発生時はロールバックした方が良い場合もある
                            # db.rollback() 

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

# TODO: 検索機能 (要件 2.4)
# TODO: 履歴管理機能 (要件 2.5)
# TODO: エクスポート機能 (要件 2.6)
# TODO: 設定メニュー (要件 6.2)

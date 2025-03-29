import streamlit as st
from database.database import SessionLocal, init_db
from models.models import Project

# --- データベース初期化 ---
init_db()

# --- セッション状態の初期化 ---
if "current_project_id" not in st.session_state:
    st.session_state.current_project_id = None
if "current_thread_id" not in st.session_state:
    st.session_state.current_thread_id = None

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
        # disabled=not projects # プロジェクトがない場合も新規作成があるので disabled にしない
    )

    if selected_project_name:
        st.session_state.current_project_id = project_map[selected_project_name]
    else:
        st.session_state.current_project_id = None # プロジェクトがない場合など

    # 新規プロジェクト作成
    with st.sidebar.expander("新しいプロジェクトを作成"): 
        new_project_name = st.text_input("プロジェクト名")
        new_system_prompt = st.text_area("システムプロンプト", value="あなたは役立つアシスタントです。")
        # TODO: モデル選択を追加 (要件 2.1)
        if st.button("作成"):
            if new_project_name:
                # 同じ名前のプロジェクトがないか確認
                existing_project = db.query(Project).filter(Project.name == new_project_name).first()
                if not existing_project:
                    new_project = Project(
                        name=new_project_name, 
                        system_prompt=new_system_prompt,
                        # model_name= # TODO: モデル選択の値を入れる
                    )
                    db.add(new_project)
                    db.commit()
                    st.session_state.current_project_id = new_project.id # 作成したプロジェクトを選択状態にする
                    db.refresh(new_project) # IDを取得するためにリフレッシュ
                    st.sidebar.success(f"プロジェクト '{new_project_name}' を作成しました！")
                    st.rerun() # サイドバーの表示を更新
                else:
                    st.sidebar.error("同じ名前のプロジェクトが既に存在します。")
            else:
                st.sidebar.warning("プロジェクト名を入力してください。")
finally:
    db.close()

# --- メインコンテンツエリア --- 
st.title("Chat") # 仮タイトル

if st.session_state.current_project_id:
    db = SessionLocal()
    try:
        current_project = db.query(Project).filter(Project.id == st.session_state.current_project_id).first()
        if current_project:
            st.subheader(f"プロジェクト: {current_project.name}")
            # TODO: スレッド管理機能 (要件 2.2)
            # TODO: チャット機能 (要件 2.3)
        else:
            st.warning("選択されたプロジェクトが見つかりません。サイドバーからプロジェクトを選択または作成してください。")
            st.session_state.current_project_id = None # 見つからない場合はリセット
    finally:
        db.close()
else:
    st.info("サイドバーからプロジェクトを選択または作成してください。")

# TODO: 検索機能 (要件 2.4)
# TODO: 履歴管理機能 (要件 2.5)
# TODO: エクスポート機能 (要件 2.6)
# TODO: 設定メニュー (要件 6.2)

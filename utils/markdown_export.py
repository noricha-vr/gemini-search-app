import os
import datetime

MARKDOWN_BASE_DIR = "markdown_files"

def sanitize_filename(name: str) -> str:
    """ファイル名として安全でない文字を置換します。"""
    # 例: スラッシュ、コロンなどをアンダースコアに置換
    # 必要に応じて他の文字も追加
    return name.replace("/", "_").replace(":", "_").replace("\\", "_")

def export_message_to_markdown(project_name: str, thread_id: int, thread_name: str, role: str, content: str):
    """
    指定されたメッセージをスレッドに対応するマークダウンファイルに追記します。

    Args:
        project_name: プロジェクト名。
        thread_id: スレッドID。
        thread_name: スレッド名（ファイル名に使用）。
        role: メッセージの役割 ('user' or 'assistant')。
        content: メッセージの内容。
    """
    try:
        # プロジェクト名のディレクトリパスを作成 (なければ作成)
        project_dir = os.path.join(MARKDOWN_BASE_DIR, sanitize_filename(project_name))
        os.makedirs(project_dir, exist_ok=True)

        # スレッド名とIDでファイル名を生成 (サニタイズ)
        # 例: "スレッド名 (ID).md"
        file_name = f"{sanitize_filename(thread_name)} ({thread_id}).md"
        file_path = os.path.join(project_dir, file_name)

        # タイムスタンプを取得
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 追記するテキストをフォーマット
        # DBロール('user'/'assistant')をそのまま使う
        formatted_message = f"**[{role.capitalize()}]** ({timestamp}):\n\n{content}\n\n---\n\n"

        # ファイルに追記モードで書き込み
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(formatted_message)
        
        # logging.debug(f"メッセージをマークダウンファイルにエクスポートしました: {file_path}")

    except Exception as e:
        # エラー発生時はログに出力（Streamlit画面には出さない方が良いかも）
        import logging
        logging.error(f"マークダウンファイルへのエクスポート中にエラーが発生しました: {e}", exc_info=True) 

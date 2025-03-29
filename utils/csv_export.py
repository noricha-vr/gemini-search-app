import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy.sql import text # text をインポート
from models.models import Project, Thread, Message
import logging

def get_all_data_as_dataframe(db: Session) -> pd.DataFrame:
    """
    データベースからすべてのプロジェクト、スレッド、メッセージを取得し、
    単一の Pandas DataFrame に結合して返します。

    Args:
        db: SQLAlchemy セッションオブジェクト。

    Returns:
        結合されたデータを含む Pandas DataFrame。
        エラーが発生した場合は空の DataFrame。
    """
    try:
        # JOIN を使って効率的に全データを取得するクエリを作成
        # SELECT句でカラム名を指定し、ラベル付けする
        stmt = text("""
            SELECT 
                p.id AS project_id,
                p.name AS project_name,
                p.system_prompt AS project_system_prompt,
                p.created_at AS project_created_at,
                t.id AS thread_id,
                t.name AS thread_name,
                t.created_at AS thread_created_at,
                m.id AS message_id,
                m.role AS message_role,
                m.content AS message_content,
                m.created_at AS message_created_at
            FROM projects p
            JOIN threads t ON p.id = t.project_id
            JOIN messages m ON t.id = m.thread_id
            ORDER BY p.id, t.id, m.created_at
        """)

        # Pandas DataFrame に読み込む (Session の bind を使用)
        df = pd.read_sql(stmt, db.bind)
        logging.info(f"{len(df)} 件のメッセージを含むデータをエクスポート用に取得しました。")
        return df

    except Exception as e:
        logging.error(f"全データ取得中にエラーが発生しました: {e}", exc_info=True)
        return pd.DataFrame() # エラー時は空の DataFrame を返す

def generate_csv_data(df: pd.DataFrame) -> bytes | None:
    """
    Pandas DataFrame を CSV 形式のバイトデータに変換します。

    Args:
        df: CSV に変換する DataFrame。

    Returns:
        CSV 形式のバイトデータ。エラーが発生した場合は None。
    """
    if df.empty:
        return None
    try:
        # DataFrame を CSV 文字列に変換 (インデックスを含めない)
        # encoding='utf-8-sig' で BOM を追加し、Excel での文字化けを防ぐ
        csv_string = df.to_csv(index=False, encoding='utf-8-sig')
        # バイトデータにエンコード
        csv_bytes = csv_string.encode('utf-8-sig')
        return csv_bytes
    except Exception as e:
        logging.error(f"CSV データ生成中にエラーが発生しました: {e}", exc_info=True)
        return None 

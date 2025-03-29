from sqlalchemy.orm import Session
from sqlalchemy import text
from models.models import Message, Thread, Project # モデルをインポート
import logging

def search_messages(db: Session, query: str) -> list[Message]:
    """
    指定されたクエリ文字列を使用して、メッセージ履歴を全文検索します。
    検索は AND 条件で行われます（すべてのキーワードを含むメッセージを検索）。

    Args:
        db: SQLAlchemy セッションオブジェクト。
        query: 検索クエリ文字列 (半角スペース区切り)。

    Returns:
        検索にヒットした Message オブジェクトのリスト。
    """
    if not query.strip():
        return []

    # FTS5 のクエリを作成 (スペースを AND に置換するような形を想定)
    # 単純にスペース区切りでも FTS5 は AND 検索として扱うことが多いが、明示的に作ることも可能
    # ここでは単純なスペース区切り文字列をそのまま使用
    # 例: "キーワード1 キーワード2" -> FTS5 は両方を含むものを検索
    # 特殊文字のエスケープが必要な場合があるかもしれない
    fts_query = query.strip()

    try:
        # message_fts テーブルを検索して message の id (rowid) を取得
        # ORDER BY rank で関連性の高い順にソート
        stmt = text("""
            SELECT rowid 
            FROM message_fts 
            WHERE message_fts MATCH :query 
            ORDER BY rank
        """)
        result = db.execute(stmt, {"query": fts_query})
        message_ids = [row[0] for row in result.fetchall()]

        if not message_ids:
            return []

        # 取得した ID に基づいて Message オブジェクトを取得
        # JOIN を使って関連する Thread と Project も効率的に取得できるが、
        # まずは Message のみを取得し、必要に応じて UI 側で追加情報を取得する
        messages = db.query(Message).filter(Message.id.in_(message_ids)).all()

        # FTS の結果順序 (rank) を保持するために、取得したメッセージを並び替える
        message_map = {msg.id: msg for msg in messages}
        ordered_messages = [message_map[id] for id in message_ids if id in message_map]

        return ordered_messages

    except Exception as e:
        logging.error(f"メッセージ検索中にエラーが発生しました (Query: {query}): {e}", exc_info=True)
        # エラーが発生した場合は空リストを返すか、例外を再発生させる
        return []

# 他の CRUD 操作関数もここに追加していく想定
# (例: get_project, create_thread, get_messages_by_thread など) 

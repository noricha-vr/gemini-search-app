from sqlalchemy.orm import Session
from sqlalchemy import text
from models.models import Message, Thread, Project # モデルをインポート
import logging
import datetime

# モジュールレベルのロガーを取得
log = logging.getLogger(__name__)

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

    # クエリを空白で分割して検索用語を抽出
    terms = query.strip().split()
    if not terms:
        return []
    
    try:
        # FTS5を使わず、SQLのLIKE演算子を使用して検索
        # 各検索用語を含むメッセージをAND条件で検索
        query_obj = db.query(Message)
        
        # すべての用語に対してフィルターを適用
        for term in terms:
            query_obj = query_obj.filter(Message.content.ilike(f'%{term}%'))
        
        # 結果を取得
        messages = query_obj.all()
        return messages

    except Exception as e:
        logging.error(f"メッセージ検索中にエラーが発生しました (Query: {query}): {e}", exc_info=True)
        # エラーが発生した場合は空リストを返すか、例外を再発生させる
        return []

def delete_thread(db: Session, thread_id: int) -> bool:
    """
    指定された ID のスレッドを削除します。
    関連するメッセージもカスケード削除されます。

    Args:
        db: SQLAlchemy セッションオブジェクト。
        thread_id: 削除するスレッドの ID。

    Returns:
        削除が成功した場合は True、スレッドが見つからない場合は False。
    """
    thread_to_delete = db.query(Thread).filter(Thread.id == thread_id).first()
    if thread_to_delete:
        try:
            # 明示的に関連メッセージを先に削除（FTSのトリガー関連の問題を回避するため）
            messages = db.query(Message).filter(Message.thread_id == thread_id).all()
            logging.info(f"スレッド ID {thread_id} から {len(messages)} 件のメッセージを削除します")
            
            # 一つずつ削除する（メッセージが多い場合はバルク削除を検討）
            for message in messages:
                db.delete(message)
            
            # 一旦コミットしてメッセージ削除を確定
            db.commit()
            logging.info(f"スレッド ID {thread_id} のメッセージを削除しました")
            
            # 次にスレッド自体を削除
            db.delete(thread_to_delete)
            db.commit()
            logging.info(f"スレッド ID {thread_id} を削除しました。")
            return True
        except Exception as e:
            db.rollback()
            logging.error(f"スレッド ID {thread_id} の削除中にエラーが発生しました: {e}", exc_info=True)
            return False
    else:
        logging.warning(f"削除対象のスレッド ID {thread_id} が見つかりません。")
        return False

def update_thread_name(db: Session, thread_id: int, new_name: str) -> bool:
    """
    指定された ID のスレッドの名前を更新します。

    Args:
        db: SQLAlchemy セッションオブジェクト。
        thread_id: 更新するスレッドの ID。
        new_name: 新しいスレッド名。

    Returns:
        更新が成功した場合は True、スレッドが見つからない場合や
        名前が空の場合は False。
    """
    if not new_name or not new_name.strip():
        logging.warning(f"スレッド ID {thread_id} の新しい名前が空です。")
        return False

    thread_to_update = db.query(Thread).filter(Thread.id == thread_id).first()
    if thread_to_update:
        try:
            thread_to_update.name = new_name
            thread_to_update.updated_at = datetime.datetime.utcnow() # 更新日時も更新
            db.commit()
            logging.info(f"スレッド ID {thread_id} の名前を '{new_name}' に更新しました。")
            return True
        except Exception as e:
            db.rollback()
            logging.error(f"スレッド ID {thread_id} の名前更新中にエラーが発生しました: {e}", exc_info=True)
            return False
    else:
        logging.warning(f"更新対象のスレッド ID {thread_id} が見つかりません。")
        return False

def delete_project(db: Session, project_id: int) -> bool:
    """
    指定された ID のプロジェクトを削除します。
    関連するスレッドとメッセージも削除されます。

    Args:
        db: SQLAlchemy セッションオブジェクト。
        project_id: 削除するプロジェクトの ID。

    Returns:
        削除が成功した場合は True、プロジェクトが見つからない場合は False。
    """
    project_to_delete = db.query(Project).filter(Project.id == project_id).first()
    if project_to_delete:
        try:
            # 関連するスレッド ID を取得
            thread_ids = [thread.id for thread in project_to_delete.threads]
            logging.info(f"プロジェクト ID {project_id} ('{project_to_delete.name}') に関連する {len(thread_ids)} 件のスレッドを削除します")

            # 各スレッドに対して、まずメッセージを削除 (delete_thread 関数を利用できるか？)
            # delete_thread はコミットを含むので、ここでは直接メッセージを削除する方が良いかも
            if thread_ids:
                message_count = db.query(Message).filter(Message.thread_id.in_(thread_ids)).count()
                logging.info(f"{message_count} 件の関連メッセージを削除します")
                db.query(Message).filter(Message.thread_id.in_(thread_ids)).delete(synchronize_session=False)
                db.commit() # メッセージ削除をコミット (FTS トリガーのため)
                logging.info("関連メッセージを削除しました")
            
            # 次に関連スレッドを削除 (カスケードで削除されるはずだが、明示的に行う)
            # ここで project_to_delete.threads を使って削除すると、メッセージ削除後に
            # session が expire している可能性があるので、再度クエリする方が安全
            threads_to_delete = db.query(Thread).filter(Thread.project_id == project_id).all()
            if threads_to_delete:
                 logging.info(f"{len(threads_to_delete)} 件のスレッドを削除します")
                 for thread in threads_to_delete:
                     db.delete(thread)
                 db.commit() # スレッド削除をコミット
                 logging.info("関連スレッドを削除しました")
            
            # 最後にプロジェクト自体を削除
            logging.info(f"プロジェクト ID {project_id} ('{project_to_delete.name}') を削除します")
            db.delete(project_to_delete)
            db.commit()
            logging.info(f"プロジェクト ID {project_id} を削除しました。")
            return True
        except Exception as e:
            db.rollback()
            logging.error(f"プロジェクト ID {project_id} の削除中にエラーが発生しました: {e}", exc_info=True)
            return False
    else:
        logging.warning(f"削除対象のプロジェクト ID {project_id} が見つかりません。")
        return False

def update_project(db: Session, project_id: int, new_name: str, new_system_prompt: str) -> bool:
    """
    指定された ID のプロジェクトの名前とシステムプロンプトを更新します。

    Args:
        db: SQLAlchemy セッションオブジェクト。
        project_id: 更新するプロジェクトの ID。
        new_name: 新しいプロジェクト名。
        new_system_prompt: 新しいシステムプロンプト。

    Returns:
        更新が成功した場合は True、プロジェクトが見つからない場合や
        名前が空または重複している場合は False。
    """
    if not new_name or not new_name.strip():
        logging.warning(f"プロジェクト ID {project_id} の新しい名前が空です。")
        return False

    project_to_update = db.query(Project).filter(Project.id == project_id).first()
    if project_to_update:
        try:
            # 名前が変更されているか、かつ新しい名前が他のプロジェクトで使われていないか確認
            if project_to_update.name != new_name:
                existing_project = db.query(Project).filter(Project.name == new_name, Project.id != project_id).first()
                if existing_project:
                    logging.error(f"プロジェクト名 '{new_name}' は既に別のプロジェクトで使用されています。")
                    # エラーをユーザーに返す必要がある (例: False を返す)
                    return False
            
            project_to_update.name = new_name
            project_to_update.system_prompt = new_system_prompt
            project_to_update.updated_at = datetime.datetime.utcnow() # 更新日時も更新
            db.commit()
            logging.info(f"プロジェクト ID {project_id} を更新しました。名前: '{new_name}")
            return True
        except Exception as e:
            db.rollback()
            logging.error(f"プロジェクト ID {project_id} の更新中にエラーが発生しました: {e}", exc_info=True)
            return False
    else:
        logging.warning(f"更新対象のプロジェクト ID {project_id} が見つかりません。")
        return False

def delete_all_threads_in_project(db: Session, project_id: int) -> bool:
    """
    指定されたプロジェクト ID に属する全てのスレッドと関連メッセージを削除します。

    Args:
        db: SQLAlchemy セッションオブジェクト。
        project_id: 対象のプロジェクト ID。

    Returns:
        削除が成功した場合は True、エラーが発生した場合は False。
    """
    # プロジェクトが存在するか一応確認 (任意)
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        logging.warning(f"全スレッド削除対象のプロジェクト ID {project_id} が見つかりません。")
        return False

    try:
        # 削除対象のスレッド ID を取得
        threads_to_delete = db.query(Thread).filter(Thread.project_id == project_id).all()
        thread_ids = [thread.id for thread in threads_to_delete]

        if not thread_ids:
            logging.info(f"プロジェクト ID {project_id} に削除対象のスレッドはありません。")
            return True # 何も削除しないが、処理としては成功
        
        logging.info(f"プロジェクト ID {project_id} から {len(thread_ids)} 件のスレッドとそのメッセージを削除します。")

        # 1. 関連するメッセージを全て削除 (FTS トリガーのため先にコミット)
        message_count = db.query(Message).filter(Message.thread_id.in_(thread_ids)).count()
        if message_count > 0:
            logging.info(f"{message_count} 件の関連メッセージを削除します。")
            db.query(Message).filter(Message.thread_id.in_(thread_ids)).delete(synchronize_session=False)
            db.commit()
            logging.info("関連メッセージを削除しました。")
        else:
            logging.info("削除対象のメッセージはありませんでした。")

        # 2. スレッドを全て削除
        logging.info(f"{len(threads_to_delete)} 件のスレッドを削除します。")
        # delete() を使うより、オブジェクトを渡して削除する方が確実な場合がある
        for thread in threads_to_delete:
            db.delete(thread)
        # db.query(Thread).filter(Thread.project_id == project_id).delete(synchronize_session=False)
        db.commit()
        logging.info("関連スレッドを削除しました。")

        logging.info(f"プロジェクト ID {project_id} の全スレッド削除が完了しました。")
        return True

    except Exception as e:
        db.rollback()
        logging.error(f"プロジェクト ID {project_id} の全スレッド削除中にエラーが発生しました: {e}", exc_info=True)
        return False

def delete_empty_threads_in_project(db: Session, project_id: int, exclude_thread_id: int | None = None) -> int:
    """
    指定されたプロジェクト内で、メッセージが存在しないチャット（スレッド）を削除します。
    特定のチャットIDを除外することも可能です。

    Args:
        db: SQLAlchemy セッションオブジェクト。
        project_id: 対象のプロジェクト ID。
        exclude_thread_id: 削除対象から除外するチャットの ID (オプション)。

    Returns:
        削除されたチャットの数。エラー時は 0。
    """
    try:
        # メッセージが存在しないスレッドの ID を取得
        # LEFT JOIN を使用し、Message が NULL のものを探す
        query = db.query(Thread.id).outerjoin(Message).filter(
            Thread.project_id == project_id,
            Message.id == None
        )
        # 除外IDが指定されていれば、条件に追加
        if exclude_thread_id is not None:
            query = query.filter(Thread.id != exclude_thread_id)
            
        empty_thread_ids = [item[0] for item in query.all()]

        if not empty_thread_ids:
            logging.debug(f"プロジェクト ID {project_id} に削除対象の空チャットは見つかりませんでした (除外ID: {exclude_thread_id})。")
            return 0

        logging.info(f"プロジェクト ID {project_id} の {len(empty_thread_ids)} 件の空のチャットを削除します (除外ID: {exclude_thread_id}): {empty_thread_ids}")
        
        # 取得した ID のスレッドを削除
        deleted_count = db.query(Thread).filter(Thread.id.in_(empty_thread_ids)).delete(synchronize_session=False)
        db.commit()
        logging.info(f"{deleted_count} 件の空のチャットを削除しました。")
        return deleted_count if deleted_count is not None else 0

    except Exception as e:
        db.rollback()
        logging.error(f"プロジェクト ID {project_id} の空チャット削除中にエラーが発生しました: {e}", exc_info=True)
        return 0

# 他の CRUD 操作関数もここに追加していく想定
# (例: get_project, create_thread, get_messages_by_thread など) 

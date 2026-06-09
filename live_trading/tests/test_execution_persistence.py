from live_trading.execution_persistence import ExecutionJournal


def test_execution_journal_tracks_only_latest_nonterminal_orders(tmp_path):
    journal = ExecutionJournal(tmp_path / "execution.sqlite3")
    journal.append("submit", {}, client_order_id="a", status="submitting")
    journal.append("accepted", {}, client_order_id="a", status="filled")
    journal.append("submit", {}, client_order_id="b", status="resting")
    rows = journal.unresolved_orders()
    assert [row["client_order_id"] for row in rows] == ["b"]


def test_execution_journal_recovers_only_unclosed_positions(tmp_path):
    journal = ExecutionJournal(tmp_path / "execution.sqlite3")
    journal.append("position_opened", {"basket_id": "one"})
    journal.append("position_opened", {"basket_id": "two"})
    journal.append("position_closed", {"basket_id": "one"})
    assert journal.open_positions() == [{"basket_id": "two"}]

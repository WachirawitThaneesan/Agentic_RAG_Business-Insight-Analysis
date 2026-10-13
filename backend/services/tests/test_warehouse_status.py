"""Actual stored decorated-year tables must remain visible in warehouse status."""
import asyncio
import duckdb


def test_status_includes_lookup_and_year_fact_tables_without_erasing_headers(monkeypatch):
    from backend.services import duckdb_warehouse as warehouse
    from backend.routes.warehouse import warehouse_status
    connection = duckdb.connect(':memory:')
    warehouse._init_schema(connection)
    monkeypatch.setattr(warehouse, '_get_conn', lambda: connection)
    warehouse.load_document_dim(1, 'source.pdf')
    warehouse.load_table_into_warehouse(1, 'decorated',
        ['item', 'ปี 2568', 'ปี 2567 (ปรับปรุงใหม่)'],
        [['profit', '49,565', '49,604']], source_page=1)
    warehouse.load_table_into_warehouse(1, 'plain', ['item','2568'], [['assets','200']], source_page=2)
    result = asyncio.run(warehouse_status())
    assert result['status'] == 'ok'
    assert result['total_fact_records'] == 1
    assert result['total_lookup_records'] == 2
    tables = {row['table_name']: row for row in result['tables']}
    assert tables['decorated']['lookup_records'] == 2
    assert tables['plain']['fact_records'] == 1
    assert connection.execute('SELECT col_name FROM dim_table_rows ORDER BY id').fetchall() == [
        ('ปี 2568',), ('ปี 2567 (ปรับปรุงใหม่)',)]
    connection.close()

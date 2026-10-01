"""Regressions from the real five-page Typhoon/Gemini staging run."""
import duckdb
from backend.services import duckdb_warehouse as w
from backend.services.financial_quality import assess_table

def test_mixed_money_percent_and_eps_cells_keep_their_dimensions(monkeypatch):
    db=duckdb.connect(":memory:");w._init_schema(db);monkeypatch.setattr(w,"_conn",db)
    w.load_table_into_warehouse(1,"summary",["รายการ","2568","2567"],
        [["รายได้ดอกเบี้ยสุทธิ","137,152","148,004"],
         ["กำไรต่อหุ้นขั้นพื้นฐาน (บาท)","20.63","20.63"],
         ["ผลตอบแทน (ร้อยละ)","3.23","3.60"]],unit="ล้านบาท",source_page=1,source_provider="gemini")
    rows=db.execute("select row_label, unit from fact_financial_metrics where metric_year='2568'").fetchall()
    assert dict(rows)=={"รายได้ดอกเบี้ยสุทธิ":"ล้านบาท","กำไรต่อหุ้นขั้นพื้นฐาน (บาท)":"บาท","ผลตอบแทน (ร้อยละ)":"%"}
    w.load_table_into_warehouse(1,"mixed",["ระยะเวลา","เงินรับฝาก 2568","เงินรับฝาก ร้อยละ"],
        [["รวม","2,850,387","100.00"]],unit="ล้านบาท",source_page=5,source_provider="gemini")
    assert db.execute("select unit from dim_table_rows where col_name like '%ร้อยละ%'").fetchone()[0]=="%"
    db.close()

def test_invalid_five_digit_year_is_quarantined_without_guessing():
    report=assess_table({"headers":["รายการ","31 ธ.ค. 25688","31 ธ.ค. 2567","31 ธ.ค. 2566"],
                         "rows":[["ภาระผูกพัน","15,437","16,728","21,064"]]})
    assert not report["accepted_rows"]
    assert "malformed_year_header" in report["row_reports"][0]["reasons"]

def test_percentage_subcolumns_keep_statement_group_and_year():
    from backend.services.table_utils import complete_column_context
    headers=["ระยะเวลา","เงินรับฝาก 31 ธ.ค. 2568","เงินรับฝาก ร้อยละ",
             "เงินรับฝาก 31 ธ.ค. 2567","เงินรับฝาก ร้อยละ",
             "เงินให้สินเชื่อ 31 ธ.ค. 2568","เงินให้สินเชื่อ ร้อยละ"]
    result=complete_column_context(headers)
    assert result[2]=="เงินรับฝาก ร้อยละ 2568"
    assert result[4]=="เงินรับฝาก ร้อยละ 2567"
    assert result[6]=="เงินให้สินเชื่อ ร้อยละ 2568"
    comparison=["รายการ","ปี 2568","ปี 2567","เพิ่ม (ลด)","การเปลี่ยนแปลง ร้อยละ"]
    assert complete_column_context(comparison)==comparison
    assert complete_column_context(["รายการ","เงินรับฝาก 25688","เงินรับฝาก ร้อยละ"])[2]=="เงินรับฝาก ร้อยละ"

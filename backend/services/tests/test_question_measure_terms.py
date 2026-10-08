from backend.services.question_measure_terms import measure_terms


def test_deadline_label_keeps_event_instead_of_day_unit():
    q = 'ผู้จัดการต้องส่งรายงานความเสี่ยงครั้งแรกภายในกี่วันนับจากวันที่รับตำแหน่ง?'
    assert measure_terms(q) == ['รายงานความเสี่ยงครั้งแรก']


def test_ratio_uses_question_nouns_and_keeps_country_scope():
    q = 'บริษัทตัวอย่างมีสัดส่วนยอดขายบริการในประเทศญี่ปุ่นคิดเป็นร้อยละเท่าใด?'
    assert measure_terms(q) == ['สัดส่วนยอดขายบริการในประเทศญี่ปุ่น']


def test_person_counts_preserve_two_requested_relations():
    q = 'บริษัทตัวอย่างมีกรรมการที่เป็นเพศชายกี่คนจากกรรมการทั้งหมด?'
    assert measure_terms(q) == ['กรรมการเพศชาย', 'กรรมการทั้งหมด']


def test_nonquantity_process_does_not_force_a_metric():
    assert measure_terms('บริษัทพัฒนาทักษะพนักงานอย่างไร?') == []


def test_known_numeric_condition_is_not_repeated_in_measure():
    q = 'บริษัทมีสัดส่วนยอดขายสินค้าที่เติบโตเกิน20เปอร์เซ็นต์คิดเป็นเท่าใด?'
    assert measure_terms(q) == []


def test_declarative_financial_question_keeps_visible_property():
    q = 'จากรายงานบริษัทตัวอย่างประจำปี2568 ยอดขายรวมมีค่าเท่าไหร่?'
    assert measure_terms(q) == ['ยอดขายรวม']


def test_count_question_names_the_facility_not_the_unit():
    q = 'บริษัทตัวอย่างมีศูนย์บริการรวมกี่แห่ง?'
    assert 'ศูนย์บริการ' in measure_terms(q)


def test_property_before_owner_keeps_named_property():
    q = 'ที่ดินและอาคารของ ABC มีจำนวนเท่าใด?'
    assert 'ที่ดินและอาคาร' in measure_terms(q)


def test_location_of_requested_count_is_retained():
    q = 'ศูนย์บริการของ ABC มีกี่แห่งในประเทศญี่ปุ่น?'
    assert 'ศูนย์บริการในประเทศญี่ปุ่น' in measure_terms(q)

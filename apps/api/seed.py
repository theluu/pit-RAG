from datetime import date
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from apps.api.models import LegalDocument, Provision
from packages.ingestion.parser import normalize, parse_legal_text

SEED_DOCUMENTS = [
    dict(
        number="45/2019/QH14",
        title="Bộ luật Lao động 2019",
        type="Bộ luật",
        authority="Quốc hội",
        issued="2019-11-20",
        effective="2021-01-01",
        domain="labor",
        url="https://vanban.chinhphu.vn/?pageid=27160&docid=198540",
        text="""CHƯƠNG III HỢP ĐỒNG LAO ĐỘNG
Điều 25. Thời gian thử việc
1. Thời gian thử việc do hai bên thỏa thuận căn cứ vào tính chất và mức độ phức tạp của công việc nhưng chỉ được thử việc một lần đối với một công việc.
2. Không quá 60 ngày đối với công việc có chức danh nghề nghiệp cần trình độ chuyên môn, kỹ thuật từ cao đẳng trở lên.
Điều 98. Tiền lương làm thêm giờ, làm việc vào ban đêm
1. Người lao động làm thêm giờ được trả lương tính theo đơn giá tiền lương hoặc tiền lương thực trả theo công việc đang làm.
b) Vào ngày nghỉ hằng tuần, ít nhất bằng 200 phần trăm.
c) Vào ngày nghỉ lễ, tết, ngày nghỉ có hưởng lương, ít nhất bằng 300 phần trăm chưa kể tiền lương ngày lễ, tết, ngày nghỉ có hưởng lương.
CHƯƠNG VII THỜI GIỜ LÀM VIỆC, THỜI GIỜ NGHỈ NGƠI
Điều 111. Nghỉ hằng tuần
1. Mỗi tuần, người lao động được nghỉ ít nhất 24 giờ liên tục. Trong trường hợp đặc biệt do chu kỳ lao động không thể nghỉ hằng tuần thì người sử dụng lao động có trách nhiệm bảo đảm cho người lao động được nghỉ tính bình quân 01 tháng ít nhất 04 ngày.
2. Người sử dụng lao động có quyền quyết định sắp xếp ngày nghỉ hằng tuần vào ngày Chủ nhật hoặc ngày xác định khác trong tuần nhưng phải ghi vào nội quy lao động.
""",
    ),
    dict(
        number="58/2014/QH13",
        title="Luật Bảo hiểm xã hội 2014",
        type="Luật",
        authority="Quốc hội",
        issued="2014-11-20",
        effective="2016-01-01",
        end="2025-06-30",
        status="replaced",
        domain="social_insurance",
        url="https://vanban.chinhphu.vn/default.aspx?pageid=27160&docid=178127",
        text="""CHƯƠNG III BẢO HIỂM XÃ HỘI BẮT BUỘC
Điều 54. Điều kiện hưởng lương hưu
1. Người lao động khi nghỉ việc có đủ 20 năm đóng bảo hiểm xã hội trở lên thì được hưởng lương hưu nếu đủ điều kiện về tuổi theo quy định.
Điều 60. Bảo hiểm xã hội một lần
1. Người lao động có yêu cầu thì được hưởng bảo hiểm xã hội một lần nếu thuộc một trong các trường hợp luật định.
""",
    ),
    dict(
        number="41/2024/QH15",
        title="Luật Bảo hiểm xã hội 2024",
        type="Luật",
        authority="Quốc hội",
        issued="2024-06-29",
        effective="2025-07-01",
        domain="social_insurance",
        url="https://vanban.chinhphu.vn/?classid=1&docid=211199&orggroupid=1&pageid=27160",
        text="""CHƯƠNG V CHẾ ĐỘ HƯU TRÍ
Điều 64. Đối tượng và điều kiện hưởng lương hưu
1. Người lao động khi nghỉ việc có thời gian đóng bảo hiểm xã hội bắt buộc từ đủ 15 năm trở lên và đủ tuổi nghỉ hưu theo quy định thì được hưởng lương hưu.
""",
    ),
    dict(
        number="111/2013/TT-BTC",
        title="Thông tư hướng dẫn Luật Thuế thu nhập cá nhân",
        type="Thông tư",
        authority="Bộ Tài chính",
        issued="2013-08-15",
        effective="2013-10-01",
        domain="personal_income_tax",
        url="https://vanban.chinhphu.vn/default.aspx?pageid=27160&docid=169421",
        text="""CHƯƠNG II CĂN CỨ TÍNH THUẾ
Điều 9. Các khoản giảm trừ
1. Giảm trừ gia cảnh là số tiền được trừ vào thu nhập chịu thuế trước khi tính thuế đối với thu nhập từ kinh doanh, tiền lương, tiền công.
a) Mức giảm trừ đối với bản thân người nộp thuế thực hiện theo nghị quyết của cơ quan có thẩm quyền.
b) Mức giảm trừ đối với mỗi người phụ thuộc thực hiện theo nghị quyết của cơ quan có thẩm quyền.
""",
    ),
    dict(
        number="954/2020/UBTVQH14",
        title="Nghị quyết điều chỉnh mức giảm trừ gia cảnh",
        type="Nghị quyết",
        authority="Ủy ban Thường vụ Quốc hội",
        issued="2020-06-02",
        effective="2020-07-01",
        domain="personal_income_tax",
        url="https://vanban.chinhphu.vn/default.aspx?pageid=27160&docid=200237",
        text="""Điều 1. Mức giảm trừ gia cảnh
1. Mức giảm trừ đối với đối tượng nộp thuế là 11 triệu đồng một tháng, 132 triệu đồng một năm.
2. Mức giảm trừ đối với mỗi người phụ thuộc là 4,4 triệu đồng một tháng.
""",
    ),
]


def load_seed() -> tuple[list[LegalDocument], list[Provision]]:
    documents: list[LegalDocument] = []
    provisions: list[Provision] = []
    for item in SEED_DOCUMENTS:
        doc_id = uuid5(NAMESPACE_URL, item["number"])
        documents.append(
            LegalDocument(
                id=doc_id,
                document_number=item["number"],
                title=item["title"],
                document_type=item["type"],
                issuing_authority=item["authority"],
                issued_date=date.fromisoformat(item["issued"]),
                effective_from=date.fromisoformat(item["effective"]),
                effective_to=date.fromisoformat(item["end"]) if item.get("end") else None,
                status=item.get("status", "active"),
                source_url=item["url"],
                checksum=sha256(item["text"].encode()).hexdigest(),
                domain=item["domain"],
            )
        )
        for i, parsed in enumerate(parse_legal_text(item["text"])):
            provisions.append(
                Provision(
                    id=uuid5(doc_id, f"{parsed.article}-{parsed.clause}-{parsed.point}-{i}"),
                    document_id=doc_id,
                    chapter=parsed.chapter,
                    article=parsed.article,
                    clause=parsed.clause,
                    point=parsed.point,
                    heading=parsed.heading,
                    content=parsed.content,
                    normalized_content=normalize(parsed.content),
                )
            )
    return documents, provisions


if __name__ == "__main__":
    docs, provisions = load_seed()
    print(f"Loaded {len(docs)} reviewed demo documents and {len(provisions)} legal provisions")
